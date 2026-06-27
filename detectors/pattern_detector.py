"""
Pattern-based Sensitive Data Detector
Regex-based detector for sensitive data.
"""

import re
from typing import Dict, List, Tuple


class PatternDetector:
    """Regex pattern detector."""

    # Priority definition (smaller number means higher priority).
    # A higher priority match overrides a lower priority overlapping match.
    PATTERN_PRIORITY = {
        'datetime': 1,       # Most specific date/time format
        'id_card': 2,        # ID number (18 digits with checksum, most specific)
        'passport': 2,
        'military_id': 2,
        'hk_macau_pass': 2,
        'taiwan_pass': 2,
        'credit_code': 2,    # Unified social credit code (18 chars with checksum)
        'case_number': 3,
        'contract_number': 3,
        'invoice_number': 3,
        'phone': 3,
        'toll_free': 3,
        'fax': 3,
        'email': 3,
        'website': 3,
        'mac_address': 3,
        'ip_address': 3,
        'license_plate': 3,
        'vin': 3,
        'amount': 3,
        'price': 3,
        'org_code': 3,
        'date': 4,
        'time': 4,
        'bank_account': 5,   # 16-19 digits, easy to mismatch
        'tax_number': 6,     # 15-20 digits, broadest
        'social_account': 2,  # Social account (QQ / WeChat)
        'full_address': 2,    # Full address has high priority to avoid being split by submatches
        'property_cert': 2,  # Property certificate is more specific than case_number, claim it first
        'permit_number': 3,
        'house_number': 7,
        'postal_code': 8,    # 6 digits, easiest to mismatch
        'patent_number': 3,
        'document_number': 3,
        'project_name': 5,   # Project name is easy to mismatch, slightly lower priority
    }

    def __init__(self):
        # All supported regex patterns.
        # Order matters: match more specific patterns first to avoid partial matches.
        self.patterns = {
            # ========== ID documents ==========
            # ID number (18 digits, with checksum)
            'id_card': r'(?<!\d)[1-9]\d{5}(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)',

            # Passport number (PRC standard E/G+8 / HK-Macau-Taiwan P+7 / H+8 / M+7 / new two-letter prefixes like EM / EH / EJ + 7 digits)
            'passport': r'(?<![A-Za-z0-9])(?:[EeGg]\d{8}|[Pp]\d{7}|[Hh]\d{8}|[Mm]\d{7}|E[A-Z]\d{7})(?![A-Za-z0-9])',

            # HK/Macau permit
            'hk_macau_pass': r'(?<![A-Za-z0-9])[WwCc]\d{8}(?![A-Za-z0-9])',

            # Taiwan permit
            'taiwan_pass': r'(?<![A-Za-z0-9])[Tt]\d{8}(?![A-Za-z0-9])',

            # Military ID
            'military_id': r'(?<![A-Za-z0-9])[军士官兵]\s?字\s?第\s?\d{4,8}\s?号(?![A-Za-z0-9])',

            # ========== Companies / institutions ==========
            # Unified social credit code (18 chars)
            'credit_code': r'(?<![0-9A-HJ-NPQRTUWXY])[0-9A-HJ-NPQRTUWXY]{2}\d{6}[0-9A-HJ-NPQRTUWXY]{10}(?![0-9A-HJ-NPQRTUWXY])',

            # Org code
            'org_code': r'(?<![0-9A-HJ-NPQRTUWXY])[0-9A-HJ-NPQRTUWXY]{8}-[0-9A-HJ-NPQRTUWXY](?![0-9A-HJ-NPQRTUWXY])',

            # Tax registration number
            'tax_number': r'(?<!\d)\d{15,20}(?!\d)',

            # ========== Cases / contracts ==========
            # Case number (strict match: year + court code + case type + number + 号)
            # Supports OCR bracket variants: ()（）〈〉《》﹝﹞〔〕
            'case_number': r'[\(（〈《﹝〔]\s*\d{4}\s*[\)）〉》﹞〕]\s*[\u4e00-\u9fa5A-Za-z0-9#\s]{1,25}号',

            # Contract number
            'contract_number': r'(?:合同编号|协议编号|Contract[-\s]?No)[：:.]\s*[A-Za-z0-9\-_]{6,30}',

            # Invoice number
            'invoice_number': r'(?:发票号码|发票代码)[：:.]\s*\d{8,20}',

            # ========== Contact details ==========
            # Mobile number (11 digits, starts with 1)
            'phone': r'(?<!\d)1[3-9]\d{9}(?![0-9A-Za-z])',

            # Landline / fax
            'fax': r'(?<!\d)(?:0\d{2,3}[- ]?\d{7,8}|\(0\d{2,3}\)\d{7,8})(?!\d)',

            # 400/800 toll-free number
            'toll_free': r'(?<!\d)[48]00[- ]?\d{3}[- ]?\d{4}(?!\d)',

            # Email
            'email': r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',

            # Website / URL
            'website': r'https?://[^\s<>"{}|\\^`\[\]））、。，；]+|(?<![A-Za-z0-9.])www\.[A-Za-z0-9][-A-Za-z0-9.]*\.[A-Za-z]{2,}(?:/[^\s<>"{}|\\^`\[\]））、。，；]*)?',

            # ========== Social accounts ==========
            # QQ ID / WeChat ID / Weibo ID / VX abbreviation
            # WeChat: '微信号: abc-123' 'wechat: john_doe' 'VX：xxxxxx', must start with a letter
            # QQ: 'QQ：12345' 'Q号: 12345', not inside a word (avoid 'QQA' mismatch)
            # Weibo: '微博: xxx' 'weibo: xxx'
            'social_account': (
                r'(?i)(?:微信号?|wechat|VX|微博号?|weibo)[\s:：]*[a-zA-Z][a-zA-Z0-9_\-]{4,19}'
                r'|(?<!\w)(?i:QQ号码?|QQ号|Q号|QQ)[\s:：]*[1-9]\d{4,9}(?!\d)'
            ),

            # ========== Network identifiers ==========
            # IP address
            'ip_address': r'(?<!\d)(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)(?!\d)',

            # MAC address
            'mac_address': r'(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}',

            # ========== Financial ==========
            # Bank card number (16-19 digit standard card number + context-sensitive "account:digits" including 8-15 digit short accounts)
            'bank_account': (
                r'(?<!\d)\d{16,19}(?!\d)'
                r'|(?:账号|账户|帐号|帐户|户口号码|户口號碼|银行账号|银行账户|收款账号)[：:.\s]*\d{8,19}'
            ),

            # Amount (RMB) - covers Arabic numerals and Chinese uppercase numerals
            'amount': (
                # ¥ / 人民币 / ￥ prefix + any number of digits (covers '¥20800000.00 元' without thousands separators)
                # 元 suffix optional: '¥1234.56' also matches
                r'(?:¥|人民币|￥)\s*\d{1,3}(?:[,，]\d{3})+(?:\.\d{1,2})?\s*(?:元|万元|亿元)?'
                r'|(?:¥|人民币|￥)\s*\d+(?:\.\d{1,2})?\s*(?:元|万元|亿元)?'
                # With thousands grouping: 1,234,567.89 元
                r'|(?<![,，\d.])\d{1,3}(?:[,，]\d{3})+(?:\.\d{1,2})?\s*(?:元|万元|亿元)'
                # Integer/decimal without thousands separator: 3799.2 元; the dot in the lookbehind prevents capturing a decimal tail
                r'|(?<![,，\d.])\d+(?:\.\d{1,2})?\s*(?:元|万元|亿元)'
                # Chinese uppercase numerals: include "零" (so "贰仟零捌拾万元整" is not cut off)
                r'|[零壹贰叁肆伍陆柒捌玖拾佰仟万亿]+[元圆][整正]?(?:[零壹贰叁肆伍陆柒捌玖拾]+[角分])*'
            ),

            # Other currency amounts (covers more currencies)
            'price': r'(?:USD|EUR|GBP|HKD|JPY|CNY|RMB|AUD|CAD|CHF|US\$|€|£|HK\$)\s*[\d,]+\.?\d*',

            # ========== Vehicles ==========
            # License plate
            'license_plate': r'[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼][A-Z][A-Z0-9]{4,5}[A-Z0-9挂学警港澳]?',

            # Vehicle identification number (VIN)
            'vin': r'(?<![A-HJ-NPR-Z0-9])[A-HJ-NPR-Z0-9]{17}(?![A-HJ-NPR-Z0-9])',

            # ========== Date / time ==========
            # Date (multiple formats)
            'date': r'\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日号]?|\d{4}年\d{1,2}月\d{1,2}日',

            # Time
            'time': r'\d{1,2}:\d{2}(?::\d{2})?|\d{1,2}时\d{1,2}分\d{1,2}秒?',

            # Date / time
            'datetime': r'\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日号\s]\s*\d{1,2}:\d{2}(?::\d{2})?',

            # ========== Addresses ==========
            # Full address (province/city/district/county/town/street + building/road/place description)
            'full_address': r'[\u4e00-\u9fa5]{2,10}(?:省|市|区|县|镇|街道)[\u4e00-\u9fa5\d]{2,50}(?:层|楼|室|栋|幢|单元|\d号|苑|园|城|座|铺|店|馆|厅|堂|坊|府|邸|庄|寓|舍|宅|村|组|路|街|巷|弄|里|胡同|大道|公路|大街|小区|花园|工业区|产业园|商务中心|\d{2,5})(?![\u4e00-\u9fa5\d%％股权])',

            # Postal code
            'postal_code': r'(?<!\d)\d{6}(?!\d)',

            # House number (单元/弄/栋/座/楼/室; note that 单元 is two chars and cannot go inside the character class)
            'house_number': r'\d+(?:弄|单元|号楼|号院|号室|栋|座|楼|室)(?:-\d+)?',

            # ========== Certificate / document numbers ==========
            # Property certificate number / real estate ownership certificate number
            # Old style: 深房地字第 XXXXX 号, FH XXXXX 号
            # New style: 粤(2024)深圳市不动产权第 0123456 号
            'property_cert': (
                r'(?:[\u4e00-\u9fa5]{1,4}房地字第|FH)\s*\d{5,15}\s*号?'
                # 不动产权第 N 号: optionally prefixed by province/municipality/district/(year) combinations
                r'|(?:[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼])?'
                r'\s*(?:[\(（]\s*\d{4}\s*[\)）])?\s*[\u4e00-\u9fa5]{2,12}'
                r'\s*不动产权第\s*[A-Za-z0-9\s]{1,15}\s*号'
            ),

            # General certificate / approval number (XX字 NNN 号, XX字第 NNN 号)
            'permit_number': r'[\u4e00-\u9fa5]{2,8}字\s*(?:第\s*)?\d{2,15}\s*号',

            # ========== Patent / trademark / copyright numbers ==========
            # Patent / trademark / copyright application number (includes international patent office codes)
            'patent_number': r'(?:专利|商标|著作权)(?:申请|注册|登记)号[：:]\s*[A-Z0-9.]+|(?:CN|US|EP|JP|WO|KR|GB|DE|FR|CA|AU)\d{4,}[A-Z]?\d?',

            # Contract / document number (extended: agreement number, letter number, etc.)
            'document_number': r'(?:文件编号|文件号|函件编号|协议号|编号)[：:.]\s*[A-Za-z0-9\-_]{4,30}',

            # ========== Project names ==========
            # Project / engineering / system / platform name
            'project_name': r'([\u4e00-\u9fa5]{2,10}(?:项目|工程|系统|平台|计划))(?![\u4e00-\u9fa5])',
        }

        # English labels for the pattern types
        self.type_names = {
            'id_card': 'ID number',
            'passport': 'Passport no.',
            'hk_macau_pass': 'HK/Macau permit',
            'taiwan_pass': 'Taiwan permit',
            'military_id': 'Military ID',
            'credit_code': 'Unified social credit code',
            'org_code': 'Org code',
            'tax_number': 'Tax registration no.',
            'case_number': 'Case number',
            'contract_number': 'Contract no.',
            'invoice_number': 'Invoice no.',
            'phone': 'Mobile number',
            'fax': 'Landline / fax',
            'toll_free': '400/800 hotline',
            'email': 'Email',
            'website': 'URL',
            'ip_address': 'IP address',
            'mac_address': 'MAC address',
            'bank_account': 'Bank card no.',
            'amount': 'Amount',
            'price': 'Price',
            'license_plate': 'License plate',
            'vin': 'VIN',
            'date': 'Date',
            'time': 'Time',
            'datetime': 'Date / time',
            'postal_code': 'Postal code',
            'house_number': 'House number',
            'social_account': 'QQ / WeChat ID',
            'full_address': 'Full address',
            'property_cert': 'Property certificate no.',
            'permit_number': 'Permit / approval no.',
            'patent_number': 'Patent / trademark no.',
            'document_number': 'Document no.',
            'project_name': 'Project name',
        }

    def detect(self, text: str, only_types: List[str] = None, exclude_types: List[str] = None) -> List[Tuple[str, str, int]]:
        """
        Detect sensitive data in text.

        Args:
            text: Input text
            only_types: Detect only the specified types
            exclude_types: Exclude the specified types

        Returns:
            List [(matched text, type, start position), ...]
        """
        raw_results = []

        for pattern_name, pattern in self.patterns.items():
            if only_types and pattern_name not in only_types:
                continue
            if exclude_types and pattern_name in exclude_types:
                continue

            for match in re.finditer(pattern, text):
                match_text = match.group(0)
                start_pos = match.start()
                priority = self.PATTERN_PRIORITY.get(pattern_name, 99)
                raw_results.append((match_text, pattern_name, start_pos, priority))

        # Sort by priority (higher priority handled first); within the same priority, by match length descending
        raw_results.sort(key=lambda x: (x[3], -len(x[0])))

        # Resolve overlaps: a higher priority match overrides a lower priority one
        filtered = []
        occupied = []  # [(start, end), ...]

        for match_text, pattern_name, start_pos, priority in raw_results:
            end_pos = start_pos + len(match_text)

            # Check whether it overlaps an already confirmed higher priority match
            overlap = False
            for occ_start, occ_end in occupied:
                if start_pos < occ_end and end_pos > occ_start:
                    overlap = True
                    break

            if not overlap:
                # Address post-processing: strip non-address prefixes like "住所" / "地址"
                if pattern_name == 'full_address':
                    for prefix_word in ('住所地', '住所', '地址'):
                        if match_text.startswith(prefix_word):
                            match_text = match_text[len(prefix_word):]
                            start_pos += len(prefix_word)
                            break
                    # Exclude court / procuratorate names (not addresses)
                    if match_text.endswith(('人民法院', '人民检察院', '中级人民法院', '高级人民法院')):
                        continue
                    # Exclude legal document / regulation references (not addresses)
                    legal_doc_terms = ('证券交易所', '交易所', '监管指引', '管理办法', '管理条例', '实施细则')
                    if any(term in match_text for term in legal_doc_terms):
                        continue
                    # Exclude mismatches containing "上市" (a verb: to go public), not the "市" of a place name
                    if '上市' in match_text:
                        continue
                # Postal code post-processing: exclude securities codes / bond codes, etc.
                if pattern_name == 'postal_code':
                    context_before = text[max(0, start_pos - 30):start_pos]
                    # Check after removing line breaks, to handle cross-line cases like "股票代\n码"
                    context_before_noline = context_before.replace('\n', '').replace('\r', '')
                    securities_keywords = (
                        '证券代码', '债券代码', '股票代码', '基金代码',
                        '代码：', '代码:', '代码为', '代码\u201c', '代码"',
                        '代码 ', '码为', '证券简称', '股票简称',
                    )
                    if any(kw in context_before_noline for kw in securities_keywords):
                        continue
                    # Exclude amount digits mismatched as a postal code (followed by 万元/元/亿元)
                    context_after = text[end_pos:min(len(text), end_pos + 5)]
                    if any(kw in context_after for kw in ('万元', '元', '亿元')):
                        continue
                    # Exclude digits inside an arithmetic expression (followed by multiply, plus/minus, or 月/天/年/日)
                    ctx_after_strip = context_after.strip()
                    if ctx_after_strip and ctx_after_strip[0] in 'x×*+-' :
                        continue
                    if any(ctx_after_strip.startswith(kw) for kw in ('月', '天', '年', '日', 'x', '×')):
                        continue
                    # Exclude digits preceded by an arithmetic or equals sign (middle of an expression)
                    ctx_before_1 = text[max(0, start_pos - 3):start_pos].strip()
                    if ctx_before_1 and ctx_before_1[-1] in '+-x×*=(（':
                        continue
                    # Exclude common stock code prefixes (specific number ranges on the Shanghai/Shenzhen exchanges)
                    # Only exclude when there is no postal-code keyword nearby
                    stock_prefixes = ('600', '601', '603', '605', '688', '689',
                                      '000', '001', '002', '003', '300', '301')
                    if match_text.startswith(stock_prefixes):
                        postal_ctx = text[max(0, start_pos - 20):min(len(text), end_pos + 10)]
                        postal_ctx_clean = postal_ctx.replace('\n', '').replace('\r', '')
                        postal_kws = ('邮编', '邮政编码', '邮政', '邮区')
                        if not any(kw in postal_ctx_clean for kw in postal_kws):
                            continue
                # Amount post-processing: digit boundary check to prevent partial digits being truncated into a match
                if pattern_name in ('amount', 'price'):
                    # Check whether a digit is immediately before the match (partial digits truncated)
                    if start_pos > 0 and text[start_pos - 1].isdigit():
                        continue
                    # Check whether a digit or hyphen is immediately after the match.
                    # Note: when the match ends with an explicit suffix like "元/圆/万元/亿元" there is already a clear amount boundary,
                    # so a following digit belongs to the next amount (adjacent amounts stick together in OCR tables) and should not be skipped.
                    if end_pos < len(text):
                        next_char = text[end_pos]
                        ends_with_yuan_suffix = match_text.endswith(
                            ('元', '圆', '万元', '亿元', '元整', '圆整')
                        )
                        if (next_char.isdigit() or next_char == '-') and not ends_with_yuan_suffix:
                            continue
                    # Exclude statutory references like "第X条/款/项/章/节" (e.g. "第2条" mistaken for "2元")
                    ctx_before = text[max(0, start_pos - 10):start_pos]
                    if any(kw in ctx_before for kw in ('第', '本条', '上条', '前条', '下条')):
                        # "第" appears within 4 chars before, and "元" immediately follows
                        nearby = text[max(0, start_pos - 4):end_pos + 2]
                        if '第' in nearby and '元' in match_text:
                            continue
                # Project name post-processing: exclude overly generic project names
                if pattern_name == 'project_name':
                    # Use the captured group text (drop lookbehind/lookahead)
                    captured = match.group(1) if match.lastindex and match.lastindex >= 1 else match_text
                    generic_projects = {
                        '测试项目', '示例项目', '工程项目', '系统项目', '本项目', '该项目',
                        '其他项目', '相关项目', '涉案项目', '目标项目', '拟建项目',
                        '建设项目', '投资项目', '合作项目', '试点项目', '重点项目',
                        '改造工程', '建设工程', '施工工程', '本工程', '该工程',
                        '管理系统', '信息系统', '业务系统', '本系统', '该系统', '操作系统',
                        '交易平台', '服务平台', '管理平台', '本平台', '该平台',
                        '网络投票平台', '投票平台', '交易系统', '信息披露平台',
                        '行动计划', '工作计划', '实施计划', '本计划', '该计划',
                        '加固改造工程',
                    }
                    if captured in generic_projects:
                        continue
                    # Exclude cross-line matches
                    if '\n' in match_text:
                        continue
                    # Exclude fragments containing a company/institution suffix (part of a company name)
                    org_keywords = ('有限公司', '有限责任', '股份', '律师事务所', '会计师', '银行')
                    cap_start = match.start(1) if match.lastindex and match.lastindex >= 1 else start_pos
                    context_around = text[max(0, cap_start - 20):min(len(text), cap_start + len(captured) + 20)]
                    if any(kw in context_around for kw in org_keywords):
                        # If the project name is wrapped inside a company name, skip
                        for kw in org_keywords:
                            if kw in context_around:
                                kw_pos = context_around.find(kw)
                                proj_pos = context_around.find(captured)
                                # If there is no clear separator (period, comma, etc.) between the company suffix and the project name, it is continuous text
                                between = context_around[min(proj_pos + len(captured), kw_pos):max(proj_pos, kw_pos)]
                                if between and not any(c in between for c in '，。；、\n'):
                                    continue
                    # Use the captured group as the actual matched text
                    match_text = captured
                    start_pos = match.start(1) if match.lastindex and match.lastindex >= 1 else start_pos
                    end_pos = start_pos + len(match_text)
                # Patent number post-processing: exclude matches that are too short or clearly not patents
                if pattern_name == 'patent_number':
                    if len(match_text) < 6:
                        continue
                # House number post-processing: exclude document numbers like "指导案例N号" / "检例第N号"
                if pattern_name == 'house_number':
                    ctx_before = text[max(0, start_pos - 15):start_pos]
                    doc_num_kws = ('指导案例', '检例', '检例第', '案例第', '第', '公告', '通知', '决定', '规定', '条')
                    if any(kw in ctx_before for kw in doc_num_kws):
                        continue
                # Passport number post-processing: the P prefix easily mismatches document/reference numbers
                if pattern_name == 'passport' and match_text[0] in 'Pp':
                    passport_ctx = text[max(0, start_pos - 50):min(len(text), end_pos + 50)]
                    passport_kws = ('护照', '出入境', '签证', 'passport', '证件号', '旅行证件')
                    if not any(kw in passport_ctx.lower() for kw in passport_kws):
                        continue
                filtered.append((match_text, pattern_name, start_pos))
                occupied.append((start_pos, end_pos))

        # Sort by position
        filtered.sort(key=lambda x: x[2])
        return filtered

    def get_all_types(self) -> Dict[str, str]:
        """Return all supported types and their labels."""
        return self.type_names.copy()
