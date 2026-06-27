"""
OllamaDetector — local LLM PII detection layer

Calls a locally deployed LLM through Ollama's OpenAI-compatible endpoint
(/v1/chat/completions), asks the model to return the sensitive entities found in
the text as JSON, then maps each entity string back to its position in the source.

Role: the 5th supplementary layer. It only covers what the first four layers
(regex + rules + CN NER + OpenAI privacy-filter) miss. Good for:
  - Highly context-dependent person names (e.g. a name right after "the Party A's
    legal representative")
  - Special institution names and place-name abbreviations that rules cannot enumerate
  - General reasoning in complex mixed Chinese/English contexts

Configuration:
  Environment variables:
    LEGAL_ANONYMIZER_OLLAMA=1            Enable this layer (off by default)
    LEGAL_ANONYMIZER_OLLAMA_URL=http://host:11434   Ollama service URL (default localhost:11434)
    LEGAL_ANONYMIZER_OLLAMA_MODEL=qwen2.5:7b        Model name (default qwen2.5:7b)

  CLI flags (see cli.py):
    --ollama                enable
    --ollama-url URL        service URL
    --ollama-model MODEL    model name

Notes:
  - Gemma models default to "thinking" (reasoning) over the /v1 endpoint, which
    leaves the message body empty. This module automatically adds
    extra_body={"reasoning_effort": "none"} for gemma models to work around it.
  - This layer uses a generative LLM (not a token classifier). It locates entities
    by searching the source for the returned entity strings, so a wrong "output
    position" cannot break redaction correctness (the worst case is a miss, not a
    misplaced false positive).
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
import urllib.error
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# Types recognized by this layer -> internal project types
OLLAMA_TYPE_MAP = {
    "person":       "person",
    "company":      "company",
    "law_firm":     "law_firm",
    "institution":  "institution",
    "government":   "government",
    "court":        "court",
    "full_address": "full_address",
    "bank_account": "bank_account",
    "case_number":  "case_number",
    "phone":        "phone",
    "email":        "email",
    "id_card":      "id_card",
    "secret":       "secret",
    "website":      "website",
}

_SYSTEM_PROMPT = """\
You are a PII extractor for Chinese legal documents. Your task is to find \
personal and sensitive information in the given text.

Return ONLY a valid JSON object with this exact structure:
{"entities": [{"text": "...", "type": "..."}]}

Valid types:
  person        — personal names (人名)
  company       — company / enterprise names (公司名)
  law_firm      — law firm names (律师事务所)
  institution   — non-profit organizations, schools, hospitals (机构)
  government    — government agencies (政府部门)
  court         — court names (法院)
  full_address  — complete street / location addresses (地址)
  bank_account  — bank account numbers (银行账号)
  case_number   — legal case numbers (案号)
  phone         — phone or fax numbers (电话/传真)
  email         — email addresses (邮箱)
  id_card       — national ID / passport numbers (身份证/护照)
  secret        — API keys, tokens, passwords (密钥/密码)
  website       — URLs and domain names (网址)

Rules:
1. "text" must be an EXACT substring copied verbatim from the document.
2. Skip entities that are clearly already in structured formats captured \
by regex (e.g., pure 18-digit numbers, phone patterns). Focus on \
context-dependent names, addresses, and compound identifiers.
3. Do not invent, paraphrase, or expand entities.
4. If nothing is found, return {"entities": []}.
5. Output only the JSON object — no markdown fences, no explanation.
"""


class OllamaDetector:
    """Local Ollama LLM PII detector (the 5th supplementary layer)"""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "qwen2.5:7b",
        timeout: int = 60,
        max_chars: int = 3000,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_chars = max_chars
        self._available: Optional[bool] = None

    # ───────────────── Availability probe ─────────────────

    def _probe(self) -> bool:
        """Send one /api/tags request to confirm the Ollama service is reachable"""
        try:
            req = urllib.request.Request(
                f"{self.base_url}/api/tags",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5):
                pass
            return True
        except Exception as e:
            logger.warning(f"[ollama] Cannot connect to {self.base_url}: {e}")
            return False

    @property
    def available(self) -> bool:
        if self._available is None:
            self._available = self._probe()
        return self._available

    # ───────────────── Main detection entry point ─────────────────

    def detect(
        self,
        text: str,
        only_types: Optional[List[str]] = None,
        exclude_types: Optional[List[str]] = None,
    ) -> List[Tuple[str, str, int]]:
        """
        Detect PII, returning [(entity_text, mapped_type, start_pos), ...].
        Signature aligns with the other Detector.detect() methods.
        """
        if not text or not self.available:
            return []

        results: List[Tuple[str, str, int]] = []
        for chunk_text, chunk_offset in self._split_chunks(text, self.max_chars):
            raw = self._call_model(chunk_text)
            if not raw:
                continue
            for entity_text, mapped_type in self._parse_response(raw):
                if only_types and mapped_type not in only_types:
                    continue
                if exclude_types and mapped_type in exclude_types:
                    continue
                # Find every occurrence of this entity in the source text
                idx = 0
                while True:
                    pos = text.find(entity_text, idx)
                    if pos == -1:
                        break
                    results.append((entity_text, mapped_type, pos))
                    idx = pos + 1

        return self._dedupe(results)

    # ───────────────── Model call ─────────────────

    def _call_model(self, text_chunk: str) -> Optional[str]:
        """Call Ollama /v1/chat/completions and return the model's output text"""
        payload: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": f"Document:\n{text_chunk}"},
            ],
            "temperature": 0,
            "stream": False,
        }

        # Gemma models default to "thinking" (reasoning) over /v1, which leaves content empty.
        # Pass reasoning_effort=none via extra_body to turn it off.
        if "gemma" in self.model.lower():
            payload["extra_body"] = {"reasoning_effort": "none"}

        try:
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{self.base_url}/v1/chat/completions",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            content = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
            return content or None
        except urllib.error.URLError as e:
            logger.warning(f"[ollama] Request failed: {e}")
            self._available = False  # Mark unavailable so later chunks are skipped
            return None
        except Exception as e:
            logger.warning(f"[ollama] Unexpected error: {e}")
            return None

    # ───────────────── Response parsing ─────────────────

    def _parse_response(self, content: str) -> List[Tuple[str, str]]:
        """
        Parse the JSON returned by the model into [(entity_text, mapped_type), ...].
        Tolerant of markdown code fences, incomplete JSON, extra explanatory text, etc.
        """
        # Strip the markdown code-fence wrapper
        content = re.sub(r"```(?:json)?\s*", "", content).strip()
        # Try to extract the first {...} block
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            return []
        try:
            obj = json.loads(match.group())
        except json.JSONDecodeError:
            logger.debug(f"[ollama] JSON parse failed, raw output: {content[:200]}")
            return []

        entities = obj.get("entities", [])
        if not isinstance(entities, list):
            return []

        results = []
        for item in entities:
            if not isinstance(item, dict):
                continue
            raw_text = item.get("text", "").strip()
            raw_type = item.get("type", "").strip().lower()
            if not raw_text or not raw_type:
                continue
            mapped = OLLAMA_TYPE_MAP.get(raw_type)
            if mapped is None:
                continue
            if len(raw_text) < 2:
                continue
            results.append((raw_text, mapped))
        return results

    # ───────────────── Utilities ─────────────────

    @staticmethod
    def _split_chunks(text: str, max_chars: int) -> List[Tuple[str, int]]:
        """Split into chunks of max_chars, breaking on paragraph/sentence boundaries where possible; returns [(chunk_text, offset)]"""
        if len(text) <= max_chars:
            return [(text, 0)]
        chunks = []
        i = 0
        while i < len(text):
            end = min(i + max_chars, len(text))
            if end < len(text):
                for sep in ("\n\n", "\n", "。", ". "):
                    cut = text.rfind(sep, i, end)
                    if cut > i + max_chars // 2:
                        end = cut + len(sep)
                        break
            chunks.append((text[i:end], i))
            i = end
        return chunks

    @staticmethod
    def _dedupe(items: List[Tuple[str, str, int]]) -> List[Tuple[str, str, int]]:
        seen = set()
        out = []
        for t, ty, p in items:
            key = (t, ty, p)
            if key not in seen:
                seen.add(key)
                out.append((t, ty, p))
        out.sort(key=lambda x: x[2])
        return out


# ───────────────── Process-level singleton ─────────────────

_SHARED: Optional[OllamaDetector] = None


def get_shared_ollama_detector(**kwargs) -> OllamaDetector:
    global _SHARED
    if _SHARED is None:
        _SHARED = OllamaDetector(**kwargs)
    return _SHARED


def is_ollama_enabled_via_env() -> bool:
    return os.environ.get("LEGAL_ANONYMIZER_OLLAMA", "").lower() in ("1", "true", "yes", "on")


def ollama_url_from_env() -> str:
    return os.environ.get("LEGAL_ANONYMIZER_OLLAMA_URL", "http://localhost:11434")


def ollama_model_from_env() -> str:
    return os.environ.get("LEGAL_ANONYMIZER_OLLAMA_MODEL", "qwen2.5:7b")
