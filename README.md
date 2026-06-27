# Legal Anonymizer

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.9%2B-green.svg)](https://www.python.org)
[![Platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Windows%20%7C%20Linux-lightgrey.svg)]()
[![Offline](https://img.shields.io/badge/Network-100%25%20Offline-success.svg)]()
[![PRs Welcome](https://img.shields.io/badge/PRs-Welcome-orange.svg)]()

> ⚠️ **Read [DISCLAIMER.md](DISCLAIMER.md) before use.** This is an assistive redaction tool and does not replace human review. The user is responsible for confirming the final result.

A **100% local, offline** anonymization tool for legal documents.
No data leaves your machine. No cloud APIs. No subscriptions.

Built for lawyers, paralegals, and compliance teams who need to redact sensitive information before sharing documents, while keeping the original formatting intact. The detection engine targets Chinese-format data and Chinese NER by default; an optional English layer can be enabled for cross-border work.

## Features

- **Fully offline** — all processing happens on your computer; nothing is uploaded
- **3-layer detection** — regex rules + Chinese NER (CLUENER) + English LLM (OpenAI privacy-filter, optional)
- **30+ sensitive data types** — names (including compound surnames), companies, ID numbers, phone numbers, bank cards, case numbers, addresses, amounts, emails, API tokens, and more
- **Triple output format** — one run produces **MD + DOCX + PDF** simultaneously
- **Format-preserving** — DOCX→DOCX keeps fonts and layout; PDF→PDF redacts in-place, preserving stamps and page structure
- **Dual OCR engines** — RapidOCR (fast, lightweight) by default; switch to PaddleOCR for complex layouts
- **Chinese-friendly** — recognizes compound surnames (欧阳 / 万俟 / 诸葛 / 皇甫 / 司马 / 上官) and automatically merges PDF layout line breaks
- **Chinese-English mixed documents** — handles bilingual legal filings, cross-border contracts, international arbitration materials
- **Web UI + CLI** — drag-and-drop browser interface, or batch-process via command line

## Quick Start

### macOS / Windows (recommended)

1. Download the latest zip from **[Releases](../../releases)**
2. Unzip anywhere (e.g., Desktop)
3. Double-click:
   - **macOS**: `Start Legal Anonymizer.command` (the "double-click me" launcher)
   - **Windows**: `Start Legal Anonymizer.bat` (the launch tool)
4. First run auto-installs dependencies and downloads the Chinese NER model (~400 MB, 3-5 minutes)
5. Browser opens at `http://127.0.0.1:8080` — start using immediately
6. Subsequent launches skip to step 5 (dependencies and models cached)

> **macOS security prompt?** Go to System Settings → Privacy & Security → scroll down → click "Open Anyway", enter your password, then double-click the file again. See [macOS-security-setup.md](macOS-security-setup.md) for details.

### Manual install

**Step 1: confirm you have Python 3.9+**

```bash
python3 --version   # macOS
python --version    # Windows
```

If not, install it from https://www.python.org/downloads/ (on Windows, check `Add Python to PATH` during installation).

**Step 2: install and launch**

```bash
git clone https://github.com/rainbow1111-lalala/legal-anonymizer.git
cd legal-anonymizer
pip3 install -r requirements.txt   # use pip on Windows
python3 web_app.py                  # use python on Windows
```

## CLI Usage

```bash
# Anonymize a Word document
python3 cli.py anonymize input.docx -o output.docx

# Anonymize a PDF
python3 cli.py anonymize input.pdf -o output.pdf

# Scanned PDF with OCR
python3 cli.py anonymize scan.pdf -o output.docx --ocr

# Analyze only (no redaction)
python3 cli.py analyze input.docx

# List all supported sensitive data types
python3 cli.py list-types
```

## Optional: Enable LLM Layers

| Layer | Model | Size | What it catches |
|---|---|---|---|
| CN NER | `uer/roberta-base-finetuned-cluener2020-chinese` | ~400 MB | Chinese names (incl. compound surnames), Chinese companies, Chinese addresses |
| EN LLM | `openai/privacy-filter` (1.5B MoE) | ~2.6 GB | English names, English addresses, international phone numbers, API tokens |

```bash
pip3 install torch transformers

# Chinese NER only (recommended; fills in Chinese names/companies/addresses the rules miss)
python3 cli.py anonymize input.docx -o output.docx --cn-llm

# English LLM only (for English-primary documents)
python3 cli.py anonymize input.docx -o output.docx --llm

# Both layers (strongest mode for Chinese-English mixed documents)
python3 cli.py anonymize input.docx -o output.docx --cn-llm --llm
```

**Three-layer arbitration:**

1. Structured data (ID numbers, bank cards, emails, etc.) is always handled by the rules engine
2. CN NER corrects boundary errors and misclassifications from the rules layer
3. Full-document consistency for repeated names: a name CN NER misses in one place is automatically extended across the whole document
4. OpenAI only fills the gaps: it covers only what the first two layers did not catch
5. CN NER does not run on English paragraphs, avoiding false positives on common English words

## Detection Benchmarks

**Hard Chinese sample** (loan-contract judgment):

| Item | Rules only | + CN NER |
|---|---|---|
| Missed Chinese names | 10+ (including 6 compound surnames) | all caught |
| Compound surname recognition | mis-split ("司马XX" → "司" + "马XX") | merged correctly |
| Full address | only address fragments caught | full address |

**Chinese-English mixed sample** (cross-border civil complaint):

| Item | Rules only | + CN NER + OpenAI |
|---|---|---|
| English names | missed | John Smith / Jennifer Chen |
| English addresses | missed | 2025 Mission Street, San Francisco |
| International phone numbers | missed | +1 / +44 |
| API tokens | missed | sk-proj-... |

## Privacy & Security

- Zero network calls during processing — `grep -r "requests\|urllib\|http" *.py` returns nothing for data paths
- LLM models download once to `~/.cache/huggingface/`, then run fully offline
- To enforce air-gap mode: `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python3 web_app.py`

## Docs

- [`docs/project-report.md`](docs/project-report.md) — full technical report (architecture, benchmarks, development history)
- [`docs/brief-report.md`](docs/brief-report.md) — summary version for sharing with colleagues
- [`Getting Started Guide.pdf`](Getting Started Guide.pdf) — illustrated 13-chapter user guide
- [`DISCLAIMER.md`](DISCLAIMER.md) — liability disclaimer (read before use)

## FAQ

**`pip install` reports `Permission denied`**
Add `--user` before the command: `pip3 install --user -r requirements.txt`

**The browser did not open automatically**
Manually enter the address shown in the terminal, usually `http://127.0.0.1:8080`

**Error `Address already in use`**
The port is taken. The program automatically tries 8080-8099. If it still fails, close the other program holding the port.

**Error `ModuleNotFoundError: No module named 'flask'`**
Dependencies were not installed successfully. Run again: `python3 -m pip install -r requirements.txt`

## Contributing

- Found a missed detection? Open an issue with a (redacted) sample text
- Found a false positive? Same
- Want a new detection type? Open an issue to discuss before PR
- Documentation improvements? PR directly

## License

Apache License 2.0 — see [LICENSE](LICENSE).

## Acknowledgements

- [OpenAI Privacy Filter](https://huggingface.co/openai/privacy-filter)
- [CLUENER 2020](https://huggingface.co/uer/roberta-base-finetuned-cluener2020-chinese)
- [RapidOCR](https://github.com/RapidAI/RapidOCR)
- [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)
- [PyMuPDF](https://github.com/pymupdf/PyMuPDF)

---

*Made with ❤️ by Lingbao Huang (Rainbow Wong)*
