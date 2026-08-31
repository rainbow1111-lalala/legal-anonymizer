"""Compatibility wrapper with fail-closed PDF security routing.

The original implementation is preserved in ``anonymizer_legacy.py``.  This
module keeps the public import path stable while tightening PDF output safety:
page-level routing for mixed PDFs and post-generation residual verification.
"""

from pathlib import Path
from typing import List, Tuple

from anonymizer_legacy import *  # noqa: F401,F403
from anonymizer_legacy import LegalAnonymizer as _LegacyLegalAnonymizer
from pdf_security import (
    anonymize_pdf_with_page_plan,
    build_pdf_page_plan,
    verify_pdf_no_residuals,
)


class LegalAnonymizer(_LegacyLegalAnonymizer):
    """Legacy anonymizer with fail-closed PDF rendering and verification."""

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
        fmt = (fmt or '').lower()

        # Non-PDF paths keep the existing behavior unchanged.
        if fmt != 'pdf' or input_suffix != '.pdf':
            return super()._write_format(
                fmt=fmt,
                input_path=input_path,
                output_path=output_path,
                input_suffix=input_suffix,
                anonymized_content=anonymized_content,
                use_ocr=use_ocr,
                ocr_engine=ocr_engine,
                whitebox_only=whitebox_only,
            )

        target_path = output_path.with_suffix('.pdf')

        # Detection already makes its OCR decision page by page.  Build the
        # output route with the same thresholds instead of classifying the
        # whole document from the first few pages.
        page_plan = build_pdf_page_plan(str(input_path), use_ocr=use_ocr)
        if not page_plan:
            return self.processor.write_file(
                anonymized_content, str(target_path), 'pdf'
            )

        rendered = anonymize_pdf_with_page_plan(
            processor=self.processor,
            input_path=str(input_path),
            output_path=str(target_path),
            mapping=self.masker.mapping,
            page_plan=page_plan,
            ocr_engine=ocr_engine,
            whitebox_only=whitebox_only,
        )

        if rendered:
            verified, issues = verify_pdf_no_residuals(
                processor=self.processor,
                pdf_path=str(target_path),
                mapping=self.masker.mapping,
                ocr_engine=ocr_engine,
                required_ocr_pages=page_plan,
            )
            if verified:
                return [('output_pdf', str(target_path))]

            # Do not leave an unverified artifact behind or expose original
            # sensitive values in logs.  The fallback below only contains the
            # already-anonymized text.
            print(
                f"[安全校验] PDF 残留扫描未通过（{len(issues)} 项），改用安全模板输出",
                flush=True,
            )
            try:
                target_path.unlink(missing_ok=True)
            except Exception:
                pass

        # Fail closed: if mixed rendering or residual verification cannot be
        # completed, return a regenerated PDF made from anonymized text rather
        # than the original-layout PDF whose safety is uncertain.
        return self.processor.write_file(
            anonymized_content, str(target_path), 'pdf'
        )
