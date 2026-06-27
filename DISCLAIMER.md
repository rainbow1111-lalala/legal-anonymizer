# Disclaimer

## Important notice

This is an **assistive redaction tool**, and it **does not replace human review**.

When you use this tool to process any legal document, contract, case file, or other confidential material, you **must**:

1. **Review every item** the tool flags as sensitive, confirming nothing is missed or misjudged;
2. **Proofread the final output** redacted file and personally confirm that every client, party, and piece of sensitive information has been properly replaced;
3. **Understand the limits**: any automated redaction tool (including this tool and the AI models it uses) can both miss items and produce false positives.

## Allocation of responsibility

- The developer of this tool **accepts no responsibility** for any information disclosure, compliance issue, client complaint, professional-discipline liability, or other consequence arising from use of this tool;
- As a **professional** (lawyer / in-house counsel / compliance officer), the user should independently judge whether this tool is suitable for their specific business scenario;
- Before delivering a redacted file to a client, opposing party, court, regulator, or the public, **the final responsibility rests with the user**.

## Suitable use cases

This tool is **suitable for**:

- Redacting internal study materials
- De-identifying papers / case studies / training materials
- Pre-processing before submitting content to AI models (ChatGPT / Claude, etc.) for semantic analysis
- Batch redaction when building a firm's internal knowledge base

This tool is **not recommended for direct use** (unless paired with strict human review):

- Redacted evidence formally submitted to a court / arbitration body
- Compliance de-identification documents reported to government regulators
- Handling documents involving state secrets / trade secrets
- Any scenario with zero tolerance for incomplete redaction

## Third-party component disclaimer

This tool integrates or depends on the following third-party open-source components, each governed by its own open-source license:

- **OpenAI Privacy Filter** (Apache 2.0) — English PII detection
- **CLUENER 2020 RoBERTa** (HuggingFace default license) — Chinese NER
- **RapidOCR** (Apache 2.0) — OCR engine
- **PaddleOCR** (Apache 2.0) — alternative OCR engine
- **PyMuPDF** (AGPL-3.0) — PDF processing
- **python-docx / Flask / PyTorch / Transformers** — respective licenses

The accuracy, stability, and compliance of third-party components are the responsibility of their respective maintainers.

## Privacy commitment

- The code of this tool is **fully open source** and can be independently audited;
- **Zero network calls**: running `grep -r "requests|urllib|http" *.py` over the project code should return nothing;
- AI models are downloaded on first run from public mirrors (HuggingFace / ModelScope) to a local `~/.cache/`, and run fully offline thereafter;
- **You can set three environment variables to completely block any model heartbeat**:
  - `HF_HUB_OFFLINE=1`
  - `TRANSFORMERS_OFFLINE=1`
  - `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=1`

## Terms of agreement

By using this tool, you are deemed to **have read and agreed to** the entire content of this disclaimer. If you do not agree, do not use it.

This disclaimer is interpreted under the Civil Code of the People's Republic of China, the Contract Law of the People's Republic of China, and other applicable laws.

---

*Last updated: 2026-04-26*
