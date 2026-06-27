"""
Custom Entity Detector
Custom entity detector. Detects person names, company names, addresses, and more.

Supports:
  1. Manually added custom entities (high precision)
  2. Automatic detection: context-keyword-based person name recognition plus
     company/institution name pattern matching
"""

import re
from typing import Dict, List, Tuple, Set


# Common Chinese surnames (top 120+ from the Hundred Family Surnames). Detection data.
COMMON_SURNAMES = set(
    '赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜'
    '戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳酆鲍史唐'
    '费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟平黄'
    '和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴宋茅庞熊纪舒屈项祝董梁杜'
    '阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡凌霍虞'
    '饶万支柯昝管卢莫经房裘缪干解应宗丁宣邓贲郁单杭洪包诸左石崔吉钮龚程'
    '嵇邢滑裴陆荣翁荀羊甄家封芮储靳汲邴糜松井富乌焦巴弓牧隗山谷车侯宓'
    '蓬全郗班仰秋仲伊宫宁仇栾暴甘钭厉戎祖武符刘景詹束龙叶幸司韶郜黎蓟'
    '薄印宿白怀蒲邰从鄂索咸籍赖卓蔺屠蒙池乔阴胥能苍双闻莘党翟谭贡劳逄'
    '姬申扶堵冉宰郦雍璩桑桂濮牛寿通边扈燕冀'
)

# Compound (two-character) surnames. Detection data.
COMPOUND_SURNAMES = {
    '欧阳', '太史', '端木', '上官', '司马', '东方', '独孤', '南宫',
    '万俟', '闻人', '夏侯', '诸葛', '尉迟', '公羊', '赫连', '澹台',
    '皇甫', '宗政', '濮阳', '公冶', '太叔', '申屠', '公孙', '慕容',
    '仲孙', '钟离', '长孙', '宇文', '司徒', '鲜于', '司空', '令狐',
}

# Context keywords that flag a person name in legal documents. Detection data.
PERSON_CONTEXT_KEYWORDS = [
    '原告', '被告', '被告人', '申请人', '被申请人', '上诉人', '被上诉人',
    '再审申请人', '再审被申请人', '第三人',
    '犯罪嫌疑人', '嫌疑人', '被执行人', '申请执行人', '被申请执行人',
    '委托代理人', '委托诉讼代理人', '诉讼代理人', '辩护人', '代理人',
    '法定代表人', '负责人', '执行人', '实际控制人', '控股股东', '经营者',
    '审判长', '审判员', '代理审判员', '书记员', '陪审员', '人民陪审员',
    '法官助理', '主审法官', '承办法官', '审判员',
    '证人', '鉴定人', '翻译人员',
    '执行董事', '监事', '总经理', '经理', '董事长', '董事',
    '经办人', '联系人', '担保人', '保证人', '借款人', '贷款人',
    '出租人', '承租人', '买受人', '出卖人', '委托人', '受托人',
    '甲方', '乙方', '丙方', '丁方',
    '收款人', '付款人', '投保人', '被保险人', '受益人',
    '保荐代表人', '项目协办人',
    '独立董事', '非独立董事',
    '执行事务合伙人', '合伙人', '有限合伙人', '普通合伙人',
    '财务总监', '财务负责人', '总会计师', '副总经理', '副总裁',
    '董事会秘书', '证券事务代表',
    '注册会计师', '签字会计师', '签字注册会计师',
]

# Institution name suffixes. Detection data.
ORG_SUFFIXES = (
    '有限公司', '有限责任公司', '股份有限公司', '股份公司',
    '集团有限公司', '集团公司', '集团',
    '律师事务所', '会计师事务所', '公证处',
    '人民法院', '人民检察院', '人民政府',
    '公安局', '派出所', '管理局', '监督局',
    '委员会', '管理委员会', '工作委员会',
    '居委会', '村委会', '街道办事处', '办事处',
    '中心', '研究院', '研究所', '实验室',
    '大学', '学院', '中学', '小学', '幼儿园',
    '医院', '卫生院', '诊所',
    '银行', '信用社', '基金会', '协会', '商会', '学会',
    # Media / publishing
    '广播电视台', '电视台', '广播电台', '广播台', '电台', '报社', '出版社', '杂志社', '通讯社',
    # Healthcare / retail
    '大药房', '药房', '药店', '连锁药店', '医药公司',
    # Partnership enterprises
    '合伙企业', '有限合伙', '普通合伙',
    # Industry short-form suffixes (common in company abbreviations)
    '药业', '置业', '实业', '物业',
)

# International company suffixes (English). Detection data.
INTL_ORG_SUFFIXES = (
    'Company', 'Co.', 'Corporation', 'Corp.', 'Corp',
    'Limited', 'Ltd.', 'Ltd',
    'LLC', 'L.L.C.', 'Inc.', 'Inc',
    'GmbH', 'AG', 'S.A.', 'S.A',
    'PLC', 'Plc', 'LLP', 'L.P.',
    'Pte. Ltd.', 'Pty Ltd',
    'K.K.', 'B.V.', 'N.V.',
)

# Court name pattern. Detection data.
COURT_PATTERN = re.compile(
    r'[\u4e00-\u9fa5]{2,10}(?:人民法院|仲裁委员会|仲裁院)'
)


class EntityDetector:
    """Custom entity detector. Supports manual entries and automatic detection."""

    # Generic role words that should not be treated as entities when used as abbreviations. Detection data.
    GENERIC_ABBREVIATIONS = {
        '公司', '保荐人', '原告', '被告', '申请人', '被申请人',
        '甲方', '乙方', '丙方', '丁方', '上诉人', '被上诉人',
        '出借人', '借款人', '出卖人', '买受人', '承租人', '出租人',
        '委托人', '受托人', '代理人', '目标公司',
        '发行人', '主承销商', '联席主承销商',
        # Generic role words in guarantee / construction contracts
        '业主', '承包商', '分包商', '发包方', '发包人', '承包人',
        '保证人', '担保人', '债权人', '债务人', '抵押人', '抵押权人',
        '质押人', '质权人', '受益人', '受让人', '让与人', '转让方', '受让方',
        '卖方', '买方', '出租方', '承租方', '业主方', '工程方', '客户',
    }

    def __init__(self):
        self.entities = {}
        self._auto_detect_enabled = True
        self.abbreviation_map = {}  # abbreviation -> full name

    def add_entity(self, entity_type: str, name: str):
        """
        Add a single entity.

        Args:
            entity_type: Entity type (person, company, address, etc.)
            name: Entity name
        """
        if entity_type not in self.entities:
            self.entities[entity_type] = []
        if name not in self.entities[entity_type]:
            self.entities[entity_type].append(name)

    def add_entities(self, entities: List[Dict]):
        """
        Add multiple entities at once.

        Args:
            entities: List of entities, e.g. [{"type": "person", "name": "张三"}, ...]
        """
        for entity in entities:
            entity_type = entity.get('type', 'unknown')
            name = entity.get('name', '')
            if name:
                self.add_entity(entity_type, name)

    def set_entities(self, entities: List[Dict]):
        """
        Set entities (replaces existing ones).

        Args:
            entities: List of entities
        """
        self.entities = {}
        self.add_entities(entities)

    def clear(self):
        """Clear all entities."""
        self.entities = {}

    def enable_auto_detect(self, enabled: bool = True):
        """Enable or disable automatic detection."""
        self._auto_detect_enabled = enabled

    def detect(self, text: str, only_types: List[str] = None, exclude_types: List[str] = None) -> List[Tuple[str, str, int]]:
        """
        Detect custom entities in the text.

        Args:
            text: Input text
            only_types: Detect only the specified types
            exclude_types: Exclude the specified types

        Returns:
            List of [(entity text, type, start position), ...]
        """
        # Merge manual entities with automatically detected ones
        all_entities_to_find = []

        # 1. Manually added entities
        for entity_type, names in self.entities.items():
            if only_types and entity_type not in only_types:
                continue
            if exclude_types and entity_type in exclude_types:
                continue
            for name in names:
                all_entities_to_find.append((name, entity_type))

        # 2. Automatically detected entities
        if self._auto_detect_enabled:
            auto_entities = self.auto_detect(text, only_types, exclude_types)
            for name, entity_type in auto_entities:
                # Avoid duplicating manual entities
                if not any(n == name and t == entity_type for n, t in all_entities_to_find):
                    all_entities_to_find.append((name, entity_type))

        # Sort by length descending so longer entities match first
        all_entities_to_find.sort(key=lambda x: len(x[0]), reverse=True)

        # Find every occurrence
        results = []
        for name, entity_type in all_entities_to_find:
            search_start = 0
            while True:
                pos = text.find(name, search_start)
                if pos == -1:
                    break

                # Check whether a longer entity already covers this position
                overlap = False
                for res in results:
                    existing_pos = res[2]
                    existing_len = res[3]
                    if existing_pos <= pos < existing_pos + existing_len:
                        overlap = True
                        break
                    if pos <= existing_pos < pos + len(name):
                        overlap = True
                        break

                if not overlap:
                    results.append((name, entity_type, pos, len(name)))

                search_start = pos + len(name)

        # Second pass for person names with a "spaced variant": handles cases where PDF
        # layout inserts spaces between characters (e.g. a three-character name split as
        # "X  X  X"). These positions are not found by a direct text.find.
        person_names = [
            (name, etype) for name, etype in all_entities_to_find
            if etype == 'person' and 2 <= len(name) <= 4
        ]
        existing_spans = [(p, p + length) for _, _, p, length in results]
        for name, etype in person_names:
            spaced_re = re.compile(r'\s*'.join(re.escape(c) for c in name))
            for m in spaced_re.finditer(text):
                pos, end = m.start(), m.end()
                # Skip positions already covered
                if any(pos < oe and end > os_ for os_, oe in existing_spans):
                    continue
                # Validate surrounding characters to avoid false matches
                # (a name variant should not be embedded inside a longer CJK entity)
                results.append((m.group(0), etype, pos, end - pos))
                existing_spans.append((pos, end))

        # Convert to a uniform format and sort by position
        final_results = [(name, etype, pos) for name, etype, pos, _ in results]
        final_results.sort(key=lambda x: x[2])
        return final_results

    def auto_detect(self, text: str, only_types: List[str] = None, exclude_types: List[str] = None) -> List[Tuple[str, str]]:
        """
        Automatically detect entities such as person names, company names, and court names.

        Args:
            text: Input text
            only_types: Detect only the specified types
            exclude_types: Exclude the specified types

        Returns:
            List of [(entity name, entity type), ...] (deduplicated)
        """
        detected: Set[Tuple[str, str]] = set()

        # ========== 1. Company / institution name detection ==========
        if self._should_detect('company', only_types, exclude_types):
            for suffix in ORG_SUFFIXES:
                pattern = re.compile(
                    rf'([\u4e00-\u9fa5]{{2,10}}(?:[（(][\u4e00-\u9fa5]+[）)])?[\u4e00-\u9fa5]{{0,4}}{re.escape(suffix)})'
                )
                for match in pattern.finditer(text):
                    raw_name = match.group(1)
                    # Clean up: strip prefixes that clearly do not belong to the institution name
                    name = self._clean_org_name(raw_name, suffix)
                    if not name:
                        continue
                    prefix = name.replace(suffix, '')
                    # Exclude generic institution names that are legal terms of art
                    non_org = {'目标公司', '关联公司', '合资公司', '控股公司', '上市公司', '拟设公司',
                               '本公司', '该公司', '分公司', '子公司', '总公司', '新公司', '老公司', '原公司',
                               '全资子公司', '参股公司', '持股公司',
                               '股份有限公司', '有限责任公司', '国有全资公司',
                               '公开发行证券公司', '发行证券公司', '延长公司'}
                    if name in non_org:
                        continue
                    # Exclude fragments that are just an industry word plus a suffix
                    # (e.g. "科技有限公司", "设备有限公司")
                    generic_prefixes = {
                        '科技', '设备', '技术', '工程', '服务', '贸易', '商贸', '电子',
                        '信息', '网络', '文化', '传媒', '教育', '餐饮', '物流', '建材',
                        '装饰', '广告', '咨询', '食品', '材料', '环保', '能源', '医药',
                        '保险',
                    }
                    if prefix in generic_prefixes:
                        continue
                    # Extension: if the prefix is an industry word after stripping a connector
                    # such as 股份/实业/控股, exclude it too. Handles truncated fragments
                    # like "电子股份有限公司".
                    stripped_prefix = prefix
                    for connector in ('股份', '实业', '控股', '产业'):
                        if stripped_prefix.endswith(connector):
                            stripped_prefix = stripped_prefix[:-len(connector)]
                            break
                    if stripped_prefix in generic_prefixes:
                        continue
                    # Exclude department-style "中心" (not a standalone entity)
                    if suffix == '中心':
                        department_keywords = {
                            '业务', '技术', '技术开发', '财务', '行政', '人力资源',
                            '研发', '销售', '市场', '客服', '运维', '数据',
                            '先进制造业', '结算', '清算', '运营', '投资管理',
                            '资产管理', '制造业', '综合管理', '管理',
                        }
                        if prefix in department_keywords:
                            continue
                        # Exclude building names like "XX中心大厦/大楼"
                        match_end = match.end()
                        after_text = text[match_end:match_end + 4].replace('\n', '').replace(' ', '')
                        if any(after_text.startswith(bs) for bs in ('大厦', '大楼', '广场')):
                            continue
                    # Exclude fragments whose prefix ends in a verb/preposition (e.g. "股权划转至公司")
                    verb_endings = '至到给向为是由将把被让与和或及'
                    if prefix and prefix[-1] in verb_endings:
                        continue
                    # Exclude OCR-truncated fragments: common truncated insurance / asset-management names
                    # e.g. "寿保险有限公司" (should be "XX人寿保险有限公司")
                    # e.g. "民财产保险股份有限公司" (should be "人民财产保险股份有限公司")
                    if prefix and prefix[0] == '寿' and any(kw in name for kw in ('保险', '资产管理')):
                        continue
                    if prefix and prefix[0] == '民' and '保险' in name and prefix[:2] != '民生':
                        continue
                    if len(prefix) >= 2:
                        entity_type = 'company'
                        if '律师事务所' in suffix:
                            entity_type = 'law_firm'
                        elif '法院' in suffix or '检察院' in suffix:
                            entity_type = 'court'
                            # Validate the court name prefix: reject verb phrases / statutory citations
                            court_prefix = name.replace(suffix, '')
                            # Starts with a verb such as 不服/服从/维持
                            if court_prefix and court_prefix[0] in '服维尊按依循和与或及从对由':
                                continue
                            # Statutory citation patterns: "第X条", "第一百七十七条", "第X审"
                            import re as _re
                            if _re.search(r'第[一二三四五六七八九十百千\d]+[条款项审]', court_prefix):
                                continue
                            # Short forms like "第二审人民法院" are generic, not a specific court
                            if court_prefix in ('第二审', '第一审', '第三审', '原审', '再审'):
                                continue
                        elif any(kw in suffix for kw in ('公安局', '管理局', '监督局', '委员会', '政府', '办事处', '派出所')):
                            entity_type = 'government'
                        elif any(kw in suffix for kw in ('大学', '学院', '中学', '小学', '幼儿园', '研究院', '研究所')):
                            # Exclude OCR fragments such as "号国家大学"
                            if prefix and prefix[0] in '号栋楼层室座':
                                continue
                            entity_type = 'institution'
                        elif any(kw in suffix for kw in ('医院', '卫生院', '诊所')):
                            entity_type = 'institution'
                        elif any(kw in suffix for kw in ('银行', '信用社')):
                            entity_type = 'bank_name'
                        # Extra validation for bank names: exclude false matches that are not bank names
                        if entity_type == 'bank_name':
                            bank_prefix = name.replace(suffix, '')
                            # A bank name prefix should contain a place name / brand word, not a verb phrase
                            bank_invalid_chars = set('并加算且又还要能会可的了过把将被让给调取查找扣冻结')
                            if any(c in bank_invalid_chars for c in bank_prefix):
                                continue
                            # Exclude prefixes containing institution words (e.g. "法院XX银行", "检察院XX银行")
                            inst_words = ('法院', '检察院', '派出所', '公安局', '政府', '委员会', '办公厅')
                            if any(iw in bank_prefix for iw in inst_words):
                                continue
                            # Exclude generic prefixes ("全国银行", "同期银行", "同业银行", "商业银行" are not specific banks)
                            generic_bank_prefixes = {
                                '全国', '全部', '全体', '同期', '同业', '商业', '部分',
                                '本国', '外国', '国内', '国外', '中外',
                                '同期全国', '中国境内', '我国', '本案',
                                '该', '本', '此',
                            }
                            if bank_prefix in generic_bank_prefixes:
                                continue
                            # Reject a generic word right before 银行 ("同期全国银行" -> 全国 is generic)
                            for gp in ('全国', '同期', '同业', '商业'):
                                if bank_prefix.endswith(gp) and len(bank_prefix) <= len(gp) + 2:
                                    bank_prefix = ''
                                    break
                            if not bank_prefix:
                                continue
                        # Filter out internal corporate committees (not government bodies)
                        if entity_type == 'government' and '委员会' in name:
                            corporate_keywords = (
                                '员工持股', '薪酬', '考核', '审计', '提名', '风控', '战略',
                                '经营', '技术', '独立董事', '董事会', '职工代表', '监事会',
                                '发行决策', '投资决策', '风险管理',
                            )
                            if any(kw in name for kw in corporate_keywords):
                                continue
                            # Exclude committee names that are too generic
                            generic_gov = {'管理委员会', '工作委员会', '监督委员会', '审判委员会'}
                            if name in generic_gov:
                                continue
                        detected.add((name, entity_type))

        # ========== 1.5 Short-form company name detection (XX公司, without "有限") ==========
        if self._should_detect('company', only_types, exclude_types):
            # Match short-form company names in context: 2-6 Chinese characters + "公司"
            # but exclude those already covered by a full company name (e.g. "XX有限公司")
            short_company_pattern = re.compile(
                r'([\u4e00-\u9fa5]{2,6}公司)(?!有限|股份|集团|律师|会计)'
            )
            for match in short_company_pattern.finditer(text):
                name = match.group(1)
                # Exclude names containing "有限" (handled by the full-suffix match)
                if '有限' in name:
                    continue
                # Exclude common non-company phrases
                non_company = {'本公司', '该公司', '分公司', '子公司', '总公司', '新公司', '老公司', '原公司',
                              '目标公司', '关联公司', '合资公司', '控股公司', '上市公司', '拟设公司',
                              '全资子公司', '参股公司', '持股公司',
                              '详见公司', '所在公司', '设立公司', '成立公司',
                              '解散公司', '触发公司', '吸收公司', '清算公司', '注销公司',
                              '全资公司', '托管公司', '代管公司', '国有全资公司',
                              '集团公司',
                              '大型保险公司', '相关子公司', '营管理公司',
                              '资本运营公司', '运营公司',
                              '资本投资运营公司', '国有资本运营公司',
                              '大型企业公司', '境内公司', '境外公司',
                              '参加公司', '加入公司', '经营公司'}
                if name in non_company:
                    continue
                # Exclude the generic "X子公司" (subsidiary references without "有限")
                if name.endswith('子公司') and '有限' not in name:
                    continue
                # Clean the prefix
                cleaned = self._clean_org_name(name, '公司')
                if cleaned in non_company:
                    continue
                # Exclude fragments starting with a generic word (e.g. "公司全资子公司")
                generic_starts = ('公司', '其公司', '的公司', '意公司')
                if cleaned and cleaned.startswith(generic_starts):
                    continue
                # Exclude generic phrasing ending in "上市公司"
                if cleaned and cleaned.endswith('上市公司'):
                    continue
                if cleaned and len(cleaned.replace('公司', '')) >= 2:
                    detected.add((cleaned, 'company'))

        # ========== 1.8 International company name detection (English suffixes) ==========
        if self._should_detect('company', only_types, exclude_types):
            for suffix in INTL_ORG_SUFFIXES:
                # Match: at least 2 words + suffix (allow internal commas, e.g. "Acme Legal Services, Inc.")
                escaped = re.escape(suffix)
                intl_pattern = re.compile(
                    rf'([A-Z][A-Za-z0-9&\-·.\',  ]+?\s*,?\s+{escaped})(?=[\s.。;；:：)）\n]|,\s+[a-z]|$)'
                )
                for match in intl_pattern.finditer(text):
                    name = match.group(1).strip()
                    # Exclude matches that are too short (need a reasonable name + suffix length)
                    name_part = name.replace(suffix, '').strip()
                    if len(name_part) < 2:
                        continue
                    # Exclude purely generic words
                    generic_intl = {'The Company', 'This Company', 'A Company', 'Said Company',
                                    'Target Company', 'Parent Company', 'Shell Company'}
                    if name in generic_intl:
                        continue
                    detected.add((name, 'company'))

        # ========== 2. Context-based person name detection ==========
        if self._should_detect('person', only_types, exclude_types):
            for keyword in PERSON_CONTEXT_KEYWORDS:
                # Pattern 1: keyword + separator + name (2-4 Chinese characters)
                # "原告：张三" "原告: 张三" "原告 张三"
                pattern_with_sep = re.compile(
                    rf'{re.escape(keyword)}[：:、\s]+\s*([\u4e00-\u9fa5]{{2,4}})(?=[，。、；：\s\n的了是为系先女男诉向不等因被涉（(教博士硕]|$)'
                )
                for match in pattern_with_sep.finditer(text):
                    candidate = match.group(1)
                    # Cross-line guard: skip if there is a newline between keyword and name
                    full_match = match.group(0)
                    sep_part = full_match[len(keyword):-len(candidate)]
                    if '\n' in sep_part and len(sep_part.strip()) == 0:
                        continue
                    if self._is_valid_name(candidate):
                        detected.add((candidate, 'person'))

                # Pattern 2: keyword directly followed by a name (no separator, stricter: 2-3 chars only)
                # "原告张三" "被告李四" "被告人刘某桂"
                pattern_no_sep = re.compile(
                    rf'{re.escape(keyword)}([\u4e00-\u9fa5]{{2,3}})(?=[，。、；：\s\n的了是为系先女男诉向不等因被涉犯（(教博士硕]|$)'
                )
                for match in pattern_no_sep.finditer(text):
                    candidate = match.group(1)
                    if self._is_valid_name(candidate):
                        detected.add((candidate, 'person'))

                # Pattern 2.5: keyword + 为/是/系 + name (2-4 chars)
                # "法定代表人为郑友妹" "实际控制人系张三"
                pattern_verb_sep = re.compile(
                    rf'{re.escape(keyword)}(?:为|是|系)([\u4e00-\u9fa5]{{2,4}})(?=[，。、；：\s\n先女男教博士硕（(]|$)'
                )
                for match in pattern_verb_sep.finditer(text):
                    candidate = match.group(1)
                    if self._is_valid_name(candidate):
                        detected.add((candidate, 'person'))

            # Pattern 3: name + 是/系/为 + legal role (reverse pattern)
            # "李娟是本案原告" "张三系被告" "王五为第三人"
            reverse_roles = [
                '原告', '被告', '上诉人', '被上诉人', '申请人', '被申请人',
                '第三人', '证人', '鉴定人', '担保人', '债权人', '债务人',
                '出借人', '借款人', '出卖人', '买受人', '承租人', '出租人',
                '委托人', '受托人', '代理人', '法定代表人', '实际控制人',
                '执行董事', '董事长', '董事', '监事', '总经理', '经理',
            ]
            reverse_roles_str = '|'.join(re.escape(r) for r in reverse_roles)
            reverse_pattern = re.compile(
                rf'([\u4e00-\u9fa5]{{2,4}})\s*(?:亦|也|又|均|都)?\s*(?:是本案|是|系|为)\s*(?:公司|本公司|目标公司|本案)?\s*(?:{reverse_roles_str})'
            )
            for match in reverse_pattern.finditer(text):
                candidate = match.group(1)
                # Strip a trailing adverb (e.g. "秦中根亦" -> "秦中根")
                while candidate and candidate[-1] in '亦也又均都':
                    candidate = candidate[:-1]
                if len(candidate) >= 2 and self._is_valid_name(candidate):
                    detected.add((candidate, 'person'))
                elif len(candidate) > 2:
                    # Greedy matching may swallow a prefix (e.g. "派郑友妹"); try trimming from the left
                    for trim in range(1, len(candidate) - 1):
                        trimmed = candidate[trim:]
                        if len(trimmed) >= 2 and self._is_valid_name(trimmed):
                            detected.add((trimmed, 'person'))
                            break

            # Pattern: name + parentheses + identity description
            # e.g. "张三（以下简称原告）"
            pattern = re.compile(
                r'([\u4e00-\u9fa5]{2,4})\s*[（(].*?(?:以下简称|以下称|简称).*?[）)]'
            )
            for match in pattern.finditer(text):
                candidate = match.group(1)
                if self._is_valid_name(candidate):
                    detected.add((candidate, 'person'))

            # Pattern: name in a signature / sign-off
            # e.g. "签名：张三" "签字人：李四"
            sign_pattern = re.compile(
                r'(?:签名|签字人?|落款)[：:]\s*([\u4e00-\u9fa5]{2,4})'
            )
            for match in sign_pattern.finditer(text):
                candidate = match.group(1)
                if self._is_valid_name(candidate):
                    detected.add((candidate, 'person'))

            # Pattern: judicial staff at the end of a judgment (both keyword and name may
            # carry spaces due to PDF layout).
            # e.g. "审  判  长   X  X  X"  "书  记  员   X  X  X"
            # The name part is anchored to end-of-line to avoid swallowing the leading
            # character of a role keyword on the next line.
            judicial_pattern = re.compile(
                r'(?:审\s*判\s*长|审\s*判\s*员|代\s*理\s*审\s*判\s*员|'
                r'书\s*记\s*员|陪\s*审\s*员|人\s*民\s*陪\s*审\s*员|'
                r'法\s*官\s*助\s*理|主\s*审\s*法\s*官|承\s*办\s*法\s*官|审\s*判\s*员|'
                r'仲\s*裁\s*员|首\s*席\s*仲\s*裁\s*员)'
                r'[：:\s]+'
                r'([一-龥](?:[ \t　]*[一-龥]){1,3})'
                r'[ \t　]*(?=[\n，。；,;.]|$)',
                re.MULTILINE
            )
            for match in judicial_pattern.finditer(text):
                raw = match.group(1)
                candidate = re.sub(r'\s+', '', raw)
                if 2 <= len(candidate) <= 4 and self._is_valid_name(candidate):
                    detected.add((candidate, 'person'))

            # Pattern: several names in a list + role suffix
            # "王晓琪和柳峰分别作为...的法定代表人" / "张三、李四、王五任董事"
            # Names are 2-4 chars; a lookahead prevents swallowing connectors like "分别/作为".
            # Connectors are 和/与/及/、/，, plus role words and verbs.
            # The lookahead requires the next character to be a connector / verb-start / punctuation
            # so connectors like "分别" are not absorbed into the end of a name.
            multi_name_role = re.compile(
                r'([一-龥]{2,4})(?=[、，,和与及分作担任为是系出\s的])'
                r'\s*[、，,和与及]\s*'
                r'([一-龥]{2,4})(?=[、，,和与及分作担任为是系出\s的])'
                r'(?:\s*[、，,和与及]\s*([一-龥]{2,4})(?=[、，,和与及分作担任为是系出\s的]))?'
                r'\s*(?:分别)?\s*(?:作为|担任|任|为|是|系|出任)'
                r'[^\n]{0,30}'
                r'(?:法定代表人|实际控制人|代表人|董事长|董事|监事|总经理|副总经理|经理'
                r'|股东|合伙人|代理人|签字人|签名人|证人|被告|原告|当事人)'
            )
            for match in multi_name_role.finditer(text):
                for grp_idx in (1, 2, 3):
                    if grp_idx > match.lastindex:
                        break
                    candidate = match.group(grp_idx)
                    if not candidate:
                        continue
                    # Greedy matching may absorb a trailing connector like "分别/作为/担任"; strip it
                    for suf in ('分别', '作为', '担任', '出任'):
                        if candidate.endswith(suf) and len(candidate) > len(suf) + 1:
                            candidate = candidate[:-len(suf)]
                            break
                    if 2 <= len(candidate) <= 4 and self._is_valid_name(candidate):
                        detected.add((candidate, 'person'))

            # Pattern: role + 为/是/系 + multiple names (separated by 、，和)
            # e.g. "原股东为宋明权、杨淑莉" "法定代表人为张三" "原告系李四、王五"
            role_to_names = re.compile(
                r'(?:法定代表人|实际控制人|代表人|原股东|现股东|控股股东|股东'
                r'|执行董事|董事长|董事|监事|总经理|副总经理|经理'
                r'|合伙人|代理人|证人|原告|被告|被告人|嫌疑人|被害人|当事人)'
                r'\s*(?:为|是|系)\s*'
                r'([一-龥]{2,4})'
                r'(?:\s*[、，,和与及]\s*([一-龥]{2,4}))?'
                r'(?:\s*[、，,和与及]\s*([一-龥]{2,4}))?'
                r'(?=[。，,；;\s\n)）]|$)'
            )
            for match in role_to_names.finditer(text):
                for grp_idx in (1, 2, 3):
                    if match.lastindex is None or grp_idx > match.lastindex:
                        break
                    candidate = match.group(grp_idx)
                    if candidate and 2 <= len(candidate) <= 4 and self._is_valid_name(candidate):
                        detected.add((candidate, 'person'))

            # Pattern: name + gender/age (common legal document format)
            # "姜妍，女，" "张三，男，1990年" "李四（男，"
            gender_patterns = [
                r'([\u4e00-\u9fa5]{2,4})[，,]\s*(?:男|女)\s*[，,]',
                r'([\u4e00-\u9fa5]{2,4})\s*[（(]\s*(?:男|女)\s*[，,）)]',
                r'([\u4e00-\u9fa5]{2,4})\s*(?:先生|女士|小姐)',
            ]
            for pat in gender_patterns:
                for match in re.finditer(pat, text):
                    candidate = match.group(1)
                    if self._is_valid_name(candidate):
                        detected.add((candidate, 'person'))

            # Pattern: name + ID card / bank account / signature (common OCR text format)
            # "姚财添 身份证号码" "陈峰 开户行" "张三（签字）"
            id_patterns = [
                r'([\u4e00-\u9fa5]{2,4})\s*[\d\W]*\s*身份证号',
                r'([\u4e00-\u9fa5]{2,4})\s*开[户己]行',
                r'([\u4e00-\u9fa5]{2,4})\s*[（(]\s*(?:签字|签章|盖章)\s*[）)]',
                r'(?:甲方|乙方|丙方|丁方)[：:]\s*([\u4e00-\u9fa5]{2,4})(?=[，。\s\d])',
                # "张三向XX法院提出" - NAME + 向 + institution
                r'([\u4e00-\u9fa5]{2,4})\s*向\s*[\u4e00-\u9fa5]{2,}(?:法院|检察院|仲裁委)',
                # "判处/判决 张三 死刑/有期徒刑" - defendant in a criminal judgment
                r'判[处决]\s*([\u4e00-\u9fa5]{2,4})\s*(?=(?:死刑|有期徒刑|无期徒刑|拘役|管制|罚金|缓刑))',
                # "张三系XX有限公司法定代表人" - 系/是 + company name + 法定代表人 (allow longer middle text)
                r'([\u4e00-\u9fa5]{2,4})\s*系[\u4e00-\u9fa5（）\s]{3,60}?法定代表人',
            ]
            for pat in id_patterns:
                for match in re.finditer(pat, text):
                    candidate = match.group(1)
                    if self._is_valid_name(candidate):
                        detected.add((candidate, 'person'))

        # ========== 3. Abbreviation tracking (以下简称"XXX") ==========
        self.abbreviation_map = {}
        abbrev_pattern = re.compile(
            r'([\u4e00-\u9fa5（()）\w]{4,50})'
            r'\s*[（(]\s*以下简称\s*'
            r'["\u201c]([^"\u201d]{1,20})["\u201d]'
            r'(?:\s*(?:或|、)\s*["\u201c]([^"\u201d]{1,20})["\u201d])?'
            r'\s*[）)]'
        )
        for match in abbrev_pattern.finditer(text):
            full_name = match.group(1).strip()
            abbrevs = [match.group(2)]
            if match.group(3):
                abbrevs.append(match.group(3))

            # Find the entity type that matches the full name
            full_type = None
            for name, etype in detected:
                if name == full_name or full_name.endswith(name) or name.endswith(full_name):
                    full_type = etype
                    full_name = name  # Use the canonical full name already detected
                    break

            for abbrev in abbrevs:
                if abbrev in self.GENERIC_ABBREVIATIONS:
                    continue
                if full_type:
                    self.abbreviation_map[abbrev] = full_name
                    detected.add((abbrev, full_type))
                else:
                    # Full name not detected -> look at the abbreviation itself (often a clean proper name)
                    if any(full_name.endswith(s) for s in ORG_SUFFIXES):
                        self.abbreviation_map[abbrev] = full_name
                        detected.add((full_name, 'company'))
                        detected.add((abbrev, 'company'))
                    elif 2 <= len(abbrev) <= 8 and re.fullmatch(r'[一-龥]+', abbrev):
                        # Fallback: the abbreviation is 2-8 pure Chinese characters (a proper name
                        # after excluding GENERIC). Even if the full name does not end in a standard
                        # ORG_SUFFIX (e.g. institutions like 纪念馆 or 故居研究会), add it as an
                        # institution type. Also try to extract a clean entity name from the tail of full_name.
                        cjk_tail = re.search(r'[一-龥]{2,16}$', full_name)
                        clean_full = cjk_tail.group(0) if cjk_tail else full_name
                        # Strip common verb prefixes
                        for v in ('现受', '本受', '受', '本', '即', '即受'):
                            if clean_full.startswith(v) and len(clean_full) > len(v) + 1:
                                clean_full = clean_full[len(v):]
                                break
                        self.abbreviation_map[abbrev] = clean_full
                        detected.add((abbrev, 'institution'))
                        if clean_full and clean_full != abbrev and len(clean_full) >= 3:
                            detected.add((clean_full, 'institution'))

        # ========== 4. Split run-together person names in signatures ==========
        if self._should_detect('person', only_types, exclude_types):
            signature_keywords = [
                '保荐代表人', '项目协办人', '经办律师', '签字律师',
                '经办会计师', '签字会计师', '签字注册会计师',
            ]
            for kw in signature_keywords:
                concat_pattern = re.compile(
                    rf'{re.escape(kw)}[：:\s]*\n?\s*([\u4e00-\u9fa5]{{4,8}})\s*(?:[\n，。]|$)'
                )
                for match in concat_pattern.finditer(text):
                    candidate = match.group(1)
                    names = self._split_concatenated_names(candidate)
                    for name in names:
                        if self._is_valid_name(name):
                            detected.add((name, 'person'))

        return list(detected)

    def _split_concatenated_names(self, text: str) -> List[str]:
        """
        Split run-together Chinese person names.
        For example "江镓伊王飞" -> ["江镓伊", "王飞"]
        """
        if len(text) < 4 or len(text) > 8:
            return [text]

        results = []
        i = 0
        while i < len(text):
            matched = False
            # Try a compound surname first (2-char surname + 1-2 char given name = 3-4 chars)
            if i + 2 <= len(text) and text[i:i+2] in COMPOUND_SURNAMES:
                for name_len in [4, 3]:
                    if i + name_len <= len(text):
                        candidate = text[i:i+name_len]
                        remaining = text[i+name_len:]
                        if self._is_valid_name(candidate) and (
                            not remaining or
                            remaining[0] in COMMON_SURNAMES or
                            any(remaining.startswith(cs) for cs in COMPOUND_SURNAMES)
                        ):
                            results.append(candidate)
                            i += name_len
                            matched = True
                            break
            # Then try a single surname (1-char surname + 1-2 char given name = 2-3 chars)
            if not matched and text[i] in COMMON_SURNAMES:
                for name_len in [3, 2]:
                    if i + name_len <= len(text):
                        candidate = text[i:i+name_len]
                        remaining = text[i+name_len:]
                        if self._is_valid_name(candidate) and (
                            not remaining or
                            remaining[0] in COMMON_SURNAMES or
                            any(remaining.startswith(cs) for cs in COMPOUND_SURNAMES)
                        ):
                            results.append(candidate)
                            i += name_len
                            matched = True
                            break
            if not matched:
                return [text]  # Cannot split; return the original text

        return results if len(results) >= 2 else [text]

    # Industry short-form suffixes: may appear inside a full company name without
    # triggering a compound-entity split. Detection data.
    _WEAK_ORG_SUFFIXES = frozenset({
        '药业', '置业', '实业', '物业',
        '大药房', '药房', '药店', '连锁药店', '医药公司',
        '广播电视台', '电视台', '广播电台', '广播台', '电台',
        '报社', '出版社', '杂志社', '通讯社',
    })

    def _clean_org_name(self, raw_name: str, suffix: str) -> str:
        """
        Clean up an institution name by stripping incorrectly included prefixes.

        For example: "原告张三诉被告北京示例科技有限公司" -> "北京示例科技有限公司"
        """
        prefix = raw_name[:-len(suffix)] if suffix else raw_name

        # Step 0: check whether the prefix contains another institution suffix (two entities merged).
        # For example "普洛药业股份有限公司北京市康达律师事务所" -> cut to "北京市康达律师事务所".
        # Also handles cases where the prefix is already a complete institution name, like "某牧业公司银行".
        # Note: industry short-form suffixes (药业, 大药房, etc.) may legitimately appear inside a
        # company name and do not trigger a split.
        compound_connectors = {'股份', '集团', '控股', '投资', '实业'}
        for known_suffix in sorted(ORG_SUFFIXES, key=len, reverse=True):
            if known_suffix in self._WEAK_ORG_SUFFIXES:
                continue  # Industry short forms are excluded from the compound-split check
            idx = prefix.find(known_suffix)
            if idx >= 0:
                remaining = prefix[idx + len(known_suffix):]
                before = prefix[:idx]
                if len(remaining) >= 2 and len(before) >= 2 and remaining not in compound_connectors:
                    return self._clean_org_name(remaining + suffix, suffix)
                elif len(remaining) == 0 and len(before) >= 2:
                    # The prefix itself ends in an institution suffix (e.g. "某牧业公司" + "银行");
                    # not a real institution name
                    return ''

        # Step 0 (supplement): a prefix ending in "公司" (not in ORG_SUFFIXES) is also treated as a
        # compound false match. For example "某牧业公司银行" -> prefix="某牧业公司" -> skip.
        if prefix.endswith('公司') and len(prefix) > 2:
            return ''

        # Step 1: check for legal-role or action keywords and cut after them
        legal_roles = [
            '原告', '被告', '申请人', '被申请人', '上诉人', '被上诉人',
            '第三人', '法定代表人', '负责人', '代理人', '委托人',
            '追加', '变更为', '转让给', '出售给', '支付给', '通知',
            '判令', '裁令', '责令', '命令', '要求',
            '诉', '起诉', '上诉', '应诉',
            '应收', '应付', '实收', '实付', '已收', '已付', '未收', '未付',
            '核查意见书', '法律意见书', '审计意见书', '专项意见书',
            '核查意见', '法律意见', '审计意见', '专项意见',
            '全资子公司', '控股子公司', '子公司',
            '召开情况', '审议情况', '表决情况',
            '接受', '使得', '主体资格', '企业类型', '类型',
            '间接持有', '直接持有', '持有', '现持有',
            '接收', '整体注入', '注入', '尚需', '修改', '触发',
            '过程中', '解散', '清算', '注销', '吸收合并', '吸收', '合并', '分立',
            '人民法院', '人民检察院',
            '委托', '配合', '协调', '同意', '登录', '已投资', '包括',
            '旗下', '围绕', '减持', '适用',
            '指定', '撤销', '裁定', '发回', '移送', '传唤',
            '审判',
            # Common verb prefixes in judgments (would cut "判决解除XX公司" down to "XX公司")
            '判决', '驳回', '确认', '批准', '否决',
            '解除', '终止', '违反', '违约',
            '不服', '服从', '尊重', '维持',
            # Statutory citation prefixes (filters "第XX条第二审人民法院")
            '第一款', '第二款', '第三款', '第四款', '第五款',
            '第六款', '第七款', '第八款', '第九款',
            '第一项', '第二项', '第三项', '第四项', '第五项',
            '第一条', '第二条', '第三条', '第四条', '第五条',
            '第六条', '第七条', '第八条', '第九条', '第十条',
            '第十一条', '第十二条', '第十三条', '第十四条', '第十五条',
            '第一百七十七条', '规定', '本规定',
            # Common transitive verbs in judgments/announcements (trap when followed by a company/institution name)
            '任', '兼任', '担任', '兼', '身兼',
            '提供', '给予', '交付', '交给', '支付给', '付给',
            '取得', '获得', '持有', '拥有', '购得', '购入',
            '出让', '转入', '投资', '入股',
            '要求', '命令', '强制', '责成',
            '前述', '该', '此',
        ]
        best_cut = -1
        for role in legal_roles:
            idx = prefix.rfind(role)
            if idx >= 0:
                cut_at = idx + len(role)
                if cut_at > best_cut:
                    best_cut = cut_at

        if best_cut > 0:
            trimmed = prefix[best_cut:]
            # Strip leftover function-word prefixes after the cut (e.g. "持有的XX" -> "的XX" -> "XX")
            leading_particles = '的了过在以为与和或及是则'
            while trimmed and trimmed[0] in leading_particles:
                trimmed = trimmed[1:]
            if len(trimmed) >= 2:
                return trimmed + suffix
            return ''

        # Step 2: cut on word-break characters
        # Includes function words, verbs, and the trailing characters of legal-role keywords (人/方)
        break_chars = (
            '的了过把将被让给在向从对与和或及是为由于到至以但却而且也又还'
            '要会可等则诉请求按照根据依照鉴于经因故系不称简小见'
            '受得入需改收并指号书'
            '人方'
        )

        last_break = -1
        for i, ch in enumerate(prefix):
            if ch in break_chars:
                last_break = i

        if last_break >= 0:
            trimmed_prefix = prefix[last_break + 1:]
            if len(trimmed_prefix) >= 2:
                return trimmed_prefix + suffix
            return ''

        # Step 3: trim a list of city names before a law firm name
        # Handles OCR / text extraction cases where city names get concatenated onto the law firm prefix.
        # For example "肥宁波济南昆明南昌北京市康达" -> "北京市康达"
        if '律师事务所' in suffix and len(prefix) > 6:
            # Find the position of the last "市" in the prefix
            last_shi = prefix.rfind('市')
            if last_shi >= 2:
                # Backtrack 2-4 characters before "市" as the city name
                for city_len in [2, 3, 4]:
                    city_start = last_shi - city_len
                    if city_start >= 0:
                        candidate = prefix[city_start:]
                        # Validate: after the city name there should be a 2-4 char firm name
                        name_part = candidate[city_len + 1:]  # The part after 市
                        if 2 <= len(name_part) <= 6:
                            return candidate + suffix
                # If there is not enough room to backtrack, start at least 2 chars before "市"
                city_start = max(0, last_shi - 2)
                candidate = prefix[city_start:]
                if len(candidate) >= 4:
                    return candidate + suffix

        return raw_name

    def _should_detect(self, entity_type: str, only_types: List[str] = None, exclude_types: List[str] = None) -> bool:
        """Check whether this type should be detected."""
        if only_types and entity_type not in only_types:
            return False
        if exclude_types and entity_type in exclude_types:
            return False
        return True

    def _is_valid_name(self, name: str) -> bool:
        """
        Validate whether a candidate string is likely a Chinese person name.

        Rule based:
        1. Length is 2-4 Chinese characters
        2. The first character (or first two characters) is a common surname
        3. Does not contain obvious non-name words
        """
        if not name or len(name) < 2 or len(name) > 4:
            return False

        # Exclude common non-name words (verbs, legal terms, generic words, etc.). Detection data.
        non_names = {
            # Legal parties / roles
            '原告', '被告', '法院', '法官', '律师', '公司', '银行',
            '本院', '本案', '本人', '本公司', '双方', '各方', '我方',
            '对方', '该公司', '该案', '对此',
            '经办律师', '签字律师', '承办律师',
            '董事', '监事', '高管', '经理', '总监', '主任',
            '教授', '博士', '硕士', '会计师', '评估师', '审计师',
            # Legal document types
            '合同', '协议', '判决', '裁定', '起诉', '上诉', '申请',
            '一审', '二审', '再审', '终审', '民事', '刑事', '行政',
            '仲裁', '调解', '执行', '审理', '答辩', '质证', '辩论',
            # Common verbs / verb phrases (prone to false matches)
            '支付', '收取', '履行', '承担', '提交', '提供', '签订',
            '办理', '缴纳', '退还', '返还', '赔偿', '补偿', '确认',
            '变更', '解除', '终止', '撤销', '认定', '驳回', '维持',
            '发生', '导致', '造成', '产生', '存在', '属于', '构成',
            '违反', '违约', '侵权', '损害', '损失', '经营', '管理',
            '建设', '开发', '投资', '运营', '使用', '占有', '处分',
            '转让', '出售', '购买', '租赁', '出租', '承租', '续租',
            '保障', '保护', '维护', '恢复', '清空', '拆除', '搬迁',
            '支付工资', '支付货款', '支付费用', '支付利息',
            '承担责任', '承担费用', '承担损失',
            '提交证据', '提供担保', '提供服务',
            # Industry / facility names (easily mistaken for person names)
            '铁路', '公路', '高速', '高铁', '地铁', '机场',
            '港口', '码头', '车站', '广场', '公园', '大厦',
            '高级管理',
            # Direction / reference words
            '如下', '以下', '以上', '其中', '之间', '之后', '之前',
            '以及', '以便', '以免', '根据', '依据', '依照', '按照',
            # Evidence / facts
            '证据', '事实', '理由', '请求', '诉求', '主张',
            '工资', '货款', '费用', '利息', '本金', '违约金',
            # Amount / quantity related (prone to OCR false matches)
            '万元', '万元整', '元整', '人民币', '美元', '港币',
            # Legal procedure / institutional terms
            '程序', '制度', '规定', '条款', '条件', '原则', '标准',
            '措施', '方案', '意见', '通知', '决定', '命令',
        }
        if name in non_names:
            return False

        # Check compound surnames
        if len(name) >= 3 and name[:2] in COMPOUND_SURNAMES:
            return True

        # Check single surnames
        if name[0] in COMMON_SURNAMES:
            return True

        return False

    def get_all_types(self) -> List[str]:
        """Return all entity types that have been added."""
        return list(self.entities.keys())
