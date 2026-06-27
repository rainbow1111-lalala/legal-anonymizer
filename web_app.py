#!/usr/bin/env python3
"""
Legal Document Anonymizer - Web UI
Legal Anonymizer - browser interface

Usage:
    python3 web_app.py
    # Open http://127.0.0.1:5000
"""

import os
# Disable PaddleOCR's network connectivity check at startup (it can block for tens of seconds)
os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', 'True')

import sys
import re
import json
import uuid
import time
import shutil
import threading
from pathlib import Path
from typing import Dict, List, Optional

# Make sure the module path is available
sys.path.insert(0, str(Path(__file__).parent))

from flask import Flask, request, jsonify, send_file, render_template
from anonymizer import LegalAnonymizer


def is_scanned_pdf(file_path: str) -> bool:
    """Detect whether a PDF is a scanned document (almost no text content)."""
    try:
        import fitz
        doc = fitz.open(file_path)
        total_text = 0
        for page in doc:
            total_text += len(page.get_text().strip())
            if total_text > 100:
                doc.close()
                return False
        doc.close()
        return True
    except Exception:
        return False

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB

# Directory configuration
BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / 'uploads'
OUTPUT_DIR = BASE_DIR / 'output'
INBOX_DIR = BASE_DIR / 'inbox'
USER_DICT_PATH = BASE_DIR / 'user_dict.json'

for d in [UPLOAD_DIR, OUTPUT_DIR, INBOX_DIR]:
    d.mkdir(exist_ok=True)


def load_user_dict() -> list:
    """Load the persisted user dictionary."""
    if USER_DICT_PATH.exists():
        try:
            with open(USER_DICT_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_user_dict(entries: list):
    """Save the user dictionary to disk."""
    with open(USER_DICT_PATH, 'w', encoding='utf-8') as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)

# Supported file formats
SUPPORTED_EXTENSIONS = {'.pdf', '.docx', '.doc', '.txt', '.md', '.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.gif', '.webp'}

# Session store (in memory, for single-user local use)
sessions: Dict[str, dict] = {}

# Session timeout (2 hours)
SESSION_TIMEOUT = 7200


def cleanup_sessions():
    """Remove expired sessions."""
    now = time.time()
    expired = [sid for sid, s in sessions.items() if now - s['created_at'] > SESSION_TIMEOUT]
    for sid in expired:
        _cleanup_session_files(sid)
        del sessions[sid]


def _cleanup_session_files(session_id: str):
    """Clean up files associated with a session."""
    session = sessions.get(session_id)
    if not session:
        return
    # Clean up the uploaded file (only the copy made from inbox)
    upload_path = session.get('upload_path')
    if upload_path and Path(upload_path).exists() and str(UPLOAD_DIR) in str(upload_path):
        try:
            Path(upload_path).unlink()
        except Exception:
            pass


def create_session(file_path: str, file_name: str) -> dict:
    """Create a new session."""
    cleanup_sessions()

    session_id = str(uuid.uuid4())[:8]
    suffix = Path(file_name).suffix.lower()

    session = {
        'id': session_id,
        'created_at': time.time(),
        'file_path': file_path,
        'file_name': file_name,
        'file_type': suffix,
        'is_pdf': suffix == '.pdf',
        'is_image': suffix in {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.gif', '.webp'},
        'file_size': os.path.getsize(file_path),
        'text': None,
        'findings': None,
        'custom_entities': [],
        'use_ocr': False,
        'ocr_engine': 'rapidocr',
        'use_cn_llm': False,
        'use_llm': False,
        'output_path': None,
        'output_format': None,
        'result': None,
    }
    sessions[session_id] = session
    return session


# ==================== Page routes ====================

@app.route('/')
def index():
    # The launch script writes ENABLE_OPENAI=0/1 based on the user's first-run choice; when disabled the front end hides the OpenAI toggle
    enable_openai = os.environ.get('ENABLE_OPENAI', '0') == '1'
    return render_template('index.html', enable_openai=enable_openai)


# ==================== API routes ====================

@app.route('/api/types', methods=['GET'])
def get_types():
    """Get all supported entity types."""
    anonymizer = LegalAnonymizer()
    types = anonymizer.get_supported_types()
    # Add the auto-detected types
    auto_types = {
        'person': 'Person name',
        'company': 'Company',
        'law_firm': 'Law firm',
        'court': 'Court',
        'government': 'Government',
        'institution': 'Institution',
        'bank_name': 'Bank',
        'address': 'Address',
        'other': 'Other',
    }
    types.update(auto_types)
    return jsonify({'types': types})


@app.route('/api/upload', methods=['POST'])
def upload_file():
    """Upload a file."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file selected'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'File name is empty'}), 400

    suffix = Path(file.filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        return jsonify({'error': f'Unsupported file format: {suffix}'}), 400

    # Save the uploaded file
    safe_name = f"{uuid.uuid4().hex[:8]}_{file.filename}"
    save_path = UPLOAD_DIR / safe_name
    file.save(str(save_path))

    session = create_session(str(save_path), file.filename)

    # Detect scanned PDF
    is_scanned = False
    if session['is_pdf']:
        is_scanned = is_scanned_pdf(str(save_path))

    return jsonify({
        'session_id': session['id'],
        'file_name': session['file_name'],
        'file_type': session['file_type'],
        'file_size': session['file_size'],
        'is_pdf': session['is_pdf'],
        'is_image': session['is_image'],
        'is_scanned': is_scanned,
    })


@app.route('/api/inbox', methods=['GET'])
def list_inbox():
    """List the files in the inbox folder."""
    files = []
    for f in sorted(INBOX_DIR.iterdir()):
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS and not f.name.startswith('.'):
            stat = f.stat()
            files.append({
                'name': f.name,
                'size': stat.st_size,
                'modified': stat.st_mtime,
                'type': f.suffix.lower(),
                'is_pdf': f.suffix.lower() == '.pdf',
            })
    return jsonify({
        'files': files,
        'inbox_path': str(INBOX_DIR),
    })


@app.route('/api/inbox/select', methods=['POST'])
def select_inbox_file():
    """Select a file from the inbox."""
    data = request.get_json()
    filename = data.get('filename')
    if not filename:
        return jsonify({'error': 'No file name specified'}), 400

    source_path = INBOX_DIR / filename
    if not source_path.exists():
        return jsonify({'error': 'File does not exist'}), 404

    # Copy to uploads (the original file is left untouched)
    safe_name = f"{uuid.uuid4().hex[:8]}_{filename}"
    dest_path = UPLOAD_DIR / safe_name
    shutil.copy2(str(source_path), str(dest_path))

    session = create_session(str(dest_path), filename)

    # Detect scanned PDF
    is_scanned = False
    if session['is_pdf']:
        is_scanned = is_scanned_pdf(str(dest_path))

    return jsonify({
        'session_id': session['id'],
        'file_name': session['file_name'],
        'file_type': session['file_type'],
        'file_size': session['file_size'],
        'is_pdf': session['is_pdf'],
        'is_image': session['is_image'],
        'is_scanned': is_scanned,
    })


def _run_single_analyze(session_id: str, use_ocr: bool, ocr_engine: str,
                         use_cn_llm: bool, use_llm: bool):
    """Background thread that runs single-file OCR + detection, updating session['analyze_progress'] as it goes."""
    session = sessions.get(session_id)
    if not session:
        return
    progress = session['analyze_progress']
    progress['stage'] = 'ocr'
    progress['started_at'] = time.time()

    # Estimate the ETA: scanned PDFs are estimated by page count, text PDFs are fast
    fp = session['file_path']
    progress['eta_s'] = _estimate_eta(fp, use_ocr) if Path(fp).suffix.lower() == '.pdf' else 5.0

    def on_progress(stage, current, total):
        progress['stage'] = stage
        progress['current'] = current
        progress['total'] = max(total, 1)
        progress['percent'] = round(current / max(total, 1) * 90, 1)  # OCR accounts for 90% of the overall process

    try:
        anonymizer = LegalAnonymizer(use_cn_llm=use_cn_llm, use_llm=use_llm)
        ud = load_user_dict()
        if ud:
            anonymizer.add_custom_entities(ud)

        text = anonymizer.processor.extract_text(
            fp, use_ocr=use_ocr, ocr_engine=ocr_engine, progress_callback=on_progress,
        )
        session['text'] = text
        if not text.strip():
            progress['stage'] = 'error'
            progress['error'] = 'The file has no content. If this is a scanned PDF, please enable OCR.'
            progress['percent'] = 100
            return

        progress['stage'] = 'detect'
        progress['percent'] = 92
        all_entities = anonymizer._detect_all(text)
        session['auto_entities'] = all_entities

        # Organize findings
        CONTEXT_WINDOW = 40
        findings, seen = {}, {}
        for entity_text, entity_type, pos in all_entities:
            key = (entity_text, entity_type)
            if key not in seen:
                start = max(0, pos - CONTEXT_WINDOW)
                end = min(len(text), pos + len(entity_text) + CONTEXT_WINDOW)
                seen[key] = text[start:end].replace('\n', ' ').strip()
            findings.setdefault(entity_type, [])
            if not any(it['text'] == entity_text for it in findings[entity_type]):
                findings[entity_type].append({'text': entity_text, 'context': seen[key]})
        session['findings'] = findings

        type_names = anonymizer.pattern_detector.type_names.copy()
        type_names.update({
            'person': 'Person name', 'company': 'Company', 'law_firm': 'Law firm',
            'court': 'Court', 'government': 'Government', 'institution': 'Institution',
            'bank_name': 'Bank', 'address': 'Address',
        })
        progress['result'] = {
            'findings': findings,
            'total_findings': len(all_entities),
            'type_count': len(findings),
            'type_names': type_names,
            'text_preview': text[:500] + ('...' if len(text) > 500 else ''),
        }
        progress['stage'] = 'done'
        progress['percent'] = 100
        progress['finished_at'] = time.time()
        progress['elapsed_s'] = round(progress['finished_at'] - progress['started_at'], 1)
    except Exception as e:
        import traceback; traceback.print_exc()
        progress['stage'] = 'error'
        progress['error'] = str(e)
        progress['percent'] = 100


@app.route('/api/analyze', methods=['POST'])
def analyze_document():
    """Start single-file analysis (async). Returns immediately; the front end polls /api/analyze/status."""
    data = request.get_json()
    session_id = data.get('session_id')
    use_ocr = data.get('use_ocr', False)
    ocr_engine = data.get('ocr_engine', 'rapidocr')
    use_cn_llm = data.get('use_cn_llm', False)
    use_llm = data.get('use_llm', False)

    session = sessions.get(session_id)
    if not session:
        return jsonify({'error': 'Session does not exist or has expired'}), 404

    session['use_ocr'] = use_ocr
    session['ocr_engine'] = ocr_engine
    session['use_cn_llm'] = use_cn_llm
    session['use_llm'] = use_llm
    session['analyze_progress'] = {
        'stage': 'queued', 'percent': 0, 'current': 0, 'total': 0,
        'eta_s': 0, 'started_at': 0, 'finished_at': 0, 'elapsed_s': 0,
        'error': None, 'result': None,
    }

    threading.Thread(
        target=_run_single_analyze,
        args=(session_id, use_ocr, ocr_engine, use_cn_llm, use_llm),
        daemon=True,
    ).start()
    return jsonify({'status': 'started', 'session_id': session_id})


@app.route('/api/analyze/status/<session_id>', methods=['GET'])
def analyze_status(session_id):
    """Query the progress of single-file analysis."""
    session = sessions.get(session_id)
    if not session or 'analyze_progress' not in session:
        return jsonify({'error': 'Session does not exist or analysis has not started'}), 404
    p = session['analyze_progress']
    now = time.time()
    payload = {
        'stage': p['stage'],
        'percent': p['percent'],
        'current': p.get('current', 0),
        'total': p.get('total', 0),
        'eta_s': p.get('eta_s', 0),
        'started_at': p.get('started_at', 0),
        'elapsed_s': p.get('elapsed_s', 0) if p['stage'] in ('done', 'error')
                     else (round(now - p['started_at'], 1) if p.get('started_at') else 0),
        'error': p.get('error'),
        'now': now,
    }
    if p['stage'] == 'done':
        payload['result'] = p.get('result')
    return jsonify(payload)




@app.route('/api/entities', methods=['POST'])
def manage_entities():
    """Manage custom entities."""
    data = request.get_json()
    session_id = data.get('session_id')
    action = data.get('action', 'add')  # add, remove, set

    session = sessions.get(session_id)
    if not session:
        return jsonify({'error': 'Session does not exist or has expired'}), 404

    entities = data.get('entities', [])

    if action == 'set':
        session['custom_entities'] = entities
    elif action == 'add':
        for entity in entities:
            if entity not in session['custom_entities']:
                session['custom_entities'].append(entity)
    elif action == 'remove':
        for entity in entities:
            if entity in session['custom_entities']:
                session['custom_entities'].remove(entity)

    return jsonify({
        'custom_entities': session['custom_entities'],
        'count': len(session['custom_entities']),
    })


@app.route('/api/anonymize', methods=['POST'])
def anonymize_document():
    """Run anonymization."""
    data = request.get_json()
    session_id = data.get('session_id')
    output_format = data.get('output_format', 'docx')
    mask_strategy = data.get('mask_strategy', 'placeholder')
    excluded_entities = data.get('excluded_entities', [])  # [{type, name}]

    session = sessions.get(session_id)
    if not session:
        return jsonify({'error': 'Session does not exist or has expired'}), 404

    if not session.get('text'):
        return jsonify({'error': 'Please analyze the document first'}), 400

    try:
        anonymizer = LegalAnonymizer(
            use_cn_llm=session.get('use_cn_llm', False),
            use_llm=session.get('use_llm', False),
        )

        # Set the mask strategy; whitebox is the placeholder strategy plus no text drawn when rendering the PDF
        pdf_whitebox = (mask_strategy == 'whitebox')
        effective_strategy = 'placeholder' if pdf_whitebox else mask_strategy
        if effective_strategy:
            anonymizer.set_all_mask_strategy(effective_strategy)

        # Placeholder style: when 'auto', pick automatically based on the CJK ratio in the text; in whitebox mode no text is drawn so the style is irrelevant
        placeholder_style = _resolve_placeholder_style(
            data.get('placeholder_style', 'auto'),
            session.get('text', '') or '',
        )
        anonymizer.set_placeholder_style(placeholder_style)

        # Inject the user dictionary plus the session's custom entities
        user_dict = load_user_dict()
        if user_dict:
            anonymizer.add_custom_entities(user_dict)
        if session['custom_entities']:
            anonymizer.add_custom_entities(session['custom_entities'])

        # Re-detect entities
        all_entities = anonymizer._detect_all(session['text'])

        # Filter out the entities the user excluded
        if excluded_entities:
            excluded_set = {(e['type'], e['name']) for e in excluded_entities}
            all_entities = [
                (text, etype, pos) for text, etype, pos in all_entities
                if (etype, text) not in excluded_set
            ]

        # Apply masking
        anonymizer.masker.reset()
        anonymized_text, detailed_mapping = anonymizer.masker.mask_all(session['text'], all_entities)

        # Save the anonymized text to the session for a later "continue anonymizing" pass
        session['anonymized_text'] = anonymized_text
        session['detailed_mapping'] = detailed_mapping

        # Build the output file name
        orig_stem = Path(session['file_name']).stem
        output_name = f"{orig_stem}_anonymized"
        output_path = OUTPUT_DIR / f"{session['id']}_{output_name}"
        input_suffix = Path(session['file_name']).suffix.lower()

        # Normalize output_format to a list
        if isinstance(output_format, str):
            formats = [output_format]
        elif isinstance(output_format, (list, tuple)):
            formats = list(output_format) if output_format else ['docx']
        else:
            formats = ['docx']

        saved_files = []
        for fmt in formats:
            files = anonymizer._write_format(
                fmt=fmt,
                input_path=Path(session['file_path']),
                output_path=output_path,
                input_suffix=input_suffix,
                anonymized_content=anonymized_text,
                use_ocr=session.get('use_ocr', False),
                ocr_engine=session.get('ocr_engine', 'rapidocr'),
                whitebox_only=pdf_whitebox,
            )
            saved_files.extend(files)

        # Save the mapping table
        mapping_path = OUTPUT_DIR / f"{session['id']}_{output_name}_mapping.json"
        anonymizer.processor.write_mapping(detailed_mapping, str(mapping_path))
        saved_files.append(('mapping_file', str(mapping_path)))

        # Determine the main output file
        main_output = None
        for key, path in saved_files:
            if key.startswith('output_'):
                main_output = path
                break

        # Collect the mapping of each output format -> path
        output_files = {}
        for key, path in saved_files:
            if key.startswith('output_'):
                fmt_name = key.replace('output_', '')   # docx/pdf/md/txt
                output_files[fmt_name] = path

        session['output_path'] = main_output
        session['output_paths'] = output_files
        session['output_format'] = output_format
        session['mapping_path'] = str(mapping_path)
        session['last_mask_strategy'] = mask_strategy
        session['last_excluded_entities'] = excluded_entities
        session['result'] = {
            'output_path': main_output,
            'output_paths': output_files,
            'mapping_path': str(mapping_path),
            'total_matched': detailed_mapping['metadata']['entity_count'],
            'replacements_made': detailed_mapping['metadata']['replacements_made'],
            'mapping': detailed_mapping['mapping'],
            'saved_files': saved_files,
        }

        return jsonify({
            'status': 'success',
            'output_path': main_output,
            'output_paths': output_files,
            'output_dir': str(OUTPUT_DIR),
            'mapping_path': str(mapping_path),
            'total_matched': detailed_mapping['metadata']['entity_count'],
            'replacements_made': detailed_mapping['metadata']['replacements_made'],
            'mapping': detailed_mapping['mapping'],
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Anonymization failed: {str(e)}'}), 500


@app.route('/api/re-anonymize', methods=['POST'])
def re_anonymize_document():
    """Continue anonymizing: after the user spots residual sensitive information, add new entities and anonymize again."""
    data = request.get_json()
    session_id = data.get('session_id')
    new_entities = data.get('entities', [])  # [{"type": "company", "name": "Acme Corp"}, ...]

    session = sessions.get(session_id)
    if not session:
        return jsonify({'error': 'Session does not exist or has expired'}), 404

    if not session.get('text'):
        return jsonify({'error': 'Please analyze and anonymize the document first'}), 400

    if not new_entities:
        return jsonify({'error': 'Please add at least one entity to anonymize'}), 400

    try:
        anonymizer = LegalAnonymizer(
            use_cn_llm=session.get('use_cn_llm', False),
            use_llm=session.get('use_llm', False),
        )

        # Inject the user dictionary
        user_dict = load_user_dict()
        if user_dict:
            anonymizer.add_custom_entities(user_dict)

        # Restore the previous custom entities and add the new ones
        all_custom = session.get('custom_entities', []) + new_entities
        session['custom_entities'] = all_custom
        anonymizer.add_custom_entities(all_custom)

        # Retrieve the previous mask strategy and exclusion list
        mask_strategy = session.get('last_mask_strategy', 'placeholder')
        output_format = session.get('output_format', 'docx')
        excluded_entities = session.get('last_excluded_entities', [])

        pdf_whitebox = (mask_strategy == 'whitebox')
        effective_strategy = 'placeholder' if pdf_whitebox else mask_strategy
        if effective_strategy:
            anonymizer.set_all_mask_strategy(effective_strategy)

        # Re-detect all entities from the original text
        all_entities = anonymizer._detect_all(session['text'])

        # Filter out the excluded ones
        if excluded_entities:
            excluded_set = {(e['type'], e['name']) for e in excluded_entities}
            all_entities = [
                (text, etype, pos) for text, etype, pos in all_entities
                if (etype, text) not in excluded_set
            ]

        # Re-apply masking
        anonymizer.masker.reset()
        anonymized_text, detailed_mapping = anonymizer.masker.mask_all(session['text'], all_entities)

        session['anonymized_text'] = anonymized_text
        session['detailed_mapping'] = detailed_mapping

        # Rewrite the files (overwriting the previous output)
        orig_stem = Path(session['file_name']).stem
        output_name = f"{orig_stem}_anonymized"
        output_path = OUTPUT_DIR / f"{session['id']}_{output_name}"
        input_suffix = Path(session['file_name']).suffix.lower()

        if isinstance(output_format, str):
            formats = [output_format]
        elif isinstance(output_format, (list, tuple)):
            formats = list(output_format) if output_format else ['docx']
        else:
            formats = ['docx']

        saved_files = []
        for fmt in formats:
            files = anonymizer._write_format(
                fmt=fmt,
                input_path=Path(session['file_path']),
                output_path=output_path,
                input_suffix=input_suffix,
                anonymized_content=anonymized_text,
                use_ocr=session.get('use_ocr', False),
                ocr_engine=session.get('ocr_engine', 'rapidocr'),
                whitebox_only=pdf_whitebox,
            )
            saved_files.extend(files)

        # Update the mapping table
        mapping_path = OUTPUT_DIR / f"{session['id']}_{output_name}_mapping.json"
        anonymizer.processor.write_mapping(detailed_mapping, str(mapping_path))
        saved_files.append(('mapping_file', str(mapping_path)))

        # Build output_paths (each format -> file path); the front end uses this to render multiple download buttons
        output_files = {}
        main_output = None
        for key, path in saved_files:
            if key.startswith('output_'):
                fmt_name = key.replace('output_', '')   # docx / pdf / md / txt
                output_files[fmt_name] = path
                if main_output is None:
                    main_output = path

        session['output_path'] = main_output
        session['output_paths'] = output_files
        session['mapping_path'] = str(mapping_path)
        session['result'] = {
            'output_path': main_output,
            'output_paths': output_files,
            'mapping_path': str(mapping_path),
            'total_matched': detailed_mapping['metadata']['entity_count'],
            'replacements_made': detailed_mapping['metadata']['replacements_made'],
            'mapping': detailed_mapping['mapping'],
            'saved_files': saved_files,
        }

        return jsonify({
            'status': 'success',
            'output_path': main_output,
            'output_paths': output_files,
            'mapping_path': str(mapping_path),
            'total_matched': detailed_mapping['metadata']['entity_count'],
            'replacements_made': detailed_mapping['metadata']['replacements_made'],
            'mapping': detailed_mapping['mapping'],
            'new_entities_added': len(new_entities),
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Continued anonymization failed: {str(e)}'}), 500


def _anonymize_filename(session: dict) -> str:
    """Apply the same anonymization to sensitive information in the file name."""
    orig_stem = Path(session['file_name']).stem
    mapping = session.get('detailed_mapping', {}).get('mapping', {})
    if not mapping:
        return orig_stem

    # Build the replacement table: original value -> placeholder, in descending length order
    replacements = {}
    for placeholder, info in mapping.items():
        original = info.get('original', '')
        if original and len(original) >= 2:
            replacements[original] = placeholder
    sorted_originals = sorted(replacements.keys(), key=len, reverse=True)

    result = orig_stem
    for original in sorted_originals:
        result = result.replace(original, replacements[original])
    return result


@app.route('/api/download/<session_id>', methods=['GET'])
def download_file(session_id):
    """Download the anonymized file. An optional ?fmt=docx/pdf/md/txt selects the format."""
    session = sessions.get(session_id)
    if not session:
        return jsonify({'error': 'File does not exist'}), 404

    fmt = request.args.get('fmt', '').lower()
    target_path = None
    if fmt and session.get('output_paths'):
        target_path = session['output_paths'].get(fmt)
    if not target_path:
        target_path = session.get('output_path')
    if not target_path:
        return jsonify({'error': 'File does not exist'}), 404

    output_path = Path(target_path)
    if not output_path.exists():
        return jsonify({'error': 'Output file does not exist'}), 404

    # Build the download file name (the file name is anonymized too)
    anonymized_stem = _anonymize_filename(session)
    download_name = f"{anonymized_stem}_anonymized{output_path.suffix}"

    return send_file(
        str(output_path),
        as_attachment=True,
        download_name=download_name,
    )


@app.route('/api/download-mapping/<session_id>', methods=['GET'])
def download_mapping(session_id):
    """Download the mapping table."""
    session = sessions.get(session_id)
    if not session or not session.get('mapping_path'):
        return jsonify({'error': 'Mapping table does not exist'}), 404

    mapping_path = Path(session['mapping_path'])
    if not mapping_path.exists():
        return jsonify({'error': 'Mapping table file does not exist'}), 404

    anonymized_stem = _anonymize_filename(session)
    download_name = f"{anonymized_stem}_mapping.json"

    return send_file(
        str(mapping_path),
        as_attachment=True,
        download_name=download_name,
    )


@app.route('/api/user-dict', methods=['GET'])
def get_user_dict():
    """Get the user dictionary."""
    entries = load_user_dict()
    return jsonify({'entries': entries, 'count': len(entries)})


@app.route('/api/user-dict/add', methods=['POST'])
def add_user_dict():
    """Add entries to the user dictionary."""
    data = request.get_json()
    new_entries = data.get('entries', [])
    current = load_user_dict()
    added = 0
    for e in new_entries:
        if e.get('name') and not any(x['type'] == e['type'] and x['name'] == e['name'] for x in current):
            current.append({'type': e['type'], 'name': e['name']})
            added += 1
    save_user_dict(current)
    return jsonify({'entries': current, 'count': len(current), 'added': added})


@app.route('/api/user-dict/remove', methods=['POST'])
def remove_user_dict():
    """Remove entries from the user dictionary."""
    data = request.get_json()
    to_remove = data.get('entries', [])
    current = load_user_dict()
    current = [x for x in current
               if not any(e['type'] == x['type'] and e['name'] == x['name'] for e in to_remove)]
    save_user_dict(current)
    return jsonify({'entries': current, 'count': len(current)})


@app.route('/api/user-dict/clear', methods=['POST'])
def clear_user_dict():
    """Clear the user dictionary."""
    save_user_dict([])
    return jsonify({'entries': [], 'count': 0})


# ==================== Batch processing ====================

# Batch state: batch_id -> {created_at, items: [...], done, total}
batches: Dict[str, dict] = {}
BATCH_TIMEOUT = 7200  # 2 hours


def _cleanup_batches():
    now = time.time()
    expired = [bid for bid, b in batches.items() if now - b['created_at'] > BATCH_TIMEOUT]
    for bid in expired:
        # Do not clean up output files, so the user has time to retrieve them
        del batches[bid]


def _detect_placeholder_style(text: str) -> str:
    """Pick the placeholder style automatically from the text's character distribution: Chinese when CJK >= Latin, otherwise English.
    This tool targets Chinese legal scenarios, so it defaults to Chinese when there is not enough text."""
    if not text:
        return 'chinese_bracket'
    cjk = sum(1 for c in text if '一' <= c <= '鿿')
    latin = sum(1 for c in text if 'a' <= c.lower() <= 'z')
    total = cjk + latin
    if total < 10:
        return 'chinese_bracket'
    return 'chinese_bracket' if cjk >= latin else 'english_bracket'


def _peek_file_text(file_path: str, max_chars: int = 3000) -> str:
    """Quickly grab the first few pages/paragraphs of text (without running OCR) for language detection."""
    try:
        suffix = Path(file_path).suffix.lower()
        if suffix == '.pdf':
            import fitz
            doc = fitz.open(file_path)
            buf = []
            for i in range(min(3, len(doc))):
                buf.append(doc[i].get_text() or '')
                if sum(len(s) for s in buf) >= max_chars:
                    break
            doc.close()
            return ''.join(buf)[:max_chars]
        if suffix in ('.docx',):
            from docx import Document
            d = Document(file_path)
            return '\n'.join(p.text for p in d.paragraphs[:80])[:max_chars]
        if suffix in ('.txt', '.md'):
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read(max_chars)
    except Exception:
        return ''
    return ''


def _resolve_placeholder_style(requested: str, text: str = '') -> str:
    """Resolve 'auto' to a concrete style; any other value is returned as-is."""
    if requested == 'auto':
        return _detect_placeholder_style(text)
    return requested or 'chinese_bracket'


def _estimate_eta(file_path: str, is_scanned: bool) -> float:
    """Estimate the processing time in seconds based on file type/size (a conservative estimate)."""
    suffix = Path(file_path).suffix.lower()
    size_kb = os.path.getsize(file_path) / 1024
    if suffix == '.pdf':
        # Page count gives a more accurate estimate; scanned OCR is slow at about 12-15s/page, text PDFs about 0.5-1s/page
        try:
            import fitz
            pages = len(fitz.open(file_path))
        except Exception:
            pages = max(1, int(size_kb / 80))
        if is_scanned:
            return max(8.0, pages * 13.0 + 3.0)
        return max(2.0, pages * 0.8 + 1.5)
    if suffix in ('.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.gif', '.webp'):
        return 8.0
    if suffix in ('.docx', '.doc'):
        return max(2.0, size_kb / 100)
    return max(1.0, size_kb / 200)


def _process_batch_item(batch_id: str, item: dict, options: dict):
    """Anonymize a single file (runs in a background thread)."""
    try:
        item['status'] = 'processing'
        item['stage'] = 'detect'
        item['started_at'] = time.time()

        anonymizer = LegalAnonymizer(
            use_cn_llm=options.get('use_cn_llm', False),
            use_llm=options.get('use_llm', False),
        )
        # In whitebox mode it still uses the placeholder strategy to generate text placeholders ([PERSON_1] etc.),
        # but passes pdf_whitebox=True so the PDF output layer draws no text and leaves only white boxes
        strategy = options.get('mask_strategy', 'placeholder')
        pdf_whitebox = (strategy == 'whitebox')
        anonymizer.set_all_mask_strategy('placeholder' if pdf_whitebox else strategy)
        # Placeholder style: when 'auto', detect Chinese/English from the file content; whitebox draws no text so the style is irrelevant
        sample = _peek_file_text(item['file_path']) if not pdf_whitebox else ''
        ph_style = _resolve_placeholder_style(
            options.get('placeholder_style', 'auto'), sample
        )
        anonymizer.set_placeholder_style(ph_style)

        # Inject the user dictionary
        ud = load_user_dict()
        if ud:
            anonymizer.add_custom_entities(ud)

        input_path = Path(item['file_path'])
        # input_path.stem already carries the batch_<id>_NN_ prefix (from the safe_name used at upload time),
        # so use the stem of the original file name here to avoid a duplicated prefix
        orig_stem = Path(item['name']).stem
        output_stem = OUTPUT_DIR / f"batch_{batch_id}_{item['idx']:02d}_{orig_stem}"

        item['stage'] = 'anonymize'
        formats = options.get('output_formats') or ['pdf' if input_path.suffix.lower() == '.pdf' else 'docx']
        is_scanned = is_scanned_pdf(str(input_path)) if input_path.suffix.lower() == '.pdf' else False
        item['is_scanned'] = is_scanned
        item['eta_s'] = round(_estimate_eta(str(input_path), is_scanned), 1)

        result = anonymizer.anonymize_file(
            input_path=str(input_path),
            output_path=str(output_stem),
            output_format=formats,
            use_ocr=is_scanned,
            ocr_engine=options.get('ocr_engine', 'rapidocr'),
            save_text_backup=True,
            save_mapping=True,
            pdf_whitebox=pdf_whitebox,
        )
        if 'error' in result:
            item['status'] = 'error'
            item['error'] = result['error']
            return

        info = result.get('result', {})
        # Collect all output files (output_pdf / output_docx / mapping_file / text_backup)
        outputs = {}
        for k, v in info.items():
            if k in ('output_pdf', 'output_docx', 'output_md', 'output_txt', 'mapping_file', 'text_backup'):
                outputs[k] = v
        item['outputs'] = outputs
        item['total_matched'] = info.get('total_matched', 0)
        item['replacements_made'] = info.get('replacements_made', 0)
        item['is_scanned'] = is_scanned
        item['status'] = 'done'
        item['stage'] = 'completed'
    except Exception as e:
        import traceback
        traceback.print_exc()
        item['status'] = 'error'
        item['error'] = str(e)
    finally:
        # Record the finish time and the actual elapsed time
        if 'started_at' in item:
            item['finished_at'] = time.time()
            item['elapsed_s'] = round(item['finished_at'] - item['started_at'], 1)
        batch = batches.get(batch_id)
        if batch:
            batch['done'] = sum(1 for it in batch['items'] if it['status'] in ('done', 'error'))


@app.route('/api/restore/extract', methods=['POST'])
def restore_extract_text():
    """Extract plain text from an uploaded anonymized file (pdf/docx/txt) for the restore page."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file selected'}), 400
    f = request.files['file']
    if not f.filename:
        return jsonify({'error': 'File name is empty'}), 400
    suffix = Path(f.filename).suffix.lower()
    if suffix not in {'.txt', '.md', '.pdf', '.docx', '.doc'}:
        return jsonify({'error': f'Unsupported format: {suffix}'}), 400
    safe_name = f"restore_{uuid.uuid4().hex[:8]}_{f.filename}"
    save_path = UPLOAD_DIR / safe_name
    f.save(str(save_path))
    try:
        from anonymizer import LegalAnonymizer as _LA
        a = _LA()
        text = a.processor.extract_text(str(save_path), use_ocr=False)
        return jsonify({'text': text, 'chars': len(text)})
    except Exception as e:
        return jsonify({'error': f'Extraction failed: {str(e)}'}), 500
    finally:
        try:
            save_path.unlink()
        except Exception:
            pass


@app.route('/api/restore', methods=['POST'])
def restore_text():
    """Restore anonymized text back to the original using the anonymization mapping JSON."""
    data = request.get_json() or {}
    anonymized_text = data.get('text', '')
    mapping_data = data.get('mapping')

    if not anonymized_text:
        return jsonify({'error': 'Please paste the anonymized text'}), 400
    if not mapping_data:
        return jsonify({'error': 'Please provide the mapping dictionary (the contents of mapping.json or an uploaded file)'}), 400

    # mapping may be a direct {placeholder: {original, type}},
    # or the full JSON exported by the tool: {metadata, mapping, replacement_log}
    if isinstance(mapping_data, dict) and 'mapping' in mapping_data and isinstance(mapping_data['mapping'], dict):
        mapping_dict = mapping_data['mapping']
    else:
        mapping_dict = mapping_data

    try:
        restored = LegalAnonymizer.restore_text(anonymized_text, mapping_dict)
        return jsonify({
            'restored': restored,
            'replacements': len(mapping_dict) if isinstance(mapping_dict, dict) else 0,
        })
    except Exception as e:
        return jsonify({'error': f'Restore failed: {str(e)}'}), 500


@app.route('/api/batch/upload', methods=['POST'])
def batch_upload():
    """Batch-upload files; returns the batch_id and metadata for each file."""
    _cleanup_batches()
    files = request.files.getlist('files')
    if not files:
        return jsonify({'error': 'No file selected'}), 400

    batch_id = uuid.uuid4().hex[:10]
    items = []
    for idx, f in enumerate(files, 1):
        if not f.filename:
            continue
        suffix = Path(f.filename).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            items.append({
                'idx': idx, 'name': f.filename, 'size': 0,
                'status': 'rejected', 'error': f'Unsupported format {suffix}',
                'file_path': None, 'outputs': {},
            })
            continue
        safe_name = f"batch_{batch_id}_{idx:02d}_{f.filename}"
        save_path = UPLOAD_DIR / safe_name
        f.save(str(save_path))
        items.append({
            'idx': idx,
            'name': f.filename,
            'file_path': str(save_path),
            'size': os.path.getsize(save_path),
            'status': 'pending',
            'stage': '',
            'is_scanned': False,
            'outputs': {},
            'total_matched': 0,
            'replacements_made': 0,
            'error': None,
        })

    batches[batch_id] = {
        'id': batch_id,
        'created_at': time.time(),
        'items': items,
        'total': sum(1 for it in items if it['status'] == 'pending'),
        'done': 0,
        'started': False,
    }
    return jsonify({
        'batch_id': batch_id,
        'count': len(items),
        'items': [
            {'idx': it['idx'], 'name': it['name'], 'size': it['size'],
             'status': it['status'], 'error': it.get('error')}
            for it in items
        ],
    })


@app.route('/api/batch/start', methods=['POST'])
def batch_start():
    """Start batch anonymization (async, processed one at a time)."""
    data = request.get_json() or {}
    batch_id = data.get('batch_id')
    options = {
        'mask_strategy': data.get('mask_strategy', 'placeholder'),
        'placeholder_style': data.get('placeholder_style', 'english_bracket'),
        'output_formats': data.get('output_formats') or None,
        'use_cn_llm': bool(data.get('use_cn_llm', False)),
        'use_llm': bool(data.get('use_llm', False)),
        'ocr_engine': data.get('ocr_engine', 'rapidocr'),
    }
    batch = batches.get(batch_id)
    if not batch:
        return jsonify({'error': 'Batch does not exist or has expired'}), 404
    if batch['started']:
        return jsonify({'error': 'Batch already started'}), 400

    batch['started'] = True

    def _run():
        for it in batch['items']:
            if it['status'] == 'pending':
                _process_batch_item(batch_id, it, options)

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'status': 'started', 'batch_id': batch_id, 'total': batch['total']})


@app.route('/api/batch/status/<batch_id>', methods=['GET'])
def batch_status(batch_id):
    batch = batches.get(batch_id)
    if not batch:
        return jsonify({'error': 'Batch does not exist or has expired'}), 404
    return jsonify({
        'batch_id': batch_id,
        'total': batch['total'],
        'done': batch['done'],
        'progress': round(batch['done'] / batch['total'] * 100, 1) if batch['total'] else 0,
        'all_finished': batch['done'] >= batch['total'],
        'items': [
            {
                'idx': it['idx'], 'name': it['name'], 'status': it['status'],
                'stage': it.get('stage', ''),
                'error': it.get('error'),
                'is_scanned': it.get('is_scanned', False),
                'total_matched': it.get('total_matched', 0),
                'replacements_made': it.get('replacements_made', 0),
                'outputs': it.get('outputs', {}),
                'eta_s': it.get('eta_s', 0),
                'started_at': it.get('started_at', 0),
                'finished_at': it.get('finished_at', 0),
                'elapsed_s': it.get('elapsed_s', 0),
            }
            for it in batch['items']
        ],
        'now': time.time(),
    })


@app.route('/api/batch/download/<batch_id>', methods=['GET'])
def batch_download(batch_id):
    """Package all output files of an entire batch into a zip for download."""
    import zipfile, io
    from urllib.parse import quote
    batch = batches.get(batch_id)
    if not batch:
        return jsonify({'error': 'Batch does not exist or has expired'}), 404

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for it in batch['items']:
            if it['status'] != 'done':
                continue
            # Directory structure inside the zip: original file name (without extension) / {output file name}
            stem = Path(it['name']).stem
            # The actual output file name carries a batch_ prefix; rename it to a clean: original_name{.pdf|_mapping.json|.txt}
            for kind, path in (it.get('outputs') or {}).items():
                if not path or not Path(path).exists():
                    continue
                p = Path(path)
                # Strip the batch_<id>_NN_ prefix so the file names in the zip are clean
                clean_name = re.sub(r'^batch_[a-f0-9]+_\d+_', '', p.name)
                arc_name = f"{stem}/{clean_name}"
                zf.write(str(p), arc_name)
    buf.seek(0)

    # Content-Disposition: use ASCII for filename and UTF-8 encoding for filename* (RFC 5987),
    # otherwise Werkzeug raises a UnicodeError on non-Latin-1 characters and the request hangs.
    ascii_name = f'batch_{batch_id}_results.zip'
    utf8_name = quote(f'batch_anonymized_results_{batch_id}.zip', safe='')
    from flask import Response
    return Response(
        buf.getvalue(),
        mimetype='application/zip',
        headers={
            'Content-Disposition': (
                f"attachment; filename=\"{ascii_name}\"; "
                f"filename*=UTF-8''{utf8_name}"
            ),
        },
    )


def find_free_port(start=8080, end=8099):
    """Find an available port."""
    import socket
    for port in range(start, end):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', port))
                return port
        except OSError:
            continue
    return start


def cleanup_old_files():
    """At startup, clean up temporary upload files older than 24 hours and output files older than 48 hours."""
    now = time.time()
    for directory, max_age in [(UPLOAD_DIR, 86400), (OUTPUT_DIR, 172800)]:
        for f in directory.iterdir():
            if f.is_file() and (now - f.stat().st_mtime) > max_age:
                try:
                    f.unlink()
                except Exception:
                    pass


import atexit

@atexit.register
def on_exit():
    """When the service stops, clean up all temporary upload files (output files are kept for the user to retrieve)."""
    for f in UPLOAD_DIR.iterdir():
        if f.is_file():
            try:
                f.unlink()
            except Exception:
                pass


if __name__ == '__main__':
    import threading
    import webbrowser

    cleanup_old_files()
    port = find_free_port()

    print()
    print("=" * 50)
    print("  Legal Anonymizer - browser interface")
    print("  by Lingbao Huang")
    print("=" * 50)
    print()
    print(f"  Inbox folder:  {INBOX_DIR}")
    print(f"  Output folder: {OUTPUT_DIR}")
    print()
    print(f"  Open in your browser: http://127.0.0.1:{port}")
    print()
    print("  All data is processed locally and never uploaded to the cloud")
    print("  Press Ctrl+C to stop the service")
    print("=" * 50)
    print()

    # Open the browser automatically after a short delay
    threading.Timer(3.0, lambda: webbrowser.open(f'http://127.0.0.1:{port}')).start()

    app.jinja_env.auto_reload = True
    app.config['TEMPLATES_AUTO_RELOAD'] = True
    app.run(host='127.0.0.1', port=port, debug=False)
