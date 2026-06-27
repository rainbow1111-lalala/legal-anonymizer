"""
LLM-based PII Detector (OpenAI privacy-filter)
A PII detector built on the OpenAI privacy-filter model (1.5B MoE, 50M active).

This model targets mainly English/Latin scripts. Per the official notes:
"Performance may drop on non-English text, non-Latin scripts." So in this project
it serves as a **supplementary layer**:
  - Cover the blind spots of the Chinese rules: English person names, English
    addresses, English institution names, API key / secret, English URLs
  - Cross-check English emails/phones/dates
  - Chinese person and company names still rely on the EntityDetector rules

Design notes:
  1. Lazy loading: the model is loaded only on the first detect() call, so startup stays fast
  2. Graceful degradation on missing dependencies: if transformers/torch is not installed,
     return an empty list and print a hint
  3. Type mapping: map the 8 privacy-filter PII classes onto the project's existing type system
  4. Offset alignment: align the offsets returned by the transformers pipeline to the
     character indices of the original text
  5. Short-fragment filtering: hits shorter than 2 characters are usually false positives
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# The 8 privacy-filter classes -> this project's types
# Note: privacy-filter's private_person has very low recall on Chinese text, so we keep
# but do not rely on it; Chinese person names fall back mainly to the EntityDetector rules layer.
LABEL_MAP = {
    "account_number": "bank_account",
    "private_address": "full_address",
    "private_email": "email",
    "private_person": "person",
    "private_phone": "phone",
    "private_url": "website",
    "private_date": "date",
    "secret": "secret",  # API key / token, a new type in this project
}

DEFAULT_MODEL_ID = "openai/privacy-filter"


class LLMDetector:
    """PII detector built on a token-classification LLM (lazy-loaded)."""

    def __init__(
        self,
        model_id: str = DEFAULT_MODEL_ID,
        device: Optional[str] = None,
        min_score: float = 0.5,
        max_chars: int = 8000,
        only_latin_spans: bool = True,
    ):
        """
        Args:
            model_id: HuggingFace model ID
            device: "cpu" | "mps" | "cuda" | None (auto-selected)
            min_score: minimum confidence threshold
            max_chars: maximum characters per inference call; longer text is chunked automatically
            only_latin_spans: when True, drop hits that contain no Latin letters or digits at all,
                              because the model's recall on Chinese is unstable and prone to
                              false positives. Turn it off to observe the model's Chinese behavior.
        """
        self.model_id = model_id
        self.device = device
        self.min_score = min_score
        self.max_chars = max_chars
        self.only_latin_spans = only_latin_spans

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
            self._load_error = (
                f"Missing dependency: {e.name}. Install with:\n"
                f"  pip install torch transformers"
            )
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

            logger.info(f"[llm_detector] loading {self.model_id} on {device} ...")
            tokenizer = AutoTokenizer.from_pretrained(self.model_id)
            model = AutoModelForTokenClassification.from_pretrained(self.model_id)
            # The HF pipeline handles BIOES aggregation itself (aggregation_strategy="simple")
            self._pipeline = pipeline(
                task="token-classification",
                model=model,
                tokenizer=tokenizer,
                aggregation_strategy="simple",
                device=device,
            )
            logger.info(f"[llm_detector] model loaded on {device}")
            return True
        except Exception as e:
            self._load_error = f"Model loading failed: {e}"
            logger.exception(self._load_error)
            return False

    @property
    def available(self) -> bool:
        """Try to load and report whether the detector is available (does not raise)."""
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
        """
        Detect PII and return [(entity_text, mapped_type, start_pos), ...].
        Matches the PatternDetector.detect() signature.
        """
        if not text or not self._ensure_loaded():
            return []

        # Run inference in chunks to avoid OOM on very long text
        results: List[Tuple[str, str, int]] = []
        offset = 0
        for chunk in self._split_chunks(text, self.max_chars):
            try:
                spans = self._pipeline(chunk)
            except Exception as e:
                logger.warning(f"[llm_detector] inference failed on chunk: {e}")
                offset += len(chunk)
                continue

            for span in spans:
                label = span.get("entity_group") or span.get("entity") or ""
                # privacy-filter labels may carry a B-/I-/E-/S- prefix
                for prefix in ("B-", "I-", "E-", "S-"):
                    if label.startswith(prefix):
                        label = label[len(prefix):]
                        break
                mapped = LABEL_MAP.get(label)
                if mapped is None:
                    continue

                score = float(span.get("score", 1.0))
                if score < self.min_score:
                    continue

                # The pipeline's start/end are offsets within the chunk
                start = int(span.get("start", 0)) + offset
                end = int(span.get("end", 0)) + offset
                if end <= start:
                    continue

                # Take the actual span by original-text index (more reliable than the
                # string the model reconstructs)
                entity_text = text[start:end]
                # Strip surrounding whitespace and common punctuation (does not touch the middle)
                l_strip = len(entity_text) - len(entity_text.lstrip(" \t\n,，。；;"))
                r_strip = len(entity_text) - len(entity_text.rstrip(" \t\n,，。；;"))
                if l_strip:
                    start += l_strip
                end -= r_strip
                entity_text = text[start:end]
                if len(entity_text) < 2:
                    continue

                # Filter out all-Chinese spans (the model's Chinese recall is unstable
                # and prone to mis-segmentation)
                if self.only_latin_spans and mapped == "person":
                    if not any(c.isascii() and c.isalnum() for c in entity_text):
                        continue

                # Type filtering
                if only_types and mapped not in only_types:
                    continue
                if exclude_types and mapped in exclude_types:
                    continue

                # Correct start to where entity_text actually appears in the original text
                real_start = text.find(entity_text, start)
                if real_start == -1:
                    real_start = start
                results.append((entity_text, mapped, real_start))

            offset += len(chunk)

        merged = self._merge_adjacent(results, text)
        merged = self._fix_url_tail(merged, text)
        merged = self._extend_boundaries(merged, text)
        return self._dedupe(merged)

    @staticmethod
    def _extend_boundaries(
        items: List[Tuple[str, str, int]], text: str
    ) -> List[Tuple[str, str, int]]:
        """
        Repair characters the model drops at span boundaries:
          - phone: extend the tail forward up to the first non-[digit/space/-] character
          - secret: extend the tail forward up to the first non-[A-Za-z0-9_\\-] character
          - account_number / bank_account: same as secret
          - website: extend the tail up to the next whitespace/Chinese/closing parenthesis
        No backward extension (it tends to swallow the leading keyword).
        """
        import string

        CHARSETS = {
            "phone": set(string.digits + " -"),
            "secret": set(string.ascii_letters + string.digits + "_-."),
            "bank_account": set(string.digits + " -"),
            "website": set(string.ascii_letters + string.digits + ":/.-?=&%#_~+@"),
        }
        out = []
        for t, ty, p in items:
            cs = CHARSETS.get(ty)
            if cs is None:
                out.append((t, ty, p))
                continue
            end = p + len(t)
            new_end = end
            while new_end < len(text) and text[new_end] in cs:
                new_end += 1
            if new_end > end:
                out.append((text[p:new_end].rstrip(" -"), ty, p))
            else:
                out.append((t, ty, p))
        return out

    @staticmethod
    def _fix_url_tail(
        items: List[Tuple[str, str, int]], text: str
    ) -> List[Tuple[str, str, int]]:
        """
        Fix: when a website is immediately followed by a secret that starts with :// or /,
        merge them into a single website.
        The model often tags 'https' as website and the rest '://host/path' as secret.
        """
        if not items:
            return items
        items = sorted(items, key=lambda x: x[2])
        out: List[Tuple[str, str, int]] = []
        i = 0
        while i < len(items):
            t, ty, p = items[i]
            if ty == "website" and i + 1 < len(items):
                nt, nty, np_ = items[i + 1]
                end = p + len(t)
                gap = text[end:np_]
                if (
                    nty == "secret"
                    and 0 <= (np_ - end) <= 1
                    and (nt.startswith("://") or nt.startswith("/"))
                    and len(gap) == 0
                ):
                    new_text = text[p : np_ + len(nt)]
                    out.append((new_text, "website", p))
                    i += 2
                    continue
            out.append((t, ty, p))
            i += 1
        return out

    @staticmethod
    def _merge_adjacent(
        items: List[Tuple[str, str, int]], text: str, max_gap: int = 3
    ) -> List[Tuple[str, str, int]]:
        """
        Merge adjacent spans of the same type (repairs subword fragmentation).
        e.g. ('zhangsan@example', email, 100) + ('.com', email, 116) -> 'zhangsan@example.com'
        Only merge spans separated by <= max_gap where the gap contains only punctuation/spaces.
        """
        if not items:
            return items
        items = sorted(items, key=lambda x: (x[2], -len(x[0])))
        merged: List[Tuple[str, str, int]] = []
        for t, ty, p in items:
            end = p + len(t)
            if merged:
                lt, lty, lp = merged[-1]
                lend = lp + len(lt)
                gap_text = text[lend:p]
                if ty == lty and 0 <= (p - lend) <= max_gap and (
                    gap_text == ""
                    or all(c in " \t.,-:/@· " for c in gap_text)
                ):
                    new_text = text[lp:end]
                    merged[-1] = (new_text, lty, lp)
                    continue
            merged.append((t, ty, p))
        return merged

    @staticmethod
    def _split_chunks(text: str, max_chars: int) -> List[str]:
        if len(text) <= max_chars:
            return [text]
        chunks = []
        i = 0
        while i < len(text):
            end = min(i + max_chars, len(text))
            # Try to cut at a line break or full stop
            if end < len(text):
                for sep in ("\n\n", "\n", "。", ". "):
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


def is_llm_enabled_via_env() -> bool:
    """Read the LEGAL_ANONYMIZER_LLM environment variable for a unified script/launcher toggle."""
    return os.environ.get("LEGAL_ANONYMIZER_LLM", "").lower() in ("1", "true", "yes", "on")


_SHARED: Optional["LLMDetector"] = None


def get_shared_detector(**kwargs) -> "LLMDetector":
    """
    Process-level shared LLMDetector singleton.
    Scenarios like the web UI build a new LegalAnonymizer on every request; this function
    avoids reloading the 1.5GB model each time.
    """
    global _SHARED
    if _SHARED is None:
        _SHARED = LLMDetector(**kwargs)
    return _SHARED
