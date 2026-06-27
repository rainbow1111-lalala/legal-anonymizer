"""
Legal Document Anonymizer - Main Class
Legal Anonymizer - core class
"""

import re
from typing import Dict, List, Tuple, Optional
from pathlib import Path

from detectors.pattern_detector import PatternDetector
from detectors.entity_detector import EntityDetector
from detectors.llm_detector import LLMDetector, is_llm_enabled_via_env, get_shared_detector
from detectors.cn_ner_detector import (
    CNNERDetector,
    get_shared_cn_detector,
    is_cn_llm_enabled_via_env,
)
from detectors.ollama_detector import (
    OllamaDetector,
    get_shared_ollama_detector,
    is_ollama_enabled_via_env,
    ollama_url_from_env,
    ollama_model_from_env,
)
from maskers.text_masker import TextMasker
from processors.file_processor import FileProcessor


class LegalAnonymizer:
    """Legal Anonymizer - main class"""

    def __init__(
        self,
        use_llm: Optional[bool] = None,
        use_cn_llm: Optional[bool] = None,
        use_ollama: Optional[bool] = None,
        llm_kwargs: Optional[Dict] = None,
        cn_llm_kwargs: Optional[Dict] = None,
        ollama_kwargs: Optional[Dict] = None,
    ):
        """
        Args:
            use_llm: Enable the OpenAI privacy filter (mainly English PII). None reads
                     the LEGAL_ANONYMIZER_LLM environment variable; False turns it off.
            use_cn_llm: Enable the CLUENER Chinese NER (Chinese names, companies,
                        addresses, and other blind spots of the rules engine).
                        None reads LEGAL_ANONYMIZER_CN_LLM; False turns it off.
            use_ollama: Enable a local Ollama LLM as the 5th supplementary layer.
                        None reads LEGAL_ANONYMIZER_OLLAMA; False turns it off.
                        Set the service URL and model name via ollama_kwargs or
                        environment variables:
                          LEGAL_ANONYMIZER_OLLAMA_URL   default http://localhost:11434
                          LEGAL_ANONYMIZER_OLLAMA_MODEL default qwen2.5:7b
            llm_kwargs / cn_llm_kwargs / ollama_kwargs: passed through to each detector
        """
        self.pattern_detector = PatternDetector()
        self.entity_detector = EntityDetector()
        self.masker = TextMasker()
        self.processor = FileProcessor()

        if use_llm is None:
            use_llm = is_llm_enabled_via_env()
        if use_cn_llm is None:
            use_cn_llm = is_cn_llm_enabled_via_env()
        if use_ollama is None:
            use_ollama = is_ollama_enabled_via_env()
        self.use_llm = bool(use_llm)
        self.use_cn_llm = bool(use_cn_llm)
        self.use_ollama = bool(use_ollama)

        self.llm_detector: Optional[LLMDetector] = None
        self.cn_ner_detector: Optional[CNNERDetector] = None
        self.ollama_detector: Optional[OllamaDetector] = None
        if self.use_llm:
            self.llm_detector = get_shared_detector(**(llm_kwargs or {}))
        if self.use_cn_llm:
            self.cn_ner_detector = get_shared_cn_detector(**(cn_llm_kwargs or {}))
        if self.use_ollama:
            kw = {"base_url": ollama_url_from_env(), "model": ollama_model_from_env()}
            kw.update(ollama_kwargs or {})
            self.ollama_detector = get_shared_ollama_detector(**kw)

    def set_mask_strategy(self, entity_type: str, strategy: str):
        """
        Set the mask strategy for a given entity type

        Args:
            entity_type: entity type
            strategy: 'placeholder' or 'partial' (partial mask)
        """
        self.masker.set_strategy(entity_type, strategy)

    def set_all_mask_strategy(self, strategy: str):
        """
        Set the mask strategy for all entity types

        Args:
            strategy: 'placeholder' or 'partial'
        """
        self.masker.set_all_strategy(strategy)

    def set_placeholder_style(self, style: str):
        """
        Switch the placeholder style:
          english_bracket (default, e.g. [PERSON_1]) / chinese_angle (angle-bracket
          style) / chinese_bracket (corner-bracket style)
        """
        self.masker.set_placeholder_style(style)

    @staticmethod
    def restore_text(anonymized_text: str, mapping_data) -> str:
        """
        Restore anonymized text back to the original using the mapping dict

        Args:
            anonymized_text: the anonymized text
            mapping_data: a dict in one of two formats:
                1. {"[PERSON_1]": {"original": "Zhang San", "type": "person"}, ...}
                   (the "mapping" field of the mapping.json the tool exports)
                2. {"[PERSON_1]": "Zhang San", ...} (simple reverse map)

        Returns:
            the restored text
        """
        if not isinstance(mapping_data, dict):
            return anonymized_text
        # Accept both {placeholder: {original, type}} and {placeholder: original}
        flat = {}
        for ph, val in mapping_data.items():
            if isinstance(val, dict):
                orig = val.get('original', '')
            else:
                orig = str(val)
            if ph and orig:
                flat[ph] = orig
        # Replace longer placeholders first (so [PERSON_1] does not corrupt part of [PERSON_11])
        for ph in sorted(flat.keys(), key=len, reverse=True):
            anonymized_text = anonymized_text.replace(ph, flat[ph])
        return anonymized_text

    def add_custom_entity(self, entity_type: str, name: str):
        """
        Add a custom entity

        Args:
            entity_type: entity type
            name: entity name
        """
        self.entity_detector.add_entity(entity_type, name)

    def add_custom_entities(self, entities: List[Dict]):
        """
        Add custom entities in batch

        Args:
            entities: list of entities [{"type": "person", "name": "Zhang San"}, ...]
        """
        self.entity_detector.add_entities(entities)

    def load_entities_from_file(self, file_path: str):
        """
        Load custom entities from a JSON file

        Args:
            file_path: path to the JSON file
        """
        import json
        path = Path(file_path)
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                entities = json.load(f)
                self.add_custom_entities(entities)

    def clear_custom_entities(self):
        """Clear custom entities"""
        self.entity_detector.clear()

    def _detect_all(self, text: str, only_types: List[str] = None, exclude_types: List[str] = None) -> List:
        """
        Fuse the detection layers:
          1. Regex (PatternDetector) -- most reliable for structured data, highest priority
          2. Rule entities (EntityDetector) -- Chinese names, companies, etc., driven by
             context keywords
          3. CN NER (CLUENER) -- catches Chinese names/companies the rules miss, and fixes
             common rule-layer errors
          4. OpenAI privacy filter -- English PII and secrets

        Conflict arbitration (only when the rules layer and CN NER overlap):
          - Same span where the rules say person but CN NER says company/institution
            -> take CN NER (fixes cross-type errors like a company name read as a person)
          - person vs person overlap -> take the longer span
            (fixes mis-cut boundaries on compound surnames, lets the longer span win)
          - Otherwise: rules win, CN NER is dropped

        The OpenAI layer does not arbitrate; it only fills gaps the rules + CN NER missed.

        Returns:
            the merged entity list [(entity text, type, position), ...]
        """
        pattern_entities = self.pattern_detector.detect(text, only_types, exclude_types)
        entity_entities = self.entity_detector.detect(text, only_types, exclude_types)
        self.masker.set_abbreviation_map(self.entity_detector.abbreviation_map)

        merged = pattern_entities + entity_entities

        # --- Layer 3: CN NER fusion (with arbitration) ---
        if self.use_cn_llm and self.cn_ner_detector is not None:
            cn_hits = self.cn_ner_detector.detect(text, only_types, exclude_types)
            merged = self._merge_cn_ner(merged, cn_hits)

        # --- Layer 4: OpenAI privacy filter (gap-fill only) ---
        if self.use_llm and self.llm_detector is not None:
            llm_entities = self.llm_detector.detect(text, only_types, exclude_types)
            occupied = [(p, p + len(t)) for t, _, p in merged]
            for t, ty, p in llm_entities:
                end = p + len(t)
                if any(p < oe and end > os_ for os_, oe in occupied):
                    continue
                merged.append((t, ty, p))
                occupied.append((p, end))

        # --- Layer 5: local Ollama LLM (gap-fill only) ---
        if self.use_ollama and self.ollama_detector is not None:
            ollama_entities = self.ollama_detector.detect(text, only_types, exclude_types)
            occupied = [(p, p + len(t)) for t, _, p in merged]
            for t, ty, p in ollama_entities:
                end = p + len(t)
                if any(p < oe and end > os_ for os_, oe in occupied):
                    continue
                merged.append((t, ty, p))
                occupied.append((p, end))

        # --- Step 7: whole-document consistency for repeated names ---
        # If a name (e.g. "Zhang San") is identified as a person in one place, mark every
        # other occurrence of that name in the document too.
        # Only for person and company/institution names; avoids blowing up on generic
        # place names or job titles.
        merged = self._expand_same_name_occurrences(text, merged)

        # --- Step 8: core brand-word expansion ---
        # For detected company/law firm/institution names, extract the core brand word
        # after stripping prefixes and suffixes, find where it appears on its own in the
        # document, and add those to the entity list.
        merged = self._add_distinctive_part_entities(text, merged)

        return merged

    @staticmethod
    def _is_scanned_pdf(pdf_path: str, sample_pages: int = 3, threshold: int = 80) -> bool:
        """Decide whether a PDF is a scanned PDF (text layer averages fewer than `threshold` characters per page over the first N pages)"""
        try:
            import fitz
            doc = fitz.open(pdf_path)
            n = min(sample_pages, len(doc))
            if n == 0:
                return False
            total = sum(len(doc[i].get_text("text").strip()) for i in range(n))
            doc.close()
            return total < threshold * n
        except Exception:
            return False

    def _write_format(
        self,
        fmt: str,
        input_path: Path,
        output_path: Path,
        input_suffix: str,
        anonymized_content: str,
        use_ocr: bool,
        ocr_engine: str = 'rapidocr',
        whitebox_only: bool = False,
    ) -> List[Tuple[str, str]]:
        """
        Write one output file in the target format. Priority:
          - fmt=docx and source is docx -> in-place replace (preserves formatting exactly)
          - fmt=pdf  and source is a text-layer PDF -> in-place redact (keeps layout/seals)
          - fmt=pdf  and source is a scanned PDF -> visual redaction (OCR + pixel redact,
            keeps the scanned look)
          - otherwise fall back to processor.write_file with a template (FangSong / 12pt / 1.5x)
        """
        fmt = (fmt or '').lower()
        target_path = output_path.with_suffix('.' + fmt) if fmt in ('md', 'pdf', 'docx', 'txt') else output_path

        # docx -> docx in place (DOCX needs no OCR, just XML replacement)
        if fmt == 'docx' and input_suffix == '.docx':
            if self.processor.anonymize_docx_inplace(
                str(input_path), str(target_path), self.masker.mapping
            ):
                return [('output_docx', str(target_path))]
            return self.processor.write_file(anonymized_content, str(target_path), 'docx')

        # pdf -> pdf
        if fmt == 'pdf' and input_suffix == '.pdf':
            # Smart path selection: even if use_ocr=True, prefer redact_annot when the PDF
            # has a text layer (an order of magnitude more accurate than OCR visual
            # redaction, and it keeps the original font size).
            actually_scanned = self._is_scanned_pdf(str(input_path))
            visual_path = use_ocr and actually_scanned

            if visual_path:
                # Scanned PDF: image-based visual redaction (keeps the original page look)
                if self.processor.anonymize_scanned_pdf_inplace(
                    str(input_path), str(target_path), self.masker.mapping, ocr_engine,
                    whitebox_only=whitebox_only,
                ):
                    return [('output_pdf', str(target_path))]
            else:
                # Text-layer PDF: standard redaction (keeps all original formatting)
                if self.processor.anonymize_pdf_inplace(
                    str(input_path), str(target_path), self.masker.mapping,
                    whitebox_only=whitebox_only,
                ):
                    return [('output_pdf', str(target_path))]
            # If both paths fail, fall back to the template
            return self.processor.write_file(anonymized_content, str(target_path), 'pdf')

        # Otherwise: fall back to template output
        return self.processor.write_file(anonymized_content, str(target_path), fmt or 'auto')

    @staticmethod
    def _expand_same_name_occurrences(text: str, entities: List) -> List:
        """
        For every identified person/company/institution, add the other occurrences across
        the whole document.
        Fixes: CN NER missing same-named entities in some contexts.
        """
        EXPAND_TYPES = {"person", "company", "institution", "law_firm", "government", "court"}
        by_position = {(p, p + len(t)): (t, ty) for t, ty, p in entities}
        known_names = {}  # name -> type (take the type from the first occurrence)
        for t, ty, p in entities:
            if ty in EXPAND_TYPES and len(t) >= 2:
                known_names.setdefault(t, ty)

        result = list(entities)
        existing_spans = [(p, p + len(t)) for t, _, p in entities]

        for name, ty in known_names.items():
            i = 0
            while True:
                idx = text.find(name, i)
                if idx == -1:
                    break
                end = idx + len(name)
                # Is there already an overlapping hit?
                overlapped = any(idx < oe and end > os_ for os_, oe in existing_spans)
                if not overlapped:
                    result.append((name, ty, idx))
                    existing_spans.append((idx, end))
                i = idx + 1
        return result

    @staticmethod
    def _add_distinctive_part_entities(text: str, entities: List) -> List:
        """
        From identified company/law firm/institution/court/government/bank entities,
        extract the "core brand word" after stripping prefixes and suffixes, then find
        where it appears on its own in the document and add it as an entity.

        Typical case: after detecting "XX (Shenzhen) Financial Leasing Co., Ltd.", a
        standalone "XX" elsewhere in the text should also be redacted.
        """
        # Only do brand expansion for company/law firm/institution/bank. Court and
        # government names are mostly administrative regions and do not brand-ize well.
        EXPAND_FROM = {"company", "law_firm", "institution", "bank_name"}

        # Leading noise words (strip first): e.g. "non-party", "plaintiff", "the above"
        # pollute the head of a brand word.
        common_leading_noise = sorted([
            '案外人', '第三人', '原告方', '被告方', '原告', '被告', '上述', '其',
            '现受', '本受', '该', '即', '向', '于', '在',
        ], key=len, reverse=True)

        # Administrative-region prefixes (stripped longest-first)
        common_prefixes = sorted([
            '中华人民共和国', '中华',
            '北京市', '上海市', '天津市', '重庆市',
            '广东省', '广州市', '深圳市', '佛山市', '东莞市', '中山市', '珠海市', '惠州市',
            '浙江省', '杭州市', '宁波市', '温州市',
            '江苏省', '南京市', '苏州市', '无锡市',
            '山东省', '济南市', '青岛市',
            '河北省', '河南省', '湖北省', '湖南省',
            '福建省', '厦门市', '泉州市',
            '四川省', '成都市',
            '陕西省', '西安市',
            '辽宁省', '大连市', '沈阳市',
            # Shenzhen districts
            '福田区', '罗湖区', '南山区', '宝安区', '龙岗区', '龙华区', '盐田区',
            '坪山区', '光明区', '大鹏新区', '前海区',
            # Other common districts
            '海淀区', '朝阳区', '东城区', '西城区', '丰台区', '通州区',
            '黄浦区', '徐汇区', '长宁区', '静安区', '浦东新区',
            '天河区', '越秀区', '海珠区', '荔湾区', '白云区', '番禺区',
            '北京', '上海', '天津', '重庆',
            '广东', '广州', '深圳', '佛山', '东莞', '中山', '珠海', '惠州',
            '浙江', '杭州', '宁波', '温州',
            '江苏', '南京', '苏州', '无锡',
            '山东', '济南', '青岛',
            '河北', '河南', '湖北', '湖南',
            '福建', '厦门', '泉州',
            '四川', '成都',
            '陕西', '西安',
            '辽宁', '大连', '沈阳',
            '中国',
        ], key=len, reverse=True)

        # Entity-type suffixes (stripped longest-first)
        common_suffixes = sorted([
            '律师事务所', '会计师事务所', '事务所',
            '股份有限公司', '有限责任公司', '集团有限公司', '有限公司',
            '集团公司', '集团', '公司', '股份',
            '人民检察院', '检察院',
            '人民政府', '管理委员会', '管委会', '司法厅', '司法部',
            '银行股份有限公司', '银行',
            '融资租赁', '租赁',
            # Industry modifiers (usually descriptors after a brand name, not the brand itself)
            '商贸', '建筑', '工程', '科技', '技术', '智能', '制造', '研发',
            '能源', '医疗', '教育', '咨询', '网络', '服务', '物流', '化工',
            '食品', '生物', '电子', '机械', '汽车', '地产', '房地产',
            '实业', '投资', '管理', '运营', '控股',
            # Property / building types
            '大厦', '广场', '中心', '大楼', '大酒店', '酒店', '商务',
        ], key=len, reverse=True)

        # Generic words that cannot stand alone as a brand (drop them even if extracted)
        BLACKLIST = {
            '公司', '集团', '事务所', '律师事务所', '律师', '法院',
            '银行', '中心', '大厦', '广场', '大楼', '政府', '检察院',
            '租赁', '股份', '有限', '关联', '物业', '商务', '世纪',
            '动产', '不动', '不动产', '动产权', '财产', '资产',
            '关联公司', '上述', '涉案', '本案', '该案',
            '工程', '建筑', '科技', '实业', '商贸', '管理', '运营',
            '其', '该', '本', '向',
        }

        # Collect existing spans to avoid duplicate additions
        existing_spans = [(p, p + len(t)) for t, _, p in entities]

        # Collect core brand -> type (keep the type from the first occurrence)
        brands = {}
        for ent_text, ent_type, _ in entities:
            if ent_type not in EXPAND_FROM:
                continue
            s = re.sub(r'[（(].*?[)）]', '', ent_text).strip()
            # Strip leading noise words first (connectors like "non-party"/"the above"/etc.)
            for noise in common_leading_noise:
                if s.startswith(noise) and len(s) > len(noise) + 1:
                    s = s[len(noise):]
                    break
            # Strip prefixes in a loop (administrative regions can stack, e.g.
            # "People's Republic of China + Guangdong Province + Shenzhen City")
            while True:
                stripped = False
                for p in common_prefixes:
                    if s.startswith(p) and len(s) > len(p) + 1:
                        s = s[len(p):]
                        stripped = True
                        break
                if not stripped:
                    break
            # Strip suffixes in a loop (entity suffixes can stack too, e.g. for
            # "Financial Leasing Co., Ltd." strip "Co., Ltd." first, then "Financial Leasing")
            while True:
                stripped = False
                for sfx in common_suffixes:
                    if s.endswith(sfx) and len(s) > len(sfx):
                        s = s[:-len(sfx)]
                        stripped = True
                        break
                if not stripped:
                    break
            s = s.strip()
            if not (2 <= len(s) <= 6 and re.fullmatch(r'[一-龥]+', s)):
                continue
            if s in BLACKLIST:
                continue
            brands.setdefault(s, ent_type)

        result = list(entities)
        for brand, ty in brands.items():
            for m in re.finditer(re.escape(brand), text):
                start = m.start()
                end = m.end()
                if any(start < oe and end > os_ for os_, oe in existing_spans):
                    continue
                result.append((brand, ty, start))
                existing_spans.append((start, end))
        return result

    @staticmethod
    def _merge_cn_ner(rule_hits: List, cn_hits: List) -> List:
        """
        Arbitrate and merge hits from the rules layer and the CN NER layer. Returns the
        merged list.

        Conflict handling (by priority):
          1. rule.person ∩ CN_NER.(company|institution|government) -> take CN NER, replace rule
          2. rule.person ∩ CN_NER.person and CN NER covers the rule -> take CN NER (longer span)
          3. other overlaps -> drop CN NER (rules win)
          4. no overlap -> keep CN NER
        """
        def span_overlaps(a_start, a_end, b_start, b_end):
            return a_start < b_end and b_start < a_end

        from detectors.cn_ner_detector import COMPOUND_SURNAMES

        def cn_wins(cn: Tuple[str, str, int], rule: Tuple[str, str, int]) -> bool:
            """Given an overlapping (cn_hit, rule_hit) pair, decide whether CN NER should win"""
            t, ty, p = cn; end = p + len(t)
            rt, rty, rp = rule; rend = rp + len(rt)
            # a) person <-> organization correction (a company name the rule mislabeled as
            #    person -> fix to company)
            if rty == "person" and ty in ("company", "institution", "government"):
                return True
            # b) person <-> person: CN NER starts with a compound surname, or is longer
            if rty == "person" and ty == "person":
                starts_with_compound = len(t) >= 3 and t[:2] in COMPOUND_SURNAMES
                if starts_with_compound or len(t) > len(rt):
                    return True
            # c) CN NER full address contains the rule's room-number/postcode fragment
            #    -> take CN NER
            if ty == "full_address" and rty in ("house_number", "postal_code", "full_address"):
                if p <= rp and end >= rend and len(t) > len(rt):
                    return True
            # d) CN NER hit is fully contained by a **same-type fragment** from the rules
            #    -> CN NER wins.
            #    Fix: greedy rule matching produces junk fragments like "verb + short
            #    company name" that occupy the short company name's (CN NER) position.
            #    CN NER confidence >= 0.8 (the default threshold) already means it is real.
            COMPAT = {
                "company": {"company"},
                "institution": {"institution", "company"},
                "government": {"government"},
                "person": {"person"},
                "full_address": {"full_address", "house_number"},
            }
            if ty in COMPAT and rty in COMPAT[ty]:
                # rule strictly contains cn, and cn is at least half the rule's length
                # (avoids misjudging short fragments)
                if rp <= p and rend >= end and len(rt) > len(t) and len(t) * 2 >= len(rt):
                    return True
            return False

        result = list(rule_hits)
        to_drop = set()

        for cn in cn_hits:
            t, ty, p = cn; end = p + len(t)
            overlapping = []
            for i, rule in enumerate(result):
                if i in to_drop:
                    continue
                rt, rty, rp = rule; rend = rp + len(rt)
                if span_overlaps(p, end, rp, rend):
                    overlapping.append((i, rule))

            if not overlapping:
                result.append(cn)
                continue

            # Check all overlapping items: only take CN NER if it wins against every one
            if all(cn_wins(cn, rule) for _, rule in overlapping):
                for i, _ in overlapping:
                    to_drop.add(i)
                result.append(cn)
            # Otherwise drop the CN NER hit (rules win)

        if to_drop:
            result = [x for i, x in enumerate(result) if i not in to_drop]
        return result

    def _build_analysis(self, all_entities: List, text: str = None, context_window: int = 0) -> Dict:
        """
        Build an analysis report from the detection results

        Args:
            all_entities: list of entities
            text: original text (when provided, context is attached; otherwise only the
                  entity name is returned)
            context_window: context window size (characters), 0 = no context
        """
        findings = {}
        for entity_text, entity_type, pos in all_entities:
            if entity_type not in findings:
                findings[entity_type] = []

            if text and context_window > 0:
                ctx_before = text[max(0, pos - context_window):pos].replace('\n', ' ')
                ctx_after = text[pos + len(entity_text):pos + len(entity_text) + context_window].replace('\n', ' ')
                entry = {
                    "text": entity_text,
                    "context": f"…{ctx_before}【{entity_text}】{ctx_after}…"
                }
                if not any(e["text"] == entity_text for e in findings[entity_type]):
                    findings[entity_type].append(entry)
            else:
                if entity_text not in findings[entity_type]:
                    findings[entity_type].append(entity_text)

        return {
            "findings": findings,
            "total_findings": len(all_entities),
            "type_count": len(findings)
        }

    def anonymize_text(
        self,
        text: str,
        only_types: List[str] = None,
        exclude_types: List[str] = None
    ) -> Tuple[str, Dict]:
        """
        Anonymize text

        Args:
            text: original text
            only_types: only redact the given types
            exclude_types: exclude the given types

        Returns:
            (anonymized text, detailed mapping info)
        """
        self.masker.reset()
        all_entities = self._detect_all(text, only_types, exclude_types)
        anonymized_text, mapping = self.masker.mask_all(text, all_entities)
        return anonymized_text, mapping

    def analyze_text(
        self,
        text: str,
        only_types: List[str] = None,
        exclude_types: List[str] = None,
        with_context: bool = False,
        context_window: int = 40
    ) -> Dict:
        """
        Analyze sensitive information in text (without actually redacting)

        Args:
            with_context: whether to attach surrounding context to the results
            context_window: context window size (characters); only used when with_context=True

        Returns:
            the analysis result; when with_context=True each finding is a {text, context} dict
        """
        all_entities = self._detect_all(text, only_types, exclude_types)
        return self._build_analysis(
            all_entities,
            text=text if with_context else None,
            context_window=context_window if with_context else 0
        )

    def anonymize_file(
        self,
        input_path: str,
        output_path: str = None,
        custom_entities: List[Dict] = None,
        output_format=None,
        only_types: List[str] = None,
        exclude_types: List[str] = None,
        use_ocr: bool = False,
        ocr_engine: str = 'rapidocr',
        save_text_backup: bool = True,
        save_mapping: bool = True,
        pdf_whitebox: bool = False,
    ) -> Dict:
        """
        Anonymize a file

        Args:
            input_path: input file path
            output_path: output file path
            custom_entities: list of custom entities
            output_format: output format. str='auto/txt/md/pdf/docx', or a list to emit
                           several formats at once, e.g. ['md','docx','pdf'] produces three
                           files (recommended). None/'auto' infers from the output suffix.
            only_types: only redact the given types
            exclude_types: exclude the given types
            use_ocr: whether to use OCR for scanned PDFs
            ocr_engine: OCR engine 'rapidocr' (default) | 'paddleocr' (slow but accurate) | 'tesseract'
            save_text_backup: whether to save a text backup
            save_mapping: whether to save the mapping table

        Returns:
            result dict
        """
        input_path = Path(input_path)

        if not input_path.exists():
            return {"error": f"File not found: {input_path}"}

        # Add custom entities (clear leftovers first to avoid cross-call contamination)
        self.entity_detector.clear()
        if custom_entities:
            self.add_custom_entities(custom_entities)

        # Extract text
        try:
            content = self.processor.extract_text(str(input_path), use_ocr=use_ocr, ocr_engine=ocr_engine)
        except Exception as e:
            return {"error": f"Failed to read file: {e}"}

        if not content.strip():
            return {"error": "File content is empty"}

        # Detect once, used for both analysis and redaction (avoids detecting twice)
        self.masker.reset()
        all_entities = self._detect_all(content, only_types, exclude_types)
        analysis = self._build_analysis(all_entities)
        anonymized_content, detailed_mapping = self.masker.mask_all(content, all_entities)

        # Prepare the result
        result_info = {
            "input_file": str(input_path),
            "analysis": analysis,
            "anonymized_content": anonymized_content,
            "mapping": detailed_mapping["mapping"],
            "total_matched": detailed_mapping["metadata"]["entity_count"],
            "replacements_made": detailed_mapping["metadata"]["replacements_made"],
            "replacement_log": detailed_mapping["replacement_log"]
        }

        # Save output
        if output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            saved_files = []

            # Parse output_format: supports list (multi-format), str (single), None (auto)
            input_suffix = input_path.suffix.lower()
            if output_format is None or output_format == 'auto':
                formats = [self.processor._guess_format(output_path)]
            elif isinstance(output_format, str):
                formats = [output_format]
            elif isinstance(output_format, (list, tuple)):
                formats = list(output_format)
            else:
                formats = [self.processor._guess_format(output_path)]

            # Generate one file per format
            for fmt in formats:
                main_files = self._write_format(
                    fmt=fmt,
                    input_path=input_path,
                    output_path=output_path,
                    input_suffix=input_suffix,
                    anonymized_content=anonymized_content,
                    use_ocr=use_ocr,
                    ocr_engine=ocr_engine,
                    whitebox_only=pdf_whitebox,
                )
                saved_files.extend(main_files)

            # Save a text backup (only when no text-format output was produced)
            if save_text_backup:
                has_text = any(k in ('output_txt', 'output_md') for k, _ in saved_files)
                if not has_text:
                    txt_path = output_path.parent / f"{output_path.stem}.txt"
                    self.processor._write_plain_text(anonymized_content, str(txt_path))
                    saved_files.append(("text_backup", str(txt_path)))

            # Save the mapping table
            if save_mapping:
                mapping_path = output_path.parent / f"{output_path.stem}_mapping.json"
                self.processor.write_mapping(detailed_mapping, str(mapping_path))
                saved_files.append(("mapping_file", str(mapping_path)))

            # Update the result info
            for key, path in saved_files:
                result_info[key] = path

        return {
            "action": "anonymize_file",
            "status": "success",
            "result": result_info
        }

    def analyze_file(
        self,
        input_path: str,
        only_types: List[str] = None,
        exclude_types: List[str] = None,
        use_ocr: bool = False,
        ocr_engine: str = 'rapidocr',
        with_context: bool = False,
        context_window: int = 40
    ) -> Dict:
        """
        Analyze a file (without actually redacting)

        Args:
            input_path: input file path
            only_types: only analyze the given types
            exclude_types: exclude the given types
            use_ocr: whether to use OCR
            ocr_engine: OCR engine 'rapidocr' (default) | 'paddleocr' | 'tesseract'
            with_context: whether to attach surrounding context
            context_window: context window size (characters)

        Returns:
            the analysis result
        """
        input_path = Path(input_path)

        if not input_path.exists():
            return {"error": f"File not found: {input_path}"}

        try:
            content = self.processor.extract_text(str(input_path), use_ocr=use_ocr, ocr_engine=ocr_engine)
        except Exception as e:
            return {"error": f"Failed to read file: {e}"}

        analysis = self.analyze_text(content, only_types, exclude_types,
                                     with_context=with_context, context_window=context_window)

        return {
            "action": "analyze_file",
            "status": "success",
            "result": {
                "input_file": str(input_path),
                "analysis": analysis
            }
        }

    def get_supported_types(self) -> Dict[str, str]:
        """Get all supported types and their descriptions"""
        return self.pattern_detector.get_all_types()

    def reset(self):
        """Reset state"""
        self.masker.reset()
        self.entity_detector.clear()
