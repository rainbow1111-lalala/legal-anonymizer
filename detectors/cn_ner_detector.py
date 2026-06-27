"""
Chinese NER Detector (CLUENER)
A Chinese named-entity recognition detector built on
uer/roberta-base-finetuned-cluener2020-chinese.

CLUENER2020 label set (10 classes) and how this project handles each:
  name         -> person       person name
  company      -> company      company name
  address      -> full_address address
  government   -> government   government agency
  organization -> institution  institution
  position     -> (dropped by default)  job title; but compound-surname patterns
                  such as Shangguan / Sima / Ouyang are merged into the adjacent name
  book         -> (dropped)    book titles (non-PII, e.g. the Civil Code)
  movie / game / scene -> (dropped) non-PII categories

Design notes:
  1. Lazy loading plus a process-level singleton (same pattern as llm_detector).
  2. Compound-surname gluing: CLUENER sometimes splits a compound-surname name
     (e.g. "Sima XX") into position="Sima" + name="XX". This detector recognizes
     compound surnames in post-processing and merges them into a complete name.
  3. False-positive filtering: book, scene, and movie labels are dropped outright.
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_MODEL_ID = "uer/roberta-base-finetuned-cluener2020-chinese"

# CLUENER -> project type
LABEL_MAP = {
    "name": "person",
    "company": "company",
    "address": "full_address",
    "government": "government",
    "organization": "institution",
    # The following are dropped by default (position is handled separately)
    "position": None,
    "book": None,
    "movie": None,
    "game": None,
    "scene": None,
}

# CLUENER often splits a compound surname into position="上官"+name="文渊";
# this set lists common compound surnames used for the merge.
COMPOUND_SURNAMES = {
    "欧阳", "太史", "端木", "上官", "司马", "东方", "独孤", "南宫",
    "万俟", "闻人", "夏侯", "诸葛", "尉迟", "公羊", "赫连", "澹台",
    "皇甫", "宗政", "濮阳", "公冶", "太叔", "申屠", "公孙", "慕容",
    "仲孙", "钟离", "长孙", "宇文", "司徒", "鲜于", "司空", "令狐",
}


class CNNERDetector:
    """Chinese NER detector (CLUENER), shared as a lazy-loaded singleton."""

    def __init__(
        self,
        model_id: str = DEFAULT_MODEL_ID,
        device: Optional[str] = None,
        min_score: float = 0.7,
        max_chars: int = 400,
        keep_position: bool = False,
    ):
        """
        Args:
            min_score: a slightly higher threshold (0.7) for CLUENER to reduce false positives
            keep_position: whether to keep the position type (dropped by default; in legal
                           documents, titles like "lawyer" or "judge" are not PII)
            max_chars: chunk length. The model has max_position_embeddings=512, and Chinese is
                       roughly one token per character, so 400 leaves a safety margin (for the
                       extra [CLS]/[SEP]/OOV tokens)
        """
        self.model_id = model_id
        self.device = device
        self.min_score = min_score
        self.max_chars = max_chars
        self.keep_position = keep_position

        self._pipeline = None
        self._load_error: Optional[str] = None

    # ---------------- Lazy loading ----------------

    def _ensure_loaded(self) -> bool:
        if self._pipeline is not None:
            return True
        if self._load_error is not None:
            return False
        try:
            import torch  # noqa: F401
            from transformers import (
                AutoModelForTokenClassification,
                AutoTokenizer,
                pipeline,
            )
        except ImportError as e:
            self._load_error = f"Missing dependency: {e.name}. Install with: pip install torch transformers"
            logger.warning(self._load_error)
            return False

        try:
            import torch

            device = self.device
            if device is None:
                if torch.cuda.is_available():
                    device = "cuda"
                elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
                    device = "mps"
                else:
                    device = "cpu"

            logger.info(f"[cn_ner] loading {self.model_id} on {device} ...")
            tok = AutoTokenizer.from_pretrained(self.model_id)
            mdl = AutoModelForTokenClassification.from_pretrained(self.model_id)
            self._pipeline = pipeline(
                task="token-classification",
                model=mdl,
                tokenizer=tok,
                aggregation_strategy="simple",
                device=device,
            )
            return True
        except Exception as e:
            self._load_error = f"Model loading failed: {e}"
            logger.exception(self._load_error)
            return False

    @property
    def available(self) -> bool:
        return self._ensure_loaded()

    @property
    def load_error(self) -> Optional[str]:
        return self._load_error

    # ---------------- Detection ----------------

    def detect(
        self,
        text: str,
        only_types: Optional[List[str]] = None,
        exclude_types: Optional[List[str]] = None,
    ) -> List[Tuple[str, str, int]]:
        if not text or not self._ensure_loaded():
            return []

        raw_spans: List[Tuple[str, str, int]] = []  # (text, raw_label, start)
        offset = 0
        for chunk in self._split_chunks(text, self.max_chars):
            try:
                spans = self._pipeline(chunk)
            except Exception as e:
                logger.warning(f"[cn_ner] inference failed: {e}")
                offset += len(chunk)
                continue

            for span in spans:
                label = span.get("entity_group") or span.get("entity") or ""
                for prefix in ("B-", "I-", "E-", "S-"):
                    if label.startswith(prefix):
                        label = label[len(prefix):]
                        break
                score = float(span.get("score", 1.0))
                if score < self.min_score:
                    continue
                start = int(span.get("start", 0)) + offset
                end = int(span.get("end", 0)) + offset
                if end <= start:
                    continue
                entity_text = text[start:end].strip()
                if len(entity_text) < 2:
                    continue
                raw_spans.append((entity_text, label, start))
            offset += len(chunk)

        # 1. Compound-surname gluing: position=<compound surname> + adjacent name -> merge into person
        merged = self._merge_compound_surname(raw_spans, text)

        # 2. Label mapping plus type filtering
        results: List[Tuple[str, str, int]] = []
        for t, raw_label, p in merged:
            if raw_label == "position" and not self.keep_position:
                continue
            mapped = LABEL_MAP.get(raw_label)
            if mapped is None:
                if raw_label == "position" and self.keep_position:
                    mapped = "position"
                else:
                    continue

            if only_types and mapped not in only_types:
                continue
            if exclude_types and mapped in exclude_types:
                continue

            # Basic filtering for name/person: drop fragments ending in a stopword
            if mapped == "person" and t[-1] in "的了过是为与和或及在":
                continue

            # Drop pure English/Latin hits. CLUENER is a Chinese model and mislabels English.
            # (Observed in testing: it tags common words like "company"/"Delaware" as companies.)
            has_cjk = any("一" <= c <= "鿿" for c in t)
            if not has_cjk:
                continue

            # government/court filtering: generic names (e.g. "second-instance court",
            # "original-trial court") are not specific institutions
            if mapped in ("government", "court", "institution"):
                generic_gov_court = {
                    "人民法院", "第一审人民法院", "第二审人民法院", "第三审人民法院",
                    "原审人民法院", "再审人民法院", "审判人民法院",
                    "人民检察院", "本院", "法院", "检察院", "原审", "一审", "二审", "再审",
                }
                if t in generic_gov_court:
                    continue
                # Statute references starting with "Article/Clause/Item/Instance X"
                import re as _re
                if _re.match(r'第[一二三四五六七八九十百千\d]+[条款项审]', t):
                    continue

            results.append((t, mapped, p))

        return self._dedupe(results)

    @staticmethod
    def _merge_compound_surname(
        spans: List[Tuple[str, str, int]], text: str
    ) -> List[Tuple[str, str, int]]:
        """Merge position=<compound surname> + adjacent name into a single name."""
        if not spans:
            return spans
        spans = sorted(spans, key=lambda x: x[2])
        out: List[Tuple[str, str, int]] = []
        i = 0
        while i < len(spans):
            t, lbl, p = spans[i]
            if (
                lbl == "position"
                and t in COMPOUND_SURNAMES
                and i + 1 < len(spans)
            ):
                nt, nlbl, np_ = spans[i + 1]
                # Strictly adjacent: the end of position == the start of name
                if nlbl == "name" and (p + len(t)) == np_:
                    merged_text = text[p : np_ + len(nt)]
                    out.append((merged_text, "name", p))
                    i += 2
                    continue
            out.append((t, lbl, p))
            i += 1
        return out

    @staticmethod
    def _split_chunks(text: str, max_chars: int) -> List[str]:
        if len(text) <= max_chars:
            return [text]
        chunks = []
        i = 0
        while i < len(text):
            end = min(i + max_chars, len(text))
            if end < len(text):
                for sep in ("\n\n", "\n", "。", "；"):
                    cut = text.rfind(sep, i, end)
                    if cut > i + max_chars // 2:
                        end = cut + len(sep)
                        break
            chunks.append(text[i:end])
            i = end
        return chunks

    @staticmethod
    def _dedupe(items: List[Tuple[str, str, int]]) -> List[Tuple[str, str, int]]:
        seen = set()
        out = []
        for t, ty, p in items:
            key = (t, ty, p)
            if key in seen:
                continue
            seen.add(key)
            out.append((t, ty, p))
        out.sort(key=lambda x: x[2])
        return out


_SHARED: Optional["CNNERDetector"] = None


def get_shared_cn_detector(**kwargs) -> "CNNERDetector":
    global _SHARED
    if _SHARED is None:
        _SHARED = CNNERDetector(**kwargs)
    return _SHARED


def is_cn_llm_enabled_via_env() -> bool:
    return os.environ.get("LEGAL_ANONYMIZER_CN_LLM", "").lower() in ("1", "true", "yes", "on")
