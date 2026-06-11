"""
多维度质量评估器

对生成的章节内容进行质量评估，包括：
- AI痕迹检测（本地规则）
- 对话密度检测
- 幽默密度检测
- 比喻密度检测
- 综合评分 + 低分原因诊断

评分低于阈值时触发重写机制。
"""

import re
import logging
from typing import Dict, List, Optional, Tuple

from novel_agent.utils.llm_client import llm_client
from novel_agent.config import config

logger = logging.getLogger(__name__)

# AI痕迹检测关键词/模式 — 命中越多扣分越重
AI_TRACE_PATTERNS = [
    (r"嘴角勾起.{0,6}弧度", "嘴角勾起弧度", 3),
    (r"眼中闪过一丝", "眼中闪过一丝", 3),
    (r"如.{1,4}般", "如X般明喻", 1),
    (r"猛地", "猛地", 1),
    (r"游戏.{0,4}才刚刚开始", "游戏才刚开始", 5),
    (r"命运.{0,6}由我.{0,4}(定|掌控|主宰)", "命运金句", 5),
    (r"在这个.{2,10}的世界里", "在这个世界里", 4),
    (r"并没有.{2,15}[，,]也没有", "并没有也没有", 4),
    (r"带来了.{2,10}[。\.]\s*\n\s*带来了", "排比收束", 4),
    (r"如同一只.{2,6}的(蝙蝠|鹰|狼|虎)", "陈词比喻", 3),
    (r"断线的风筝", "断线风筝", 3),
    (r"如潮水般", "如潮水般", 2),
    (r"如鬼魅般", "如鬼魅般", 2),
    (r"冷冷道|淡淡道|冷笑道", "模板对话标签", 1),
    (r"像.{1,8}一[样本]", "像X一样明喻", 1),
    (r"像是.{2,15}[，。]", "像是比喻句", 1),
    (r"就好像", "就好像", 1),
    (r"仿佛.{1,8}一[样本]", "仿佛X一样", 1),
    (r"(?:^|[，。！？\n])像[是个]", "裸像比喻", 1),
    (r"瞬间", "瞬间", 1),
    (r"骤然", "骤然", 1),
    (r"像是.{2,15}(?=[，。！？\n])", "像是短句", 1),
    (r"(?:^|[，。！？\s])像[一个两几道条团块把只](?:[^\n，。]{0,6})", "像+量词比喻", 1),
    (r"一下[。\s\S]{0,30}两下[。\s\S]{0,30}三下", "计数套路", 2),
]

ENGLISH_LEAK_PATTERN = re.compile(
    r'(?<![a-zA-Z])([a-zA-Z]{3,})\s*[（(].{1,5}[）)](?![a-zA-Z])',
    re.UNICODE
)

BARE_ENGLISH_PATTERN = re.compile(
    r'(?<![a-zA-Z])([a-zA-Z]{4,})(?![a-zA-Z（(])',
    re.UNICODE
)

# 幽默/吐槽关键词
HUMOR_KEYWORDS = [
    '吐槽', '无语', '尴尬', '懵', '一口老血', '我靠', '卧槽',
    '我擦', '我嘞个去', '什么鬼', '这什么', '不是吧', '离谱',
    '我人傻了', '我裂开', '整活', '翻白眼', '嘴角一抽',
    '差点没喷出来', '一脸懵逼', '满头黑线', '嘴角微抽',
    '你搁这', '搁这儿', '你在逗我', '开什么玩笑',
    '脑子有病', '谁他妈', '什么玩意儿', '搞毛',
    '冷笑', '嗤笑', '苦笑', '皮笑肉不笑',
]


class QualityEvaluator:
    """
    多维度质量评估器（增强版）

    评估维度：
    1. AI痕迹检测（本地正则，权重 30%）
    2. 对话密度（本地统计，权重 15%）
    3. 比喻/幽默质量（本地统计，权重 15%）
    4. LLM 综合评估（情节连贯 + 角色一致 + 世界观，权重 40%）

    提供低分原因诊断，供重写系统使用。
    """

    # 重写触发阈值
    REWRITE_THRESHOLD = 0.70

    # 允许裸英文的题材类型（系统流、游戏流、科幻等）
    ENGLISH_ALLOWED_GENRES = {
        '系统', '游戏', '科幻', '末世', '末日', '星际',
        '科技', '未来', '网游', '电竞', '程序', '程序员',
        '黑客', 'AI', '人工智能', '虚拟', '数据', '网络',
        '机械', '机甲', '赛博', '量子', '纳米', '生化',
    }

    def __init__(self, genre: str = ""):
        self.last_score: float = 0.0
        self.last_details: Dict = {}
        self.last_issues: List[Dict] = []
        self.genre = genre
        self._allow_bare_english = self._check_allow_bare_english(genre)

    # 已处理的英文词（与 chapter_generator.py 中的 replacements 和 whitelist 保持同步）
    ENGLISH_PROCESSED_WORDS = {
        # replacements 中的词
        'momentum', 'impact', 'buffer', 'status', 'critical', 'lethal', 'void',
        'aura', 'mana', 'combo', 'damage', 'burst', 'shatter', 'pulse', 'surge',
        'realm', 'flesh', 'blindly', 'render', 'failure', 'lazarus', 'corrupt',
        'corrupted', 'texture', 'missing', 'object', 'memory', 'leak', 'detected',
        'identity', 'fragmentation', 'project',
        # whitelist 中的词
        'null', 'true', 'false', 'none', 'bug', 'npc', 'vip', 'debuff', 'buff',
        'boss', 'hp', 'mp', 'sp', 'exp', 'lv', 'error', 'save', 'cpu', 'gpu',
        'ram', 'rom', 'ai', 'ui', 'id', 'loading', 'online', 'offline', 'sale',
        'feed', 'point', 'not', 'found', 'beta', 'app', 'max', 'min', 'pass',
        'fail', 'ping', 'log', 'data', 'core', 'root', 'admin', 'patch', 'cache',
        'v0', 'v1', 'v2', 'v3',
    }

    def _is_meaningless_gibberish(self, word: str) -> bool:
        """判断英文词是否为无意义乱码"""
        word_lower = word.lower()
        
        # 长度超过10个字母且没有常见英文模式的，可能是乱码
        if len(word) > 10:
            # 检查是否有连续重复的字母（乱码特征）
            if re.search(r'(.)\1{2,}', word):
                return True
            # 检查是否都是辅音字母组合（无元音）
            if not re.search(r'[aeiouy]', word_lower):
                return True
        
        # 检查是否是常见乱码模式（如 Base64 编码片段）
        if re.match(r'^[A-Za-z0-9+/]{8,}$', word):
            return True
        
        # 检查是否是随机字母组合（连续多个辅音）
        consonant_groups = re.findall(r'[bcdfghjklmnpqrstvwxyz]{4,}', word_lower)
        if any(len(g) >= 5 for g in consonant_groups):
            return True
        
        return False

    def _check_allow_bare_english(self, genre: str) -> bool:
        """判断题材是否允许裸英文"""
        if not genre:
            return False
        for allowed_genre in self.ENGLISH_ALLOWED_GENRES:
            if allowed_genre in genre:
                return True
        return False

    def evaluate(self, content: str, chapter_number: int = 0) -> float:
        """
        对章节内容进行综合质量评估

        Args:
            content: 章节正文
            chapter_number: 章节序号

        Returns:
            综合评分（0-1）
        """
        logger.debug(f"正在评估第 {chapter_number} 章质量...")
        chars = len(content)
        issues: List[Dict] = []

        # ---- 本地评估维度 ----
        ai_trace_score, ai_hits = self._local_ai_trace_check(content)
        dialogue_score, dialogue_info = self._local_dialogue_check(content)
        style_score, style_info = self._local_style_check(content)

        # ---- LLM 评估维度 ----
        llm_score = self._evaluate_llm_comprehensive(content, chapter_number)

        # ---- 加权综合评分 ----
        total_score = (
            ai_trace_score * 0.30 +
            dialogue_score * 0.15 +
            style_score * 0.15 +
            llm_score * 0.40
        )

        # ---- 诊断低分原因 ----
        if ai_trace_score < 0.7:
            issues.append({
                "dimension": "ai_traces",
                "severity": "high" if ai_trace_score < 0.5 else "medium",
                "reason": f"AI痕迹过多（评分{ai_trace_score:.2f}）",
                "details": ai_hits[:8],
                "fix_hint": "减少AI高频词，增加自然表达",
            })

        if dialogue_score < 0.6:
            issues.append({
                "dimension": "dialogue",
                "severity": "high" if dialogue_score < 0.4 else "medium",
                "reason": f"对话密度偏低（{dialogue_info['ratio']:.1f}%）",
                "details": [f"对话字符{dialogue_info['dialogue_chars']}，总字符{chars}"],
                "fix_hint": "增加角色对话，用对话推进剧情而非旁白叙述",
            })

        if style_score < 0.6:
            issues.append({
                "dimension": "style",
                "severity": "medium",
                "reason": f"文笔风格评分偏低（{style_score:.2f}）",
                "details": style_info.get("issues", []),
                "fix_hint": "减少比喻密度，增加幽默吐槽，丰富句式变化",
            })

        if llm_score < 0.6:
            issues.append({
                "dimension": "llm_quality",
                "severity": "high",
                "reason": f"LLM综合评估偏低（{llm_score:.2f}）",
                "details": [],
                "fix_hint": "改善情节逻辑、角色行为一致性、节奏控制",
            })

        self.last_score = total_score
        self.last_issues = issues
        self.last_details = {
            "ai_trace": ai_trace_score,
            "ai_trace_hits": ai_hits,
            "dialogue": dialogue_score,
            "dialogue_ratio": dialogue_info["ratio"],
            "style": style_score,
            "style_info": style_info,
            "llm_score": llm_score,
            "total": total_score,
            "issues": issues,
            "chapter_number": chapter_number,
            "needs_rewrite": total_score < self.REWRITE_THRESHOLD,
        }

        if ai_hits:
            logger.warning(f"AI痕迹检测命中: {ai_hits}")
        if issues:
            reasons = "; ".join(i["reason"] for i in issues)
            logger.warning(f"第 {chapter_number} 章低分原因: {reasons}")

        return total_score

    def diagnose(self) -> List[Dict]:
        """
        返回最近一次评估的低分原因列表。
        
        每个 issue 包含：
        - dimension: 维度名称
        - severity: 严重程度 (high/medium/low)
        - reason: 原因描述
        - details: 详细信息
        - fix_hint: 修复建议
        
        Returns:
            问题列表
        """
        return self.last_issues

    def needs_rewrite(self) -> bool:
        """判断最近评估是否需要重写"""
        return self.last_details.get("needs_rewrite", False)

    # ==================== 本地检测 ====================

    def _local_ai_trace_check(self, content: str) -> Tuple[float, List[str]]:
        """本地AI痕迹检测"""
        total_penalty = 0
        hits = []
        char_count = max(1, len(content))
        per_thousand = char_count / 1000

        for pattern, name, penalty in AI_TRACE_PATTERNS:
            matches = re.findall(pattern, content)
            count = len(matches)
            if count > 0:
                if penalty >= 3:
                    total_penalty += penalty * count
                    hits.append(f"{name}x{count}")
                else:
                    tolerance = max(1, int(per_thousand))
                    excess = count - tolerance
                    if excess > 0:
                        total_penalty += penalty * excess
                        hits.append(f"{name}x{count}(容忍{tolerance},超出{excess})")

        # 破折号密度
        dash_count = content.count("——")
        if dash_count > 10:
            total_penalty += (dash_count - 10) * 0.5
            hits.append(f"破折号过多({dash_count}次)")

        # 比喻密度
        metaphor_count = len(re.findall(
            r"如.{1,6}[般似]|像.{1,15}[，。\n]|仿佛.{1,6}[一样般]|好似|犹如|宛如",
            content
        ))
        metaphor_density = metaphor_count / (char_count / 1000)
        if metaphor_density > 3:
            total_penalty += (metaphor_density - 3) * 0.5
            hits.append(f"比喻过密({metaphor_count}次, {metaphor_density:.1f}/千字)")

        # 英文泄露
        eng_leaks = ENGLISH_LEAK_PATTERN.findall(content)
        if eng_leaks:
            total_penalty += len(eng_leaks) * 5
            hits.append(f"英文泄露x{len(eng_leaks)}")

        # 段落重复
        lines = content.split('\n')
        dup_count = sum(
            1 for i in range(1, len(lines))
            if lines[i].strip() and len(lines[i].strip()) > 5
            and lines[i].strip() == lines[i - 1].strip()
        )
        if dup_count > 0:
            total_penalty += dup_count * 3
            hits.append(f"段落重复x{dup_count}")

        # 裸英文（题材相关时不检查）
        if not self._allow_bare_english:
            bare_eng = BARE_ENGLISH_PATTERN.findall(content)
            # 过滤规则：
            # 1. 排除已处理的英文词（在 replacements 或 whitelist 中）
            # 2. 排除无意义的乱码词
            bare_eng = [
                w for w in bare_eng 
                if w.lower() not in self.ENGLISH_PROCESSED_WORDS 
                and not self._is_meaningless_gibberish(w)
            ]
            if bare_eng:
                total_penalty += len(bare_eng) * 3
                hits.append(f"裸英文x{len(bare_eng)}")

        score = max(0.0, min(1.0, 1.0 - total_penalty / 20.0))
        return score, hits

    def _local_dialogue_check(self, content: str) -> Tuple[float, Dict]:
        """
        对话密度检测。
        
        匹配多种引号格式，计算对话字符占比。
        评分标准：>= 25% → 1.0, 15% → 0.7, 5% → 0.3, 0% → 0.1
        """
        dialogue_patterns = [
            r'[\u201c"][^"\u201d]{1,300}[\u201d"]',    # "" 和 ""
            r'[\u300c\u300e][^\u300d\u300f]{1,300}[\u300d\u300f]',  # 「」『』
        ]
        
        dialogue_chars = 0
        dialogue_count = 0
        for pattern in dialogue_patterns:
            matches = re.findall(pattern, content)
            dialogue_chars += sum(len(m) for m in matches)
            dialogue_count += len(matches)
        
        chars = len(content)
        ratio = dialogue_chars / chars * 100 if chars > 0 else 0
        
        # 评分：阶梯式
        if ratio >= 25:
            score = 1.0
        elif ratio >= 20:
            score = 0.85
        elif ratio >= 15:
            score = 0.70
        elif ratio >= 10:
            score = 0.55
        elif ratio >= 5:
            score = 0.35
        else:
            score = 0.15
        
        info = {
            "ratio": ratio,
            "dialogue_chars": dialogue_chars,
            "dialogue_count": dialogue_count,
            "total_chars": chars,
        }
        
        return score, info

    def _local_style_check(self, content: str) -> Tuple[float, Dict]:
        """
        文笔风格检测（本地规则）。
        
        检测维度：
        - 比喻密度（像/仿佛/好似/犹如/宛如）
        - 幽默/吐槽密度
        - "他"开头段落密度
        - 短句碎片化程度
        """
        chars = max(1, len(content))
        per_k = chars / 1000
        issues = []
        penalties = 0.0

        # 1. 比喻密度
        xiang_count = len(re.findall(r'像(?:是)?', content))
        fangfu_count = content.count('仿佛')
        simile_total = xiang_count + fangfu_count
        simile_density = simile_total / per_k
        
        if simile_density > 3.0:
            penalties += 3.0
            issues.append(f"比喻过密: {simile_density:.1f}/千字")
        elif simile_density > 2.0:
            penalties += 1.5
            issues.append(f"比喻偏多: {simile_density:.1f}/千字")

        # 2. 幽默/吐槽密度
        humor_count = sum(
            content.count(kw) for kw in HUMOR_KEYWORDS
        )
        humor_per_chapter = humor_count  # 每章的幽默词次数
        
        if humor_per_chapter < 2:
            penalties += 2.0
            issues.append(f"幽默/吐槽过少: {humor_count}处")
        elif humor_per_chapter < 5:
            penalties += 0.5

        # 3. "他"开头段落密度
        paras = [p.strip() for p in content.split('\n\n') if p.strip()]
        ta_openings = sum(1 for p in paras if p and p[0] == '他' and len(p) > 1)
        ta_ratio = ta_openings / max(1, len(paras))
        
        if ta_ratio > 0.3:
            penalties += 1.5
            issues.append(f"'他'开头过多: {ta_openings}/{len(paras)}段 ({ta_ratio:.0%})")

        # 4. 短句碎片化
        lines = content.split('\n')
        short_lines = sum(1 for l in lines if l.strip() and len(l.strip()) < 15)
        short_ratio = short_lines / max(1, len(lines))
        
        if short_ratio > 0.5:
            penalties += 1.0
            issues.append(f"短句碎片化: {short_ratio:.0%}的行<15字")

        score = max(0.0, min(1.0, 1.0 - penalties / 8.0))
        info = {"issues": issues, "simile_density": simile_density, "humor_count": humor_count}
        
        return score, info

    # ==================== LLM 评估 ====================

    def _evaluate_llm_comprehensive(self, content: str, chapter_number: int) -> float:
        """
        LLM 综合评估（单次调用，多维度打分）。
        
        将原来 3 次独立的 LLM 调用合并为 1 次，减少 API 消耗，
        同时让 LLM 在上下文中做更综合的判断。
        """
        prompt = (
            f"请评估以下第{chapter_number}章小说的质量（每个维度0-10分）。\n\n"
            f"评估维度：\n"
            f"1. 情节连贯性：剧情逻辑自洽、推进自然、节奏合理\n"
            f"2. 角色塑造：行为符合人设、对话有个性、互动自然\n"
            f"3. 世界观统一：力量体系一致、环境描述合理、名词统一\n"
            f"4. 文笔质量：描写生动、句式多样、没有AI模板感\n\n"
            f"章节内容（前2500字）：\n{content[:2500]}\n\n"
            f"请严格按以下格式输出（每行一个维度:分数）：\n"
            f"连贯:X\n角色:X\n世界:X\n文笔:X"
        )

        try:
            result = llm_client.generate(
                prompt=prompt,
                system_prompt="你是一位严格的网文编辑，按格式输出4个评分。",
                temperature=0.1,
                max_tokens=64,
            )
            
            # 解析多维度评分
            scores = self._parse_llm_scores(result)
            if scores:
                # 加权平均：连贯30% + 角色25% + 世界20% + 文笔25%
                avg = (
                    scores.get("连贯", 7) * 0.30 +
                    scores.get("角色", 7) * 0.25 +
                    scores.get("世界", 7) * 0.20 +
                    scores.get("文笔", 7) * 0.25
                ) / 10.0
                return min(1.0, max(0.0, avg))
            
            # 解析失败，尝试提取单个数字
            nums = re.findall(r'(\d+\.?\d*)', result)
            if nums:
                return min(1.0, max(0.0, float(nums[0]) / 10.0))
            
            return 0.65  # 默认

        except Exception as e:
            logger.warning(f"LLM综合评估失败: {e}")
            return 0.65

    def _parse_llm_scores(self, text: str) -> Dict[str, float]:
        """解析 LLM 返回的多维度评分"""
        scores = {}
        for line in text.strip().split('\n'):
            line = line.strip()
            match = re.match(r'(连贯|角色|世界|文笔)\s*[:：]\s*(\d+\.?\d*)', line)
            if match:
                dim = match.group(1)
                val = float(match.group(2))
                scores[dim] = min(10.0, max(0.0, val))
        return scores

    def get_last_report(self) -> Dict:
        """获取最近一次评估的详细报告"""
        return self.last_details
