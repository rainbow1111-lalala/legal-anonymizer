"""
File Processor - Handles reading/writing various file formats
"""

import os
import sys
import json
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any

# Try importing optional dependencies
try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False

try:
    from docx import Document
    from docx.shared import Pt, RGBColor
    from docx.oxml.ns import qn
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.enums import TA_LEFT
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    from rapidocr import RapidOCR as _RapidOCR
    HAS_RAPIDOCR = True
except ImportError:
    HAS_RAPIDOCR = False


def _io_bytes_png(pil_image) -> bytes:
    """PIL Image -> PNG bytes, avoids writing a temp file each time"""
    import io as _io
    buf = _io.BytesIO()
    pil_image.save(buf, format='PNG')
    return buf.getvalue()

try:
    from paddleocr import PaddleOCR as _PaddleOCR
    HAS_PADDLEOCR = True
except ImportError:
    HAS_PADDLEOCR = False

try:
    import pytesseract
    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False

# At least one OCR engine is available
HAS_OCR = HAS_PIL and (HAS_RAPIDOCR or HAS_PADDLEOCR or HAS_TESSERACT)


class FileProcessor:
    """File processor"""

    # Engine singleton cache
    _rapidocr_instance = None
    _paddle_ocr_instance = None

    @classmethod
    def _get_rapidocr(cls):
        """Lazy-load the RapidOCR instance (default engine, lightweight and fast)"""
        if cls._rapidocr_instance is None and HAS_RAPIDOCR:
            cls._rapidocr_instance = _RapidOCR()
        return cls._rapidocr_instance

    @classmethod
    def _get_paddle_ocr(cls):
        """Lazy-load the PaddleOCR instance (accurate mode, slower but stronger on complex layouts)"""
        if cls._paddle_ocr_instance is None and HAS_PADDLEOCR:
            # PaddleOCR 3.5 uses the mobile model (the server model is too slow for CPU inference)
            cls._paddle_ocr_instance = _PaddleOCR(
                lang='ch',
                use_textline_orientation=True,
                text_detection_model_name='PP-OCRv5_mobile_det',
                text_recognition_model_name='PP-OCRv5_mobile_rec',
            )
        return cls._paddle_ocr_instance

    def __init__(self):
        self.supported_formats = {
            'input': ['.txt', '.md', '.pdf', '.docx', '.doc'],
            'output': ['.txt', '.md', '.pdf', '.docx']
        }

    def extract_text(self, file_path: str, use_ocr: bool = False, ocr_engine: str = 'rapidocr',
                     progress_callback=None) -> str:
        """
        Extract text from a file

        Args:
            file_path: file path
            use_ocr: whether to use OCR (PDF/image only)
            ocr_engine: 'rapidocr' (default, fast) | 'paddleocr' (slow but accurate) | 'tesseract' (fallback)
            progress_callback: optional progress callback, signature fn(stage:str, current:int, total:int)
                              stage can be 'ocr_page_done' / 'extract_done'

        Returns:
            the extracted text content
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        suffix = path.suffix.lower()

        if suffix == '.pdf':
            text = self._extract_pdf_text(file_path, use_ocr, ocr_engine, progress_callback=progress_callback)
        elif suffix == '.docx':
            text = self._extract_docx_text(file_path)
        elif suffix == '.doc':
            text = self._extract_doc_text(file_path)
        elif suffix in ['.txt', '.md']:
            text = self._extract_plain_text(file_path)
        elif suffix in ['.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.gif', '.webp']:
            text = self._extract_image_text(file_path, ocr_engine)
        else:
            # By default, try reading it as a text file
            try:
                text = self._extract_plain_text(file_path)
            except:
                raise ValueError(f"Unsupported file format: {suffix}")

        # Merge line breaks between CJK characters: PDF extraction layout can insert line breaks
        # between Chinese characters (e.g. "XX\n公司", "姓\n名"), splitting one entity into
        # multiple fragments. Normalize before handing off to the detection layer.
        return self._normalize_cjk_linebreaks(text)

    @staticmethod
    def _normalize_cjk_linebreaks(text: str) -> str:
        """
        1. Strip control characters not allowed in XML (NULL bytes, etc.) -- common in OCR output
        2. Merge a single line break between two Chinese characters (keep paragraph breaks = consecutive line breaks)
        """
        import re
        # First strip XML-illegal control characters, to avoid downstream docx/PDF write failures
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
        # A single \n (Chinese on both sides), replace with nothing
        text = re.sub(r'([一-龥])\n([一-龥])', r'\1\2', text)
        # Chinese + \n + Chinese punctuation
        text = re.sub(r'([一-龥])\n([（）《》、，。；：])', r'\1\2', text)
        text = re.sub(r'([（《、，。；：])\n([一-龥])', r'\1\2', text)
        # Line break joining a digit and Chinese (address "宿舍6 栋\n102", case number "（2006）192\n号")
        text = re.sub(r'([一-龥])\n(\d)', r'\1\2', text)
        text = re.sub(r'(\d)\n([一-龥])', r'\1\2', text)
        # Line break between Chinese and Latin letters (e.g. "SOHO现代城A座1203\n室")
        text = re.sub(r'([一-龥])\n([A-Za-z])', r'\1\2', text)
        text = re.sub(r'([A-Za-z])\n([一-龥])', r'\1\2', text)
        return text

    def _extract_pdf_text(self, pdf_path: str, use_ocr: bool = False, ocr_engine: str = 'rapidocr',
                          progress_callback=None) -> str:
        """Extract text from a PDF. ocr_engine: rapidocr (default) | paddleocr | tesseract"""
        if not HAS_PYMUPDF:
            raise ImportError("PyMuPDF is required: pip install pymupdf")

        import time as _time
        from concurrent.futures import ThreadPoolExecutor

        doc = fitz.open(pdf_path)
        page_count = doc.page_count

        # First decide per page whether to OCR or extract directly (PDF rendering must run on the
        # main thread; PyMuPDF Page is not thread-safe)
        page_jobs = []  # [(page_num, native_text, ocr_image_or_None)]
        for page_num, page in enumerate(doc, 1):
            native_text = page.get_text()
            need_ocr = use_ocr or (HAS_OCR and len(native_text.strip()) < 50)
            # use_ocr=True but the page already has an adequate text layer: do not force OCR (saves 5-10x time)
            if use_ocr and len(native_text.strip()) >= 200:
                need_ocr = False

            ocr_img = None
            if need_ocr and HAS_PIL:
                # Render the pixmap on the main thread (150 DPI)
                pix = page.get_pixmap(matrix=fitz.Matrix(2.08, 2.08))
                ocr_img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                pix = None  # release early
            page_jobs.append((page_num, native_text, ocr_img))

        doc.close()  # release PDF resources, no longer needed during the OCR stage

        ocr_pages = sum(1 for _, _, img in page_jobs if img is not None)
        if ocr_pages > 0:
            print(f"[OCR] {page_count} pages total, {ocr_pages} need OCR (the rest extract the text layer directly)", flush=True)

        # Multithreading: ONNX Runtime is already multithreaded internally; 2 workers already saturate the CPU.
        # Too many workers add memory pressure with diminishing returns.
        max_workers = min(2, ocr_pages or 1)

        # Use a counter, safe under multithreading (the GIL protects int += 1)
        ocr_done_counter = [0]
        ocr_total = ocr_pages

        def process_page(job):
            page_num, native_text, ocr_img = job
            t0 = _time.time()
            if ocr_img is not None:
                text = self._ocr_image(ocr_img, ocr_engine)
                text = self._fix_ocr_text(text)
                elapsed = _time.time() - t0
                print(f"[OCR] Page {page_num}/{page_count} done, took {elapsed:.1f}s", flush=True)
                ocr_done_counter[0] += 1
                if progress_callback:
                    try:
                        progress_callback('ocr_page_done', ocr_done_counter[0], ocr_total)
                    except Exception:
                        pass
            else:
                text = self._fix_line_breaks(native_text)
            return page_num, text

        text_parts = [None] * page_count
        if max_workers > 1 and ocr_pages > 1:
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                for page_num, text in pool.map(process_page, page_jobs):
                    text_parts[page_num - 1] = text
        else:
            for job in page_jobs:
                page_num, text = process_page(job)
                text_parts[page_num - 1] = text

        return '\n\n'.join(text_parts)

    def _ocr_pdf_page(self, page, ocr_engine: str = 'rapidocr') -> str:
        """OCR a PDF page. Render to an image first, then call the engine"""
        if not HAS_PIL:
            return ""

        try:
            # Render at 150 DPI (sharp enough for legal documents, about 30% faster than 200 DPI)
            pix = page.get_pixmap(matrix=fitz.Matrix(2.08, 2.08))  # 2.08 x 72 ~ 150
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            return self._ocr_image(img, ocr_engine)
        except Exception:
            return ""

    def _ocr_image(self, img, ocr_engine: str = 'rapidocr') -> str:
        """OCR a PIL Image, trying engines in the given priority order"""
        # Try engines in the specified order
        engines_order = []
        if ocr_engine == 'paddleocr':
            engines_order = ['paddleocr', 'rapidocr', 'tesseract']
        elif ocr_engine == 'tesseract':
            engines_order = ['tesseract', 'rapidocr', 'paddleocr']
        else:  # default rapidocr
            engines_order = ['rapidocr', 'paddleocr', 'tesseract']

        for eng in engines_order:
            try:
                if eng == 'rapidocr' and HAS_RAPIDOCR:
                    return self._ocr_with_rapidocr(img)
                if eng == 'paddleocr' and HAS_PADDLEOCR:
                    return self._ocr_with_paddleocr(img)
                if eng == 'tesseract' and HAS_TESSERACT:
                    return self._ocr_with_tesseract(img)
            except Exception:
                continue

        return ""

    def _ocr_with_rapidocr(self, img) -> str:
        """RapidOCR implementation: fast, lightweight, the default choice
        Optimization: pass the numpy array directly, skipping PNG encoding (saves 200-500ms per page)
        """
        import numpy as np
        ocr = self._get_rapidocr()
        # PIL Image -> numpy (RapidOCR accepts numpy arrays directly)
        img_array = np.array(img)
        result = ocr(img_array)
        if result and result.txts:
            lines = []
            for txt, score in zip(result.txts, result.scores or []):
                if score > 0.5:
                    lines.append(txt)
            return '\n'.join(lines) if lines else '\n'.join(result.txts)
        return ""

    def _ocr_with_paddleocr(self, img) -> str:
        """PaddleOCR 3.5 implementation: slow but more accurate on complex layouts"""
        import numpy as np
        ocr = self._get_paddle_ocr()
        img_array = np.array(img)
        result = ocr.predict(img_array)
        if result:
            lines = []
            for page_result in result:
                # PaddleOCR 3.5 returns a dict-like result containing rec_texts / rec_scores
                rec_texts = page_result.get('rec_texts') if hasattr(page_result, 'get') else None
                rec_scores = page_result.get('rec_scores') if hasattr(page_result, 'get') else None
                if rec_texts:
                    if rec_scores:
                        for t, s in zip(rec_texts, rec_scores):
                            if s > 0.6:
                                lines.append(t)
                    else:
                        lines.extend(rec_texts)
            return '\n'.join(lines)
        return ""

    def _ocr_with_tesseract(self, img) -> str:
        """Tesseract fallback"""
        custom_config = r'-l chi_sim+eng --oem 1 --psm 6'
        return pytesseract.image_to_string(img, config=custom_config)

    def _fix_ocr_text(self, text: str) -> str:
        """Fix line-break and spacing issues in OCR-extracted text so sentences flow"""
        import re

        # Step 1: remove OCR noise characters (vertical bars, garbage from scan edges, etc.)
        # Drop trailing/leading | and other common OCR noise
        text = re.sub(r'\s*\|\s*', '', text)
        # Drop isolated garbage characters (lone chars that are not Chinese, ASCII alphanumeric, or punctuation)
        # Keep Chinese, Latin letters, digits, and common punctuation
        text = re.sub(r'(?<=[。，、；：！？）\)）])\s*[a-zA-Z]{1,3}\s*(?=\n|$)', '', text)

        # Step 2: clean up extra whitespace
        # Collapse consecutive spaces into one
        text = re.sub(r'[ \t]{2,}', ' ', text)

        # Step 3: drop spaces between Chinese characters
        # Run multiple passes to ensure all are removed
        for _ in range(3):
            text = re.sub(r'([\u4e00-\u9fa5])\s+([\u4e00-\u9fa5])', r'\1\2', text)
        # Extra spaces between Chinese and digits
        text = re.sub(r'([\u4e00-\u9fa5])\s+(\d)', r'\1\2', text)
        text = re.sub(r'(\d)\s+([\u4e00-\u9fa5])', r'\1\2', text)
        # Spaces between Chinese and punctuation
        text = re.sub(r'([\u4e00-\u9fa5])\s+([，。、；：！？）\)》」』】])', r'\1\2', text)
        text = re.sub(r'([（\(《「『【])\s+([\u4e00-\u9fa5])', r'\1\2', text)

        # Step 4: merge broken lines
        lines = text.split('\n')
        merged_lines = []
        buffer = ''

        for line in lines:
            stripped = line.strip()

            # Skip empty lines
            if not stripped:
                if buffer:
                    merged_lines.append(buffer)
                    buffer = ''
                continue

            # Skip pure-noise lines (short lines with no Chinese or digits)
            clean_chars = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fa5]', '', stripped)
            if len(clean_chars) < 2:
                continue

            if not buffer:
                buffer = stripped
            else:
                last_char = buffer[-1] if buffer else ''

                # Only break paragraphs at clear sentence-ending punctuation
                if last_char in '。！？':
                    merged_lines.append(buffer)
                    buffer = stripped
                else:
                    # In all other cases, merge (including comma/semicolon endings)
                    buffer += stripped

        if buffer:
            merged_lines.append(buffer)

        return '\n'.join(merged_lines)

    def _fix_line_breaks(self, text: str) -> str:
        """Fix common line-break splitting in PDF text extraction (non-OCR mode)"""
        import re

        # Fix organization names split by line breaks (general rule)
        org_suffixes = (
            r'有限公司|有限责任公司|股份有限公司|股份公司'
            r'|集团公司|集团|律师事务所|会计师事务所|公证处'
            r'|人民法院|人民检察院|人民政府'
            r'|公安局|派出所|管理局|监督局|委员会'
            r'|居委会|村委会|街道办事处|办事处'
            r'|研究院|研究所|实验室|大学|学院|医院'
            r'|银行|信用社|基金会|协会|商会|学会'
        )
        text = re.sub(
            rf'([\u4e00-\u9fa5]{{1,15}})\n({org_suffixes})',
            r'\1\2', text
        )

        # Fix the case where a company name breaks before its suffix
        # e.g. "国新健康保障服\n务集团股份有限公司" -> joined
        # No strict lookbehind, because formats like PDF signature pages may be followed directly by "年月日"
        text = re.sub(
            rf'([\u4e00-\u9fa5])'
            rf'\n'
            rf'([\u4e00-\u9fa5]{{1,20}}(?:{org_suffixes}))',
            r'\1\2', text
        )

        # Fix common words split by line breaks
        text = re.sub(
            r'([\u4e00-\u9fa5])(?<![。！？；：，、）》」』】])\n(?=[\u4e00-\u9fa5]{1,3}(?:[。！？；：，、）》」』】\n]|$))',
            r'\1', text
        )

        return text

    def _extract_doc_text(self, doc_path: str) -> str:
        """Extract text from a legacy .doc file"""
        import subprocess
        import platform

        # macOS: use textutil
        if platform.system() == 'Darwin':
            try:
                result = subprocess.run(
                    ['textutil', '-convert', 'txt', '-stdout', doc_path],
                    capture_output=True, text=True, timeout=30
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

        # Linux: try antiword
        try:
            result = subprocess.run(
                ['antiword', doc_path],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        # Linux: try libreoffice
        try:
            import tempfile
            with tempfile.TemporaryDirectory() as tmpdir:
                result = subprocess.run(
                    ['libreoffice', '--headless', '--convert-to', 'txt:Text', '--outdir', tmpdir, doc_path],
                    capture_output=True, text=True, timeout=60
                )
                if result.returncode == 0:
                    txt_file = Path(tmpdir) / (Path(doc_path).stem + '.txt')
                    if txt_file.exists():
                        return txt_file.read_text(encoding='utf-8')
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        raise ImportError(
            "Cannot read the .doc file. Please install one of the following tools:\n"
            "  macOS: textutil (built in)\n"
            "  Linux: sudo apt install antiword  or  sudo apt install libreoffice\n"
            "  Or convert the file to .docx format and try again"
        )

    def _extract_docx_text(self, docx_path: str) -> str:
        """Extract text from a Word document (filtering out field codes like HYPERLINK)"""
        if not HAS_DOCX:
            raise ImportError("python-docx is required: pip install python-docx")

        import re

        doc = Document(docx_path)
        content = []

        def clean_hyperlinks(t):
            t = re.sub(r'HYPERLINK\s+"[^"]*"\s*(?:\\[a-z]\s+"[^"]*"\s*)*', '', t)
            t = re.sub(r'HYPERLINK\s+\S+\s*', '', t)
            return t

        def extract_paragraphs(paras):
            for para in paras:
                text = clean_hyperlinks(para.text)
                if text.strip():
                    content.append(text)

        # Headers and footers (each section)
        for section in doc.sections:
            for hf in [section.header, section.footer,
                       section.first_page_header, section.first_page_footer,
                       section.even_page_header, section.even_page_footer]:
                if hf and not hf.is_linked_to_previous:
                    extract_paragraphs(hf.paragraphs)

        # Body paragraphs
        extract_paragraphs(doc.paragraphs)

        # Tables
        for table in doc.tables:
            for row in table.rows:
                row_text = []
                for cell in row.cells:
                    text = clean_hyperlinks(cell.text.strip())
                    if text:
                        row_text.append(text)
                if row_text:
                    content.append(' | '.join(row_text))

        return '\n'.join(content)

    def anonymize_docx_inplace(self, input_path: str, output_path: str, mapping: dict) -> bool:
        """
        Apply redaction replacements while preserving all formatting of the original Word document.

        Implemented by directly manipulating <w:t> elements at the XML layer, covering:
        - Body paragraphs, tables, text boxes
        - Text inside hyperlinks
        - Headers and footers
        - Comments
        - Revisions / track changes (<w:ins>, <w:del>)
        - Footnotes, endnotes

        Each run's font, size, color, bold, paragraph spacing, and other formatting attributes are fully preserved.
        """
        if not HAS_DOCX:
            return False

        try:
            from lxml import etree
        except ImportError:
            # python-docx ships with the lxml dependency
            return False

        try:
            doc = Document(input_path)

            # Build the replacement table (descending length, to avoid substring issues)
            replacements = {}
            for (etype, original), masked in mapping.items():
                replacements[original] = masked
            sorted_originals = sorted(replacements.keys(), key=len, reverse=True)

            if not sorted_originals:
                doc.save(output_path)
                return True

            W_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
            W_T = f'{{{W_NS}}}t'
            W_R = f'{{{W_NS}}}r'
            W_P = f'{{{W_NS}}}p'
            XML_NS = 'http://www.w3.org/XML/1998/namespace'

            def get_t_elements_from_para(para_elem):
                """Get all <w:t> elements in a paragraph (including those inside w:ins/w:del/w:hyperlink)"""
                return list(para_elem.iter(W_T))

            def replace_in_paragraph(para_elem):
                """Apply all replacements to a single paragraph, one at a time, refreshing state"""
                for original in sorted_originals:
                    masked = replacements[original]
                    # Re-fetch the t elements after each replacement (because the text has changed)
                    while True:
                        t_elems = get_t_elements_from_para(para_elem)
                        if not t_elems:
                            break
                        texts = [t.text or '' for t in t_elems]
                        full_text = ''.join(texts)

                        pos = full_text.find(original)
                        if pos == -1:
                            break

                        end_pos = pos + len(original)

                        # Locate the specific <w:t> elements and offsets
                        char_idx = 0
                        start_ti = end_ti = -1
                        start_offset = end_offset = 0

                        for ti, text in enumerate(texts):
                            t_start = char_idx
                            t_end = char_idx + len(text)

                            if start_ti == -1 and t_start <= pos < t_end:
                                start_ti = ti
                                start_offset = pos - t_start

                            if t_start < end_pos <= t_end:
                                end_ti = ti
                                end_offset = end_pos - t_start
                                break

                            char_idx = t_end

                        if start_ti == -1 or end_ti == -1:
                            break

                        if start_ti == end_ti:
                            # Replace within the same <w:t>
                            t = t_elems[start_ti]
                            t.text = t.text[:start_offset] + masked + t.text[end_offset:]
                        else:
                            # Replace across <w:t> elements: put the replacement text in the first, clear the middle, keep the tail
                            t_elems[start_ti].text = texts[start_ti][:start_offset] + masked
                            for ti in range(start_ti + 1, end_ti):
                                t_elems[ti].text = ''
                            t_elems[end_ti].text = texts[end_ti][end_offset:]

                        # Make sure text with leading/trailing spaces keeps xml:space="preserve"
                        for ti in range(start_ti, min(end_ti + 1, len(t_elems))):
                            t = t_elems[ti]
                            if t.text and (t.text[0] == ' ' or t.text[-1] == ' ' or '  ' in t.text):
                                t.set(f'{{{XML_NS}}}space', 'preserve')

            def process_element_tree(root_elem):
                """Process all paragraphs in an XML element tree"""
                for para in root_elem.iter(W_P):
                    replace_in_paragraph(para)

            # 1. Process the main document (body, tables, text boxes, hyperlinks, revisions, etc. all covered)
            process_element_tree(doc.element.body)

            # 2. Process headers and footers
            for section in doc.sections:
                for hf in [section.header, section.footer,
                           section.first_page_header, section.first_page_footer,
                           section.even_page_header, section.even_page_footer]:
                    try:
                        if hf and hf.is_linked_to_previous is False:
                            process_element_tree(hf.element)
                    except Exception:
                        pass

            # 3. Process related parts such as comments, footnotes, and endnotes
            PART_REL_TYPES = [
                'http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments',
                'http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes',
                'http://schemas.openxmlformats.org/officeDocument/2006/relationships/endnotes',
            ]
            for rel in doc.part.rels.values():
                if rel.reltype in PART_REL_TYPES:
                    try:
                        part_elem = rel.target_part.element
                        process_element_tree(part_elem)
                    except Exception:
                        pass

            doc.save(output_path)
            return True

        except Exception:
            import traceback
            traceback.print_exc()
            return False

    def _extract_plain_text(self, file_path: str) -> str:
        """Extract from a plain text file (auto-trying common Chinese encodings)"""
        for enc in ('utf-8-sig', 'utf-8', 'gbk', 'gb18030'):
            try:
                with open(file_path, 'r', encoding=enc) as f:
                    return f.read()
            except UnicodeDecodeError:
                continue
        # Final fallback: replace characters that cannot be decoded
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read()

    def _extract_image_text(self, image_path: str, ocr_engine: str = 'rapidocr') -> str:
        """Extract text from an image (OCR)"""
        if not HAS_OCR:
            raise ImportError(
                "OCR dependencies are required:\n"
                "  Recommended: pip install rapidocr pillow\n"
                "  Alternative: pip install paddleocr paddlepaddle\n"
                "  Fallback: pip install pytesseract (also requires the tesseract binary)"
            )

        img = Image.open(image_path)
        return self._ocr_image(img, ocr_engine)

    def anonymize_pdf_inplace(
        self, input_path: str, output_path: str, mapping: dict,
        whitebox_only: bool = False,
    ) -> bool:
        """
        PDF -> PDF in-place redaction (preserves all formatting of the original PDF: fonts, layout, seals, signatures)

        Uses PyMuPDF's redaction mechanism:
          1. Locate each original sensitive text's coordinate box with page.search_for
          2. add_redact_annot covers the original location with a white background + placeholder text
          3. apply_redactions performs the actual erasure

        Chinese font handling:
          - Prefer "china-s" (PyMuPDF built-in Simplified Chinese)
          - Fall back to system PingFang/STHeiti on failure
          - Last-resort fallback helv (a Latin font, which loses the glyphs of Chinese placeholders)

        Args:
            input_path: source PDF
            output_path: redacted PDF
            mapping: {(type, original): placeholder, ...} (same structure as TextMasker.mapping)
        """
        if not HAS_PYMUPDF:
            return False

        try:
            import fitz as _fitz

            # Build the original -> masked replacement dict, descending length to avoid substring issues
            replacements = {}
            for (etype, original), masked in mapping.items():
                if original and masked:
                    replacements[original] = masked
            if not replacements:
                # No entities: just copy
                doc = _fitz.open(input_path)
                doc.save(output_path)
                doc.close()
                return True

            sorted_originals = sorted(replacements.keys(), key=len, reverse=True)

            # PyMuPDF's built-in china-s (Simplified) CJK font, no fontfile needed
            fontname = 'china-s'

            doc = _fitz.open(input_path)

            for page in doc:
                # Build a character-level bbox map: allows entities to match across lines
                flat_text, char_rects = self._build_char_map(page, _fitz)

                # Take the median font size of the page body (so placeholder size matches the original, no longer smaller)
                page_font_sizes = []
                try:
                    pd = page.get_text("dict")
                    for block in pd.get("blocks", []):
                        for line in block.get("lines", []):
                            for span in line.get("spans", []):
                                size = span.get("size", 0)
                                if size and len(span.get("text", "")) > 0:
                                    page_font_sizes.append(size)
                except Exception:
                    pass
                page_font_sizes.sort()
                page_default_size = (
                    page_font_sizes[len(page_font_sizes) // 2]
                    if page_font_sizes else 11
                )

                first_seen: set = set()  # write the placeholder only once per original, clear the rest

                for original in sorted_originals:
                    masked = replacements[original]
                    occurrences = self._find_rects_for_entity(
                        flat_text, char_rects, original, _fitz
                    )
                    for occ_idx, rects in enumerate(occurrences):
                        if not rects:
                            continue
                        # Multiple rects (cross-line case): write the placeholder only in the first segment; erase the rest
                        for ri, rect in enumerate(rects):
                            # Slightly enlarge the rect to fully cover the glyph (the char bbox sometimes omits the descender)
                            padded = _fitz.Rect(
                                rect.x0 - 0.5, rect.y0 - 1.5,
                                rect.x1 + 0.5, rect.y1 + 1.5,
                            )
                            # Prefer the page body's median font size, fall back to estimating from rect.height
                            fontsize = page_default_size
                            # If the original rect height is much smaller than the page font size (small fields), estimating from rect is better
                            est = rect.height * 0.85
                            if est < page_default_size * 0.7:
                                fontsize = max(8, est)
                            page.add_redact_annot(
                                padded,
                                text="" if whitebox_only else (masked if ri == 0 else ""),
                                fontname=fontname,
                                fontsize=fontsize,
                                text_color=(0, 0, 0),
                                fill=(1, 1, 1),
                                align=_fitz.TEXT_ALIGN_LEFT,
                            )

                # Apply redaction.
                #   images=PDF_REDACT_IMAGE_NONE -> do not erase images (keep seals/signatures)
                #   graphics=PDF_REDACT_LINE_ART_NONE -> do not erase line art (keep table borders)
                #   text=True -> erase text in the matched areas
                page.apply_redactions(
                    images=_fitz.PDF_REDACT_IMAGE_NONE,
                    graphics=_fitz.PDF_REDACT_LINE_ART_NONE,
                )

                # Cleanup sweep: some PDFs (e.g. Jinge signature files) have a second text layer the first pass missed.
                # Use search_for to find leftovers, sweeping at most 2 rounds.
                for _ in range(2):
                    had_residue = False
                    for original in sorted_originals:
                        masked = replacements[original]
                        rects = page.search_for(original)
                        for r in rects:
                            if r.width > 0.5:  # skip zero-width ghosts
                                had_residue = True
                                padded = _fitz.Rect(
                                    r.x0 - 0.5, r.y0 - 1.5,
                                    r.x1 + 0.5, r.y1 + 1.5,
                                )
                                fontsize = max(7, min(13, r.height * 0.72))
                                page.add_redact_annot(
                                    padded,
                                    text="" if whitebox_only else masked,
                                    fontname=fontname,
                                    fontsize=fontsize,
                                    text_color=(0, 0, 0),
                                    fill=(1, 1, 1),
                                    align=_fitz.TEXT_ALIGN_LEFT,
                                )
                    if not had_residue:
                        break
                    page.apply_redactions(
                        images=_fitz.PDF_REDACT_IMAGE_NONE,
                        graphics=_fitz.PDF_REDACT_LINE_ART_NONE,
                    )

            doc.save(output_path, deflate=True, garbage=3)
            doc.close()
            return True
        except Exception:
            import traceback
            traceback.print_exc()
            return False

    @staticmethod
    def _build_char_map(page, _fitz):
        """
        Use rawdict to get the bbox of every character on the page.
        Returns (flat_text, char_rects), the two are one-to-one; a '\\n' is appended at each line end with rect=None.

        Key point: a char bbox's y coordinates only cover near the glyph origin, which misses
        erasing the ascender/descender. Here each character's y coordinate is extended to the full
        bbox y range of its line, so apply_redactions erases the entire glyph cleanly.
        """
        raw = page.get_text("rawdict")
        flat = []
        rects = []
        for block in raw.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                line_bbox = line.get("bbox")
                if line_bbox:
                    line_y0, line_y1 = line_bbox[1], line_bbox[3]
                else:
                    line_y0 = line_y1 = None
                for span in line.get("spans", []):
                    for ch in span.get("chars", []):
                        c = ch.get("c") or ""
                        bbox = ch.get("bbox")
                        if not c:
                            continue
                        if bbox and line_y0 is not None:
                            # Use the char's own x, and the line's y (to cover the full glyph height)
                            r = _fitz.Rect(bbox[0], line_y0, bbox[2], line_y1)
                        elif bbox:
                            r = _fitz.Rect(bbox)
                        else:
                            r = None
                        flat.append(c)
                        rects.append(r)
                flat.append("\n")
                rects.append(None)
        return "".join(flat), rects

    @staticmethod
    def _find_rects_for_entity(flat_text: str, char_rects: list, entity: str, _fitz):
        """
        Find all occurrences of entity in flat_text, allowing a \\n (layout line break) between Chinese/digit characters.
        Returns a list of lists: a rect list for each occurrence (multiple segments if it spans lines).
        """
        import re
        # Build a "line-break tolerant" regex for entity: allow inserting one \n between CJK/digit characters
        def is_break_allowed(ch):
            return ('一' <= ch <= '鿿') or ch.isdigit() or ch.isalpha() or ch in ' \t'

        pattern_parts = []
        for i, ch in enumerate(entity):
            pattern_parts.append(re.escape(ch))
            if i < len(entity) - 1 and is_break_allowed(ch) and is_break_allowed(entity[i + 1]):
                pattern_parts.append(r"\n?")
        pattern = "".join(pattern_parts)

        occurrences = []
        for m in re.finditer(pattern, flat_text):
            rs = []
            current = None
            for i in range(m.start(), m.end()):
                r = char_rects[i] if i < len(char_rects) else None
                if r is None:
                    if current is not None:
                        rs.append(current)
                        current = None
                    continue
                if current is None:
                    current = _fitz.Rect(r)
                elif abs(r.y0 - current.y0) > 2 and abs(r.y1 - current.y1) > 2:
                    rs.append(current)
                    current = _fitz.Rect(r)
                else:
                    current |= r  # union
            if current is not None:
                rs.append(current)
            if rs:
                occurrences.append(rs)
        return occurrences

    def anonymize_scanned_pdf_inplace(
        self, input_path: str, output_path: str, mapping: dict,
        ocr_engine: str = 'rapidocr', whitebox_only: bool = False,
    ) -> bool:
        """
        Visual redaction for scanned PDFs (keeps the original page image, only covers sensitive text positions with a white box + placeholder)

        Difference from anonymize_pdf_inplace:
          - That one targets **text-layer PDFs**: it redacts text objects directly, preserving all original formatting
          - This one targets **scanned PDFs**: the original "text" is image content, so it must OCR first to get
            character positions, then use PDF_REDACT_IMAGE_PIXELS to erase the underlying image and overlay the placeholder

        Effect: the output PDF looks almost identical to the original scan (keeps seals/signatures/header/paper background),
        only sensitive text becomes a "[PERSON_1]"-style placeholder on a white block.

        Args:
            input_path: source scanned PDF
            output_path: output redacted PDF
            mapping: TextMasker.mapping, {(etype, original): placeholder, ...}
            ocr_engine: OCR engine, currently only 'rapidocr' is supported (PaddleOCR does not return box data)
        """
        if not HAS_PYMUPDF or not HAS_PIL:
            return False
        if not HAS_RAPIDOCR:
            print("  ⚠️ Visual redaction of scanned PDFs requires RapidOCR, please install: pip install rapidocr")
            return False

        try:
            import fitz as _fitz
            import numpy as np
            import time as _time

            # Keep entity_type info (used for the "distinctive identifying part" judgment)
            replacements = {}
            entity_types = {}  # original -> type
            for (etype, original), masked in mapping.items():
                if original and masked and len(original) >= 1:
                    replacements[original] = masked
                    entity_types[original] = etype
            if not replacements:
                # No sensitive entities: just copy
                doc = _fitz.open(input_path)
                doc.save(output_path)
                doc.close()
                return True

            # Longer strings first (avoid "张三" matching a substring of "张三李四")
            sorted_originals = sorted(replacements.keys(), key=len, reverse=True)

            doc = _fitz.open(input_path)
            page_count = doc.page_count
            ocr = self._get_rapidocr()
            total_redacted = 0

            print(f"[Visual redaction] {page_count} scanned PDF pages total, processing page by page...", flush=True)

            # Key: draw the redaction directly on the image with PIL, to avoid PDF rotation coordinate conversion issues
            from PIL import ImageDraw, ImageFont

            # Find a system Chinese font (used to draw the placeholder on PIL)
            font_path = None
            for cand in (
                '/System/Library/Fonts/PingFang.ttc',
                '/System/Library/Fonts/STHeiti Light.ttc',
                '/System/Library/Fonts/Hiragino Sans GB.ttc',
                'C:/Windows/Fonts/simhei.ttf',
                'C:/Windows/Fonts/msyh.ttc',
                '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
            ):
                if os.path.exists(cand):
                    font_path = cand
                    break

            # Output new PDF (assemble each page from the redacted image)
            out_doc = _fitz.open()

            for page_num, page in enumerate(doc, 1):
                t0 = _time.time()

                # Render at 200 DPI (image used for output, quality first)
                render_dpi = 200
                scale = render_dpi / 72
                mat = _fitz.Matrix(scale, scale)
                pix = page.get_pixmap(matrix=mat)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                img_array = np.array(img)
                pix = None

                # OCR
                result = ocr(img_array)
                if not result or not result.txts or result.boxes is None:
                    # Nothing recognized, put the original image back as-is
                    new_page = out_doc.new_page(width=page.rect.width, height=page.rect.height)
                    img_bytes = _io_bytes_png(img)
                    new_page.insert_image(new_page.rect, stream=img_bytes)
                    print(f"  Page {page_num}/{page_count} had no OCR result, original image restored", flush=True)
                    continue

                # Draw on the PIL canvas
                draw = ImageDraw.Draw(img)

                # Key: group and sort by "visual line" before joining, to avoid order scrambling when OCR splits one line into left/right segments
                raw_lines = []
                for li, (line_text, line_box) in enumerate(zip(result.txts, result.boxes)):
                    bxs = [float(p[0]) for p in line_box]
                    bys = [float(p[1]) for p in line_box]
                    raw_lines.append({
                        'text': line_text,
                        'x0': min(bxs), 'x1': max(bxs),
                        'y0': min(bys), 'y1': max(bys),
                        'y_center': (min(bys) + max(bys)) / 2,
                        'h': max(bys) - min(bys),
                    })

                # Sort by y_center; within a y tolerance = average line height x 0.5, treat as the same visual line
                raw_lines.sort(key=lambda L: L['y_center'])
                avg_h = sum(L['h'] for L in raw_lines) / max(len(raw_lines), 1)
                tolerance = max(avg_h * 0.5, 5)
                groups = []
                cur_group = []
                last_yc = None
                for L in raw_lines:
                    if last_yc is None or abs(L['y_center'] - last_yc) <= tolerance:
                        cur_group.append(L)
                    else:
                        groups.append(cur_group)
                        cur_group = [L]
                    last_yc = L['y_center']
                if cur_group:
                    groups.append(cur_group)
                # Within each group sort by x0 (left -> right); groups are already sorted by y
                ordered_lines = []
                for grp in groups:
                    grp.sort(key=lambda L: L['x0'])
                    ordered_lines.extend(grp)

                # Joined text used for cross-line matching
                line_specs = []  # [(line_text, x0, x1, y0, y1, char_start_global)]
                joined = ""
                for L in ordered_lines:
                    char_start = len(joined)
                    line_specs.append((
                        L['text'], L['x0'], L['x1'], L['y0'], L['y1'], char_start,
                    ))
                    joined += L['text']

                # Full-width/half-width equivalence normalization (OCR easily reads ( as (, and vice versa)
                def normalize(s):
                    return s.translate(str.maketrans('()[]【】《》＜＞，。；：！？',
                                                       '()[]<><><>,.;:!?'))
                joined_norm = normalize(joined)

                # === Strategy: match entity substrings per line (avoid relying on cross-line join order) ===
                # For each entity: iterate over every OCR line and find the longest substring of the entity in that line.
                # This way, no matter how OCR splits things (horizontal cut, vertical cut, left/right segments), any
                # entity fragment visible in that line gets covered, and OCR misalignment / scrambled order does not affect the result.
                page_redacted = 0
                # Already-covered intervals per line [(line_idx, char_start, char_end), ...]
                line_handled = {i: [] for i in range(len(line_specs))}
                # Which entities have already had a placeholder written (avoid repeating [PERSON_1] across lines)
                placeholder_written = set()

                def longest_common_substring(a, b, min_len=2):
                    """Find the longest substring of a within b. Returns (a_start, b_start, length) or None"""
                    for L in range(min(len(a), len(b)), min_len - 1, -1):
                        for i in range(len(a) - L + 1):
                            sub = a[i:i + L]
                            j = b.find(sub)
                            if j != -1:
                                return (i, j, L)
                    return None

                def char_width_weight(c):
                    """Estimate character width weight: CJK = 2, half-width = 1"""
                    if '一' <= c <= '鿿':
                        return 2.0  # CJK character
                    if '　' <= c <= '〿' or '＀' <= c <= '￯':
                        return 2.0  # CJK punctuation / full-width
                    return 1.0  # half-width ASCII / digit / punctuation

                def pixel_offset_in_line(text, char_idx, line_x0, line_w):
                    """Using CJK double-width weights, compute pixel X from the char_idx character position"""
                    if not text:
                        return line_x0
                    weights = [char_width_weight(c) for c in text]
                    total = sum(weights)
                    if total <= 0:
                        return line_x0
                    cum = sum(weights[:char_idx])
                    return line_x0 + (cum / total) * line_w

                def get_distinctive_part(entity, etype):
                    """Extract the 'brand/distinctive identifying part' of an entity, dropping generic prefixes/suffixes"""
                    import re as _re
                    if etype in ('company', 'law_firm', 'institution', 'bank_name'):
                        # Remove parenthesized content (both Chinese and Latin parentheses)
                        s = _re.sub(r'[（(].*?[)）]', '', entity)
                        # Remove common place-name prefixes
                        for p in ('北京', '上海', '广东省', '广州市', '深圳市', '深圳', '广州',
                                  '中国', '中华人民共和国', '中华', '广东', '浙江省', '浙江',
                                  '江苏省', '山东省', '河北省', '河南省'):
                            if s.startswith(p):
                                s = s[len(p):]
                        # Remove common suffixes (longer suffixes first)
                        for sfx in sorted([
                            '律师事务所', '会计师事务所', '事务所',
                            '股份有限公司', '有限责任公司', '有限公司',
                            '集团有限公司', '集团公司',
                            '公司', '集团', '股份',
                        ], key=len, reverse=True):
                            if s.endswith(sfx):
                                s = s[:-len(sfx)]
                                break
                        return s.strip() if len(s.strip()) >= 2 else None
                    if etype == 'court':
                        for sfx in ('中级人民法院', '高级人民法院', '人民法院', '人民检察院',
                                    '法院', '检察院', '仲裁院', '仲裁委员会'):
                            if entity.endswith(sfx):
                                core = entity[:-len(sfx)]
                                return core if len(core) >= 2 else None
                        return entity
                    if etype == 'government':
                        for sfx in ('司法厅', '司法部', '人民政府', '管理委员会', '办公厅',
                                    '公安局', '派出所', '工商局'):
                            if entity.endswith(sfx):
                                core = entity[:-len(sfx)]
                                return core if len(core) >= 2 else None
                        return entity
                    # Person names / case numbers / credit codes, etc.: distinctive on their own
                    return entity

                for original in sorted_originals:
                    masked = replacements[original]
                    etype = entity_types.get(original, 'unknown')
                    orig_norm = normalize(original)
                    if len(orig_norm) < 2:
                        continue

                    # Do not short-match digit/Latin entities (prone to false positives); require at least 3 Chinese chars to avoid generic words like "公司"/"国际"
                    is_alnum = orig_norm.replace('.', '').replace('-', '').isalnum() and \
                               all(ord(c) < 128 for c in orig_norm)
                    if is_alnum:
                        min_match_len = 4
                    elif len(orig_norm) <= 3:
                        # The entity itself is only 2-3 chars (person name/brand): must match in full
                        min_match_len = len(orig_norm)
                    else:
                        # Long entity (4+ chars): minimum 3 chars (avoid generic words like "公司" matching, but still hit when OCR fragments)
                        min_match_len = 3

                    # Compute the "distinctive identifying part" (e.g. "北京XX（深圳）律师事务所" -> "XX")
                    distinctive = get_distinctive_part(original, etype)
                    distinctive_norm = normalize(distinctive) if distinctive else None

                    # Find lines containing the "distinctive part" (those are 100% true hits); their y_center is used to delimit the "same visual line"
                    distinctive_y_centers = []
                    if distinctive_norm and distinctive_norm != orig_norm:
                        # The entity itself has a distinctive part (i.e. the name contains a generic suffix)
                        for spec in line_specs:
                            lt_norm = normalize(spec[0])
                            if distinctive_norm in lt_norm:
                                yc = (spec[3] + spec[4]) / 2
                                distinctive_y_centers.append((yc, spec[4] - spec[3]))

                    for li, spec in enumerate(line_specs):
                        lt, lx0, lx1, ly0, ly1, gstart = spec
                        lt_norm = normalize(lt)
                        line_yc = (ly0 + ly1) / 2
                        line_h = ly1 - ly0

                        match = longest_common_substring(orig_norm, lt_norm, min_len=min_match_len)
                        if not match:
                            continue
                        ent_start, local_s, length = match
                        local_e = local_s + length
                        ent_end = ent_start + length

                        # Anti-false-positive gate:
                        # If the entity has a distinctive part (e.g. a company has a brand name) and the current line lacks that distinctive part,
                        # then this line must be on the same visual line (close y) as some line containing the distinctive part before redacting is allowed
                        if distinctive_y_centers:
                            line_has_distinctive = distinctive_norm in lt_norm
                            if not line_has_distinctive:
                                tol = max(line_h * 0.6, 5)
                                same_row = any(
                                    abs(line_yc - dyc) <= tol
                                    for dyc, _ in distinctive_y_centers
                                )
                                if not same_row:
                                    continue  # skip: the generic part appearing in an unrelated line is a false positive

                        # Overlap check
                        if any(s < local_e and local_s < e for s, e in line_handled[li]):
                            continue
                        line_handled[li].append((local_s, local_e))

                        line_w = max(lx1 - lx0, 1)
                        # Compute the position precisely with CJK double-width weights (avoids offset in mixed Chinese/English text)
                        sub_x0 = pixel_offset_in_line(lt, local_s, lx0, line_w)
                        sub_x1 = pixel_offset_in_line(lt, local_e, lx0, line_w)

                        pad_x, pad_y = 2, 2
                        rect_x0 = sub_x0 - pad_x
                        rect_x1 = sub_x1 + pad_x
                        rect_y0 = ly0 - pad_y
                        rect_y1 = ly1 + pad_y

                        draw.rectangle(
                            [(rect_x0, rect_y0), (rect_x1, rect_y1)],
                            fill="white", outline=None,
                        )

                        # Decide what text to write in this segment:
                        #   - whitebox_only: force no text, a pure white box
                        #   - partial mask (mask length == entity length): write the slice for this line (e.g. "张*")
                        #     such a mask carries information itself ("张*" shows there is a surname but hides the given name), keep it
                        #   - placeholder mode (e.g. [PERSON_1] / <人物1> / 〔姓名1〕): write the full placeholder centered in the white box
                        if whitebox_only:
                            text_to_draw = ''
                        else:
                            same_length = len(masked) == len(orig_norm)
                            if same_length:
                                # partial mode: this line only draws the corresponding slice
                                text_to_draw = masked[ent_start:ent_end]
                            else:
                                # placeholder mode: draw the full placeholder for each occurrence (one per line even across lines)
                                text_to_draw = masked

                        if text_to_draw:
                            line_h = ly1 - ly0
                            avail_w = rect_x1 - rect_x0
                            # Adaptive font size: start at 0.75 of line height, shrink gradually until text width <= 95% of available width
                            font_size = max(10, int(line_h * 0.75))
                            font = None
                            text_w = text_h = 0
                            for fs in range(font_size, 7, -1):
                                try:
                                    f = ImageFont.truetype(font_path, fs) if font_path else ImageFont.load_default()
                                    bb = draw.textbbox((0, 0), text_to_draw, font=f)
                                    tw = bb[2] - bb[0]
                                    th = bb[3] - bb[1]
                                except Exception:
                                    f = ImageFont.load_default()
                                    tw = fs * len(text_to_draw) // 2
                                    th = fs
                                if tw <= avail_w * 0.95:
                                    font, text_w, text_h = f, tw, th
                                    break
                            if font is None:
                                font = ImageFont.load_default()
                                text_w, text_h = avail_w * 0.9, line_h * 0.5

                            tx = rect_x0 + max((avail_w - text_w) / 2, 0)
                            ty = rect_y0 + max((rect_y1 - rect_y0 - text_h) / 2, 0)
                            draw.text((tx, ty), text_to_draw, fill="black", font=font)

                        page_redacted += 1

                # Use the finished image as the new page background
                new_page = out_doc.new_page(width=page.rect.width, height=page.rect.height)
                img_bytes = _io_bytes_png(img)
                new_page.insert_image(new_page.rect, stream=img_bytes)

                total_redacted += page_redacted
                elapsed = _time.time() - t0
                print(f"  Page {page_num}/{page_count}: redacted {page_redacted} item(s), took {elapsed:.1f}s", flush=True)

            print(f"[Visual redaction] Done, redacted {total_redacted} item(s) in total", flush=True)

            out_doc.save(output_path, deflate=True, garbage=3)
            out_doc.close()
            doc.close()
            return True
        except Exception:
            import traceback
            traceback.print_exc()
            return False

    def write_file(self, text: str, output_path: str, output_format: str = 'auto') -> List[Tuple[str, str]]:
        """
        Write a file

        Args:
            text: text content
            output_path: output file path
            output_format: output format (auto, txt, md, pdf, docx)

        Returns:
            a list [(file_type, file_path), ...]
        """
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        if output_format == 'auto':
            output_format = self._guess_format(path)

        saved_files = []

        if output_format == 'pdf':
            pdf_path = path if path.suffix.lower() == '.pdf' else path.with_suffix('.pdf')
            if self._write_pdf(text, str(pdf_path)):
                saved_files.append(('output_pdf', str(pdf_path)))
            else:
                # PDF generation failed, fall back to text
                txt_path = path.with_suffix('.txt')
                self._write_plain_text(text, str(txt_path))
                saved_files.append(('output_txt', str(txt_path)))

        elif output_format == 'docx':
            docx_path = path if path.suffix.lower() == '.docx' else path.with_suffix('.docx')
            if self._write_docx(text, str(docx_path)):
                saved_files.append(('output_docx', str(docx_path)))
            else:
                txt_path = path.with_suffix('.txt')
                self._write_plain_text(text, str(txt_path))
                saved_files.append(('output_txt', str(txt_path)))

        elif output_format == 'md':
            md_path = path if path.suffix.lower() == '.md' else path.with_suffix('.md')
            self._write_plain_text(text, str(md_path))
            saved_files.append(('output_md', str(md_path)))

        else:  # txt
            txt_path = path if path.suffix.lower() == '.txt' else path.with_suffix('.txt')
            self._write_plain_text(text, str(txt_path))
            saved_files.append(('output_txt', str(txt_path)))

        return saved_files

    def _guess_format(self, path: Path) -> str:
        """Guess the format from the file extension"""
        suffix = path.suffix.lower()
        if suffix == '.pdf' and (HAS_REPORTLAB or HAS_PYMUPDF):
            return 'pdf'
        elif suffix in ['.docx', '.doc'] and HAS_DOCX:
            return 'docx'
        elif suffix == '.md':
            return 'md'
        else:
            return 'txt'

    def _write_plain_text(self, text: str, file_path: str) -> bool:
        """Write a plain text file"""
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(text)
            return True
        except Exception:
            return False

    def _write_pdf(self, text: str, file_path: str) -> bool:
        """Write a PDF file"""
        if HAS_REPORTLAB:
            try:
                return self._write_pdf_reportlab(text, file_path)
            except Exception:
                pass

        if HAS_PYMUPDF:
            try:
                return self._write_pdf_fitz(text, file_path)
            except Exception:
                pass

        return False

    def _write_pdf_reportlab(self, text: str, file_path: str) -> bool:
        """Create a PDF using reportlab"""
        import platform
        import os

        doc = SimpleDocTemplate(str(file_path), pagesize=A4,
                                leftMargin=50, rightMargin=50,
                                topMargin=50, bottomMargin=50)
        story = []

        # Fallback template: FangSong, Small Four, 1.5 line spacing
        # Small Four = 12pt, 1.5x = 18pt leading
        styles = getSampleStyleSheet()
        normal_style = ParagraphStyle(
            'Normal',
            parent=styles['Normal'],
            fontSize=12,
            leading=18,  # 12pt * 1.5
            alignment=TA_LEFT,
            spaceBefore=0,
            spaceAfter=0,
        )

        # Try loading a Chinese font (supports macOS / Windows / Linux)
        font_loaded = False
        font_paths = []
        if platform.system() == 'Darwin':
            # macOS prefers FangSong-style fonts (Kaiti/STFangsong), otherwise falls back to PingFang
            font_paths = [
                '/System/Library/Fonts/Supplemental/Songti.ttc',
                '/System/Library/Fonts/STHeiti Light.ttc',
                '/System/Library/Fonts/PingFang.ttc',
                '/System/Library/Fonts/Hiragino Sans GB.ttc',
            ]
        elif platform.system() == 'Windows':
            windir = os.environ.get('WINDIR', 'C:\\Windows')
            font_paths = [
                os.path.join(windir, 'Fonts', 'simfang.ttf'),   # FangSong, preferred
                os.path.join(windir, 'Fonts', 'simsun.ttc'),    # SimSun
                os.path.join(windir, 'Fonts', 'msyh.ttc'),      # Microsoft YaHei
                os.path.join(windir, 'Fonts', 'simhei.ttf'),    # SimHei
                os.path.join(windir, 'Fonts', 'msyhbd.ttc'),    # Microsoft YaHei Bold
            ]
        else:  # Linux
            font_paths = [
                '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
                '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
                '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
            ]

        for font_path in font_paths:
            if os.path.exists(font_path):
                try:
                    pdfmetrics.registerFont(TTFont('ChineseFont', font_path))
                    normal_style.fontName = 'ChineseFont'
                    font_loaded = True
                    break
                except Exception:
                    continue

        if not font_loaded:
            normal_style.fontName = 'Helvetica'

        lines = text.split('\n')
        for line in lines:
            if line.strip():
                p = Paragraph(line, normal_style)
                story.append(p)
            else:
                story.append(Spacer(1, 6))

        doc.build(story)
        return True

    def _write_pdf_fitz(self, text: str, file_path: str) -> bool:
        """Create a PDF using PyMuPDF (fallback option, supports Chinese)"""
        import os

        doc = fitz.open()
        margin = 50
        font_size = 11
        line_height = 16
        page_height = 842
        page_width = 595
        max_y = page_height - margin

        # Try loading a Chinese font
        font_path = None
        font_name = "helv"

        # Cross-platform Chinese font search
        import platform as _plat
        candidate_fonts = [
            # macOS
            '/System/Library/Fonts/PingFang.ttc',
            '/System/Library/Fonts/STHeiti Light.ttc',
            '/System/Library/Fonts/Hiragino Sans GB.ttc',
            '/System/Library/Fonts/STSong.ttf',
            # Linux
            '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
            '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
            '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        ]
        # Windows fonts
        if _plat.system() == 'Windows':
            windir = os.environ.get('WINDIR', 'C:\\Windows')
            candidate_fonts = [
                os.path.join(windir, 'Fonts', 'msyh.ttc'),
                os.path.join(windir, 'Fonts', 'simfang.ttf'),
                os.path.join(windir, 'Fonts', 'simsun.ttc'),
                os.path.join(windir, 'Fonts', 'simhei.ttf'),
            ] + candidate_fonts
        for fp in candidate_fonts:
            if os.path.exists(fp):
                font_path = fp
                break

        page = doc.new_page()
        current_y = margin

        if font_path:
            # Use an external Chinese font
            page.insert_font(fontname="cjk", fontfile=font_path)
            font_name = "cjk"

        lines = text.split('\n')
        for line in lines:
            if current_y + line_height > max_y:
                page = doc.new_page()
                current_y = margin
                if font_path:
                    page.insert_font(fontname="cjk", fontfile=font_path)

            if line.strip():
                try:
                    page.insert_text(
                        (margin, current_y), line,
                        fontsize=font_size, fontname=font_name
                    )
                except Exception:
                    # Final fallback: ASCII only
                    safe_line = ''.join([c if ord(c) < 128 else '?' for c in line])
                    page.insert_text(
                        (margin, current_y), safe_line,
                        fontsize=font_size, fontname="helv"
                    )

            current_y += line_height

        doc.save(file_path)
        doc.close()
        return True

    def _write_docx(self, text: str, file_path: str) -> bool:
        """
        Write a Word document - fallback template (FangSong / Small Four / 1.5 line spacing)

        Formatting spec:
        - Font: FangSong (uniform for Chinese and English)
        - Body: Small Four (12pt), 1.5 line spacing, 0 space before/after
        - Headings: Small Three (15pt) bold, 0.5 line space before/after
        - Margins: top 3.7cm, bottom 3.5cm, left 2.8cm, right 2.6cm
        """
        if not HAS_DOCX:
            return False

        try:
            from docx.oxml import OxmlElement
            from docx.shared import Cm, Emu
            from docx.enum.text import WD_LINE_SPACING
            import re as _re

            FONT_NAME = '仿宋'
            BODY_SIZE = Pt(12)       # Small Four = 12pt
            TITLE_SIZE = Pt(15)      # Small Three = 15pt
            LINE_SPACING = 1.5       # 1.5 line spacing
            TITLE_SPACE = Pt(6)      # 0.5 line ~ 6pt (based on 12pt body)

            doc = Document()

            # Margins
            for section in doc.sections:
                section.top_margin = Cm(3.7)
                section.bottom_margin = Cm(3.5)
                section.left_margin = Cm(2.8)
                section.right_margin = Cm(2.6)

            def _set_rfonts_on_element(element):
                """Set the FangSong font on an XML element"""
                rPr = element.find(qn('w:rPr'))
                if rPr is None:
                    rPr = OxmlElement('w:rPr')
                    element.append(rPr)
                rFonts = rPr.find(qn('w:rFonts'))
                if rFonts is None:
                    rFonts = OxmlElement('w:rFonts')
                    rPr.append(rFonts)
                for attr in ('w:eastAsia', 'w:ascii', 'w:hAnsi', 'w:cs'):
                    rFonts.set(qn(attr), FONT_NAME)
                # Clear theme font overrides
                for theme_attr in ('w:eastAsiaTheme', 'w:asciiTheme', 'w:hAnsiTheme', 'w:cstheme'):
                    try:
                        del rFonts.attrib[qn(theme_attr)]
                    except (KeyError, ValueError):
                        pass

            def _set_line_spacing(para, spacing, rule=WD_LINE_SPACING.MULTIPLE):
                """Set paragraph line spacing (default 1.5x multiple line spacing)"""
                pf = para.paragraph_format
                pf.line_spacing_rule = rule
                pf.line_spacing = spacing

            def _is_title(line):
                """Determine whether a line is a heading (matches only document names and section headings)"""
                stripped = line.strip()
                if not stripped or len(stripped) > 25:
                    return False
                # Document names (must be standalone short titles)
                doc_titles = [
                    r'^(?:民事|刑事|行政)?(?:起诉状|答辩状|上诉状|代理意见|判决书|裁定书|调解书|决定书|申请书|异议书)$',
                    r'^(?:关于.+的(?:函|通知|公告|意见|决定|报告|说明|声明|承诺书))$',
                    r'^(?:租赁|买卖|借款|委托|合作|劳动|服务|股权转让)?(?:合同|协议)(?:书)?$',
                ]
                for pat in doc_titles:
                    if _re.search(pat, stripped):
                        return True
                # Section headings (standalone short lines like "诉讼请求", "事实与理由")
                section_titles = [
                    r'^(?:诉讼请求|事实与理由|证据清单|判决如下|本院认为|裁判结果|审理查明)$',
                    r'^第[一二三四五六七八九十\d]+[章节部分](?:\s|$)',
                ]
                for pat in section_titles:
                    if _re.search(pat, stripped):
                        return True
                return False

            # Set Normal style defaults
            normal_style = doc.styles['Normal']
            normal_style.font.name = FONT_NAME
            normal_style.font.size = BODY_SIZE
            _set_rfonts_on_element(normal_style.element)
            normal_pf = normal_style.paragraph_format
            normal_pf.space_before = Pt(0)
            normal_pf.space_after = Pt(0)
            normal_pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
            normal_pf.line_spacing = LINE_SPACING

            # Set docDefaults
            styles_element = doc.styles.element
            rPrDefault = styles_element.find(qn('w:docDefaults'))
            if rPrDefault is None:
                rPrDefault = OxmlElement('w:docDefaults')
                styles_element.insert(0, rPrDefault)
            rPrDef = rPrDefault.find(qn('w:rPrDefault'))
            if rPrDef is None:
                rPrDef = OxmlElement('w:rPrDefault')
                rPrDefault.append(rPrDef)
            rPr = rPrDef.find(qn('w:rPr'))
            if rPr is None:
                rPr = OxmlElement('w:rPr')
                rPrDef.append(rPr)
            rFonts = rPr.find(qn('w:rFonts'))
            if rFonts is None:
                rFonts = OxmlElement('w:rFonts')
                rPr.append(rFonts)
            for attr in ('w:eastAsia', 'w:ascii', 'w:hAnsi', 'w:cs'):
                rFonts.set(qn(attr), FONT_NAME)
            sz = rPr.find(qn('w:sz'))
            if sz is None:
                sz = OxmlElement('w:sz')
                rPr.append(sz)
            sz.set(qn('w:val'), '24')  # 12pt = 24 half-points
            szCs = rPr.find(qn('w:szCs'))
            if szCs is None:
                szCs = OxmlElement('w:szCs')
                rPr.append(szCs)
            szCs.set(qn('w:val'), '24')

            # Cleanup: strip control characters not allowed in XML (common in OCR results)
            # Keep only \t \n \r and printable characters, drop other C0 control characters
            import re as _re
            text = _re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)

            # Process the text content
            lines = text.split('\n')
            for line in lines:
                stripped = line.strip()
                # Skip page separator markers
                if stripped.startswith('=' * 10):
                    continue
                if stripped.startswith('第 ') and stripped.endswith(' 页'):
                    continue

                if stripped:
                    para = doc.add_paragraph()
                    is_title = _is_title(stripped)

                    run = para.add_run(stripped)
                    run.font.name = FONT_NAME
                    _set_rfonts_on_element(run._element)

                    if is_title:
                        run.font.size = TITLE_SIZE
                        run.bold = True
                        para.paragraph_format.space_before = TITLE_SPACE
                        para.paragraph_format.space_after = TITLE_SPACE
                    else:
                        run.font.size = BODY_SIZE
                    _set_line_spacing(para, LINE_SPACING)
                else:
                    # Empty line: keep formatting consistent
                    para = doc.add_paragraph()
                    _set_rfonts_on_element(para._element)
                    _set_line_spacing(para, LINE_SPACING)

            doc.save(file_path)
            return True
        except Exception:
            import traceback
            traceback.print_exc()
            return False

    def write_mapping(self, mapping: Dict, file_path: str):
        """Write the mapping table"""
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)

    def get_supported_input_formats(self) -> List[str]:
        """Get the supported input formats"""
        return self.supported_formats['input'].copy()

    def get_supported_output_formats(self) -> List[str]:
        """Get the supported output formats"""
        return self.supported_formats['output'].copy()
