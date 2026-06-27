#!/usr/bin/env python3
"""
Generate the "Legal Anonymizer - Getting Started Guide" PDF.
"""

import os
import sys
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.units import mm, cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, KeepTogether, HRFlowable
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


# ============ Font registration ============
def register_fonts():
    """Register Chinese fonts."""
    font_paths = {
        'PingFang': [
            '/System/Library/Fonts/PingFang.ttc',
            '/System/Library/Fonts/STHeiti Light.ttc',
            '/System/Library/Fonts/Hiragino Sans GB.ttc',
        ],
        'PingFangBold': [
            '/System/Library/Fonts/PingFang.ttc',
            '/System/Library/Fonts/STHeiti Medium.ttc',
        ],
    }

    registered = False
    # macOS fonts
    for font_path in font_paths['PingFang']:
        if os.path.exists(font_path):
            try:
                pdfmetrics.registerFont(TTFont('PingFang', font_path, subfontIndex=0))
                pdfmetrics.registerFont(TTFont('PingFangBold', font_path, subfontIndex=1))
                registered = True
                break
            except Exception:
                continue

    if not registered:
        # Windows / Linux fallback
        fallback_fonts = [
            'C:/Windows/Fonts/msyh.ttc',      # Microsoft YaHei
            'C:/Windows/Fonts/simsun.ttc',     # SimSun
            '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        ]
        for font_path in fallback_fonts:
            if os.path.exists(font_path):
                try:
                    pdfmetrics.registerFont(TTFont('PingFang', font_path, subfontIndex=0))
                    pdfmetrics.registerFont(TTFont('PingFangBold', font_path, subfontIndex=1))
                    registered = True
                    break
                except Exception:
                    continue

    if not registered:
        print("Warning: no Chinese font found. The PDF may not display Chinese correctly.")
        # Fall back to Helvetica
        pdfmetrics.registerFontFamily('PingFang', normal='Helvetica', bold='Helvetica-Bold')


register_fonts()


# ============ Color definitions ============
PRIMARY = HexColor('#1a5276')      # Dark blue
ACCENT = HexColor('#2980b9')       # Bright blue
SUCCESS = HexColor('#27ae60')      # Green
WARNING = HexColor('#e67e22')      # Orange
DANGER = HexColor('#c0392b')       # Red
BG_LIGHT = HexColor('#f8f9fa')     # Light gray background
BG_BLUE = HexColor('#eaf2f8')      # Light blue background
BORDER = HexColor('#bdc3c7')       # Border gray
TEXT_DARK = HexColor('#2c3e50')    # Dark text
TEXT_GRAY = HexColor('#7f8c8d')    # Gray text


# ============ Style definitions ============
def create_styles():
    """Create the PDF styles."""
    styles = {}

    styles['title'] = ParagraphStyle(
        'Title',
        fontName='PingFangBold',
        fontSize=24,
        textColor=PRIMARY,
        alignment=TA_CENTER,
        spaceAfter=6 * mm,
        leading=32,
    )

    styles['subtitle'] = ParagraphStyle(
        'Subtitle',
        fontName='PingFang',
        fontSize=12,
        textColor=TEXT_GRAY,
        alignment=TA_CENTER,
        spaceAfter=15 * mm,
        leading=18,
    )

    styles['h1'] = ParagraphStyle(
        'H1',
        fontName='PingFangBold',
        fontSize=18,
        textColor=PRIMARY,
        spaceBefore=12 * mm,
        spaceAfter=6 * mm,
        leading=24,
        borderPadding=(0, 0, 2 * mm, 0),
    )

    styles['h2'] = ParagraphStyle(
        'H2',
        fontName='PingFangBold',
        fontSize=14,
        textColor=ACCENT,
        spaceBefore=8 * mm,
        spaceAfter=4 * mm,
        leading=20,
    )

    styles['h3'] = ParagraphStyle(
        'H3',
        fontName='PingFangBold',
        fontSize=12,
        textColor=TEXT_DARK,
        spaceBefore=5 * mm,
        spaceAfter=3 * mm,
        leading=17,
    )

    styles['body'] = ParagraphStyle(
        'Body',
        fontName='PingFang',
        fontSize=10.5,
        textColor=TEXT_DARK,
        alignment=TA_JUSTIFY,
        spaceAfter=3 * mm,
        leading=17,
        firstLineIndent=0,
    )

    styles['body_indent'] = ParagraphStyle(
        'BodyIndent',
        parent=styles['body'],
        leftIndent=8 * mm,
    )

    styles['bullet'] = ParagraphStyle(
        'Bullet',
        fontName='PingFang',
        fontSize=10.5,
        textColor=TEXT_DARK,
        spaceAfter=2 * mm,
        leading=17,
        leftIndent=8 * mm,
        bulletIndent=3 * mm,
    )

    styles['code'] = ParagraphStyle(
        'Code',
        fontName='Courier',
        fontSize=9.5,
        textColor=HexColor('#2d3436'),
        backColor=BG_LIGHT,
        spaceAfter=3 * mm,
        leading=15,
        leftIndent=8 * mm,
        rightIndent=8 * mm,
        borderPadding=(3 * mm, 3 * mm, 3 * mm, 3 * mm),
    )

    styles['tip'] = ParagraphStyle(
        'Tip',
        fontName='PingFang',
        fontSize=10,
        textColor=HexColor('#1e8449'),
        spaceAfter=3 * mm,
        leading=16,
        leftIndent=10 * mm,
        rightIndent=5 * mm,
    )

    styles['warning'] = ParagraphStyle(
        'Warning',
        fontName='PingFang',
        fontSize=10,
        textColor=HexColor('#a04000'),
        spaceAfter=3 * mm,
        leading=16,
        leftIndent=10 * mm,
        rightIndent=5 * mm,
    )

    styles['footer'] = ParagraphStyle(
        'Footer',
        fontName='PingFang',
        fontSize=8,
        textColor=TEXT_GRAY,
        alignment=TA_CENTER,
    )

    styles['toc'] = ParagraphStyle(
        'TOC',
        fontName='PingFang',
        fontSize=11,
        textColor=ACCENT,
        spaceAfter=3 * mm,
        leading=18,
        leftIndent=5 * mm,
    )

    return styles


# ============ Helper functions ============
def make_tip_box(text, styles, box_type='tip'):
    """Create a callout box."""
    if box_type == 'tip':
        bg = HexColor('#e8f8f5')
        border_color = SUCCESS
        prefix = 'TIP'
    elif box_type == 'warning':
        bg = HexColor('#fef9e7')
        border_color = WARNING
        prefix = 'Caution'
    elif box_type == 'danger':
        bg = HexColor('#fdedec')
        border_color = DANGER
        prefix = 'Important'
    else:
        bg = BG_BLUE
        border_color = ACCENT
        prefix = 'Note'

    style = styles[box_type] if box_type in styles else styles['tip']
    content = Paragraph(f'<b>{prefix}:</b> {text}', style)

    t = Table([[content]], colWidths=[155 * mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), bg),
        ('BOX', (0, 0), (-1, -1), 1, border_color),
        ('LEFTPADDING', (0, 0), (-1, -1), 4 * mm),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4 * mm),
        ('TOPPADDING', (0, 0), (-1, -1), 3 * mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3 * mm),
    ]))
    return t


def make_step(number, title, description, styles):
    """Create a step block."""
    num_style = ParagraphStyle(
        f'StepNum{number}',
        fontName='PingFangBold',
        fontSize=14,
        textColor=white,
        alignment=TA_CENTER,
        leading=18,
    )
    title_style = ParagraphStyle(
        f'StepTitle{number}',
        fontName='PingFangBold',
        fontSize=12,
        textColor=PRIMARY,
        leading=17,
    )
    desc_style = ParagraphStyle(
        f'StepDesc{number}',
        fontName='PingFang',
        fontSize=10.5,
        textColor=TEXT_DARK,
        leading=16,
    )

    num_para = Paragraph(str(number), num_style)
    title_para = Paragraph(title, title_style)
    desc_para = Paragraph(description, desc_style)

    t = Table(
        [[num_para, title_para], ['', desc_para]],
        colWidths=[12 * mm, 143 * mm],
        rowHeights=[8 * mm, None],
    )
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, 0), ACCENT),
        ('ROUNDEDCORNERS', [3, 3, 3, 3]),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (0, 0), (0, 0), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 2 * mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2 * mm),
        ('LEFTPADDING', (1, 0), (1, -1), 4 * mm),
        ('SPAN', (0, 0), (0, 1)),
    ]))
    return t


# ============ Page template ============
def on_page(canvas, doc):
    """Header and footer."""
    canvas.saveState()
    # Footer
    canvas.setFont('PingFang', 8)
    canvas.setFillColor(TEXT_GRAY)
    canvas.drawCentredString(A4[0] / 2, 12 * mm, f'- {doc.page} -')
    canvas.drawString(15 * mm, 12 * mm, 'Legal Anonymizer by Lingbao Huang')
    canvas.restoreState()


def on_first_page(canvas, doc):
    """No header on the first page."""
    canvas.saveState()
    canvas.setFont('PingFang', 8)
    canvas.setFillColor(TEXT_GRAY)
    canvas.drawCentredString(A4[0] / 2, 12 * mm, f'- {doc.page} -')
    canvas.restoreState()


# ============ Content builder ============
def build_content(styles):
    """Build the PDF content."""
    story = []

    # ===== Cover =====
    story.append(Spacer(1, 40 * mm))
    story.append(Paragraph('Legal Anonymizer', styles['title']))
    story.append(Paragraph('Getting Started Guide', ParagraphStyle(
        'SubTitle2', fontName='PingFangBold', fontSize=18,
        textColor=ACCENT, alignment=TA_CENTER, spaceAfter=8 * mm, leading=24,
    )))
    story.append(HRFlowable(width='60%', thickness=1, color=ACCENT,
                            spaceAfter=8 * mm, spaceBefore=3 * mm))
    story.append(Paragraph(
        'Runs fully on your machine | No network, no uploads | Auto-detects 30+ types of sensitive data',
        styles['subtitle']
    ))
    story.append(Spacer(1, 15 * mm))
    story.append(Paragraph(
        'For macOS / Windows / Linux',
        ParagraphStyle('Platform', fontName='PingFang', fontSize=11,
                       textColor=TEXT_GRAY, alignment=TA_CENTER, leading=16)
    ))
    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(
        'by <b>Lingbao Huang</b>',
        ParagraphStyle('Author', fontName='PingFang', fontSize=12,
                       textColor=ACCENT, alignment=TA_CENTER, leading=16)
    ))

    story.append(PageBreak())

    # ===== Table of contents =====
    story.append(Paragraph('Contents', styles['h1']))
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=5 * mm))
    toc_items = [
        '1. Product overview',
        '2. Before you install',
        '3. Quick start (recommended)',
        '4. First-launch option: do you handle English documents?',
        '5. Manual install (alternative)',
        '6. How to use - browser interface',
        '7. Detection layers: rules + Chinese NER + English LLM',
        '8. OCR engines: RapidOCR / PaddleOCR',
        '9. Output formats: MD / DOCX / PDF',
        '10. How to use - command line',
        '11. Supported types of sensitive data',
        '12. Frequently asked questions',
        '13. Privacy and security',
    ]
    for item in toc_items:
        story.append(Paragraph(item, styles['toc']))
    story.append(PageBreak())

    # ===== 1. Product overview =====
    story.append(Paragraph('1. Product overview', styles['h1']))
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=5 * mm))

    story.append(Paragraph(
        'Legal Anonymizer is a redaction tool that <b>runs entirely on your machine</b>, '
        'built for legal professionals. It automatically detects and replaces more than 30 types of '
        'sensitive data in a document, including personal information, company names, '
        'case numbers, amounts, and addresses. This keeps private data out of files you share, archive, or publish.',
        styles['body']
    ))

    story.append(Paragraph('Key features', styles['h3']))

    features = [
        ['Fully offline', 'All processing happens locally. No external API calls, no data uploads.'],
        ['Many input formats', 'Supports PDF (including scanned PDFs via OCR), Word (DOCX/DOC), TXT, Markdown, and images.'],
        ['Many output formats', 'One redaction run produces MD, DOCX, and PDF together. Pick whichever you need.'],
        ['Original layout kept', 'DOCX to DOCX keeps fonts, sizes, headers and footers. PDF to PDF redacts in place and keeps the layout and seals.'],
        ['Three detection layers', 'Regex rules + Chinese NER (CLUENER) + English LLM (OpenAI privacy-filter, optional).'],
        ['Smart detection', 'Auto-detects 30+ types of sensitive data: person names (including compound surnames), companies, ID numbers, mobile numbers, bank cards, case numbers, addresses, and more.'],
        ['Two OCR engines', 'RapidOCR by default (fast, lightweight). Switch to PaddleOCR for complex layouts (accurate, slower).'],
        ['Flexible strategies', 'Two modes: placeholder replacement ([PERSON_1]) or partial mask (138****5678).'],
        ['Conflict arbitration', 'When rule and LLM results overlap, five arbitration rules resolve them and correct each other.'],
        ['Same-name expansion', 'The same name is redacted consistently at every occurrence in the document.'],
        ['Custom dictionary', 'Add or exclude terms by hand to fit a specific document.'],
    ]

    for title, desc in features:
        story.append(Paragraph(
            f'<bullet>&bull;</bullet> <b>{title}</b> - {desc}',
            styles['bullet']
        ))

    # ===== 2. Before you install =====
    story.append(Paragraph('2. Before you install', styles['h1']))
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=5 * mm))

    story.append(Paragraph('System requirements', styles['h3']))

    req_data = [
        ['Item', 'Requirement'],
        ['Operating system', 'macOS 10.15+ / Windows 10+ / Linux'],
        ['Python', 'Python 3.9 or later (3.11 recommended)'],
        ['Disk space', 'About 1.5 GB base (PyTorch + venv); '
                     '+400 MB for the Chinese NER model; +2.6 GB for the English model'],
        ['Memory', '8 GB or more recommended (about 3-4 GB while an LLM model is loaded)'],
        ['Browser', 'Chrome / Edge / Safari / Firefox (any)'],
        ['Network', 'The first launch needs internet to download dependencies and models. After that it runs fully offline.'],
    ]
    req_table = Table(req_data, colWidths=[35 * mm, 120 * mm])
    req_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), PRIMARY),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('FONTNAME', (0, 0), (-1, 0), 'PingFangBold'),
        ('FONTNAME', (0, 1), (-1, -1), 'PingFang'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, BG_LIGHT]),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5 * mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5 * mm),
        ('LEFTPADDING', (0, 0), (-1, -1), 3 * mm),
    ]))
    story.append(req_table)

    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph('Check whether Python is installed', styles['h3']))
    story.append(Paragraph(
        '<b>macOS:</b> press Command + Space, search for "Terminal", open it, and type:',
        styles['body']
    ))
    story.append(Paragraph('python3 --version', styles['code']))
    story.append(Paragraph(
        '<b>Windows:</b> press Win + R, type cmd and press Enter, then type:',
        styles['body']
    ))
    story.append(Paragraph('python --version', styles['code']))
    story.append(Paragraph(
        'If it shows Python 3.x.x (for example Python 3.11.3), Python is installed. '
        'If it says "command not found", download and install it from python.org.',
        styles['body']
    ))
    story.append(make_tip_box(
        'When installing Python on Windows, <b>be sure to check</b> "Add Python to PATH" '
        '(the checkbox at the bottom of the installer). Otherwise the python command will not work in the command line.',
        styles, 'warning'
    ))

    # ===== 3. Quick start =====
    story.append(PageBreak())
    story.append(Paragraph('3. Quick start (recommended)', styles['h1']))
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=5 * mm))

    story.append(Paragraph(
        'This is the simplest way to launch. Two steps: unzip, then double-click.',
        styles['body']
    ))

    story.append(Paragraph('macOS users', styles['h2']))

    story.append(make_step(1, 'Unzip the file',
        'Unzip the downloaded legal-anonymizer.zip anywhere you like (for example, the Desktop).',
        styles))
    story.append(Spacer(1, 3 * mm))
    story.append(make_step(2, 'Double-click to launch',
        'Double-click <b>[Double-click me!] Start Legal Anonymizer.command</b> in the folder. '
        'The first run installs dependencies automatically, then opens your browser.',
        styles))

    story.append(Spacer(1, 5 * mm))
    story.append(make_tip_box(
        'The first time, macOS may show a security prompt saying the developer cannot be verified. '
        'Open <b>System Settings > Privacy & Security</b>, scroll down to the blocked item, '
        'click <b>"Open Anyway"</b>, and confirm with your password. After that, double-clicking will not prompt again.',
        styles, 'warning'
    ))

    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph('Windows users', styles['h2']))

    story.append(make_step(1, 'Unzip the file',
        'Right-click legal-anonymizer.zip and choose "Extract All".',
        styles))
    story.append(Spacer(1, 3 * mm))
    story.append(make_step(2, 'Double-click to launch',
        'Double-click <b>Start Legal Anonymizer.bat</b> in the folder.',
        styles))

    # ===== 4. First-launch option =====
    story.append(PageBreak())
    story.append(Paragraph('4. First-launch option: do you handle English documents?', styles['h1']))
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=5 * mm))

    story.append(Paragraph(
        'The first time you double-click the launch script, the tool asks you one question:',
        styles['body']
    ))
    story.append(make_tip_box(
        '<b>"Do you often handle English or cross-border legal documents? (y / n)"</b>',
        styles, 'info'
    ))
    story.append(Paragraph(
        'This decides whether to enable English detection (based on the OpenAI privacy-filter model). '
        'By default the tool detects all sensitive data in Chinese documents. '
        'English detection is only useful for lawyers handling cross-border matters.',
        styles['body']
    ))

    story.append(Paragraph('Choose "y" (yes) - enable English detection', styles['h3']))
    en_yes = [
        'Detects English person names (for example, John Smith), English addresses, international phone numbers, and API keys.',
        'Turning on the OpenAI switch for the first time downloads about <b>2.6 GB</b> of model (one time).',
        'Good for cross-border arbitration, cross-border contracts, and foreign-invested company matters.',
    ]
    for p in en_yes:
        story.append(Paragraph(f'<bullet>&bull;</bullet> {p}', styles['bullet']))

    story.append(Paragraph('Choose "n" (no) - Chinese-only mode', styles['h3']))
    en_no = [
        'Detects Chinese PII only, but accuracy on Chinese documents is already near 100%.',
        '<b>Saves 2.6 GB of disk space and the first-time download.</b>',
        'Fits the vast majority of Chinese legal work (contracts, judgments, and pleadings are all in Chinese).',
        'The browser interface will not show the OpenAI switch.',
    ]
    for p in en_no:
        story.append(Paragraph(f'<bullet>&bull;</bullet> {p}', styles['bullet']))

    story.append(make_tip_box(
        '<b>Chose wrong and want to switch?</b> Delete the <code>.user_config</code> file in the project root, '
        'then double-click the launch script again to choose once more.',
        styles, 'tip'
    ))

    # ===== 5. Manual install =====
    story.append(PageBreak())
    story.append(Paragraph('5. Manual install (alternative)', styles['h1']))
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=5 * mm))

    story.append(Paragraph(
        'If the quick start does not work, you can install manually.',
        styles['body']
    ))

    story.append(make_step(1, 'Open Terminal / Command Prompt',
        '<b>macOS:</b> Command + Space > search for "Terminal"<br/>'
        '<b>Windows:</b> Win + R > type cmd > Enter',
        styles))
    story.append(Spacer(1, 3 * mm))

    story.append(make_step(2, 'Go to the project folder',
        'Type cd in the terminal, then drag the folder from Finder / File Explorer into the terminal window and press Enter.<br/>'
        'Or type the path directly, for example: cd ~/Desktop/legal-anonymizer',
        styles))
    story.append(Spacer(1, 3 * mm))

    story.append(make_step(3, 'Install dependencies (first time only)',
        '<b>macOS:</b> pip3 install -r requirements.txt<br/>'
        '<b>Windows:</b> pip install -r requirements.txt<br/>'
        'Wait for it to finish. No red errors means success.',
        styles))
    story.append(Spacer(1, 3 * mm))

    story.append(make_step(4, 'Start the tool',
        '<b>macOS:</b> python3 web_app.py<br/>'
        '<b>Windows:</b> python web_app.py<br/>'
        'It opens your browser automatically. If it does not, open the address shown in the terminal (usually http://127.0.0.1:8080).',
        styles))

    story.append(Spacer(1, 5 * mm))
    story.append(make_tip_box(
        'Do not close the terminal window. Closing the terminal stops the service. Close it only when you are done.',
        styles, 'danger'
    ))

    # ===== 6. How to use - browser interface =====
    story.append(PageBreak())
    story.append(Paragraph('6. How to use - browser interface', styles['h1']))
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=5 * mm))

    story.append(Paragraph('Basic workflow', styles['h2']))

    story.append(make_step(1, 'Upload a file',
        'Drag a file onto the upload area, or click to select one. Supports PDF, DOCX, and TXT.<br/>'
        'You can also drop files into the inbox folder under the project directory and pick them on the page.',
        styles))
    story.append(Spacer(1, 3 * mm))

    story.append(make_step(2, 'Automatic analysis',
        'After upload, the tool scans the document and lists every piece of sensitive data it finds. '
        'Each item has a checkbox, so you can uncheck anything you do not want redacted.',
        styles))
    story.append(Spacer(1, 3 * mm))

    story.append(make_step(3, 'Add items by hand (optional)',
        'If you spot anything that was missed, add it to the custom dictionary by hand. '
        'The dictionary is saved and applies automatically next time.',
        styles))
    story.append(Spacer(1, 3 * mm))

    story.append(make_step(4, 'Run redaction',
        'Click "Run redaction", wait for it to finish, then download the redacted file.<br/>'
        'A mapping table (JSON) is also created, recording the original content behind each placeholder.',
        styles))

    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph('Redaction strategies', styles['h2']))

    strategy_data = [
        ['Strategy', 'Example', 'When to use'],
        ['Placeholder replacement', 'Zhang San > [PERSON_1]', 'Hides the original entirely. Good for public release.'],
        ['Partial mask', '138****5678', 'Keeps part of the value for cross-checking. Good for internal use.'],
    ]
    strategy_table = Table(strategy_data, colWidths=[30 * mm, 60 * mm, 65 * mm])
    strategy_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), PRIMARY),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('FONTNAME', (0, 0), (-1, 0), 'PingFangBold'),
        ('FONTNAME', (0, 1), (-1, -1), 'PingFang'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, BG_LIGHT]),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5 * mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5 * mm),
        ('LEFTPADDING', (0, 0), (-1, -1), 3 * mm),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(strategy_table)

    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph('Continue redaction', styles['h2']))
    story.append(Paragraph(
        'After the first pass, if some sensitive data is still missing, use "Continue redaction": '
        'add the missed terms by hand and the tool reprocesses from the original text. '
        'The newly added terms are also saved to the dictionary for later use.',
        styles['body']
    ))

    # ===== 7. Detection layers =====
    story.append(PageBreak())
    story.append(Paragraph('7. Detection layers: rules + Chinese NER + English LLM', styles['h1']))
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=5 * mm))

    story.append(Paragraph(
        'The tool uses a <b>three-layer detection architecture</b>. Each layer handles a different kind of '
        'sensitive data, and the layers work together and correct each other. This is the main reason for its high accuracy.',
        styles['body']
    ))

    layer_data = [
        ['Layer', 'What it detects', 'Speed'],
        ['Regex rules', 'ID numbers, mobile numbers, email, case numbers, credit codes, and 30+ other structured data', 'Very fast (milliseconds)'],
        ['Chinese NER (CLUENER)', 'Chinese person names (including compound surnames), company names, law firms, addresses, institutions', 'Fast (seconds)'],
        ['English LLM (OpenAI, optional)', 'English person names, English addresses, international phone numbers, API keys', 'Slower (a few seconds)'],
    ]
    layer_table = Table(layer_data, colWidths=[40 * mm, 90 * mm, 25 * mm])
    layer_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), PRIMARY),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('FONTNAME', (0, 0), (-1, 0), 'PingFangBold'),
        ('FONTNAME', (0, 1), (-1, -1), 'PingFang'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, BG_LIGHT]),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5 * mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5 * mm),
        ('LEFTPADDING', (0, 0), (-1, -1), 3 * mm),
    ]))
    story.append(layer_table)

    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph('Detection-layer switches in the browser', styles['h3']))
    story.append(Paragraph(
        'Below the upload area there are two (or three) switches:',
        styles['body']
    ))
    switch_points = [
        '<b>Enable OCR</b> - required for scanned PDFs and images; optional for non-scanned PDFs.',
        '<b>Chinese NER</b> - <b>recommended for every Chinese document</b>, since it fills the gaps the rules miss.',
        '<b>OpenAI privacy-filter</b> - shown only if you chose "yes" at first launch; turn it on when handling English documents.',
    ]
    for p in switch_points:
        story.append(Paragraph(f'<bullet>&bull;</bullet> {p}', styles['bullet']))

    # ===== 8. OCR engines =====
    story.append(PageBreak())
    story.append(Paragraph('8. OCR engines: RapidOCR / PaddleOCR', styles['h1']))
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=5 * mm))

    story.append(Paragraph(
        'When the input is a scanned PDF or an image, the tool uses an OCR engine to turn the image into text. '
        'Two engines are built in:',
        styles['body']
    ))

    ocr_data = [
        ['Engine', 'Speed (per page)', 'Accuracy', 'Size', 'Default'],
        ['RapidOCR', 'About 2 sec', 'Good', '15 MB', '✓'],
        ['PaddleOCR 3.5', 'About 30 sec', 'Slightly better (complex layouts)', 'About 200 MB', ''],
    ]
    ocr_table = Table(ocr_data, colWidths=[35 * mm, 30 * mm, 40 * mm, 25 * mm, 15 * mm])
    ocr_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), PRIMARY),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('FONTNAME', (0, 0), (-1, 0), 'PingFangBold'),
        ('FONTNAME', (0, 1), (-1, -1), 'PingFang'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, BG_LIGHT]),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5 * mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5 * mm),
        ('LEFTPADDING', (0, 0), (-1, -1), 3 * mm),
        ('ALIGN', (-1, 0), (-1, -1), 'CENTER'),
    ]))
    story.append(ocr_table)

    story.append(Spacer(1, 5 * mm))
    story.append(make_tip_box(
        '<b>When should you switch to PaddleOCR?</b> '
        'RapidOCR already reads most documents well. If a particular scanned PDF has a lot of garbled characters '
        '(for example, seals, smudged text, or complex tables), enable OCR, then check "PaddleOCR" and re-analyze.',
        styles, 'tip'
    ))

    # ===== 9. Output formats =====
    story.append(PageBreak())
    story.append(Paragraph('9. Output formats: MD / DOCX / PDF', styles['h1']))
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=5 * mm))

    story.append(Paragraph(
        'The tool can <b>output all three formats at once</b>. On the redaction page, the "Output format" area has '
        'three checkboxes. Select all of them, or only the ones you need.',
        styles['body']
    ))

    out_data = [
        ['Format', 'Keeps original layout', 'When to use'],
        ['MD (Markdown)', '×', 'Quick preview, copy and paste, import into note apps'],
        ['DOCX (Word)', '✓ Keeps fonts, sizes, and layout when the input is DOCX', 'Lawyer work drafts, case archiving, sending to clients'],
        ['PDF', '✓ Redacts in place when the input is PDF, keeping layout, seals, and signatures', 'Formal documents, court evidence, external delivery'],
    ]
    out_table = Table(out_data, colWidths=[30 * mm, 65 * mm, 60 * mm])
    out_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), PRIMARY),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('FONTNAME', (0, 0), (-1, 0), 'PingFangBold'),
        ('FONTNAME', (0, 1), (-1, -1), 'PingFang'),
        ('FONTSIZE', (0, 0), (-1, -1), 9.5),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, BG_LIGHT]),
        ('TOPPADDING', (0, 0), (-1, -1), 2 * mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2 * mm),
        ('LEFTPADDING', (0, 0), (-1, -1), 3 * mm),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    story.append(out_table)

    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(
        '<b>What does "keeps original layout" mean?</b> For example, if you input a Word contract '
        '(KaiTi, size 12, 1.5 line spacing), the output DOCX is still KaiTi, size 12, 1.5 line spacing. '
        'Only the party names become placeholders. Likewise, a PDF input yields a redacted PDF that keeps all of its layout, fonts, and seals.',
        styles['body']
    ))

    story.append(make_tip_box(
        '<b>Cross-format output (for example, PDF to DOCX):</b> the result is re-laid-out using '
        '<b>FangSong, size 12, 1.5 line spacing</b> (the standard legal-document template).',
        styles, 'info'
    ))

    # ===== 10. How to use - command line =====
    story.append(PageBreak())
    story.append(Paragraph('10. How to use - command line', styles['h1']))
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=5 * mm))

    story.append(Paragraph(
        'The command line is good for batch processing or integrating into a workflow.',
        styles['body']
    ))

    cmd_examples = [
        ('Redact a Word document (keep original layout)', 'python3 cli.py anonymize input.docx -o output.docx --cn-llm'),
        ('Redact a PDF (in-place PDF redaction)', 'python3 cli.py anonymize input.pdf -o output.pdf --cn-llm'),
        ('Output MD + DOCX + PDF in one run', 'python3 cli.py anonymize input.pdf -o output -f md,docx,pdf --cn-llm'),
        ('Scanned PDF (enable OCR + Chinese NER)', 'python3 cli.py anonymize scan.pdf -o output.docx --ocr --cn-llm'),
        ('Use the PaddleOCR engine for a scan', 'python3 cli.py anonymize scan.pdf -o out.docx --ocr --ocr-engine paddleocr'),
        ('All layers on (mixed Chinese/English cross-border case)', 'python3 cli.py anonymize input.pdf -o out.pdf --cn-llm --llm'),
        ('Analyze only, no redaction', 'python3 cli.py analyze input.docx --cn-llm'),
        ('List all supported types', 'python3 cli.py list-types'),
        ('Redact mobile numbers and email only', 'python3 cli.py anonymize input.pdf --only phone,email'),
        ('Use the partial-mask strategy', 'python3 cli.py anonymize input.pdf --mask-strategy partial'),
    ]

    for desc, cmd in cmd_examples:
        story.append(Paragraph(f'<b>{desc}:</b>', styles['body']))
        story.append(Paragraph(cmd, styles['code']))

    # ===== 11. Supported types of sensitive data =====
    story.append(PageBreak())
    story.append(Paragraph('11. Supported types of sensitive data', styles['h1']))
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=5 * mm))

    story.append(Paragraph(
        'The tool auto-detects the following 30+ types of sensitive data:',
        styles['body']
    ))

    type_data = [
        ['Category', 'Types covered'],
        ['ID documents', 'ID number, passport no., HK/Macau permit, Taiwan permit, military ID'],
        ['Companies / institutions', 'Unified social credit code, org code, tax registration no., company name, law firm name'],
        ['Cases / contracts', 'Case number, contract no., invoice no., document no.'],
        ['Contact details', 'Mobile number, landline / fax, 400/800 hotline, email, URL'],
        ['Social accounts', 'QQ / WeChat ID'],
        ['Financial', 'Bank card no., RMB amount (including Chinese capital figures), foreign-currency amount'],
        ['Vehicle', 'License plate, VIN'],
        ['Address', 'Full address, postal code, house number'],
        ['Person names', 'Person names in legal documents, detected from surrounding context keywords'],
        ['Institution names', 'Companies, law firms, courts, government bodies, banks, schools, hospitals, and more'],
        ['Date and time', 'Date, time, date / time'],
        ['Network identifiers', 'IP address, MAC address'],
        ['Certificate numbers', 'Property certificate no., permit / approval no., patent / trademark no.'],
        ['Project names', 'Project, works, system, and platform names'],
    ]

    type_table = Table(type_data, colWidths=[28 * mm, 127 * mm])
    type_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), PRIMARY),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('FONTNAME', (0, 0), (-1, 0), 'PingFangBold'),
        ('FONTNAME', (0, 1), (-1, -1), 'PingFang'),
        ('FONTSIZE', (0, 0), (-1, -1), 9.5),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, BG_LIGHT]),
        ('TOPPADDING', (0, 0), (-1, -1), 2 * mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2 * mm),
        ('LEFTPADDING', (0, 0), (-1, -1), 3 * mm),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    story.append(type_table)

    # ===== 12. Frequently asked questions =====
    story.append(PageBreak())
    story.append(Paragraph('12. Frequently asked questions', styles['h1']))
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=5 * mm))

    faqs = [
        ('pip install fails with Permission denied',
         'Add --user before the command: pip3 install --user -r requirements.txt'),
        ('The browser did not open after launch',
         'Open your browser by hand and enter the address shown in the terminal (usually http://127.0.0.1:8080).'),
        ('Launch fails with Address already in use',
         'The port is taken. The program automatically tries ports 8080-8099. If all are taken, close other programs and retry.'),
        ('On Windows, the python command opens the Microsoft Store',
         'In System Settings, turn off the Python entries under "App execution aliases", or run with the full path.'),
        ('macOS says command not found: python3',
         'You need to install Python. Or try installing the Xcode command line tools: xcode-select --install'),
        ('Error: ModuleNotFoundError',
         'Dependencies did not install correctly. Run the pip install command again. Make sure pip and python match: python3 -m pip install -r requirements.txt'),
        ('I chose not to install the English model earlier and now want to use it',
         'Delete the .user_config file in the project root and double-click the launch script again. It will ask once more. Choose "y" to enable English detection.'),
        ('Model downloads are slow in mainland China',
         'The launch script uses the hf-mirror.com mirror by default. If it is still slow, set the environment variable by hand: export HF_ENDPOINT=https://hf-mirror.com'),
        ('After checking "Chinese NER", the first analysis took a long time',
         'This is normal. The first time it runs, it downloads about a 400 MB model from HuggingFace (1-3 minutes in China). After that, every later run takes only seconds.'),
        ('There is no OpenAI switch in the browser',
         'That means you chose "Chinese-only mode" at first launch. Delete .user_config and restart to choose again.'),
        ('The DOCX output does not match the original layout',
         'When the input is DOCX and the output is also DOCX, the tool keeps the original layout automatically. If the input is PDF, the output DOCX uses the FangSong, size 12, 1.5 line spacing standard template.'),
        ('The PDF output looks different from the original PDF',
         'When the input is PDF and the output is also PDF, it does "in-place redaction": it keeps the original PDF fonts, layout, seals, and signatures, and only replaces sensitive text with placeholders.'),
        ('OCR produces many garbled characters',
         'The default RapidOCR is good enough for most cases. For complex layouts, enable OCR, switch to the "PaddleOCR" engine, and re-analyze (slower but slightly more accurate).'),
        ('A scanned PDF does not read any text',
         'Turn on the "Enable OCR" switch. The RapidOCR engine is built in, no extra install needed. The first run downloads about a 15 MB model automatically.'),
        ('Some sensitive data was not detected',
         'First, turn on the "Chinese NER" layer (strongly recommended). Second, add it by hand using the browser "User dictionary" feature. The dictionary is saved.'),
        ('I want to look the original text back up after redaction',
         'Each redaction run produces a _mapping.json table linking placeholders to the original text. Keep it as carefully as the original file.'),
    ]

    for q, a in faqs:
        story.append(Paragraph(f'<b>Q: {q}</b>', styles['body']))
        story.append(Paragraph(f'A: {a}', styles['body_indent']))
        story.append(Spacer(1, 2 * mm))

    # ===== 13. Privacy and security =====
    story.append(Paragraph('13. Privacy and security', styles['h1']))
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=5 * mm))

    story.append(make_tip_box(
        'All processing runs <b>entirely on your machine</b>. It <b>calls no external API</b> and '
        '<b>uploads no data</b> to the cloud. The code is fully open source and auditable, so it suits highly confidential legal files.',
        styles, 'tip'
    ))

    story.append(Spacer(1, 5 * mm))

    security_points = [
        'All text analysis and replacement happen in memory. Nothing is sent over the network.',
        'All AI models (Chinese NER / OpenAI / RapidOCR / PaddleOCR) run fully offline after the first download. '
        'No internet needed.',
        'Uploaded files are cleaned up automatically once processing finishes (deleted after 24 hours in browser mode).',
        'The generated mapping table (_mapping.json) links the original sensitive data to the placeholders. Keep it safe.',
        'We recommend deleting the mapping file after you are done, or storing it in a secure location.',
        'The source code is fully open source and auditable. Run grep -r "requests|urllib|http" *.py to verify '
        'the project code itself makes zero network calls.',
        'You can set three environment variables to cut off the network completely: HF_HUB_OFFLINE=1, TRANSFORMERS_OFFLINE=1, '
        'PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=1.',
    ]
    for point in security_points:
        story.append(Paragraph(
            f'<bullet>&bull;</bullet> {point}',
            styles['bullet']
        ))

    story.append(Spacer(1, 10 * mm))
    story.append(make_tip_box(
        '<b>Mapping-table security note:</b> the _mapping.json file generated after redaction contains the full mapping of '
        'the original sensitive data. Keep it as carefully as the original file, and do not share it alongside the redacted file.',
        styles, 'danger'
    ))

    story.append(Spacer(1, 20 * mm))
    story.append(HRFlowable(width='40%', thickness=0.5, color=BORDER,
                            spaceAfter=5 * mm, spaceBefore=5 * mm))
    story.append(Paragraph(
        'Questions or suggestions are welcome. Enjoy using it!',
        ParagraphStyle('EndNote', fontName='PingFang', fontSize=11,
                       textColor=TEXT_GRAY, alignment=TA_CENTER, leading=16)
    ))
    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph(
        'Made with love by <b>Lingbao Huang</b>',
        ParagraphStyle('Brand', fontName='PingFang', fontSize=10,
                       textColor=ACCENT, alignment=TA_CENTER, leading=14)
    ))

    return story


# ============ Main entry point ============
def main():
    output_path = Path(__file__).parent / 'Getting Started Guide.pdf'

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        title='Legal Anonymizer - Getting Started Guide',
        author='Legal Anonymizer',
    )

    styles = create_styles()
    story = build_content(styles)

    doc.build(story, onFirstPage=on_first_page, onLaterPages=on_page)
    print(f'PDF generated successfully: {output_path}')


if __name__ == '__main__':
    main()
