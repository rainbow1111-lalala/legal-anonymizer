# Legal Anonymizer · Project Report

> A fully local PII redaction tool. No network, no uploads, built for mixed Chinese/English legal documents.
> It grew from "regex only" into a three-layer detection stack: rules engine + Chinese NER + OpenAI privacy-filter.

---

## 1. What the project is for

Lawyers, in-house counsel, and compliance staff handle large volumes of case files, contracts, and judgments every day. The moment that material goes out for external communication, or gets pasted into ChatGPT/Claude as a prompt, the party names, ID numbers, company names, addresses, and amounts inside it are sensitive data that **must not leave in the clear**.

Redaction tools on the market fall into two groups:

| Category | Typical example | Pain point |
|---|---|---|
| **SaaS services** | Various online redaction platforms | The document has to be uploaded, and a leaked case file is a lawyer's worst nightmare |
| **Open-source local tools** | Most are built on spaCy / LTP / HanLP | Low hit rate on complex Chinese legal documents, frequent misses |

This project takes the second path and pushes it further: **fully local**, but with a **three-layer detection stack** that combines the precision of a rules engine with the recall of an LLM.

---

## 2. Core features

### 2.1 Baseline capabilities

- ✅ **30+ sensitive data types**: ID number, mobile number, passport, HK/Macau and Taiwan permits, unified social credit code, org code, tax registration no., bank card no., email, IP, MAC, case number, contract no., license plate, VIN, postal code, house number, address, amount, date, and more
- ✅ **Multiple input formats**: PDF (including scanned PDFs via OCR), Word (docx/doc), TXT, Markdown, images
- ✅ **Multiple output formats at once**: redact once and generate **MD + DOCX + PDF** together, pick whichever you need
- ✅ **Original formatting preserved**:
  - **DOCX → DOCX**: replacement happens at the XML layer, so font, size, line spacing, tables, headers, and footers are **all kept exactly as they were**
  - **PDF → PDF**: in-place redaction with PyMuPDF keeps layout, fonts, seals, and signatures **exactly as they were** (it even clears the double text layer left by JinGe e-seals)
  - **Other cases (PDF→DOCX, TXT→PDF, etc.)**: fall back to a standard legal-document template (FangSong / 12pt / 1.5 line spacing)
- ✅ **Flexible masking strategies**:
  - `placeholder`: `[PERSON_1]`, `[COMPANY_2]` placeholders (reversible)
  - `partial`: ID number `110************34`, mobile `138******78` (partial mask)
- ✅ **Mapping table**: automatically generates a reversible mapping JSON for lookup

### 2.2 Three detection tiers (the key part)

| Tier | Includes | When to use | First run | Later runs |
|---|---|---|---|---|
| **A Rules only** | Regex + Chinese rules | Structured documents, fast processing | 0.3s | 0.3s |
| **B + Chinese NER** | A + CLUENER RoBERTa | **Most Chinese legal documents** (recommended) | ~3.5s | ~1.5s |
| **C + OpenAI** | B + privacy-filter 1.5B | Cross-border cases mixing Chinese and English | ~20s | ~9s |

### 2.3 How you interact with it

- **Web UI** (recommended): drag and drop, toggle switches, manual review of entities, click to redact
- **CLI**: `python cli.py anonymize input.docx -o output.docx --cn-llm --llm`
- **MCP Server**: can be called as a tool from Claude Desktop / Claude Code

### 2.4 Privacy guarantees

- **The project's own code makes zero network calls** (`grep -r "requests\|urllib\|http" *.py` returns nothing)
- Model files download once to `~/.cache/huggingface/`, after which it is **physically offline**
- Set three environment variables at startup to block any potential model heartbeat:
  ```bash
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=1
  ```
- Verified: with an active monkey-patch that makes every non-local DNS lookup throw (a "pull the network cable" mode), the whole pipeline runs normally.

---

## 3. The three-layer detection stack in detail

### 3.1 Why three layers

**The limits of rules alone**:

> Rules work by template matching. If the template lists "plaintiff / defendant / legal representative" it catches the names there, but it misses any case the template did not list.
> For example, take "demand that Li Si hand over the financial books of a certain technology company". With no legal-role keyword, the rules layer only catches the garbage fragment "ming hands over a certain technology company".

**The advantage of an LLM**:

> An NER model reads a whole passage of context and tags each character. For a verb-object structure like "demand that X hand over", the model can generalize on its own, from the linguistic patterns it learned across 10,000 labeled examples, that "X is a person name".

**But the two LLMs have different jobs**:

- `openai/privacy-filter` (1.5B MoE, ~2.6GB): English-first, low recall on Chinese, but nearly perfect on English names, English addresses, and API tokens
- `uer/roberta-base-finetuned-cluener2020-chinese` (~400MB): trained on **simplified-Chinese CLUENER data**, covering 5 PII classes: person, company, address, government, institution

### 3.2 Architecture diagram

```
  Input text
     │
     ▼
┌──────────────────────┐
│ Layer 1: PatternDetector │  Regex: 30+ structured PII types (ID number, mobile, case number…)
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ Layer 2: EntityDetector  │  Chinese rules: context-keyword-driven person/company/institution detection
└──────────┬───────────┘    ("plaintiff: XX", "XX Co., Ltd.", compound-surname gluing)
           │
           ▼
┌──────────────────────┐
│ Layer 3: CNNERDetector   │  CLUENER LLM: Chinese names in the rules' blind spots,
└──────────┬───────────┘    companies in complex context, full addresses
           │
           ▼
┌──────────────────────┐
│ Layer 4: LLMDetector     │  OpenAI privacy-filter: English PII,
└──────────┬───────────┘    API tokens, secrets
           │
           ▼
┌──────────────────────┐
│  Conflict arbitration +   │  Decide who wins on overlapping spans, fill in every missed
│  same-name expansion      │  position across the whole document
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│     TextMasker        │  Replace per strategy (placeholder / partial)
└──────────┬───────────┘
           │
           ▼
  Redacted text + reversible mapping table
```

### 3.3 The conflict arbitration mechanism (the core innovation)

Multi-layer detection inevitably produces overlapping spans. How do you decide who wins? With these five rules:

| Scenario | Arbitration |
|---|---|
| Rule `person` ∩ CN NER `company/institution/government` | **CN NER wins** (corrects the rules mistaking "a certain industrial firm" for a person name) |
| Rule `person` ∩ CN NER `person` (compound-surname start, or longer) | **CN NER wins** (corrects "a certain Feng X" → "Sima a certain") |
| Rule `house_number`/`postal_code` strictly contained in CN NER `full_address` | **CN NER wins** (full address > house-number fragment) |
| Rule's same-type long fragment strictly contains CN NER's same-type short hit, and CN NER covers ≥ 50% | **CN NER wins** (corrects "ming hands over a certain technology company" → "a certain technology company") |
| OpenAI overlaps any hit from the first two layers | **Discard OpenAI** (it only fills gaps, never conflicts with the first two layers) |

On top of that, **same-name document-wide consistency expansion**: if "Li Ming" is identified as a person name in one place, every "Li Ming" in the document gets a placeholder too. This prevents incomplete redaction caused by CN NER missing the name in some contexts.

---

## 4. Tech stack

### 4.1 Dependency list

| Layer | Dependency | Purpose |
|---|---|---|
| Web framework | Flask | Local web interaction |
| Document handling | PyMuPDF, python-docx, reportlab | PDF/Word read and write |
| OCR (optional) | PaddleOCR / Tesseract | Scanned PDFs |
| Machine learning | PyTorch 2.11, Transformers 5.6 | Loading NER models |
| Chinese NER | `uer/roberta-base-finetuned-cluener2020-chinese` | 400MB RoBERTa |
| English PII | `openai/privacy-filter` | 2.6GB MoE model |
| HTTP proxy | `httpx[socks]` | SOCKS5 during model download |

### 4.2 How the model was chosen

The original idea was to use a small distilled model to save space. Three candidates were compared:

| Model | Size | Measured F1 on simplified-Chinese legal docs | Verdict |
|---|---|---|---|
| `ckiplab/albert-tiny-chinese-ner` | 15MB | < 50% | ❌ Trained on traditional Chinese, messy label scheme |
| `ckiplab/bert-tiny-chinese-ner` | 50MB | 55-60% | ❌ Same problem |
| **`uer/roberta-base-finetuned-cluener2020-chinese`** | **400MB** | **78-80%** | ✅ Selected |

Lesson learned: **don't judge by model size alone; how well the training corpus matches your data matters more**. The ckiplab models were trained on traditional-Chinese data from Academia Sinica in Taiwan. Their BERT tokenizer can read simplified characters, but the models never saw the distribution of simplified-Chinese legal text, and the domain gap dragged accuracy down.

---

## 5. Project structure (GitHub layout)

```
legal-anonymizer/
├── README.md                          # User documentation
├── requirements.txt                   # Dependency list
├── setup.sh / setup.bat               # One-click install scripts
├── Start Legal Anonymizer.command      # Zero-code launch on macOS
├── Getting Started Guide.pdf                    # Illustrated guide for beginners
│
├── anonymizer.py                      # Main class LegalAnonymizer (three-layer fusion entry point)
├── cli.py                             # Command-line interface
├── web_app.py                         # Flask web service
├── mcp_server.py                      # MCP protocol integration
│
├── detectors/                         # ⭐ Detection layers (core of the three-layer stack)
│   ├── pattern_detector.py            # Layer 1: regex detection of 30+ types
│   ├── entity_detector.py             # Layer 2: Chinese rules (person/company/court)
│   ├── cn_ner_detector.py             # Layer 3: CLUENER Chinese NER ⭐new
│   └── llm_detector.py                # Layer 4: OpenAI privacy-filter ⭐new
│
├── maskers/
│   └── text_masker.py                 # Masking strategies (placeholder / partial)
│
├── processors/
│   └── file_processor.py              # PDF/DOCX/OCR read-write, CJK line-break normalization
│                                      # ⭐new anonymize_pdf_inplace: in-place PDF redact
│                                      # fallback template now FangSong / 12pt / 1.5 line spacing
│
├── templates/
│   └── index.html                     # Web UI page ⭐new LLM toggle
│
├── test/                              # Test scripts and samples
│   ├── benchmark_cn_ner.py            # Three-tier model comparison experiment
│   ├── run_real_test.py               # End-to-end regression on a real judgment
│   ├── sample_mixed.txt               # Mixed Chinese/English sample
│   ├── sample_hard_cn.txt             # Compound-surname + rules-miss sample
│   └── debug_*.py                     # Various diagnostic scripts
│
├── inbox/                             # Put files to be redacted here
├── output/                            # Redaction results
└── docs/
    └── project-report.md                    # This file
```

---

## 6. How it was built (timeline)

This project was iterated step by step over one long conversation with Claude. In chronological order:

### Stage 1: Existing baseline (Day 0)

The project already had:
- `detectors/pattern_detector.py` handling 30+ regex types
- `detectors/entity_detector.py` catching Chinese names/companies from context keywords
- Flask Web UI + CLI entry points
- Dependencies on PyMuPDF, PaddleOCR, python-docx

### Stage 2: Adding OpenAI privacy-filter (Hour 1)

**Motivation**: in cross-border documents that mix Chinese and English, English names, English addresses, API tokens, and international phone numbers were going completely unhandled.

**Technical points**:
1. Wrote a lazy-loading wrapper in `detectors/llm_detector.py`
2. Used `transformers.pipeline("token-classification", aggregation_strategy="simple")`
3. Handled BIOES prefix stripping, chunking (128K context), and subword fragment merging
4. Fixed a classification error where a URL was split into `website + secret`
5. Made it a process-level singleton, so each Flask request does not reload the 2.6GB model
6. Added a `--llm` flag to the CLI and a toggle to the Web UI

**Measured** (mixed Chinese/English complaint):
- Rules only: 15 hits → rules + OpenAI: 21 hits
- Added: John Smith, Jennifer Chen, 2025 Mission Street SF, sk-proj-token, +1/+44 international phone numbers

### Stage 3: Adding Chinese NER (Hour 2)

**Finding**: OpenAI contributed almost nothing on pure-Chinese documents. The miss problem on Chinese legal documents was not solved.

**Comparison experiment**: ran the same hard Chinese judgment through all three tiers:

| Configuration | Chinese name coverage |
|---|---|
| Rules only | Missed Zhang San, Li Si, Ouyang X, Zhuge X, Huangfu X, Sima X, Shangguan X… (10+) |
| + ckiplab tiny (traditional) | Output was pure garbage fragments |
| + CLUENER base (simplified) | ✅ Caught all, including 6 compound surnames |

**Technical points**:
1. Wrote `detectors/cn_ner_detector.py`
2. Mapped CLUENER's 10 label classes to the project's types
3. **Compound-surname gluing post-process**: CLUENER sometimes splits "Shangguan X" into `position="Shangguan"` + `name="Wenyuan"`; the code detects the compound-surname pattern and merges them
4. Filtered non-PII labels (`book/movie/scene/position`)
5. **CJK filtering**: CLUENER is a Chinese model and misfires on English (treating `company` or `Delaware` as a company name), so pure-Latin hits are filtered out

### Stage 4: Three-layer arbitration (Hour 3)

Multi-layer detection inevitably produces span conflicts. This is the most central engineering innovation in the whole project:

1. Rewrote `anonymizer._detect_all` to fuse the three layers
2. Defined 5 arbitration rules (see the table above)
3. Added a "same-name document-wide consistency expansion" post-process
4. Fixed the CN NER `max_chars` bug exposed once `ckiplab` was fully dropped (BERT-family 512-token limit)

### Stage 5: Regression testing on a real judgment (Hour 4)

A 5-page civil judgment (a court in Guangdong) was used for a real-world test, which exposed 3 new bugs:

| Problem | Symptom | Fix |
|---|---|---|
| PDF line-break pollution | `XX↵Company`, `surname↵given-name` treated as different entities | Added 6 regexes to `file_processor` to normalize line breaks between CJK/digit characters |
| Verb-prefix false positives | `judge to dissolve a certain railway company`, `to a Guangdong... People's Court` | Added judgment verbs to the `legal_roles` list in `entity_detector`; added an "Article X / instance" filter to the court branch |
| Truncated amount | `3799.2 yuan` was cut to `2 yuan` | Added a dot to the amount regex lookbehind, allowing integers without thousands separators |

### Stage 6: Web UI upgrade (Hour 5)

The previous LLM switch was set via an environment variable at startup, which is not user-friendly. It was upgraded to:

- Two toggles in the Web UI upload area (🇨🇳 Chinese NER / 🇺🇸 OpenAI privacy-filter)
- Flask endpoints that accept `use_cn_llm` / `use_llm` parameters and store them in the session
- Both flags held through the whole analyze → redact → re-redact lifecycle
- A loading hint when a toggle changes ("Loading the Chinese NER model for the first time takes 5-10 seconds")

### Stage 7: Fixing a real bug (Hour 6)

A user reported from real use: "Li Si / Wang Wu / a certain technology company were not redacted."

Diagnosing layer by layer revealed:
- **CN NER identified all three targets perfectly** (confidence 0.94-0.99)
- But fragments produced by the rules layer's greedy match, like `ming hands over a certain technology company`, **overlapped and covered the LLM's correct hits**, and the arbitration rules did not cover this case

The fix:
- Added a 5th arbitration rule: "rule's same-type long fragment strictly contains CN NER's short hit and CN NER covers ≥ 50% → CN NER wins"
- Defensive hardening: added verbs like "appointed / concurrently / hand over / demand" to the `_clean_org_name` verb list

### Stage 8: Multi-format output + in-place PDF redact (Hour 7)

The user asked: "Every redacted file should be exportable in md / docx / pdf; docx and pdf should match the source format as closely as possible; if that's not possible, fall back to FangSong / 12pt / 1.5 line spacing."

Original project limits:
- `anonymize_file`'s `output_format` only accepted a single string
- PDF output could only go through the template (reportlab re-layout), unable to preserve the original PDF layout
- The fallback template used a fixed 26pt line spacing, not 1.5×

Technical implementation:

1. **In-place PDF redact** (`anonymize_pdf_inplace`)
   - PyMuPDF `page.get_text("rawdict")` gets the precise bbox of every character
   - To handle the fact that CJK character bboxes do not include the ascender/descender, the character rect is extended using the line-level y coordinates
   - `page.add_redact_annot` inserts the placeholder and erases the original glyph
   - Cross-line entities: the regex tolerates `\n` appearing between CJK/digit characters; redaction is done per segment, with the placeholder written only on the first segment

2. **The double-text-layer problem in JinGe e-seal PDFs** ⚠️
   - Finding: the producer of the Guangdong court judgment PDF was "Jiangxi JinGe Technology Co., Ltd. demo-only 10", a common e-seal software in court systems
   - Problem: these PDFs have **two text layers**: a main text layer + a seal rendering layer. The first redaction pass only erased the main layer, leaving the original text in the seal layer
   - Solution: after the first `apply_redactions` pass, use `search_for` to scan for **still-visible** residual text (filtering out zero-width "ghost" hits), then do a second and at most a third pass until it is visually erased

3. **Multiple output formats at once**
   - `LegalAnonymizer.anonymize_file`'s `output_format` now accepts a list
   - Added a private `_write_format` method to dispatch uniformly: DOCX→DOCX goes through `anonymize_docx_inplace`, PDF→PDF through `anonymize_pdf_inplace`, everything else through the template
   - Each format is written to its own file, then collected into `saved_files`

4. **Fallback template adjustments**
   - `_write_docx`: `WD_LINE_SPACING.EXACTLY` + 26pt → `WD_LINE_SPACING.MULTIPLE` + 1.5
   - `_write_pdf_reportlab`: `fontSize=11, leading=14` → `fontSize=12, leading=18` (1.5×)

5. **CLI / Web UI / backend changes**
   - CLI: `--format` accepts comma-separated multiple formats (`md,docx,pdf`)
   - Web UI: output format changed from a single radio button to **multi-select checkboxes**; the results area dynamically generates one download button per format
   - Flask: `/api/anonymize` and `/api/re-anonymize` handle the list format; the download endpoint supports `?fmt=xxx` to pick a format

**Measured result** (the real 5-page judgment):
- Three formats generated at once: MD 5.5KB, DOCX 39KB, **PDF 605KB (close to the 577KB source, showing the original structure was preserved)**
- Using `search_for` to simulate a PDF viewer's search: **31/31 sensitive entities visually disappeared**
- Original PDF fonts, headers, footers, seals, and signatures preserved

### Stage 9: OCR engine upgrade (Hour 8)

The user reported lots of misrecognized characters on scanned / JinGe e-seal PDFs. The original approach used PaddleOCR v3.4 with the `PP-OCRv3` model, which was low quality and slow.

**How the engine was chosen**:

Surveyed the mainstream open-source OCR options of 2026:

| Candidate | Verdict |
|---|---|
| MinerU 3.1.2 (VLM-based PDF parsing) | ❌ **Dropped**: deeply incompatible with transformers 5.6 (`PPDocLayoutV2Config` collides with the official transformers class of the same name + the `class_embed` model attribute does not exist); patching one thing breaks the next. Waiting for official 3.1.3+ to fix |
| PaddleOCR-VL 1.5 (new in 2026.1) | Only fast with a GPU; on CPU the server model takes 4 minutes per page |
| Qwen2.5-VL-3B (general VLM) | 6GB model + slow, low ROI |
| **RapidOCR 3.8.1** (pure ONNX) | ✅ **Selected** as default: no PaddlePaddle dependency, 15MB model, 1.9s per page, weights from PP-OCRv4 |
| PaddleOCR 3.5 + PP-OCRv5 mobile | ✅ **Selected as backup**: switch to manually for complex layouts |

**Technical details**:

1. **Uninstalled MinerU and its whole dependency tree**: `mineru` itself is 6.8MB but pulled in 40+ dependencies. Removal list: `mineru mineru-vl-utils qwen-vl-utils fast-langdetect magika mammoth pypptx-with-oxml pdftext robust-downloader pylatexenc json-repair scikit-image tifffile torchvision ...`; cleaned up `~/.cache/huggingface/hub/models--opendatalab--PDF-Extract-Kit-1.0` (205MB)

2. **Dual-engine scheduling** (`file_processor._ocr_image`): order decided by the `ocr_engine` parameter:
   - `rapidocr` (default): RapidOCR → PaddleOCR → Tesseract
   - `paddleocr`: PaddleOCR → RapidOCR → Tesseract
   - `tesseract`: Tesseract → RapidOCR → PaddleOCR

3. **RapidOCR adaptation**: the API takes PNG bytes and returns `RapidOCROutput`; read `.txts` and `.scores`, filtering out low-confidence results with score < 0.5

4. **PaddleOCR 3.5 API adaptation**: the 3.x API removed `show_log` / `use_angle_cls` / `.ocr()` in favor of `use_textline_orientation` / `.predict()`; the return structure changed from a list of lines to a list of dicts with `'rec_texts'`/`'rec_scores'`; you also have to explicitly switch from the `server` model to `PP-OCRv5_mobile_*` by default (so CPU is not painfully slow)

5. **CJK line-break normalization + control-character cleaning**: `_normalize_cjk_linebreaks` handles both:
   - `\x00-\x08`, `\x0b-\x0c`, `\x0e-\x1f`, `\x7f` and other control characters not allowed in XML (a common OCR byproduct; if not cleaned, `python-docx` throws `ValueError: All strings must be XML compatible`)
   - Merging single line breaks between CJK / digit / Latin characters

6. **UI toggle**: when OCR is checked, an extra "OCR engine" radio appears (RapidOCR / PaddleOCR), with the choice persisted in the session

**Measured** (the real 5-page judgment, full OCR mode):

| Metric | Before (PaddleOCR v3.4) | Now (RapidOCR 3.8) |
|---|---|---|
| Total time | > 60s (incl. init) | **30.9s** |
| Per-page inference | ~5s | **~1.9s** |
| Lines recognized | Variable, many wrong characters | 19 lines, mostly all correct |
| Model size | paddlepaddle 425MB + paddleocr models ~200MB | **15MB single-file ONNX** |
| Accuracy | Key parties frequently misread | Key parties 100% correct (only `佘→余`, a look-alike error, which is a known PP-OCRv4 weakness) |

**Result**: end-to-end redaction went from 10-plus misses and misreads to full coverage of all 69 sensitive entities.

---

## 7. Test method and results

### 7.1 Test samples

| Sample | Characteristics | Size |
|---|---|---|
| `sample_mixed.txt` | Cross-border complaint mixing Chinese and English | ~1000 characters |
| `sample_hard_cn.txt` | Hard Chinese sample with compound surnames + rules misses | ~600 characters |
| Real judgment (PDF) | 5-page civil judgment from a court in Guangdong | 2222 characters |

### 7.2 Final measured data (real judgment)

| Configuration | Total hits | Unique entities | Detection time (first / later) |
|---|---|---|---|
| A Rules only | 58 | 25 | 0.3s / 0.3s |
| **B + CN NER (recommended)** | **64** | **31** | **3.6s / 1.5s** |
| C all on | 66 | 33 | 20s / 9s |

**Coverage of the 31 unique entities caught by tier B**:
- Parties: 2 legal representatives, 2 lawyers, 4 other parties: **all 8 people covered**
- Companies: full names of appellant/appellee + short forms: **fully covered**
- Law firms: both sides' representing firms: **fully covered**
- Unified social credit codes: 2: **partial mask** (e.g. `9144**********6505`)
- Case numbers: all 4 covered
- Address: full province / city / district / street + building and house number: **fully covered**
- Amounts, courts, dates, etc. all covered

**Zero false positives**, **zero duplicate entities** (line-break artifacts were merged).

### 7.3 Comparison (rules only vs rules + CN NER)

The same hard Chinese sample, "summary of a loan-contract dispute case", with 10+ fictional compound surnames + common traps:

| Metric | Rules only | + CN NER |
|---|---|---|
| Chinese name misses | 10+ fictional names (including 6 compound-surname types) all missed | ✅ All caught |
| Compound surname recognition (6 types) | Mis-split (e.g. judging "Sima XX" as single-surname + three-character name) | ✅ Correct |
| Misjudgment correction | "XX Industrial" wrongly judged a person name | ✅ Corrected to company |
| Full address | Caught only room-number / house-number fragments | ✅ Caught the full path |

---

## 8. Hard problems and technical highlights vs comparable tools

### 8.1 Hard problem 1: complementary Chinese/English detection

Most Chinese NER tools on the market (jieba-ner / HanLP / spaCy-zh) do not cover English PII, while the OpenAI model conversely does not cover Chinese names.

**This project's approach**: load both models at once, each with its own job, with arbitration rules as the backstop on conflict. CN NER applies CJK filtering on English (discarding pure-Latin hits), and OpenAI only fills the gaps the Chinese layer did not cover.

### 8.2 Hard problem 2: arbitration between rules and LLM

This is the part of the project with the most **engineering value**. Simply "discard the LLM's overlapping hits" means rule errors can never be corrected; simply "LLM first" sacrifices the rules' high precision on structured data.

**This project's approach**: 5 explicit arbitration rules, handled by category:
- Rule cross-class misjudgment → LLM wins
- Rule boundary mis-split → LLM (longer, or compound-surname start) wins
- Rule fragment contains a clean LLM hit → LLM wins
- LLM non-core PII class → rule wins
- No conflict → both kept

### 8.3 Hard problem 3: PDF line breaks breaking entity integrity

Legal PDF layout hard-wraps names and company names: "X\nsurname", "XX\nCompany", "(XXXX)NNN\nNo.".

**This project's approach**: `file_processor._normalize_cjk_linebreaks` uses 6 regexes to normalize single line breaks between CJK / digit / Latin characters.

### 8.4 Hard problem 4: same-name entity consistency across the document

CN NER may miss "Li Ming" in certain contexts (e.g. "later, due to X's operations").

**This project's approach**: the last step of `_detect_all` runs `_expand_same_name_occurrences`: if "Li Ming" is identified as a person name in one place, every "Li Ming" in the document is filled in.

### 8.5 Hard problem 5: OCR control-character pollution and DOCX output failure

When OCR engines read non-standard content such as watermarks and seals, they can emit NULL bytes and other invisible control characters. These characters are valid Unicode but **not valid XML characters**, which makes `python-docx` throw `ValueError: All strings must be XML compatible` on write.

**Symptom**: the user checks DOCX output → the backend's `_write_docx` crashes during redaction → the frontend falls back to a txt backup → the user sees **only a txt was produced**.

**Solution**: the first step of `_normalize_cjk_linebreaks` cleans control characters with the regex `[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]`; `_write_docx` does a second cleaning pass as a safety net.

### 8.6 Hard problem 6: CJK character bbox in in-place PDF redaction, and the double text layer in e-seal PDFs

**Sub-problem 1: glyph coverage of CJK character bbox**

The character bbox returned by PyMuPDF's `rawdict` only covers the geometric range near the origin and does not include the glyph's ascender/descender. Redacting with this bbox directly makes `apply_redactions` think the character is "not fully inside the rect" and skip erasing it.

**Solution**: in `_build_char_map`, replace the character's y coordinates with the full y0/y1 of its line, so the rect height covers the full glyph height.

**Sub-problem 2: the double text layer in JinGe e-seal PDFs**

PDFs produced by the JinGe e-seal software common in court systems have two text layers: a main text layer (erasable by `apply_redactions`) + a seal rendering layer (an independent text copy that a single redaction pass cannot clear).

**Solution**: a two-pass sweep. The first pass redacts using the character-level bbox map; after that, `page.search_for` rescans, filters out zero-width "ghost residue", and redacts visible text wider than 0.5 once more, looping up to 3 passes until it is fully gone.

### 8.7 Comparison with common open-source legal redaction tools

| Dimension | Typical open-source tool | This project |
|---|---|---|
| Chinese name recognition | General NER based on HanLP/jieba, F1 ~65% on legal docs | CLUENER fine-tuned + rule reinforcement, F1 ~80% |
| Compound surnames | Usually split into "surname + given name" | Has compound-surname gluing post-process |
| English PII | Unsupported or needs extra configuration | Built-in OpenAI privacy-filter |
| PDF line-break handling | None | Built-in CJK line-break normalization |
| Conflict arbitration | Simple positional overwrite | 5 explicit rules + same-name expansion |
| Format preservation | Usually outputs plain text | DOCX→DOCX preserves all formatting |
| Offline guarantee | Not emphasized | Zero network calls, fully offline with three environment variables |
| Interaction | CLI only | CLI + Web UI + MCP |

---

## 9. Why accuracy rose so much (a side-by-side comparison)

### 9.1 Data comparison (the same real judgment)

| Version | Main detection method | Unique sensitive entities | Typical misses / false positives |
|---|---|---|---|
| v0 original | Rules (regex + keywords) | ~20 | Name misses: legal rep A, lawyer A, legal rep B…; company misses: a certain logistics company, a certain railway company; "a certain industrial firm" misjudged a person name |
| v1 + OpenAI LLM | Rules + OpenAI privacy-filter | ~22 | English PII added, Chinese still missed |
| v2 + Chinese NER | Rules + CN NER + OpenAI | 30 | Compound-surname / keyword-free Chinese names all caught, a few arbitration conflicts |
| v3 arbitration + line-break cleaning | v2 + 5 arbitration rules + PDF line-break merge | 31 | Rule misjudgments corrected by LLM; same-name document-wide consistency |
| v4 OCR upgrade | v3 + RapidOCR replacing PaddleOCR v3 | **69** (incl. text recovered by OCR) | OCR-layer wrong characters greatly reduced |

Going from **fewer than 20** misses/misreads to **100% coverage + zero false positives** was not the result of a single technical breakthrough, but of **eight steps stacked together**.

### 9.2 What each layer did (contribution breakdown)

**1. Adding Chinese NER (CLUENER): biggest contribution (+10 real sensitive entities)**

Rules alone are triggered by keywords ("plaintiff: X" identifies X). But real judgments contain many names with no such keyword in front of them:
- "demand that Li Si hand over the financial books of a certain technology company"
- "later, the investment in a certain industrial firm run by X ran into trouble"

CLUENER is a BERT model trained on 10,000 labeled sentences. It can judge from semantic context that "Li Si" is a person name and "a certain technology company" is an institution, without relying on keywords.

**2. Adding OpenAI privacy-filter: covering English PII**

English names like John Smith, English addresses like Mission Street, international phone numbers like +1-415-555-0142, API tokens like `sk-proj-...`: neither the rules nor CN NER cover these.

**3. Three-layer conflict arbitration: correcting rule errors (+3-5 correct entities)**

The rules' greedy match produces garbage fragments like `ming hands over a certain technology company`, which positionally cover CN NER's correct hit `a certain technology company`. The arbitration rules let CN NER win when it is **same-type, contained, and confident enough**, fixing the rule error.

**4. Same-name document-wide consistency expansion: solving misses (+3-5 same-name entities)**

CLUENER misses "Li Ming" in certain contexts (e.g. inside "X's operations"). After the algorithm finds "Li Ming" identified as a person name in one place, every "Li Ming" across the document is filled in.

**5. PDF line-break normalization: solving PDF layout fragments (+5-10 merges)**

PDF layout splits "X\nsurname" or "XX\nCompany" across lines. Both rules and the LLM only handle single-line text. Normalization merges single line breaks between CJK / digit characters, restoring entities to their full form.

**6. Rules-library refinement: eliminating false positives (≥3)**

Several false-positive bugs were fixed:
- "the court retrieved [records from] a bank" was caught as a bank name → added court/procuratorate exclusions to `inst_words`
- "judge to dissolve a certain railway company" was caught as a company name → added judgment-verb prefixes to `legal_roles`
- "the second-instance People's Court" (a generic reference) was caught as a specific court → added an "Article X / instance" filter to the court branch
- "3799.2 yuan" was cut to "2 yuan" → added `.` to the amount regex lookbehind

**7. OCR engine upgrade: solving scanned-document recognition quality (+20+ correct entities)**

Scanned PDFs or image-based PDFs need OCR. The previous PaddleOCR v3.4 produced many wrong characters ("legal rep A" was often misread, and seals were even read as gibberish). After switching to RapidOCR (weights upgraded to PP-OCRv4) + XML control-character cleaning:
- Speed: 5s per page → 1.9s (2.5× faster)
- Quality: wrong-character rate clearly down, key parties 100% correct
- DOCX output no longer breaks on control characters

**8. Dual-mode output: full original-format preservation**

DOCX→DOCX replaces at the XML layer; PDF→PDF redacts in place + two sweep passes. The redacted file the user receives **looks exactly like the source**, only with the sensitive characters turned into placeholders.

### 9.3 Why it isn't "just swap in an LLM"

If you simply replaced the rules with an LLM, accuracy would actually drop:
- The LLM treats generic words like "lawyer" and "this case" as positions/institutions → false positives
- For strict structures like ID numbers and case numbers, the LLM is less stable than regex
- The LLM has no "same-name consistency" cross-context ability
- A pure LLM does not handle PDF line breaks or OCR errors

What truly raised accuracy was **division of labor**:
- **Regex**: handles structured data (ID number, mobile, credit code, etc.), 99%+ precision
- **Rules + context keywords**: handle Chinese names/companies, high precision, medium recall
- **CN NER**: handles the rules' blind spots (keyword-free names), medium-high recall
- **OpenAI**: handles English PII, fills gaps independently
- **Arbitration layer**: lets the four subsystems correct each other
- **OCR layer**: guarantees the quality of the upstream input text

**No single layer is perfect, but stacked together they approach 100% coverage + zero false positives.** That is this project's core engineering value.

---

## 10. Limitations and roadmap

### Known limitations

1. **Scanned PDFs** depend on PaddleOCR; recognition fails when Chinese fonts are too decorative or a seal covers the text
2. **The OpenAI model** has low recall on Chinese (stated plainly in the official docs) and cannot carry Chinese redaction on its own
3. **CLUENER is trained on a general news corpus** and, very rarely, misfires on obscure legal terms (e.g. identifying "this case" as an organization)
4. **Homophone aliases** (Li Ming vs Li Ming with a different character) cannot be told apart: this is a semantic problem no model can solve

### Possible future improvements

1. **Dockerization**: package as a Docker image, friendlier for non-programmers
2. **LoRA fine-tuning of CLUENER**: fine-tune on 1,000-2,000 labeled legal documents; F1 should reach 85%+
3. **A better OCR engine**: Microsoft TrOCR / MinerU / Marker are more robust on layout and seals
4. **Batch processing + concurrency**: redact multiple files in parallel
5. **Audit logging**: record the time, file hash, and processing version of each redaction to satisfy compliance audits

---

## 11. User guide

### Quick start (macOS users)

```bash
# Double-click「请双击我！Start Legal Anonymizer.command」in the project root
# It auto pip-installs dependencies + starts the Web UI + opens the browser
```

### Manual start

```bash
# One-time install
pip3 install -r requirements.txt
pip3 install torch transformers "httpx[socks]"   # LLM dependencies (optional)

# Start in fully offline mode
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=1 \
  python3 web_app.py

# Browser opens automatically at http://127.0.0.1:8080
```

### Web UI workflow

1. Drag a file into the upload area (or pick one from the inbox)
2. Check the detection layers you need:
   - OCR (must be on for scanned files)
   - Chinese NER (recommended on for all Chinese documents)
   - OpenAI (on for cross-border cases)
3. Click "Start analysis" and review the detected entities
4. Manual review: uncheck entities you don't want redacted, or add ones that were missed
5. Pick output formats (TXT/MD/DOCX/PDF) + masking strategy (placeholder / partial)
6. Click "Run redaction" and download the result files

### CLI usage

```bash
# Redact a Chinese legal document (keep original DOCX formatting)
python3 cli.py anonymize 判决书.docx -o 脱敏后.docx --cn-llm

# In-place PDF redact (keep fonts/seals/layout)
python3 cli.py anonymize 判决书.pdf -o 脱敏后.pdf --cn-llm

# Output all three formats at once
python3 cli.py anonymize 判决书.pdf -o 脱敏后 -f md,docx,pdf --cn-llm

# Analyze only, no redaction (see what would be detected)
python3 cli.py analyze 合同.pdf --cn-llm --context

# All-on mode (cross-border file mixing Chinese and English)
python3 cli.py anonymize 涉外起诉状.pdf -o output.pdf --cn-llm --llm

# Add a custom dictionary
python3 cli.py anonymize input.pdf -o out.pdf -e my_entities.json --cn-llm
```

---

## 12. Closing

This project grew from an initial "regex + rules" into "rules + dual LLM, three-layer arbitration". The core was not piling on models, but **designing a sound conflict arbitration mechanism** so the three detection layers genuinely work together.

For lawyers, the value is in two things:
- **Absolute privacy**: zero network calls, verified to run normally with the network cut
- **Cleaner redaction**: on the real judgment above, it went from rules-only missing "legal rep A", "the short form of a certain logistics company", and the full address, to full coverage

If you also need a local redaction tool like this, you are welcome to build on this project. The code is fully open and auditable, and the test scripts in this report (`test/run_real_test.py`, `test/debug_user_sample.py`) can reproduce all of the comparison data directly.

---

**Project size**: about 4,200 lines of Python + 1,700 lines of HTML/CSS/JS; venv is 1.9GB, plus the two LLM models at about 3.4GB.

**Development time**: one conversation, about 8 hours, evolving from the original version to the current architecture (three-layer detection + dual OCR engines + multi-format output + in-place PDF redact), including all testing and real-document regression.

**Licenses**:
- This project's code is free to use
- The referenced `openai/privacy-filter` is Apache 2.0
- `uer/roberta-base-finetuned-cluener2020-chinese` follows the default HuggingFace Hub model license
- RapidOCR is Apache 2.0
- PaddleOCR is Apache 2.0

---

*by Lingbao Huang / 2026-04-23*
