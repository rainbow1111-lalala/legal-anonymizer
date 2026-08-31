"""PDF security helpers for mixed-page routing and residual verification."""

from __future__ import annotations

import re
import tempfile
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _load_pdf_runtime():
    try:
        import fitz
        import processors.file_processor as fp_module
    except Exception:
        return None, None, None

    try:
        from PIL import Image
    except Exception:
        Image = None

    return fitz, Image, fp_module


def _page_needs_ocr(native_text: str, use_ocr: bool, has_ocr: bool) -> bool:
    """Mirror FileProcessor._extract_pdf_text's page-level OCR decision."""
    text_len = len((native_text or '').strip())
    need_ocr = bool(use_ocr) or (has_ocr and text_len < 50)
    if use_ocr and text_len >= 200:
        need_ocr = False
    return need_ocr


def build_pdf_page_plan(pdf_path: str, use_ocr: bool = False) -> List[bool]:
    """Return one route decision per page; True means visual/OCR redaction."""
    fitz, _, fp_module = _load_pdf_runtime()
    if fitz is None:
        return []

    try:
        doc = fitz.open(pdf_path)
        try:
            return [
                _page_needs_ocr(
                    page.get_text(), use_ocr, bool(fp_module.HAS_OCR)
                )
                for page in doc
            ]
        finally:
            doc.close()
    except Exception:
        return []


def anonymize_pdf_with_page_plan(
    processor,
    input_path: str,
    output_path: str,
    mapping: dict,
    page_plan: List[bool],
    ocr_engine: str = 'rapidocr',
    whitebox_only: bool = False,
) -> bool:
    """Render PDF using a page-level native/visual redaction plan.

    Pure native and pure scanned PDFs keep the existing optimized paths. Mixed
    PDFs are split page-by-page so an image page cannot accidentally pass
    through native-only redaction because earlier pages contain text.
    """
    fitz, _, _ = _load_pdf_runtime()
    if fitz is None or not page_plan:
        return False

    if all(not use_visual for use_visual in page_plan):
        return processor.anonymize_pdf_inplace(
            input_path, output_path, mapping, whitebox_only=whitebox_only
        )

    if all(page_plan):
        return processor.anonymize_scanned_pdf_inplace(
            input_path,
            output_path,
            mapping,
            ocr_engine,
            whitebox_only=whitebox_only,
        )

    try:
        source = fitz.open(input_path)
        if source.page_count != len(page_plan):
            source.close()
            return False

        out_doc = fitz.open()
        try:
            with tempfile.TemporaryDirectory(prefix='legal-anonymizer-mixed-') as tmp:
                tmp_dir = Path(tmp)

                for page_index, use_visual in enumerate(page_plan):
                    page_in = tmp_dir / f'page_{page_index + 1}_in.pdf'
                    page_out = tmp_dir / f'page_{page_index + 1}_out.pdf'

                    one_page = fitz.open()
                    one_page.insert_pdf(
                        source, from_page=page_index, to_page=page_index
                    )
                    one_page.save(str(page_in))
                    one_page.close()

                    if use_visual:
                        ok = processor.anonymize_scanned_pdf_inplace(
                            str(page_in),
                            str(page_out),
                            mapping,
                            ocr_engine,
                            whitebox_only=whitebox_only,
                        )
                    else:
                        ok = processor.anonymize_pdf_inplace(
                            str(page_in),
                            str(page_out),
                            mapping,
                            whitebox_only=whitebox_only,
                        )

                    if not ok or not page_out.exists():
                        return False

                    redacted_page = fitz.open(str(page_out))
                    try:
                        out_doc.insert_pdf(redacted_page)
                    finally:
                        redacted_page.close()

            out_doc.save(output_path, deflate=True, garbage=3)
            return True
        finally:
            out_doc.close()
            source.close()
    except Exception:
        return False


def _normalize(value: str) -> str:
    value = unicodedata.normalize('NFKC', str(value or ''))
    return re.sub(r'\s+', '', value)


def _known_originals(mapping: dict) -> List[Tuple[str, str]]:
    originals: List[Tuple[str, str]] = []
    for key, masked in (mapping or {}).items():
        if not isinstance(key, tuple) or len(key) != 2:
            continue
        entity_type, original = key
        normalized = _normalize(original)
        if original and masked and len(normalized) >= 2:
            originals.append((str(entity_type), normalized))
    return originals


def verify_pdf_no_residuals(
    processor,
    pdf_path: str,
    mapping: dict,
    ocr_engine: str = 'rapidocr',
    required_ocr_pages: Optional[List[bool]] = None,
) -> Tuple[bool, List[Dict]]:
    """Scan generated PDF for known originals in text and rendered pixels.

    The scan intentionally does not return the sensitive original value in its
    issue records, so diagnostic logs cannot become another disclosure path.
    OCR-routed pages are fail-closed when the verification OCR pass itself is
    unavailable or produces no usable text.
    """
    fitz, Image, fp_module = _load_pdf_runtime()
    if fitz is None:
        return False, [{'reason': 'pymupdf_unavailable'}]

    originals = _known_originals(mapping)
    if not originals:
        return True, []

    issues: List[Dict] = []

    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return False, [{'reason': 'output_unreadable'}]

    try:
        for page_index, page in enumerate(doc):
            page_num = page_index + 1
            native_text = _normalize(page.get_text('text'))

            for entity_type, normalized in originals:
                if normalized in native_text:
                    issues.append({
                        'page': page_num,
                        'surface': 'text',
                        'entity_type': entity_type,
                        'reason': 'known_original_residual',
                    })

            must_verify_ocr = bool(
                required_ocr_pages
                and page_index < len(required_ocr_pages)
                and required_ocr_pages[page_index]
            )

            # Always attempt a pixel-level verification when OCR is available;
            # it catches image residuals that PDF text extraction cannot see.
            ocr_text = ''
            ocr_attempted = False
            if Image is not None and fp_module is not None and fp_module.HAS_OCR:
                try:
                    ocr_attempted = True
                    pix = page.get_pixmap(
                        matrix=fitz.Matrix(2.08, 2.08), alpha=False
                    )
                    img = Image.frombytes(
                        'RGB', [pix.width, pix.height], pix.samples
                    )
                    pix = None
                    ocr_text = processor._ocr_image(img, ocr_engine) or ''
                except Exception:
                    ocr_text = ''

            normalized_ocr = _normalize(ocr_text)
            if normalized_ocr:
                for entity_type, normalized in originals:
                    if normalized in normalized_ocr:
                        issues.append({
                            'page': page_num,
                            'surface': 'ocr',
                            'entity_type': entity_type,
                            'reason': 'known_original_residual',
                        })
            elif must_verify_ocr:
                issues.append({
                    'page': page_num,
                    'surface': 'ocr',
                    'reason': (
                        'verification_ocr_empty'
                        if ocr_attempted
                        else 'verification_ocr_unavailable'
                    ),
                })
    finally:
        doc.close()

    # Keep diagnostics deterministic and compact.
    deduped: List[Dict] = []
    seen = set()
    for issue in issues:
        key = tuple(sorted(issue.items()))
        if key not in seen:
            seen.add(key)
            deduped.append(issue)

    return not deduped, deduped
