# Legal Anonymizer · 法律文档脱敏工具

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-green.svg)](https://www.python.org)
[![Platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Windows%20%7C%20Linux-lightgrey.svg)]()
[![Offline](https://img.shields.io/badge/Network-100%25%20Offline-success.svg)]()
[![PRs Welcome](https://img.shields.io/badge/PRs-Welcome-orange.svg)]()

**[English](#english) · [中文](#中文)**

---

<a id="english"></a>

## English

A **100% local, offline** anonymization tool for legal documents.  
No data leaves your machine. No cloud APIs. No subscriptions.

Built for lawyers, paralegals, and compliance teams who need to redact sensitive information before sharing documents — while keeping the original formatting intact.

### Features

- **Fully offline** — all processing happens on your computer; nothing is uploaded
- **3-layer detection** — regex rules + Chinese NER (CLUENER) + English LLM (OpenAI privacy-filter, optional)
- **30+ sensitive data types** — names (including compound surnames), companies, ID numbers, phone numbers, bank cards, case numbers, addresses, amounts, emails, API tokens, and more
- **Triple output format** — one run produces **MD + DOCX + PDF** simultaneously
- **Format-preserving** — DOCX→DOCX keeps fonts and layout; PDF→PDF redacts in-place, preserving stamps and page structure
- **Dual OCR engines** — RapidOCR (fast, lightweight) by default; switch to PaddleOCR for complex layouts
- **Chinese-English mixed documents** — handles bilingual legal filings, cross-border contracts, international arbitration materials
- **Web UI + CLI** — drag-and-drop browser interface, or batch-process via command line
- **Batch review and multi-round redaction** — one batch is analyzed first, reviewed by a human, then redacted; missed terms can be added later and placeholder numbering stays stable across V1/V2/V3
- **Batch restore dictionary** — a batch shares one cumulative mapping, so redacted files can be restored in bulk to Word
- **Linked full-name / short-name placeholders** — declarations such as "hereinafter referred to as" are detected, and the short name gets its own placeholder linked to the full name (e.g. `[COMPANY_1]` and `[COMPANY_1_ABBR]`), so a restore returns each to its own original wording

> The batch restore dictionary contains every original sensitive value. It is deliberately kept out of the results zip and must be downloaded separately; keep it on your own machine and never send it together with the redacted files.

### Quick Start

#### macOS / Windows (recommended)

1. Download the latest zip from **[Releases](../../releases)**
2. Unzip anywhere (e.g., Desktop)
3. Double-click:
   - **macOS**: `【请双击我！】启动脱敏工具.command`
   - **Windows**: `启动脱敏工具.bat`
4. First run auto-installs dependencies and downloads the NER model (~400 MB)
5. Browser opens at `http://127.0.0.1:8080` — start using immediately
6. Subsequent launches skip to step 5 (everything cached)

> **macOS security prompt?** Go to System Settings → Privacy & Security → scroll down → click "Open Anyway", enter your password, then double-click the file again.

#### Manual install

```bash
git clone https://github.com/rainbow1111-lalala/legal-anonymizer.git
cd legal-anonymizer
pip3 install -r requirements.txt
python3 web_app.py
```

### CLI Usage

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

### Optional: Enable LLM Layers

| Layer | Model | Size | What it catches |
|---|---|---|---|
| CN NER | `uer/roberta-base-finetuned-cluener2020-chinese` | ~400 MB | Chinese names (incl. compound), companies, addresses |
| EN LLM | `openai/privacy-filter` (1.5B MoE) | ~2.6 GB | English names, addresses, international phone numbers, API tokens |

```bash
pip3 install torch transformers

# Chinese NER only (recommended for Chinese documents)
python3 cli.py anonymize input.docx -o output.docx --cn-llm

# English LLM only (English-primary documents)
python3 cli.py anonymize input.docx -o output.docx --llm

# Both layers (Chinese-English mixed documents)
python3 cli.py anonymize input.docx -o output.docx --cn-llm --llm
```

### Privacy & Security

- Zero network calls during processing — `grep -r "requests\|urllib\|http" *.py` returns nothing for data paths
- LLM models download once to `~/.cache/huggingface/`, then run fully offline
- To enforce air-gap mode: `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python3 web_app.py`

### Docs

- [`docs/项目报告.md`](docs/项目报告.md) — full technical report (architecture, benchmarks, development history)
- [`docs/简明版报告.md`](docs/简明版报告.md) — summary version for sharing with colleagues
- [`首次使用指南.pdf`](首次使用指南.pdf) — illustrated 13-chapter user guide (Chinese)
- [`DISCLAIMER.md`](DISCLAIMER.md) — liability disclaimer (read before use)

### Contributing

- Found a missed detection? Open an issue with a (redacted) sample text
- Found a false positive? Same
- Want a new detection type? Open an issue to discuss before PR
- Documentation improvements? PR directly

### License

Apache License 2.0 — see [LICENSE](LICENSE).

---

*Made with ❤️ by 黄灵宝同学（Rainbow Wong）*

---

<a id="中文"></a>

## 中文

> ⚠️ **使用前请阅读 [DISCLAIMER.md（免责声明）](DISCLAIMER.md)**：本工具是辅助性脱敏工具，**不能替代人工复核**。最终脱敏结果由使用者负责确认。

一款**完全本地运行**、**不联网不上传**的法律文书敏感信息脱敏工具。律师、法务、合规人员的本地脱敏助手。

中文法律文书 100% 本地脱敏 · 支持中英混合涉外文件 · 一键输出 MD/DOCX/PDF 三格式 · 保留原文档字体排版盖章

### 功能亮点

- 🔒 **100% 本地运行**：所有处理在你电脑上完成，不调用任何外部 API，不上传任何数据
- 🎯 **三层智能检测**：正则规则 + 中文 NER（CLUENER）+ 英文 LLM（OpenAI privacy-filter，可选）
- 📑 **30+ 种敏感信息**：人名（含复姓）、公司、身份证、手机、银行卡、案号、地址、金额、邮箱、API token 等
- 📋 **多格式同时输出**：一次脱敏生成 **MD + DOCX + PDF** 三份文件
- 🎨 **原格式保留**：DOCX→DOCX 完整保留字体/排版；PDF→PDF 原地脱敏保留布局/盖章
- 🔍 **双 OCR 引擎**：默认 RapidOCR（快、轻量），复杂排版可切 PaddleOCR
- 🇨🇳 **中文友好**：复姓识别（欧阳/万俟/诸葛/皇甫/司马/上官）、PDF 排版换行自动合并
- 🌐 **网页 + 命令行**：拖拽上传可视化操作，或 CLI 批处理，皆可
- 🗂️ **批量与多轮补充脱敏**：同一批次可反复追加遗漏词，V1/V2/V3 占位符编号保持稳定
- 📖 **批次还原字典**：一个批次使用一份累计映射，可批量还原并统一输出 Word
- 🔗 **全称—简称关联脱敏**：识别“以下简称/下称/简称”等声明；全称与简称使用关联但不同的占位符（如 `〔公司1〕`、`〔公司1简化名〕`），还原时分别恢复原文

### 批量多轮脱敏与还原

1. 切换到「批量处理」，选择多个文件。
2. 选择是否启用中文 NER / 英文隐私识别，并可输入本批次自定义敏感词。
3. 点击「识别并进入人工检查」；系统只生成识别清单，此时不改写文件。
4. 在「批次统一人工检查」中复核所有文件合并后的敏感项：相同“类型＋词汇”只显示一次，并标注涉及文件数、出现次数和示例上下文。编辑、删除或人工补充均应用于整个批次，无需在文件间切换。
5. 在独立的「全称—简称对应检查」中确认、编辑或删除对应关系；全称与简称仍使用关联但不同的占位符。
6. 确认总表后再开始批量脱敏。如果第一轮结果仍有遗漏，点击「发现遗漏，继续脱敏」生成 V2/V3。
7. 添加的词条会追加到当前批次词典；系统从原文件生成下一版，旧占位符不重新编号。
8. 「下载脱敏成果（zip）」只包含脱敏后的文件，不含还原字典；还原字典用「单独下载还原字典」按钮单独取回，再到「脱敏还原」批量生成 Word ZIP。

> 还原字典包含全部敏感原文，等同于一份明文对照表。工具刻意不把它打进成果 zip，请只留在本机，不要与脱敏文件一起发给无权接收人。

### 快速开始（推荐）

1. 在右侧 **[Releases](../../releases)** 页下载最新版 zip
2. 解压到任意位置（如桌面）
3. 双击：
   - **macOS**：`【请双击我！】启动脱敏工具.command`
   - **Windows**：`启动脱敏工具.bat`
4. 首次启动自动安装依赖、下载中文 NER 模型（~400MB，3-5 分钟）
5. 浏览器自动打开 `http://127.0.0.1:8080`，开始用
6. 以后再启动直接到第 5 步（依赖和模型已缓存）

> **macOS 弹出安全提示？** 系统设置 → 隐私与安全性 → 向下滚动 → 点「仍要打开」→ 输入密码 → 再次双击文件

### 手动安装

**第一步：确认有 Python 3.10+**

```bash
python3 --version   # macOS
python --version    # Windows
```

没有则去 https://www.python.org/downloads/ 安装（Windows 安装时勾选 `Add Python to PATH`）。

**第二步：安装并启动**

```bash
git clone https://github.com/rainbow1111-lalala/legal-anonymizer.git
cd legal-anonymizer
pip3 install -r requirements.txt   # Windows 用 pip
python3 web_app.py                  # Windows 用 python
```

### 命令行用法

```bash
# 脱敏 Word 文档
python3 cli.py anonymize input.docx -o output.docx

# 脱敏 PDF
python3 cli.py anonymize input.pdf -o output.pdf

# 扫描版 PDF 启用 OCR
python3 cli.py anonymize scan.pdf -o output.docx --ocr

# 只分析不脱敏
python3 cli.py analyze input.docx

# 查看支持的所有类型
python3 cli.py list-types
```

### 可选：启用 LLM 补充检测

| 层 | 模型 | 大小 | 主要补盲 |
|---|---|---|---|
| CN NER | `uer/roberta-base-finetuned-cluener2020-chinese` | ~400 MB | 中文人名（含复姓）、中文公司、中文地址 |
| OpenAI | `openai/privacy-filter`（1.5B MoE） | ~2.6 GB | 英文人名、英文地址、国际电话、API token |

```bash
pip3 install torch transformers

# 只开中文 NER（推荐，补规则漏掉的中文人名/公司/地址）
python3 cli.py anonymize input.docx -o output.docx --cn-llm

# 只开 OpenAI（文档以英文为主时）
python3 cli.py anonymize input.docx -o output.docx --llm

# 全开（中英混合最强模式）
python3 cli.py anonymize input.docx -o output.docx --cn-llm --llm
```

**三层仲裁机制：**

1. 结构化数据（身份证/银行卡/邮箱等）一律由正则处理
2. CN NER 可纠错规则层的边界错切和分类误判
3. 同名全文一致性：CN NER 漏检的同名人名自动扩展到全文
4. OpenAI 仅补空位：只覆盖前两层都没抓到的位置
5. 英文段落不跑 CN NER，避免英文普通词误报

### 三层检测实测收益

**硬中文样本**（借款合同判决书）：

| 项 | 纯规则 | +CN NER |
|---|---|---|
| 中文人名漏检 | 10+ 处（含 6 种复姓） | 全部抓到 |
| 复姓识别 | 错切（"司马XX"→"司"+"马XX"） | 正确合并 |
| 完整地址 | 只抓地址碎片 | 完整地址 |

**中英混合样本**（涉外民事起诉状）：

| 项 | 纯规则 | +CN NER +OpenAI |
|---|---|---|
| 英文人名 | 漏 | John Smith / Jennifer Chen |
| 英文地址 | 漏 | 2025 Mission Street, San Francisco |
| 国际电话 | 漏 | +1 / +44 |
| API token | 漏 | sk-proj-... |

### 隐私安全

- 处理过程零网络请求——`grep -r "requests\|urllib\|http" *.py` 数据路径返回空
- LLM 模型一次性下载到 `~/.cache/huggingface/`，之后全程离线推理
- 彻底断网模式：`HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python3 web_app.py`

### 深入文档

- [`docs/项目报告.md`](docs/项目报告.md) —— 详细技术报告（架构、实测、开发历程）
- [`docs/简明版报告.md`](docs/简明版报告.md) —— 公众号友好版，适合分享给同行
- [`首次使用指南.pdf`](首次使用指南.pdf) —— 13 章节图文使用手册
- [`DISCLAIMER.md`](DISCLAIMER.md) —— 免责声明（使用前必读）

### 常见问题

**`pip install` 报 `Permission denied`**  
在命令前加 `--user`：`pip3 install --user -r requirements.txt`

**浏览器没有自动打开**  
手动输入终端中显示的地址，通常是 `http://127.0.0.1:8080`

**报错 `Address already in use`**  
端口被占用，程序会自动尝试 8080-8099。仍失败则关掉占用端口的其他程序。

**报错 `ModuleNotFoundError: No module named 'flask'`**  
依赖未装成功时，优先重新执行 `bash setup.sh`。安装器会验证 Python 版本和核心组件，并将 OCR、NER 分组安装；详情记录在 `.setup.log`。不要使用 macOS 命令行工具自带的 Python 3.9，因为新版 OCR/NER 依赖已不再提供对应安装包。

### 贡献

- 发现漏检 → 提 issue 附带（脱敏过的）样例文本
- 发现误报 → 同上
- 想加新检测类型 → 先提 issue 讨论再 PR
- 文档改进 → 直接 PR

### 协议

Apache License 2.0 —— 见 [LICENSE](LICENSE)

### 致谢

- [OpenAI Privacy Filter](https://huggingface.co/openai/privacy-filter)
- [CLUENER 2020](https://huggingface.co/uer/roberta-base-finetuned-cluener2020-chinese)
- [RapidOCR](https://github.com/RapidAI/RapidOCR)
- [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)
- [PyMuPDF](https://github.com/pymupdf/PyMuPDF)

---

*Made with ❤️ by 黄灵宝同学（Rainbow Wong）*
