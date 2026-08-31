import tempfile
import unittest
from pathlib import Path

try:
    import fitz
except ImportError:  # pragma: no cover
    fitz = None

from pdf_security import (
    anonymize_pdf_with_page_plan,
    build_pdf_page_plan,
    verify_pdf_no_residuals,
)


@unittest.skipUnless(fitz is not None, 'PyMuPDF required')
class PDFSecurityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _make_pdf(self, path: Path, page_texts):
        doc = fitz.open()
        for text in page_texts:
            page = doc.new_page()
            if text:
                page.insert_text((72, 72), text)
        doc.save(str(path))
        doc.close()

    def test_page_plan_is_page_scoped_for_mixed_pdf(self):
        path = self.root / 'mixed.pdf'
        dense = 'A' * 220
        self._make_pdf(path, [dense, dense, dense, ''])

        plan = build_pdf_page_plan(str(path), use_ocr=True)

        self.assertEqual(plan, [False, False, False, True])

    def test_mixed_renderer_uses_native_and_visual_routes(self):
        source = self.root / 'mixed.pdf'
        output = self.root / 'out.pdf'
        self._make_pdf(source, ['native page', ''])

        class FakeProcessor:
            def __init__(self):
                self.calls = []

            def _copy(self, kind, input_path, output_path):
                self.calls.append(kind)
                doc = fitz.open(input_path)
                doc.save(output_path)
                doc.close()
                return True

            def anonymize_pdf_inplace(self, input_path, output_path, mapping, **kwargs):
                return self._copy('native', input_path, output_path)

            def anonymize_scanned_pdf_inplace(self, input_path, output_path, mapping, *args, **kwargs):
                return self._copy('visual', input_path, output_path)

        processor = FakeProcessor()
        ok = anonymize_pdf_with_page_plan(
            processor=processor,
            input_path=str(source),
            output_path=str(output),
            mapping={},
            page_plan=[False, True],
        )

        self.assertTrue(ok)
        self.assertEqual(processor.calls, ['native', 'visual'])
        doc = fitz.open(str(output))
        self.assertEqual(doc.page_count, 2)
        doc.close()

    def test_residual_scan_rejects_known_native_text(self):
        path = self.root / 'leak.pdf'
        secret = 'WMH-SECRET-928374'
        self._make_pdf(path, [secret])

        class NoOCRProcessor:
            pass

        ok, issues = verify_pdf_no_residuals(
            processor=NoOCRProcessor(),
            pdf_path=str(path),
            mapping={('secret', secret): '[SECRET_1]'},
            required_ocr_pages=[False],
        )

        self.assertFalse(ok)
        self.assertTrue(any(i.get('surface') == 'text' for i in issues))
        # Diagnostic output must not echo the sensitive original.
        self.assertNotIn(secret, repr(issues))

    def test_clean_native_output_passes_known_original_scan(self):
        path = self.root / 'clean.pdf'
        secret = 'WMH-SECRET-928374'
        self._make_pdf(path, ['[SECRET_1]'])

        class NoOCRProcessor:
            pass

        ok, issues = verify_pdf_no_residuals(
            processor=NoOCRProcessor(),
            pdf_path=str(path),
            mapping={('secret', secret): '[SECRET_1]'},
            required_ocr_pages=[False],
        )

        self.assertTrue(ok, issues)


if __name__ == '__main__':
    unittest.main()
