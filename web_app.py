#!/usr/bin/env python3
"""
Legal Document Anonymizer - Web UI
法律文档脱敏工具 - Web 界面

Usage:
    python3 web_app.py
    # Open http://127.0.0.1:5000
"""

import os
# 禁用 PaddleOCR 启动时的网络连通性检测（会阻塞数十秒）
os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', 'True')

import sys
import re
import json
import uuid
import time
import shutil
import threading
import io
import zipfile
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

# 确保模块路径
sys.path.insert(0, str(Path(__file__).parent))

from flask import Flask, request, jsonify, send_file, render_template
from anonymizer import LegalAnonymizer


def is_scanned_pdf(file_path: str) -> bool:
    """检测PDF是否为扫描版（文本内容极少）"""
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

# 目录配置
BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / 'uploads'
OUTPUT_DIR = BASE_DIR / 'output'
INBOX_DIR = BASE_DIR / 'inbox'
USER_DICT_PATH = BASE_DIR / 'user_dict.json'

for d in [UPLOAD_DIR, OUTPUT_DIR, INBOX_DIR]:
    d.mkdir(exist_ok=True)


def load_user_dict() -> list:
    """加载持久化用户词典"""
    if USER_DICT_PATH.exists():
        try:
            with open(USER_DICT_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_user_dict(entries: list):
    """保存用户词典到磁盘"""
    with open(USER_DICT_PATH, 'w', encoding='utf-8') as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


def safe_client_filename(filename: str, fallback: str = 'document') -> str:
    """保留中文文件名，同时阻断路径穿越和控制字符。"""
    name = Path(filename or '').name
    name = re.sub(r'[\\/\x00-\x1f\x7f]+', '_', name).strip(' .')
    return name or fallback

# 支持的文件格式
SUPPORTED_EXTENSIONS = {'.pdf', '.docx', '.doc', '.txt', '.md', '.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.gif', '.webp'}

# 会话存储（内存，单用户本地使用）
sessions: Dict[str, dict] = {}

# 会话超时时间（2小时）
SESSION_TIMEOUT = 7200


def cleanup_sessions():
    """清理过期会话"""
    now = time.time()
    expired = [sid for sid, s in sessions.items() if now - s['created_at'] > SESSION_TIMEOUT]
    for sid in expired:
        _cleanup_session_files(sid)
        del sessions[sid]


def _cleanup_session_files(session_id: str):
    """清理会话相关文件"""
    session = sessions.get(session_id)
    if not session:
        return
    # 清理上传文件（仅清理从 inbox 复制过来的副本）
    upload_path = session.get('upload_path')
    if upload_path and Path(upload_path).exists() and str(UPLOAD_DIR) in str(upload_path):
        try:
            Path(upload_path).unlink()
        except Exception:
            pass


def create_session(file_path: str, file_name: str) -> dict:
    """创建新会话"""
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


# ==================== 页面路由 ====================

@app.route('/')
def index():
    import importlib.util
    # 启动脚本根据用户首次选择写入 ENABLE_OPENAI=0/1，未启用时前端隐藏 OpenAI 开关
    ai_runtime = (
        importlib.util.find_spec('torch') is not None
        and importlib.util.find_spec('transformers') is not None
    )
    enable_cn_ner = ai_runtime
    enable_openai = os.environ.get('ENABLE_OPENAI', '0') == '1' and ai_runtime
    enable_rapidocr = (
        importlib.util.find_spec('rapidocr') is not None
        and importlib.util.find_spec('onnxruntime') is not None
    )
    enable_paddleocr = importlib.util.find_spec('paddleocr') is not None
    return render_template(
        'index.html',
        enable_openai=enable_openai,
        enable_cn_ner=enable_cn_ner,
        enable_rapidocr=enable_rapidocr,
        enable_paddleocr=enable_paddleocr,
    )


# ==================== API 路由 ====================

@app.route('/api/types', methods=['GET'])
def get_types():
    """获取所有支持的实体类型"""
    anonymizer = LegalAnonymizer()
    types = anonymizer.get_supported_types()
    # 补充自动检测类型
    auto_types = {
        'person': '人名',
        'company': '公司名',
        'law_firm': '律师事务所',
        'court': '法院',
        'government': '政府机关',
        'institution': '机构',
        'bank_name': '银行',
        'address': '地址',
        'other': '其他',
    }
    types.update(auto_types)
    return jsonify({'types': types})


@app.route('/api/upload', methods=['POST'])
def upload_file():
    """上传文件"""
    if 'file' not in request.files:
        return jsonify({'error': '未选择文件'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': '文件名为空'}), 400

    suffix = Path(file.filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        return jsonify({'error': f'不支持的文件格式: {suffix}'}), 400

    # 保存上传文件
    safe_name = f"{uuid.uuid4().hex[:8]}_{file.filename}"
    save_path = UPLOAD_DIR / safe_name
    file.save(str(save_path))

    session = create_session(str(save_path), file.filename)

    # 检测扫描版PDF
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
    """列出 inbox 文件夹中的文件"""
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
    """从 inbox 选择文件"""
    data = request.get_json()
    filename = data.get('filename')
    if not filename:
        return jsonify({'error': '未指定文件名'}), 400

    source_path = INBOX_DIR / filename
    if not source_path.exists():
        return jsonify({'error': '文件不存在'}), 404

    # 复制到 uploads（不修改原文件）
    safe_name = f"{uuid.uuid4().hex[:8]}_{filename}"
    dest_path = UPLOAD_DIR / safe_name
    shutil.copy2(str(source_path), str(dest_path))

    session = create_session(str(dest_path), filename)

    # 检测扫描版PDF
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
    """后台线程跑单文件 OCR + 检测，期间更新 session['analyze_progress']"""
    session = sessions.get(session_id)
    if not session:
        return
    progress = session['analyze_progress']
    progress['stage'] = 'ocr'
    progress['started_at'] = time.time()

    # 计算 ETA：扫描版按页数预估，文字版很快
    fp = session['file_path']
    progress['eta_s'] = _estimate_eta(fp, use_ocr) if Path(fp).suffix.lower() == '.pdf' else 5.0

    def on_progress(stage, current, total):
        progress['stage'] = stage
        progress['current'] = current
        progress['total'] = max(total, 1)
        progress['percent'] = round(current / max(total, 1) * 90, 1)  # OCR 占总流程 90%

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
            progress['error'] = '文件内容为空，如果是扫描版 PDF 请启用 OCR'
            progress['percent'] = 100
            return

        progress['stage'] = 'detect'
        progress['percent'] = 92
        all_entities = anonymizer._detect_all(text)
        session['auto_entities'] = all_entities

        # 整理 findings
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
            'person': '人名', 'company': '公司名', 'law_firm': '律师事务所',
            'court': '法院', 'government': '政府机关', 'institution': '机构',
            'bank_name': '银行', 'address': '地址',
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
    """启动单文件分析（异步）。调用后立即返回，前端轮询 /api/analyze/status"""
    data = request.get_json()
    session_id = data.get('session_id')
    use_ocr = data.get('use_ocr', False)
    ocr_engine = data.get('ocr_engine', 'rapidocr')
    use_cn_llm = data.get('use_cn_llm', False)
    use_llm = data.get('use_llm', False)

    session = sessions.get(session_id)
    if not session:
        return jsonify({'error': '会话不存在或已过期'}), 404

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
    """查询单文件分析进度"""
    session = sessions.get(session_id)
    if not session or 'analyze_progress' not in session:
        return jsonify({'error': '会话不存在或未开始分析'}), 404
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
    """管理自定义实体"""
    data = request.get_json()
    session_id = data.get('session_id')
    action = data.get('action', 'add')  # add, remove, set

    session = sessions.get(session_id)
    if not session:
        return jsonify({'error': '会话不存在或已过期'}), 404

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
    """执行脱敏"""
    data = request.get_json()
    session_id = data.get('session_id')
    output_format = data.get('output_format', 'docx')
    mask_strategy = data.get('mask_strategy', 'placeholder')
    excluded_entities = data.get('excluded_entities', [])  # [{type, name}]

    session = sessions.get(session_id)
    if not session:
        return jsonify({'error': '会话不存在或已过期'}), 404

    if not session.get('text'):
        return jsonify({'error': '请先分析文档'}), 400

    try:
        anonymizer = LegalAnonymizer(
            use_cn_llm=session.get('use_cn_llm', False),
            use_llm=session.get('use_llm', False),
        )

        # 设置掩码策略；whitebox 是占位符策略 + PDF 渲染时不画文字
        pdf_whitebox = (mask_strategy == 'whitebox')
        effective_strategy = 'placeholder' if pdf_whitebox else mask_strategy
        if effective_strategy:
            anonymizer.set_all_mask_strategy(effective_strategy)

        # 占位符风格：'auto' 时根据文本中 CJK 占比自动选；whitebox 模式不画文字所以风格无关紧要
        placeholder_style = _resolve_placeholder_style(
            data.get('placeholder_style', 'auto'),
            session.get('text', '') or '',
        )
        anonymizer.set_placeholder_style(placeholder_style)

        # 注入用户词典 + 会话自定义实体
        user_dict = load_user_dict()
        if user_dict:
            anonymizer.add_custom_entities(user_dict)
        if session['custom_entities']:
            anonymizer.add_custom_entities(session['custom_entities'])

        # 重新检测实体
        all_entities = anonymizer._detect_all(session['text'])

        # 过滤掉用户排除的实体
        if excluded_entities:
            excluded_set = {(e['type'], e['name']) for e in excluded_entities}
            all_entities = [
                (text, etype, pos) for text, etype, pos in all_entities
                if (etype, text) not in excluded_set
            ]

        # 执行掩码
        anonymizer.masker.reset()
        anonymized_text, detailed_mapping = anonymizer.masker.mask_all(session['text'], all_entities)

        # 保存脱敏后文本到 session，供后续"继续脱敏"使用
        session['anonymized_text'] = anonymized_text
        session['detailed_mapping'] = detailed_mapping

        # 生成输出文件名
        orig_stem = Path(session['file_name']).stem
        output_name = f"{orig_stem}_anonymized"
        output_path = OUTPUT_DIR / f"{session['id']}_{output_name}"
        input_suffix = Path(session['file_name']).suffix.lower()

        # 归一化 output_format 为 list
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

        # 保存映射表
        mapping_path = OUTPUT_DIR / f"{session['id']}_{output_name}_mapping.json"
        anonymizer.processor.write_mapping(detailed_mapping, str(mapping_path))
        saved_files.append(('mapping_file', str(mapping_path)))

        # 确定主输出文件
        main_output = None
        for key, path in saved_files:
            if key.startswith('output_'):
                main_output = path
                break

        # 收集每种输出格式 → 路径的映射
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
        return jsonify({'error': f'脱敏失败: {str(e)}'}), 500


@app.route('/api/re-anonymize', methods=['POST'])
def re_anonymize_document():
    """继续脱敏：用户发现残留敏感信息后，添加新实体再次脱敏"""
    data = request.get_json()
    session_id = data.get('session_id')
    new_entities = data.get('entities', [])  # [{"type": "company", "name": "源德盛"}, ...]

    session = sessions.get(session_id)
    if not session:
        return jsonify({'error': '会话不存在或已过期'}), 404

    if not session.get('text'):
        return jsonify({'error': '请先分析并脱敏文档'}), 400

    if not new_entities:
        return jsonify({'error': '请至少添加一个需脱敏的实体'}), 400

    try:
        anonymizer = LegalAnonymizer(
            use_cn_llm=session.get('use_cn_llm', False),
            use_llm=session.get('use_llm', False),
        )

        # 注入用户词典
        user_dict = load_user_dict()
        if user_dict:
            anonymizer.add_custom_entities(user_dict)

        # 恢复之前的自定义实体 + 添加新实体
        all_custom = session.get('custom_entities', []) + new_entities
        session['custom_entities'] = all_custom
        anonymizer.add_custom_entities(all_custom)

        # 获取之前的掩码策略和排除列表
        mask_strategy = session.get('last_mask_strategy', 'placeholder')
        output_format = session.get('output_format', 'docx')
        excluded_entities = session.get('last_excluded_entities', [])

        pdf_whitebox = (mask_strategy == 'whitebox')
        effective_strategy = 'placeholder' if pdf_whitebox else mask_strategy
        if effective_strategy:
            anonymizer.set_all_mask_strategy(effective_strategy)

        # 用原始文本重新检测全部实体
        all_entities = anonymizer._detect_all(session['text'])

        # 过滤排除的
        if excluded_entities:
            excluded_set = {(e['type'], e['name']) for e in excluded_entities}
            all_entities = [
                (text, etype, pos) for text, etype, pos in all_entities
                if (etype, text) not in excluded_set
            ]

        # 重新执行掩码
        anonymizer.masker.reset()
        anonymized_text, detailed_mapping = anonymizer.masker.mask_all(session['text'], all_entities)

        session['anonymized_text'] = anonymized_text
        session['detailed_mapping'] = detailed_mapping

        # 重新写入文件（覆盖之前的输出）
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

        # 更新映射表
        mapping_path = OUTPUT_DIR / f"{session['id']}_{output_name}_mapping.json"
        anonymizer.processor.write_mapping(detailed_mapping, str(mapping_path))
        saved_files.append(('mapping_file', str(mapping_path)))

        # 构建 output_paths（每种格式 → 文件路径），前端用来生成多个下载按钮
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
        return jsonify({'error': f'继续脱敏失败: {str(e)}'}), 500


def _anonymize_filename(session: dict) -> str:
    """对文件名中的敏感信息也做脱敏替换"""
    orig_stem = Path(session['file_name']).stem
    mapping = session.get('detailed_mapping', {}).get('mapping', {})
    if not mapping:
        return orig_stem

    # 构建替换表：原始值 -> 占位符，按长度降序
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
    """下载脱敏后的文件。可选 ?fmt=docx/pdf/md/txt 指定格式。"""
    session = sessions.get(session_id)
    if not session:
        return jsonify({'error': '文件不存在'}), 404

    fmt = request.args.get('fmt', '').lower()
    target_path = None
    if fmt and session.get('output_paths'):
        target_path = session['output_paths'].get(fmt)
    if not target_path:
        target_path = session.get('output_path')
    if not target_path:
        return jsonify({'error': '文件不存在'}), 404

    output_path = Path(target_path)
    if not output_path.exists():
        return jsonify({'error': '输出文件不存在'}), 404

    # 构造下载文件名（文件名也脱敏）
    anonymized_stem = _anonymize_filename(session)
    download_name = f"{anonymized_stem}_脱敏版{output_path.suffix}"

    return send_file(
        str(output_path),
        as_attachment=True,
        download_name=download_name,
    )


@app.route('/api/download-mapping/<session_id>', methods=['GET'])
def download_mapping(session_id):
    """下载映射表"""
    session = sessions.get(session_id)
    if not session or not session.get('mapping_path'):
        return jsonify({'error': '映射表不存在'}), 404

    mapping_path = Path(session['mapping_path'])
    if not mapping_path.exists():
        return jsonify({'error': '映射表文件不存在'}), 404

    anonymized_stem = _anonymize_filename(session)
    download_name = f"{anonymized_stem}_映射表.json"

    return send_file(
        str(mapping_path),
        as_attachment=True,
        download_name=download_name,
    )


@app.route('/api/user-dict', methods=['GET'])
def get_user_dict():
    """获取用户词典"""
    entries = load_user_dict()
    return jsonify({'entries': entries, 'count': len(entries)})


@app.route('/api/user-dict/add', methods=['POST'])
def add_user_dict():
    """向用户词典添加词条"""
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
    """从用户词典删除词条"""
    data = request.get_json()
    to_remove = data.get('entries', [])
    current = load_user_dict()
    current = [x for x in current
               if not any(e['type'] == x['type'] and e['name'] == x['name'] for e in to_remove)]
    save_user_dict(current)
    return jsonify({'entries': current, 'count': len(current)})


@app.route('/api/user-dict/clear', methods=['POST'])
def clear_user_dict():
    """清空用户词典"""
    save_user_dict([])
    return jsonify({'entries': [], 'count': 0})


# ==================== 批量处理 ====================

# 批次状态：batch_id -> {created_at, items: [...], done, total}
batches: Dict[str, dict] = {}
BATCH_TIMEOUT = 7200  # 2 小时


def _normalize_dictionary_entries(entries) -> List[dict]:
    """清洗、去重自定义词条，并限制单条长度。"""
    result = []
    seen = set()
    for raw in entries or []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get('name', '')).strip()
        entity_type = str(raw.get('type', 'other')).strip() or 'other'
        if not name or len(name) > 500:
            continue
        key = (entity_type, name)
        if key in seen:
            continue
        seen.add(key)
        item = {'type': entity_type, 'name': name}
        scope = raw.get('item_indices')
        if isinstance(scope, list):
            item['item_indices'] = sorted({int(x) for x in scope if str(x).isdigit()})
        result.append(item)
    return result


def _merge_dictionary_entries(current: List[dict], additions: List[dict]) -> int:
    """原地追加词条；返回新增数量。"""
    existing = {
        (e.get('type', 'other'), e.get('name', ''), tuple(e.get('item_indices', [])))
        for e in current
    }
    added = 0
    for entry in _normalize_dictionary_entries(additions):
        key = (entry['type'], entry['name'], tuple(entry.get('item_indices', [])))
        if key not in existing:
            current.append(entry)
            existing.add(key)
            added += 1
    return added


def _normalize_abbreviation_relations(relations) -> List[dict]:
    """清洗批次级全称—简称关系。"""
    result = []
    seen = set()
    for raw in relations or []:
        if not isinstance(raw, dict):
            continue
        full_name = str(raw.get('full_name', '')).strip()
        abbreviation = str(raw.get('abbreviation', '')).strip()
        entity_type = str(raw.get('type', 'company')).strip() or 'company'
        if (
            not full_name or not abbreviation or full_name == abbreviation
            or len(full_name) > 500 or len(abbreviation) > 500
        ):
            continue
        key = (entity_type, full_name, abbreviation)
        if key in seen:
            continue
        seen.add(key)
        result.append({
            'type': entity_type,
            'full_name': full_name,
            'abbreviation': abbreviation,
        })
    return result


def _mapping_as_entities(mapping: dict) -> List[dict]:
    """将前序文件已识别的实体作为后续文件的精确词典。"""
    result = []
    for info in (mapping or {}).values():
        if isinstance(info, dict) and info.get('original'):
            result.append({
                'type': info.get('type', 'other'),
                'name': info['original'],
            })
    return result


def _dictionary_for_item(batch: dict, item_idx: int) -> List[dict]:
    entries = []
    for entry in batch.get('dictionary', []):
        scope = entry.get('item_indices')
        if not scope or item_idx in scope:
            entries.append({'type': entry['type'], 'name': entry['name']})
    # 已分配占位符的原文必须继续被精确识别，以保持跨文件一致。
    entries.extend(_mapping_as_entities(batch.get('mapping', {})))
    return _normalize_dictionary_entries(entries)


def _write_batch_mapping(batch: dict) -> str:
    """只导出批次级映射，不写入原文上下文。"""
    path = OUTPUT_DIR / f"batch_{batch['id']}_mapping_v{batch['version']}.json"
    payload = {
        'metadata': {
            'format': 'legal-anonymizer-batch-mapping',
            'format_version': 2,
            'batch_id': batch['id'],
            'batch_version': batch['version'],
            'created_at': int(time.time()),
            'entity_count': len(batch.get('mapping', {})),
            'file_count': len(batch.get('items', [])),
        },
        'files': [
            {
                'idx': it['idx'],
                'name': it['name'],
                'latest_version': it.get('version', 0),
            }
            for it in batch.get('items', []) if it.get('file_path')
        ],
        'mapping': batch.get('mapping', {}),
        'history': batch.get('history', []),
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    batch['mapping_path'] = str(path)
    return str(path)


def _batch_type_names(anonymizer: LegalAnonymizer) -> dict:
    names = anonymizer.pattern_detector.type_names.copy()
    names.update({
        'person': '人名', 'company': '公司名', 'law_firm': '律师事务所',
        'court': '法院', 'government': '政府机关', 'institution': '机构',
        'bank_name': '银行', 'address': '地址', 'project_name': '项目名称',
        'other': '其他',
    })
    return names


def _analyze_batch_item(batch_id: str, item: dict, options: dict):
    """仅识别不脱敏，生成可汇总到批次检查页的结果。"""
    item['analysis_status'] = 'processing'
    item['analysis_error'] = None
    item['analysis_started_at'] = time.time()
    try:
        anonymizer = LegalAnonymizer(
            use_cn_llm=options.get('use_cn_llm', False),
            use_llm=options.get('use_llm', False),
        )
        entries = _normalize_dictionary_entries(options.get('entries', []))
        if entries:
            anonymizer.add_custom_entities(entries)

        input_path = Path(item['file_path'])
        use_ocr = (
            is_scanned_pdf(str(input_path))
            if input_path.suffix.lower() == '.pdf' else
            input_path.suffix.lower() in {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.gif', '.webp'}
        )
        item['is_scanned'] = use_ocr
        text = anonymizer.processor.extract_text(
            str(input_path),
            use_ocr=use_ocr,
            ocr_engine=options.get('ocr_engine', 'rapidocr'),
        )
        if not text.strip():
            raise ValueError('文件内容为空；如为扫描文件，请检查 OCR 依赖')

        entities = anonymizer._detect_all(text)
        findings = {}
        finding_lookup = {}
        for entity_text, entity_type, pos in entities:
            key = (entity_type, entity_text)
            if key in finding_lookup:
                finding_lookup[key]['occurrence_count'] += 1
                continue
            start = max(0, pos - 40)
            end = min(len(text), pos + len(entity_text) + 40)
            context = text[start:end].replace('\n', ' ').strip()
            entry = {
                'text': entity_text,
                'context': context,
                'occurrence_count': 1,
            }
            finding_lookup[key] = entry
            findings.setdefault(entity_type, []).append(entry)

        entity_types = {}
        for entity_text, entity_type, _ in entities:
            entity_types.setdefault(entity_text, entity_type)
        abbreviations = []
        for abbreviation, full_name in anonymizer.entity_detector.abbreviation_map.items():
            abbreviations.append({
                'type': entity_types.get(abbreviation, entity_types.get(full_name, 'company')),
                'full_name': full_name,
                'abbreviation': abbreviation,
            })

        item['findings'] = findings
        item['abbreviations'] = abbreviations
        item['type_names'] = _batch_type_names(anonymizer)
        item['analysis_entity_count'] = len(entities)
        item['analysis_unique_count'] = len(finding_lookup)
        item['analysis_status'] = 'done'
    except Exception as exc:
        import traceback
        traceback.print_exc()
        item['analysis_status'] = 'error'
        item['analysis_error'] = str(exc)
        item['findings'] = {}
        item['abbreviations'] = []
    finally:
        item['analysis_elapsed_s'] = round(
            time.time() - item.get('analysis_started_at', time.time()), 1
        )


def _run_batch_analysis(batch_id: str, options: dict):
    batch = batches.get(batch_id)
    if not batch:
        return
    try:
        for item in batch['items']:
            if item.get('file_path'):
                _analyze_batch_item(batch_id, item, options)
                batch['analysis_done'] = sum(
                    1 for current in batch['items']
                    if current.get('file_path') and current.get('analysis_status') in ('done', 'error')
                )
    finally:
        batch['analysis_running'] = False
        batch['analysis_complete'] = True


def _cleanup_batches():
    now = time.time()
    expired = [bid for bid, b in batches.items() if now - b['created_at'] > BATCH_TIMEOUT]
    for bid in expired:
        # 不再清理输出文件，让用户来得及取回
        del batches[bid]


def _detect_placeholder_style(text: str) -> str:
    """根据文本字符分布自动选占位符风格：CJK ≥ 拉丁用中文，否则英文。
    本工具面向中文法律场景，文本不足时默认中文。"""
    if not text:
        return 'chinese_bracket'
    cjk = sum(1 for c in text if '一' <= c <= '鿿')
    latin = sum(1 for c in text if 'a' <= c.lower() <= 'z')
    total = cjk + latin
    if total < 10:
        return 'chinese_bracket'
    return 'chinese_bracket' if cjk >= latin else 'english_bracket'


def _peek_file_text(file_path: str, max_chars: int = 3000) -> str:
    """快速取文件前几页/前几段文字（不跑 OCR）用于语言判断"""
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
    """把 'auto' 解析成具体风格；其它值原样返回"""
    if requested == 'auto':
        return _detect_placeholder_style(text)
    return requested or 'chinese_bracket'


def _estimate_eta(file_path: str, is_scanned: bool) -> float:
    """根据文件类型/大小预估处理秒数（保守估计）"""
    suffix = Path(file_path).suffix.lower()
    size_kb = os.path.getsize(file_path) / 1024
    if suffix == '.pdf':
        # 用页数判断更准；扫描版 OCR 慢约 12-15s/页，文字版 PDF 约 0.5-1s/页
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
    """单个文件脱敏（在后台线程里跑）"""
    try:
        batch = batches[batch_id]
        version = batch['version']
        item['status'] = 'processing'
        item['stage'] = 'detect'
        item['started_at'] = time.time()
        item['error'] = None

        anonymizer = LegalAnonymizer(
            use_cn_llm=options.get('use_cn_llm', False),
            use_llm=options.get('use_llm', False),
        )
        # whitebox 模式仍然用 placeholder 策略生成文本占位符（[PERSON_1]等），
        # 但会传 pdf_whitebox=True 让 PDF 输出层不画文字、只留白框
        strategy = options.get('mask_strategy', 'placeholder')
        pdf_whitebox = (strategy == 'whitebox')
        anonymizer.set_all_mask_strategy('placeholder' if pdf_whitebox else strategy)
        # 占位符风格：'auto' 时按文件内容判断中/英；whitebox 不画文字所以风格无关
        sample = _peek_file_text(item['file_path']) if not pdf_whitebox else ''
        ph_style = _resolve_placeholder_style(
            options.get('placeholder_style', 'auto'), sample
        )
        anonymizer.set_placeholder_style(ph_style)

        input_path = Path(item['file_path'])
        # input_path.stem 已经带了 batch_<id>_NN_ 前缀（来自 upload 时的 safe_name），
        # 这里取原始文件名的 stem 避免重复前缀
        orig_stem = Path(item['name']).stem
        output_stem = OUTPUT_DIR / (
            f"batch_{batch_id}_v{version}_{item['idx']:02d}_{orig_stem}"
        )

        item['stage'] = 'anonymize'
        formats = options.get('output_formats') or ['pdf' if input_path.suffix.lower() == '.pdf' else 'docx']
        is_scanned = is_scanned_pdf(str(input_path)) if input_path.suffix.lower() == '.pdf' else False
        item['is_scanned'] = is_scanned
        item['eta_s'] = round(_estimate_eta(str(input_path), is_scanned), 1)

        result = anonymizer.anonymize_file(
            input_path=str(input_path),
            output_path=str(output_stem),
            custom_entities=_dictionary_for_item(batch, item['idx']),
            excluded_entities=item.get('excluded_entities', []),
            output_format=formats,
            use_ocr=is_scanned,
            ocr_engine=options.get('ocr_engine', 'rapidocr'),
            save_text_backup=True,
            save_mapping=False,
            pdf_whitebox=pdf_whitebox,
            initial_mapping=batch.get('mapping', {}),
            abbreviation_relations=options.get('abbreviation_relations'),
        )
        if 'error' in result:
            item['status'] = 'error'
            item['error'] = result['error']
            return

        info = result.get('result', {})
        # 前序文件和旧版本的占位符保持不变，仅追加新映射。
        batch['mapping'].update(info.get('mapping', {}))

        # 收集当前版本的输出文件
        outputs = {}
        for k, v in info.items():
            if k in ('output_pdf', 'output_docx', 'output_md', 'output_txt', 'text_backup'):
                outputs[k] = v
        item['outputs'] = outputs
        current_placeholders = {
            log.get('masked_text') for log in info.get('replacement_log', [])
            if log.get('masked_text')
        }
        item['total_matched'] = len(current_placeholders)
        item['replacements_made'] = info.get('replacements_made', 0)
        item['is_scanned'] = is_scanned
        item['version'] = version
        item.setdefault('versions', []).append({
            'version': version,
            'outputs': dict(outputs),
            'total_matched': item['total_matched'],
            'replacements_made': item['replacements_made'],
        })
        item['status'] = 'done'
        item['stage'] = 'completed'
    except Exception as e:
        import traceback
        traceback.print_exc()
        item['status'] = 'error'
        item['error'] = str(e)
    finally:
        # 记录完成时间和实际耗时
        if 'started_at' in item:
            item['finished_at'] = time.time()
            item['elapsed_s'] = round(item['finished_at'] - item['started_at'], 1)
        batch = batches.get(batch_id)
        if batch:
            targets = set(batch.get('target_indices', []))
            batch['done'] = sum(
                1 for it in batch['items']
                if it['idx'] in targets and it['status'] in ('done', 'error')
            )


def _run_batch_pass(batch_id: str, options: dict, added_entries: List[dict]):
    """顺序跑完一轮，以便前一份文件的映射可被后一份复用。"""
    batch = batches.get(batch_id)
    if not batch:
        return
    try:
        targets = set(batch.get('target_indices', []))
        for item in batch['items']:
            if item['idx'] in targets and item.get('file_path'):
                _process_batch_item(batch_id, item, options)
        batch.setdefault('history', []).append({
            'version': batch['version'],
            'created_at': int(time.time()),
            'added_entries': [
                {'type': e['type'], 'name': e['name']} for e in added_entries
            ],
            'processed_items': sorted(targets),
        })
        _write_batch_mapping(batch)
    finally:
        batch['running'] = False


@app.route('/api/restore/extract', methods=['POST'])
def restore_extract_text():
    """从上传的脱敏后文件（pdf/docx/txt）提取纯文本，给还原页用"""
    if 'file' not in request.files:
        return jsonify({'error': '未选择文件'}), 400
    f = request.files['file']
    if not f.filename:
        return jsonify({'error': '文件名为空'}), 400
    suffix = Path(f.filename).suffix.lower()
    if suffix not in {'.txt', '.md', '.pdf', '.docx', '.doc'}:
        return jsonify({'error': f'不支持的格式: {suffix}'}), 400
    safe_name = f"restore_{uuid.uuid4().hex[:8]}_{f.filename}"
    save_path = UPLOAD_DIR / safe_name
    f.save(str(save_path))
    try:
        from anonymizer import LegalAnonymizer as _LA
        a = _LA()
        text = a.processor.extract_text(str(save_path), use_ocr=False)
        return jsonify({'text': text, 'chars': len(text)})
    except Exception as e:
        return jsonify({'error': f'提取失败: {str(e)}'}), 500
    finally:
        try:
            save_path.unlink()
        except Exception:
            pass


@app.route('/api/restore', methods=['POST'])
def restore_text():
    """根据脱敏映射 JSON 把脱敏文本还原成原文"""
    data = request.get_json() or {}
    anonymized_text = data.get('text', '')
    mapping_data = data.get('mapping')

    if not anonymized_text:
        return jsonify({'error': '请粘贴脱敏后的文本'}), 400
    if not mapping_data:
        return jsonify({'error': '请提供映射字典（mapping.json 的内容或上传文件）'}), 400

    # mapping 可能是直接的 {占位符: {original, type}}，
    # 也可能是工具导出的完整 JSON：{metadata, mapping, replacement_log}
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
        return jsonify({'error': f'还原失败: {str(e)}'}), 500


@app.route('/api/batch/upload', methods=['POST'])
def batch_upload():
    """批量上传文件，返回 batch_id 与每个文件的元信息"""
    _cleanup_batches()
    files = request.files.getlist('files')
    if not files:
        return jsonify({'error': '未选择文件'}), 400

    batch_id = uuid.uuid4().hex[:10]
    items = []
    for idx, f in enumerate(files, 1):
        if not f.filename:
            continue
        suffix = Path(f.filename).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            items.append({
                'idx': idx, 'name': f.filename, 'size': 0,
                'status': 'rejected', 'error': f'不支持的格式 {suffix}',
                'file_path': None, 'outputs': {},
            })
            continue
        original_name = safe_client_filename(f.filename, f'document_{idx}{suffix}')
        safe_name = f"batch_{batch_id}_{idx:02d}_{original_name}"
        save_path = UPLOAD_DIR / safe_name
        f.save(str(save_path))
        items.append({
            'idx': idx,
            'name': original_name,
            'file_path': str(save_path),
            'size': os.path.getsize(save_path),
            'status': 'pending',
            'stage': '',
            'is_scanned': False,
            'outputs': {},
            'total_matched': 0,
            'replacements_made': 0,
            'version': 0,
            'versions': [],
            'analysis_status': 'pending',
            'analysis_error': None,
            'findings': {},
            'abbreviations': [],
            'type_names': {},
            'excluded_entities': [],
            'review_custom_entities': [],
            'error': None,
        })

    batches[batch_id] = {
        'id': batch_id,
        'created_at': time.time(),
        'items': items,
        'total': sum(1 for it in items if it['status'] == 'pending'),
        'done': 0,
        'started': False,
        'running': False,
        'version': 0,
        'dictionary': [],
        'mapping': {},
        'mapping_path': None,
        'history': [],
        'target_indices': [],
        'options': {},
        'analysis_running': False,
        'analysis_complete': False,
        'analysis_done': 0,
        'analysis_total': sum(1 for it in items if it.get('file_path')),
        'analysis_options': {},
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


@app.route('/api/batch/analyze', methods=['POST'])
def batch_analyze():
    """启动批量识别，完成后由用户在批次总表中统一复核。"""
    data = request.get_json() or {}
    batch = batches.get(data.get('batch_id'))
    if not batch:
        return jsonify({'error': '批次不存在或已过期'}), 404
    if batch.get('running') or batch.get('analysis_running'):
        return jsonify({'error': '当前批次正在处理'}), 409
    if batch.get('started'):
        return jsonify({'error': '批次已进入脱敏阶段'}), 409

    options = {
        'use_cn_llm': bool(data.get('use_cn_llm', False)),
        'use_llm': bool(data.get('use_llm', False)),
        'ocr_engine': data.get('ocr_engine', 'rapidocr'),
        'entries': _normalize_dictionary_entries(load_user_dict())
                   + _normalize_dictionary_entries(data.get('entries', [])),
    }
    batch['analysis_options'] = options
    batch['analysis_running'] = True
    batch['analysis_complete'] = False
    batch['analysis_done'] = 0
    batch['analysis_total'] = sum(1 for it in batch['items'] if it.get('file_path'))
    batch['created_at'] = time.time()
    for item in batch['items']:
        if item.get('file_path'):
            item['analysis_status'] = 'pending'
            item['analysis_error'] = None
            item['findings'] = {}
            item['abbreviations'] = []

    threading.Thread(
        target=_run_batch_analysis,
        args=(batch['id'], options),
        daemon=True,
    ).start()
    return jsonify({
        'status': 'started', 'batch_id': batch['id'],
        'total': batch['analysis_total'],
        'use_cn_llm': options['use_cn_llm'],
        'use_llm': options['use_llm'],
    })


@app.route('/api/batch/start', methods=['POST'])
def batch_start():
    """开始批量脱敏（异步，逐个跑）"""
    data = request.get_json() or {}
    batch_id = data.get('batch_id')
    analyzed_options = batch.get('analysis_options', {}) if (batch := batches.get(batch_id)) else {}
    options = {
        'mask_strategy': data.get('mask_strategy', 'placeholder'),
        'placeholder_style': data.get('placeholder_style', 'english_bracket'),
        'output_formats': data.get('output_formats') or None,
        'use_cn_llm': bool(data.get('use_cn_llm', analyzed_options.get('use_cn_llm', False))),
        'use_llm': bool(data.get('use_llm', analyzed_options.get('use_llm', False))),
        'ocr_engine': data.get('ocr_engine', analyzed_options.get('ocr_engine', 'rapidocr')),
        'abbreviation_relations': (
            _normalize_abbreviation_relations(data.get('abbreviation_relations', []))
            if 'abbreviation_relations' in data else None
        ),
    }
    if not batch:
        return jsonify({'error': '批次不存在或已过期'}), 404
    if batch['started']:
        return jsonify({'error': '批次已开始'}), 400

    batch['started'] = True
    batch['running'] = True
    batch['version'] = 1
    batch['options'] = options
    initial_entries = _normalize_dictionary_entries(load_user_dict())
    initial_entries.extend(_normalize_dictionary_entries(data.get('entries', [])))
    batch['dictionary'] = []
    _merge_dictionary_entries(batch['dictionary'], initial_entries)

    # 应用逐文件人工复核结果：删除项不参与脱敏；编辑项用新词替换旧词；
    # 人工补充和编辑后的实体仅对指定文件生效。
    reviews = data.get('reviews', {})
    for item in batch['items']:
        review = reviews.get(str(item['idx']), reviews.get(item['idx'], {}))
        if not isinstance(review, dict):
            review = {}
        # 兼容旧版前端的 excluded_entities 字段。
        deleted = _normalize_dictionary_entries(
            review.get('deleted_entities', review.get('excluded_entities', []))
        )
        edited = _normalize_dictionary_entries(review.get('edited_entities', []))
        custom = _normalize_dictionary_entries(review.get('custom_entities', []))
        custom = _normalize_dictionary_entries(custom + edited)
        item['excluded_entities'] = deleted
        item['review_custom_entities'] = custom
        scoped_custom = [dict(entry, item_indices=[item['idx']]) for entry in custom]
        _merge_dictionary_entries(batch['dictionary'], scoped_custom)
    batch['target_indices'] = [
        it['idx'] for it in batch['items'] if it['status'] == 'pending'
    ]
    batch['total'] = len(batch['target_indices'])
    batch['done'] = 0

    threading.Thread(
        target=_run_batch_pass,
        args=(batch_id, options, initial_entries),
        daemon=True,
    ).start()
    return jsonify({
        'status': 'started', 'batch_id': batch_id,
        'total': batch['total'], 'version': batch['version'],
        'dictionary_count': len(batch['dictionary']),
    })


@app.route('/api/batch/refine', methods=['POST'])
def batch_refine():
    """在同一批次内追加遗漏词条，从原文件重新生成新版结果。"""
    data = request.get_json() or {}
    batch = batches.get(data.get('batch_id'))
    if not batch:
        return jsonify({'error': '批次不存在或已过期'}), 404
    if batch.get('running'):
        return jsonify({'error': '当前批次仍在处理，请稍后再更新'}), 409

    additions = _normalize_dictionary_entries(data.get('entries', []))
    if not additions:
        return jsonify({'error': '请至少添加一个遗漏敏感词'}), 400

    requested = data.get('item_indices')
    valid_indices = {it['idx'] for it in batch['items'] if it.get('file_path')}
    if isinstance(requested, list) and requested:
        selected = set()
        for value in requested:
            try:
                idx = int(value)
            except (TypeError, ValueError):
                continue
            if idx in valid_indices:
                selected.add(idx)
        target_indices = sorted(selected)
        if not target_indices:
            return jsonify({'error': '没有选中可处理的文件'}), 400
        for entry in additions:
            entry['item_indices'] = target_indices
    else:
        target_indices = sorted(valid_indices)

    added = _merge_dictionary_entries(batch['dictionary'], additions)
    if added == 0:
        return jsonify({'error': '这些词条已在当前批次词典中'}), 400

    if data.get('save_to_user_dict'):
        persistent = load_user_dict()
        plain_additions = [
            {'type': e['type'], 'name': e['name']} for e in additions
        ]
        _merge_dictionary_entries(persistent, plain_additions)
        save_user_dict(persistent)

    batch['version'] += 1
    batch['running'] = True
    batch['target_indices'] = target_indices
    batch['total'] = len(target_indices)
    batch['done'] = 0
    batch['created_at'] = time.time()  # 用户活动时续期
    for item in batch['items']:
        if item['idx'] in set(target_indices):
            item['status'] = 'pending'
            item['stage'] = ''
            item['error'] = None

    threading.Thread(
        target=_run_batch_pass,
        args=(batch['id'], batch['options'], additions),
        daemon=True,
    ).start()
    return jsonify({
        'status': 'started', 'batch_id': batch['id'],
        'version': batch['version'], 'total': batch['total'],
        'added': added, 'dictionary_count': len(batch['dictionary']),
    })


@app.route('/api/batch/status/<batch_id>', methods=['GET'])
def batch_status(batch_id):
    batch = batches.get(batch_id)
    if not batch:
        return jsonify({'error': '批次不存在或已过期'}), 404
    return jsonify({
        'batch_id': batch_id,
        'version': batch.get('version', 0),
        'analysis_running': batch.get('analysis_running', False),
        'analysis_complete': batch.get('analysis_complete', False),
        'analysis_done': batch.get('analysis_done', 0),
        'analysis_total': batch.get('analysis_total', 0),
        'analysis_options': {
            'use_cn_llm': batch.get('analysis_options', {}).get('use_cn_llm', False),
            'use_llm': batch.get('analysis_options', {}).get('use_llm', False),
            'ocr_engine': batch.get('analysis_options', {}).get('ocr_engine', 'rapidocr'),
        },
        'total': batch['total'],
        'done': batch['done'],
        'progress': round(batch['done'] / batch['total'] * 100, 1) if batch['total'] else 0,
        'all_finished': not batch.get('running', False),
        'can_refine': batch.get('started', False) and not batch.get('running', False),
        'dictionary_count': len(batch.get('dictionary', [])),
        'mapping_count': len(batch.get('mapping', {})),
        'history': batch.get('history', []),
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
                'analysis_status': it.get('analysis_status', 'pending'),
                'analysis_error': it.get('analysis_error'),
                'analysis_entity_count': it.get('analysis_entity_count', 0),
                'analysis_unique_count': it.get('analysis_unique_count', 0),
                'analysis_elapsed_s': it.get('analysis_elapsed_s', 0),
                'findings': it.get('findings', {}),
                'abbreviations': it.get('abbreviations', []),
                'type_names': it.get('type_names', {}),
            }
            for it in batch['items']
        ],
        'now': time.time(),
    })


@app.route('/api/batch/download/<batch_id>', methods=['GET'])
def batch_download(batch_id):
    """打包下载整个批次的所有输出文件为 zip"""
    from urllib.parse import quote
    batch = batches.get(batch_id)
    if not batch:
        return jsonify({'error': '批次不存在或已过期'}), 404

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for it in batch['items']:
            if it['status'] != 'done':
                continue
            # 在 zip 内的目录结构：原文件名（去后缀）/ {输出文件名}
            stem = Path(it['name']).stem
            # 输出文件实际名带 batch_ 前缀，重命名为简洁的：原名{.pdf|_mapping.json|.txt}
            for kind, path in (it.get('outputs') or {}).items():
                if not path or not Path(path).exists():
                    continue
                p = Path(path)
                # 把 batch_<id>_NN_ 前缀剥掉，让 zip 里文件名干净
                clean_name = re.sub(r'^batch_[a-f0-9]+_v\d+_\d+_', '', p.name)
                arc_name = f"{stem}/{clean_name}"
                zf.write(str(p), arc_name)
    buf.seek(0)

    # Content-Disposition：filename 用 ASCII，filename* 用 UTF-8 编码（RFC 5987），
    # 否则 Werkzeug 会因非 Latin-1 字符报 UnicodeError 让请求挂死。
    ascii_name = f'batch_{batch_id}_results.zip'
    utf8_name = quote(f'批量脱敏结果_{batch_id}.zip', safe='')
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


@app.route('/api/batch/mapping/<batch_id>', methods=['GET'])
def batch_mapping_download(batch_id):
    """单独下载批次还原字典。

    字典含全部敏感原文，不随脱敏成果 zip 一起打包，避免用户把成果转发
    给外部时连同还原字典一并发出。
    """
    from urllib.parse import quote
    batch = batches.get(batch_id)
    if not batch:
        return jsonify({'error': '批次不存在或已过期'}), 404
    mapping_path = batch.get('mapping_path')
    if not mapping_path or not Path(mapping_path).exists():
        return jsonify({'error': '当前批次尚未生成还原字典'}), 404

    filename = f"批次还原字典_v{batch.get('version', 0)}.json"
    with open(mapping_path, 'rb') as f:
        payload = f.read()
    from flask import Response
    return Response(
        payload,
        mimetype='application/json',
        headers={
            'Content-Disposition': (
                'attachment; filename="batch_mapping.json"; '
                f"filename*=UTF-8''{quote(filename)}"
            ),
        },
    )


@app.route('/api/batch/restore', methods=['POST'])
def batch_restore_files():
    """使用一个批次字典还原多个文件，统一输出 Word ZIP。"""
    files = request.files.getlist('files')
    mapping_upload = request.files.get('mapping')
    if not files:
        return jsonify({'error': '请选择至少一个脱敏后文件'}), 400
    if not mapping_upload:
        return jsonify({'error': '请选择批次还原字典 JSON'}), 400

    try:
        mapping_payload = json.load(mapping_upload.stream)
    except Exception as exc:
        return jsonify({'error': f'还原字典无法解析: {exc}'}), 400
    mapping = (
        mapping_payload.get('mapping')
        if isinstance(mapping_payload, dict) and isinstance(mapping_payload.get('mapping'), dict)
        else mapping_payload
    )
    if not isinstance(mapping, dict) or not mapping:
        return jsonify({'error': '还原字典中没有有效映射'}), 400

    anonymizer = LegalAnonymizer()
    report = []
    zip_buffer = io.BytesIO()
    with tempfile.TemporaryDirectory(prefix='restore_', dir=str(OUTPUT_DIR)) as temp_dir:
        temp_root = Path(temp_dir)
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            used_names = set()
            for idx, uploaded in enumerate(files, 1):
                if not uploaded.filename:
                    continue
                original_name = safe_client_filename(uploaded.filename, f'document_{idx}.txt')
                suffix = Path(original_name).suffix.lower()
                if suffix not in {'.docx', '.doc', '.pdf', '.txt', '.md'}:
                    report.append(f'{original_name}: 跳过，不支持的格式 {suffix}')
                    continue

                source_path = temp_root / f'{idx:03d}_{original_name}'
                uploaded.save(str(source_path))
                output_name = f'{Path(original_name).stem}_已还原.docx'
                if output_name in used_names:
                    output_name = f'{Path(original_name).stem}_已还原_{idx}.docx'
                used_names.add(output_name)
                output_path = temp_root / output_name

                try:
                    use_ocr = suffix == '.pdf' and is_scanned_pdf(str(source_path))
                    extracted = anonymizer.processor.extract_text(
                        str(source_path), use_ocr=use_ocr
                    )
                    occurrences = sum(extracted.count(ph) for ph in mapping if ph)
                    if suffix == '.docx':
                        ok = anonymizer.processor.restore_docx_inplace(
                            str(source_path), str(output_path), mapping
                        )
                    else:
                        restored = LegalAnonymizer.restore_text(extracted, mapping)
                        ok = anonymizer.processor._write_docx(restored, str(output_path))
                    if not ok or not output_path.exists():
                        raise RuntimeError('无法生成 Word 文件')
                    zf.write(str(output_path), output_name)
                    note = f'已还原 {occurrences} 处占位符'
                    if occurrences == 0:
                        note += '（请检查文件与字典是否匹配）'
                    report.append(f'{original_name}: {note}')
                except Exception as exc:
                    report.append(f'{original_name}: 还原失败 - {exc}')

            zf.writestr('还原报告.txt', '\n'.join(report))

    zip_buffer.seek(0)
    from flask import Response
    return Response(
        zip_buffer.getvalue(),
        mimetype='application/zip',
        headers={
            'Content-Disposition': (
                'attachment; filename="restored_word_files.zip"; '
                "filename*=UTF-8''%E6%89%B9%E9%87%8F%E8%BF%98%E5%8E%9FWord.zip"
            ),
        },
    )


def find_free_port(start=8080, end=8099):
    """找到一个可用端口"""
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
    """启动时清理超过24小时的临时上传文件，超过48小时的输出文件"""
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
    """服务停止时清理所有上传临时文件（输出文件保留供用户取回）"""
    if not UPLOAD_DIR.exists():
        return
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
    print("  法律文档脱敏工具 - Web 界面")
    print("  by 黄灵宝同学")
    print("=" * 50)
    print()
    print(f"  Inbox 文件夹: {INBOX_DIR}")
    print(f"  输出文件夹:   {OUTPUT_DIR}")
    print()
    print(f"  请在浏览器中打开: http://127.0.0.1:{port}")
    print()
    print("  数据完全本地处理，不上传云端")
    print("  按 Ctrl+C 停止服务")
    print("=" * 50)
    print()

    # 延迟 1.5 秒后自动打开浏览器
    threading.Timer(3.0, lambda: webbrowser.open(f'http://127.0.0.1:{port}')).start()

    app.run(host='127.0.0.1', port=port, debug=False)
