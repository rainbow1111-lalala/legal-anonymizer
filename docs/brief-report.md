# A local redaction tool for lawyers

> No network, no uploads, no leaks. From rough to usable in 7 hours.

---

## Why I built this

Lawyers handle contracts and judgments full of client names, ID numbers, and company names every day. This material:

- Can't go straight into ChatGPT to help you organize it: a leak crosses a professional-ethics red line
- Can't go into one of those online "redaction" tools either: that's like sending your client's case file to a stranger
- Can only be combed through by hand, one item at a time: a 50-page judgment will make your eyes blur

So I wanted a redaction tool that **runs entirely on your own computer and needs no network**. Upload a file, click once, download the result: that simple. And it has to be **accurate**.

---

## What it can do now

**One-sentence version**: it automatically masks every piece of sensitive information in a Word / PDF / TXT file (names, company names, ID numbers, phone numbers, addresses, amounts, case numbers…) and gives you a clean version + a mapping table.

**What sensitive information it can detect**:

| Category | Examples |
|---|---|
| Identity | ID number, passport, HK/Macau and Taiwan permits, military ID, unified social credit code |
| Contact | Mobile number, landline, 400 hotline, email, QQ/WeChat ID, address |
| Financial | Bank card no., amount (RMB / USD / written form), license plate |
| Legal-specific | Case number, contract no., invoice no., document no. |
| Parties | Chinese names (including compound surnames like Ouyang, Sima, Shangguan), company names, law firms, courts, government |
| English | English names like John Smith, English addresses, international phone numbers, API keys |

**Three detection methods working together**:

1. **The "rote memory" layer**: for fixed-format things like ID numbers, mobiles, and emails, a rules engine matches them precisely with regex
2. **The "reads Chinese" layer**: a small AI model (400MB) trained to recognize Chinese names/companies/addresses; even without a keyword like "plaintiff", it can judge from context that "Li Ming" is a person name
3. **The "understands English" layer**: an AI model OpenAI just open-sourced (2.6GB) that covers English sensitive information

**In plain terms**: rules handle the structured and strict cases; AI understands language and fills what the rules miss.

**For scanned PDFs / image PDFs**, two OCR engines are built in and switch as needed:
- **RapidOCR** (default, 15MB, 1.9s per page): fast, good enough for everyday documents
- **PaddleOCR 3.5** (backup, downloaded on demand, slower per page but more accurate on complex layouts): the lawyer can switch to it with a toggle in the Web UI

---

## The nicest part: **formatting kept exactly as it was**

The common problem with other redaction tools: feed in a Word file and you get back plain text, with fonts, line spacing, and tables all gone: you have to re-format it yourself.

**This tool is different**:

- **Word in → Word out**: it uses your original document structure, so font, size, paragraphs, tables, headers, and footers are identical, only the sensitive characters become placeholders like `[PERSON_1]`
- **PDF in → PDF out**: it "wipes out" the sensitive characters directly on the original PDF and stamps a placeholder over them, keeping layout, seals, and signatures intact
- **One-click export of three formats**: redact once and get Markdown + Word + PDF together

If the source is plain text with no formatting to preserve, it automatically applies the page layout lawyers commonly use: **FangSong / 12pt / 1.5 line spacing**.

---

## A real test: a 5-page civil judgment

I ran a real Guangdong court civil judgment (5 pages, with an e-seal) through it:

- The tool detected 30+ sensitive entities (via native text extraction) / 69+ (via OCR reconstruction)
- All parties (including both legal representatives, both lawyers, attendees: 8 people in total)
- All company names (full names of both appellant/appellee + various short forms)
- Two law firms, two unified social credit codes, four case numbers
- The full address (a long "Nanshan District, Shenzhen, Guangdong…" string)
- The judgment amount of 3,799.2 yuan

**100% coverage, zero false positives.**

The output PDF opens **almost identical** to the original: fonts, layout, headers, footers, and seals untouched, only the sensitive characters replaced with labels like `[PERSON_X]` and `[COMPANY_X]`.

---

## Why accuracy went up so much

A lot of people ask this. The answer: **it's not one clever trick, it's 8 small improvements stacked together.**

Split the project into 5 versions by time and you'll see accuracy climb each generation:

| Version | Core change | Sensitive entities caught |
|---|---|---|
| **v0 original** | Regex + keyword matching | ~20 |
| **v1** | Added English AI detection (OpenAI) | ~22 |
| **v2** | Added Chinese AI detection (CLUENER) | ~30 |
| **v3** | Added three-layer conflict arbitration + PDF line-break merge | ~31 |
| **v4** | Switched to a stronger OCR engine (RapidOCR) | **69+** |

From **missing half** to **catching everything**, each step has a concrete reason behind it:

### 1. The Chinese AI (CLUENER) reads context
The old rules relied on keywords: "plaintiff: Zhang San" catches Zhang San. But many names carry no keyword, e.g. "**demand that Li Si hand over the financial books of a certain technology company**": the rules catch nothing. The AI reads the whole sentence and knows "Li Si" is a person name. **Contribution: added 10-plus Chinese names.**

### 2. The English AI (OpenAI) covers English PII
English names like John Smith, English addresses like 2025 Mission Street, API tokens like `sk-proj-...`: neither the rules nor the Chinese AI catch these; OpenAI fills them in.

### 3. The three layers correct each other
The rules' greedy match grabs "X hands over a certain technology company" as one company name (wrong); the Chinese AI catches "a certain technology company" (right). The arbitration rules let the AI overwrite the rule's mistake.

### 4. Same-name consistency across the document
The AI may miss "Li Ming" in some contexts. Once the algorithm finds "Li Ming" identified somewhere, **every "Li Ming" in the document is filled in automatically**, leaving none behind.

### 5. PDF line breaks merged automatically
PDF layout prints "a certain company" as "a certain\ncompany" across lines. Without merging, it's detected as two different entities. Single line breaks between CJK characters are merged automatically so the entity stays whole.

### 6. Rules-library refinement
Fixed a pile of concrete bugs:
- "the court retrieved [records from] a bank" is no longer misread as a bank name
- "judge to dissolve a certain company" is no longer misread as a company name (verb + short-form fragment false positive)
- "3799.2 yuan" is no longer cut to "2 yuan"

### 7. OCR engine upgrade (the most recent improvement)
The old PaddleOCR (a model from 2-3 years ago) had many wrong characters and was slow. Switched to **RapidOCR + the PP-OCRv4 model**:
- Speed: 5s per page → 1.9s
- Wrong characters: greatly reduced
- Size: 500MB → 15MB

This makes scanned PDFs recognizable reliably, and redaction quality rose sharply.

### 8. DOCX output fixed
OCR sometimes reads invisible garbage characters that prevented DOCX from being written. After adding a cleaning layer, the **"only a txt, no docx"** problem is fully solved.

---

**The key insight**: how good a redaction tool is **does not depend on how powerful your AI is**, but on whether **rules, AI, OCR, text cleaning, and format preservation** all work together. No single layer is perfect, but stacked together they make a near-perfect tool.

---

## How it beats "rule-based redaction"

A traditional redaction tool with no AI, tested on this judgment, **missed 10-plus Chinese names**. Why?

Because traditional rules have to be triggered by keywords: seeing "plaintiff: Zhang San" identifies Zhang San, seeing "defendant: Li Si" identifies Li Si. But in reality many names carry no such keyword:

> "**later, the investment in a certain industrial firm run by Zhang San ran into trouble**…"
> "**demand that Li Si hand over the financial books of a certain technology company**…"

With no "plaintiff/defendant" keyword, traditional rules catch nothing. The AI model is different: it reads the whole sentence and judges from linguistic habit that "Zhang San", "Li Si", and "a certain technology company" must be person or company names.

**And compound surnames**: Ouyang X, Moqi X, Zhuge X, Huangfu X, Sima X, Shangguan X: traditional tools often split the boundary wrong (recognizing "Sima XX" as "Si" + "ma XX"), while the AI recognizes them cleanly.

---

## Fully offline: how I proved it

A lawyer asked: "Can you really say it never goes online?"

I gave three proofs:

**1. The project's own code has no network calls**

```
$ grep -r "requests|urllib|http" *.py
(no output, zero hits)
```

**2. Both AI models download to local storage once**

- The `~/.cache/huggingface/` folder holds the complete model weights
- After that, all inference happens locally

**3. The hard test: cut the network and see if it still runs**

I used code to **actively intercept every external DNS request** (equivalent to pulling the network cable), then ran the whole redaction pipeline:

```
✓ Both AI models loaded normally
✓ All sensitive entities identified correctly
✓ The redacted file output normally
```

**Not a single byte was ever sent out.**

---

## How to use it

### Recommended: the Web interface

1. Double-click `Start Legal Anonymizer.command` in the project
2. The browser opens automatically
3. Drag a file in (or pick one from the inbox folder)
4. Check "Chinese NER" (strongly recommended)
5. Click "Start analysis"
6. Manually review the detected sensitive information (you can add or remove items)
7. Check the output formats you want (MD / DOCX / PDF, multi-select)
8. Click "Run redaction"
9. Download the result

**No coding required.**

### For programmers: the command line

```bash
# Single file, single format
python3 cli.py anonymize 判决书.pdf -o 脱敏后.pdf --cn-llm

# Output three formats at once
python3 cli.py anonymize 判决书.pdf -o 脱敏后 -f md,docx,pdf --cn-llm
```

---

## An honest disclaimer

This tool is not all-powerful:

1. **Scanned PDFs need OCR**: if your PDF is a scanned image (not native text), you need to enable OCR (the tool has built-in RapidOCR + PaddleOCR dual engines)
2. **OCR occasionally makes look-alike errors**: "佘" may be read as "余", and "己" and "已" are easily confused: this is a common weakness of all lightweight OCR models, so if such key surnames appear in your document, review once by hand after redaction
3. **Occasional false positives**: however accurate the AI is, it can still treat "this case" as an institution or "lawyer" as a person name, so **review the analysis results by hand before running redaction**
4. **Similar names can't be told apart**: Zhang San vs Zhang San (different characters) vs Zhang Sanfeng: if all are sensitive, all get redacted; but if you only want to redact some, you have to pick by hand
5. **The AI models take space**: about 3.4GB after a full install, most of it the two AI models. Install them if space is no concern; if it is, you can install only the small Chinese NER one (400MB)

---

## A note to fellow lawyers

A lawyer's work deals with sensitive information every day. I'm a lawyer too, and I understand the weight of a client's case file. **Any redaction scheme that uploads files to someone else's server is unacceptable to us.**

This tool solves exactly that one problem: **let you use AI to assist your legal work with peace of mind**, while guaranteeing not one byte of your client's information leaves your machine.

If you're a lawyer who needs a tool like this, you're welcome to try it. The code is fully open, every line auditable, with no backdoors and no tracking.

---

*by Lingbao Huang / 2026-04-23*

---

## Appendix: how this differs from the detailed technical report

This is the **plain-language version**: no architecture diagram, no F1 scores, no Python code: meant for non-technical peers, clients, or general readers.

If you want the technical details:
- The conflict arbitration rules of the three-layer detection stack
- Why the ckiplab tiny traditional-Chinese model was dropped
- How the double text layer in JinGe e-seals in PDFs is handled
- The code file structure and what each module does

See **`project-report.md`** in the same directory.
