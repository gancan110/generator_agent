"""
章节内容生成器

基于大纲、知识库和上下文，调用 LLM 生成单个章节的正文内容。
支持分段生成长章节和质量控制。
支持根据 Skill 定制系统提示和后处理规则。
"""

import re
import logging
from typing import Dict, Optional, List, TYPE_CHECKING

from novel_agent.utils.llm_client import llm_client
from novel_agent.database.mysql_client import db_client
from novel_agent.database.models import Chapter
from novel_agent.config import config

if TYPE_CHECKING:
    from novel_agent.skills.context import SkillContext

logger = logging.getLogger(__name__)

# "在这个...的世界里" 替换池 — 根据匹配内容选择具体化替换
_IN_THIS_WORLD_ALTS = [
    "此处", "眼下", "如今", "这世道", "这鬼地方", "这破地方",
    "这年头", "眼下的局势", "如今的局面", "当下的处境",
]
_in_this_world_counter = 0

def _replace_in_this_world(match):
    """将 '在这个XX的世界里' 替换为更具体的短句"""
    global _in_this_world_counter
    _in_this_world_counter += 1
    return _IN_THIS_WORLD_ALTS[_in_this_world_counter % len(_IN_THIS_WORLD_ALTS)]


class ChapterGenerator:
    """
    章节内容生成器

    根据大纲、世界观、角色档案和悬念状态，
    调用 LLM 生成连贯的章节正文。
    支持根据 Skill 定制写作风格和后处理规则。
    """

    def __init__(self, project_id: int, skill_context: Optional["SkillContext"] = None):
        """
        Args:
            project_id: 项目 ID
            skill_context: Skill 上下文（可选）
        """
        self.project_id = project_id
        self.skill = skill_context

    def get_system_prompt(self) -> str:
        """获取当前的系统提示（供重写器使用）"""
        return self._build_system_prompt()

    def generate_chapter(
        self,
        chapter_number: int,
        chapter_outline: Dict,
        knowledge_context: Dict[str, str],
        previous_chapter_summary: str = "",
        pending_suspense: List[Dict] = None,
    ) -> Dict:
        """
        生成单个章节的完整内容

        Args:
            chapter_number: 章节序号
            chapter_outline: 该章节的大纲信息
            knowledge_context: 知识库上下文
            previous_chapter_summary: 上一章摘要
            pending_suspense: 当前未解决的悬念

        Returns:
            章节数据字典 {title, content, summary, word_count, ...}
        """
        logger.info(f"正在生成第 {chapter_number} 章...")

        # 构建悬念上下文
        suspense_text = ""
        if pending_suspense:
            suspense_items = [
                f"- [{s.get('level', 'B')}] {s.get('title', '')}"
                for s in pending_suspense[:5]  # 限制悬念数量
            ]
            suspense_text = "\n".join(suspense_items)

        # 构建 LLM 上下文
        context = {}
        if previous_chapter_summary:
            context["上一章摘要"] = previous_chapter_summary

        if suspense_text:
            context["当前悬念"] = suspense_text

        # 添加知识库上下文（限制总量）
        # 记忆系统已在上游做过预算控制，此处放宽截断阈值
        for key, value in knowledge_context.items():
            if value:
                # 带前缀标记的条目来自记忆系统，已在 flatten_context 中控制长度
                is_memory_entry = key and key[0] in "★◆◇○"
                max_len = 3000 if is_memory_entry else 1500
                context[key] = value[:max_len]

        # 分段生成
        chapter_content = self._generate_in_segments(
            chapter_number=chapter_number,
            chapter_outline=chapter_outline,
            context=context,
        )

        # 统一后处理（包含 Skill 定制扩展）
        chapter_content = self._apply_post_processing(chapter_content)

        # 生成章节摘要
        summary = self._generate_summary(chapter_content, chapter_number)

        # 构建章节数据
        chapter_data = {
            "chapter_number": chapter_number,
            "title": chapter_outline.get("title", f"第{chapter_number}章"),
            "content": chapter_content,
            "summary": summary,
            "word_count": len(chapter_content),
            "new_characters": chapter_outline.get("characters", []),
            "new_suspense": chapter_outline.get("suspense", []),
        }

        # 存储到数据库
        chapter_record = Chapter(
            project_id=self.project_id,
            chapter_number=chapter_number,
            title=chapter_data["title"],
            content=chapter_content,
            word_count=chapter_data["word_count"],
            summary=summary,
            new_characters=chapter_data["new_characters"],
            new_suspense=chapter_data["new_suspense"],
        )
        db_client.add(chapter_record)

        logger.info(
            f"第 {chapter_number} 章已生成: "
            f"「{chapter_data['title']}」({chapter_data['word_count']} 字)"
        )
        return chapter_data

    def _apply_post_processing(self, content: str) -> str:
        """
        统一后处理入口。

        执行标准后处理链，然后应用 Skill 定制的扩展规则。
        """
        # 标准后处理链（始终执行）
        content = self._clean_chapter_ending(content)
        content = self._deduplicate_paragraphs(content)
        content = self._replace_banned_patterns(content)
        content = self._fix_english_leaks(content)
        content = self._diversify_actions(content)
        content = self._reduce_similes(content)
        content = self._reduce_shunjian(content)
        content = self._reduce_fangfu(content)
        content = self._diversify_openings(content)
        content = self._merge_short_lines(content)

        # Skill 定制后处理
        if self.skill:
            # 题材特有的禁用模式
            banned_extra = self.skill.get_banned_patterns_extra()
            if banned_extra:
                content = self._apply_extra_banned(content, banned_extra)

            # 题材特有的同义词池
            synonym_extra = self.skill.get_synonym_pools_extra()
            if synonym_extra:
                content = self._apply_extra_synonyms(content, synonym_extra)

        # 对话密度检测（仅记录日志，不做文本修改）
        self._check_dialogue_density(content)

        return content

    def _apply_extra_banned(self, content: str, patterns: List[dict]) -> str:
        """应用 Skill 定义的额外禁用模式"""
        count = 0
        for p in patterns:
            pattern = p.get("pattern", "")
            if not pattern:
                continue
            replacement = p.get("replacement", "") or ""
            if pattern in content:
                content = content.replace(pattern, replacement)
                count += 1
        if count > 0:
            logger.info(f"Skill 额外禁用模式：替换 {count} 处")
        return content

    def _apply_extra_synonyms(self, content: str, pools: dict) -> str:
        """应用 Skill 定义的额外同义词池"""
        count = 0
        for original, alternatives in pools.items():
            occurrences = content.count(original)
            if occurrences <= 1:
                continue
            # 保留第1次，替换后续
            parts = content.split(original)
            rebuilt = parts[0]
            for i, part in enumerate(parts[1:]):
                if i < 1:
                    rebuilt += original + part
                else:
                    alt = alternatives[(i - 1) % len(alternatives)]
                    rebuilt += alt + part
                    count += 1
            content = rebuilt
        if count > 0:
            logger.info(f"Skill 额外同义词池：替换 {count} 处")
        return content

    def _build_system_prompt(self) -> str:
        """
        构建章节生成的系统提示。

        采用"通用基础 + Skill 覆盖"模式：
        - 通用部分（排版格式、通用禁止清单）始终保留
        - 题材相关部分（身份、时间体系、写作规则）根据 Skill 定制
        """
        # ===== 通用基础（所有题材共享）=====
        base = (
            "你是一位有十年经验的网文老手，笔风粗粝干脆、不讲废话。"
            "你写的东西像真人写的，绝不像AI生成的。"
            "以下铁律你必须遵守，违反任何一条就算失败：\n\n"
            "【排版格式 — 最重要的一条】\n"
            "- 必须按正常小说格式写作：每个自然段包含3-8句话，段落之间用空行分隔\n"
            "- 绝对禁止每句话独占一行！这不是诗歌，是小说！\n"
            "- 段落内的句子之间不要换行，直接连写\n"
            "- 对话可以独立成段，但也要写完整，不要一个字一行\n\n"
            "【禁止清单 — 出现以下任何表达直接判定为失败】\n"
            "- 禁止使用'嘴角勾起XX弧度''嘴角扯出XX''嘴角微微抽动'\n"
            "- 禁止使用'眼中闪过一丝XX'\n"
            "- 禁止使用'如XX般'类明喻超过每千字1次\n"
            "- 禁止使用'像XX一样''像是XX''仿佛XX一般'类明喻，全章总计不超过5次\n"
            "- 绝对禁止以'像'字开头的短句（如'像刀。''像是XXX。'），这是最严重的AI标记\n"
            "- 禁止使用'游戏，才刚刚开始''故事才刚开始''命运，由我自己掌控'等金句式收尾\n"
            "- 禁止使用'猛地'超过每千字1次，多用'霍然''倏地''陡然'等替换\n"
            "- 禁止使用'瞬间''骤然'超过每千字1次\n"
            "- 禁止用'——'破折号做插入语超过每千字1次\n"
            "- 禁止在章末使用排比式总结句或连续的决心宣言\n"
            "- 禁止用'并没有XX，也没有XX，只有XX'句式\n"
            "- 禁止用'在这个XX的世界里'做世界观解释\n"
            "- 禁止连续两段用形容词开头的描写句\n"
            "- 禁止章末出现超过200字的抒情/哲理/决心宣誓收尾\n"
            "- 绝对禁止输出任何英文单词（包括括号内的翻译），全文必须是纯中文\n"
            "- 禁止同一段落重复相同的句子\n\n"
        )

        # ===== 题材相关部分（根据 Skill 定制）=====
        if self.skill:
            # 题材身份
            genre_identity = self.skill.get_genre_identity()
            if genre_identity:
                base += f"【题材定位】\n{genre_identity}\n\n"

            # 写作风格（Skill 定制版）
            base += "【写作风格要求】\n"

            # 从 Skill 获取额外写作规则
            extra_rules = self.skill.get_extra_writing_rules()
            if extra_rules:
                for i, rule in enumerate(extra_rules, start=1):
                    base += f"{i}. {rule}\n"
            else:
                # 默认写作规则
                base += (
                    "1. 要有反差行为幽默感，但是该悲伤时一定要将悲伤的深度和情感表达出来\n"
                    "2. 对话要'脏'要'真'：底层人说粗话、说断句、说口语，不说书面语\n"
                    "3. 世界观只通过情节和对话展示，绝不旁白解释\n"
                    "4. 金手指使用必须有代价、有失误、有限制，不能完美碾压\n"
                    "5. 描写用具体感官细节替代抽象形容词（写气味就写什么味，不要写'绝望的味道'）\n"
                    "6. 反派要有基本行为逻辑，不能只是送经验的工具人\n"
                    "7. 战斗场景要有意外和变数，不能主角每次都完美操作\n"
                    "8. 比喻用暗喻或借代，严禁用'像''如''仿佛'等标记词的短句比喻\n"
                    "9. 【幽默密度要求】每章至少包含3-5处角色吐槽、系统吐槽或反差笑点\n"
                    "   - 角色之间要有互怼、抬杠、阴阳怪气的对话\n"
                    "   - 遇到严肃场景时，用一句不合时宜的大实话打破气氛\n"
                    "   - 内心独白要有自嘲和吐槽，不能全是正经分析\n"
                    "10. 对话占比不低于30%，用对话推进剧情和角色塑造\n"
                )

            # 时间体系（Skill 定制）
            time_system = self.skill.get_time_system()
            if time_system:
                base += f"\n【时间体系】{time_system}\n"

            # 题材特有禁止项
            extra_banned = self.skill.get_extra_banned_patterns()
            if extra_banned:
                base += "\n【题材禁止清单】\n"
                for p in extra_banned:
                    base += f"- {p}\n"

            # 词汇约束
            forbidden_terms = self.skill.get_forbidden_modern_terms()
            if forbidden_terms:
                terms = "、".join(forbidden_terms)
                base += f"\n- 禁止出现以下词汇：{terms}\n"
        else:
            # 无 Skill 时使用默认规则
            base += (
                "【写作风格要求】\n"
                "1. 要有反差行为幽默感，但是该悲伤时一定要将悲伤的深度和情感表达出来\n"
                "2. 对话要'脏'要'真'：底层人说粗话、说断句、说口语，不说书面语\n"
                "3. 世界观只通过情节和对话展示，绝不旁白解释\n"
                "4. 金手指使用必须有代价、有失误、有限制，不能完美碾压\n"
                "5. 描写用具体感官细节替代抽象形容词（写气味就写什么味，不要写'绝望的味道'）\n"
                "6. 反派要有基本行为逻辑，不能只是送经验的工具人\n"
                "7. 战斗场景要有意外和变数，不能主角每次都完美操作\n"
                "8. 比喻用暗喻或借代，严禁用'像''如''仿佛'等标记词的短句比喻\n"
                "9. 【幽默密度要求】每章至少包含3-5处角色吐槽、系统吐槽或反差笑点\n"
                "   - 角色之间要有互怼、抬杠、阴阳怪气的对话\n"
                "   - 遇到严肃场景时，用一句不合时宜的大实话打破气氛\n"
                "   - 内心独白要有自嘲和吐槽，不能全是正经分析\n"
                "10. 对话占比不低于30%，用对话推进剧情和角色塑造\n"
            )

        return base

    def _generate_in_segments(
        self,
        chapter_number: int,
        chapter_outline: Dict,
        context: Dict[str, str],
    ) -> str:
        """
        分段生成长章节内容

        将一章分为多个片段生成，确保每段质量可控。

        Args:
            chapter_number: 章节序号
            chapter_outline: 章节大纲
            context: 上下文信息

        Returns:
            完整章节文本
        """
        target_words = config.generation.words_per_chapter
        segment_words = config.generation.words_per_segment
        num_segments = max(1, target_words // segment_words)

        segments = []
        previous_segment = ""
        used_scene_fingerprints = []  # 跨段场景指纹，防止重复场景

        # 构建系统提示（根据 Skill 定制）
        system_prompt = self._build_system_prompt()

        for seg_idx in range(num_segments):
            segment_position = f"{seg_idx + 1}/{num_segments}"

            prompt = (
                f"请为小说第 {chapter_number} 章生成第 {segment_position} 部分的内容。\n\n"
                f"章节标题：{chapter_outline.get('title', '')}\n"
                f"章节大纲：{chapter_outline.get('summary', '')}\n"
                f"关键事件：{', '.join(chapter_outline.get('key_events', []))}\n"
            )

            if seg_idx == 0:
                prompt += (
                    "\n这是本章的开头部分：\n"
                    "1. 必须正面处理上一章结尾留下的悬念，不能跳过\n"
                    "2. 用具体场景细节开场，不要用旁白解释\n"
                    "3. 快速进入冲突，不要铺太多环境描写\n"
                    "4. 开头500字内必须出现至少一轮角色对话或系统提示\n"
                )
            elif seg_idx == num_segments - 1:
                prompt += (
                    "\n这是本章的结尾部分：\n"
                    "1. 收束本章核心冲突\n"
                    "2. 用具体的悬念画面收尾（比如一个意外事件、一句对话、一个动作），"
                    "绝不要用感慨式金句或哲理段落收尾\n"
                    "3. 结尾的悬念收束控制在150字以内，干净利落\n"
                    "4. 禁止在结尾出现超过3句的内心独白或世界观感慨\n"
                    "5. 让读者想知道'接下来会发生什么'\n"
                    "6. 最好用一句对话或一个具体动作收尾\n"
                )
            else:
                prompt += (
                    "\n这是本章的中间部分：\n"
                    "1. 推进剧情，保持紧凑\n"
                    "2. 如有战斗，必须包含至少一个意外或变数\n"
                    "3. 不要让主角太顺利，适当让他犯错或受挫\n"
                    "4. 本段至少包含2轮角色对话（不是独白，是有来有回的对话）\n"
                )

            # 所有段落的通用要求：对话 + 幽默
            prompt += (
                "\n\n【对话与幽默要求 — 必须遵守】\n"
                "- 本段对话占比不低于25%：角色之间要有实际交流，不是自言自语\n"
                "- 对话要有口语感：用断句、语气词（'靠''得''行了''少来'），"
                "不要用完整的书面语句\n"
                "- 至少1处幽默元素：角色吐槽、内心自嘲、不合时宜的大实话、"
                "或者系统/旁白的反差评论\n"
                "- 不同角色说话风格要有差异：主角冷静简短，配角碎嘴或阴阳怪气\n"
            )

            if previous_segment:
                # 传递前段末尾内容以保持连贯
                tail = previous_segment[-800:] if len(previous_segment) > 800 else previous_segment
                prompt += f"\n紧接以下内容继续写：\n---\n{tail}\n---\n"

            # 传递已用场景指纹，防止跨段重复
            if used_scene_fingerprints:
                prompt += (
                    "\n\n【禁止重复以下已写过的场景/视角】\n"
                    + "\n".join(f"- {fp}" for fp in used_scene_fingerprints)
                    + "\n如果需要切换到反派视角，必须使用不同的角色或不同的信息内容。"
                    + "\n禁止再次使用'猛地睁开眼'作为叙事起点。"
                )

            prompt += (
                f"\n本段目标字数：约 {segment_words} 字。"
                "\n直接输出小说正文，不要任何前言、解释或标注。"
            )

            segment = llm_client.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=config.generation.chapter_temperature,
                max_tokens=4096,
                context=context if seg_idx == 0 else {},
            )

            # 提取本段场景指纹，传递给后续段
            fingerprints = self._extract_scene_fingerprints(segment)
            used_scene_fingerprints.extend(fingerprints)

            segments.append(segment)
            previous_segment = segment

        return "\n\n".join(segments)

    def _clean_chapter_ending(self, content: str) -> str:
        """
        清理过长的抒情/哲理/决心宣誓结尾

        检测维度：
        1. 抽象感慨/哲理句式标记（扩展版）
        2. 重复句式（连续多行以相同结构开头）
        3. 短句密度（大量10字以下独立行）
        4. 尾部比喻密度（最后200字内比喻过多 = 抒情收尾）
        """
        if len(content) < 1000:
            return content

        # 取末尾800字进行分析
        tail = content[-800:]
        
        # 检测抒情/哲理/决心密度标记（扩展版）
        abstract_markers = [
            r"命运的齿轮", r"这个世界", r"一切才刚刚开始",
            r"或许.*就是", r"也许.*才是", r"终究",
            r"在这个.*的世界", r"没有人知道",
            r"他知道.*不再.*", r"她明白.*永远",
            r"路.*还很长", r"故事.*才刚",
            r"他是.*[。，]", r"她已不再是", r"不再.*蝼蚁",
            r"磨掉", r"每一[个刻息]", r"都是生死",
            r"才刚刚开始", r"也才刚开始",
            # 新增：诗意/哲理标记
            r"挽歌", r"号角", r"星辰", r"夜空",
            r"闪烁", r"照亮.*夜", r"奏响", r"吹响",
            r"独自", r"最后一页", r"第一页", r"翻开",
            r"直到.*最后", r"哪怕.*也",
            r"无人知道", r"没人知道",
            r"不肯熄灭", r"闪到最后",
        ]
        
        marker_count = sum(
            1 for p in abstract_markers if re.search(p, tail)
        )
        
        # 检测重复句式：末尾连续多行以相同2字开头
        tail_lines = [l.strip() for l in tail.split('\n') if l.strip()]
        repetitive_prefixes = 0
        if len(tail_lines) >= 4:
            last_4_prefixes = [l[:2] for l in tail_lines[-8:] if len(l) > 2]
            if last_4_prefixes:
                most_common = max(set(last_4_prefixes), key=last_4_prefixes.count)
                repetitive_prefixes = last_4_prefixes.count(most_common)
        
        # 检测短句密度（10字以下的独立行占比）
        short_lines = [l for l in tail_lines if 0 < len(l) <= 10]
        short_density = len(short_lines) / max(1, len(tail_lines))
        
        # 新增：尾部比喻密度检测 — 最后200字内有2个以上比喻 = 抒情收尾
        tail_200 = content[-200:] if len(content) >= 200 else content
        tail_metaphors = len(re.findall(r'像是|仿佛|如同|好像|像是|像.*[，。]', tail_200))
        tail_metaphor_heavy = tail_metaphors >= 2
        
        # 如果满足以下任一条件，触发截断：
        # 1. 抽象标记 >= 2
        # 2. 重复句式 >= 4行
        # 3. 短句密度 > 60%
        # 4. 尾部比喻密度过高
        should_trim = (
            marker_count >= 2 or
            repetitive_prefixes >= 4 or
            short_density > 0.6 or
            tail_metaphor_heavy
        )
        
        if should_trim:
            # 向前找最后一个"具体"句子（对话/动作/感官）
            concrete_patterns = [
                r"[说道喊骂叫哼笑哭]+[：:」""]",  # 对话
                r"[走跑跳踢打拍推拉拿抓握]+[了过着向到]",  # 动作
                r"[看听感觉触闻]+[到了见着]",  # 感官
                r"[！!？?]",  # 语气词结尾
                r"[。，]",  # 普通叙述句结尾（通常比抒情句更具体）
            ]
            
            search_area = content[-800:]
            last_concrete_pos = -1
            for p in concrete_patterns:
                matches = list(re.finditer(p, search_area))
                if matches:
                    # 不取最后一个，取倒数第3-5个（跳过尾部抒情）
                    idx = max(0, len(matches) - 4)
                    pos = matches[idx].end()
                    last_concrete_pos = max(last_concrete_pos, pos)
            
            if last_concrete_pos > 0:
                cut_pos = len(content) - 800 + last_concrete_pos
                content = content[:cut_pos].rstrip()
                logger.info(f"章节结尾已清理：截断抒情/重复段落，保留 {len(content)} 字")
        
        return content

    def _deduplicate_paragraphs(self, content: str) -> str:
        """
        去除重复段落
        
        检测并移除连续重复的行（LLM偶尔会生成重复段落）。
        也检测非连续但完全相同的行（跳过空行和太短的行）。
        """
        lines = content.split('\n')
        cleaned = []
        seen_lines = set()
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            
            # 跳过空行和太短的行（标点等）
            if not stripped or len(stripped) <= 3:
                cleaned.append(line)
                continue
            
            # 检测连续重复
            if i > 0 and stripped == lines[i - 1].strip():
                logger.info(f"段落去重：移除连续重复行 - {stripped[:30]}")
                continue
            
            # 检测非连续重复（完全相同的行出现超过1次）
            if stripped in seen_lines and len(stripped) > 10:
                logger.info(f"段落去重：移除非连续重复行 - {stripped[:30]}")
                continue
            
            seen_lines.add(stripped)
            cleaned.append(line)
        
        result = '\n'.join(cleaned)
        if len(result) < len(content):
            removed = len(content) - len(result)
            logger.info(f"段落去重完成：移除 {removed} 字")
        
        return result

    def _merge_short_lines(self, content: str, min_paragraph_len: int = 40) -> str:
        """
        将碎片化的短句行合并为正常散文段落。
        
        分两阶段处理：
        1. 段内合并：同一空行块内的连续短行合并
        2. 跨段合并：连续的单句短段落合并为完整段落
        """
        # === 阶段1：段内合并 ===
        lines = content.split('\n')
        merged = []
        buffer = ""
        
        for line in lines:
            stripped = line.strip()
            
            # 空行 → 段落分隔
            if not stripped:
                if buffer:
                    merged.append(buffer)
                    buffer = ""
                merged.append("")
                continue
            
            # 对话行（含引号）→ 独立成段
            if any(q in stripped for q in '"""「」『』'):
                if buffer:
                    merged.append(buffer)
                    buffer = ""
                merged.append(stripped)
                continue
            
            # 场景切换行 → 独立成段
            if stripped in ("……", "…", "---", "***"):
                if buffer:
                    merged.append(buffer)
                    buffer = ""
                merged.append(stripped)
                continue
            
            # 短行（<25字）→ 合并到buffer
            if len(stripped) < 25:
                if buffer:
                    buffer += stripped
                else:
                    buffer = stripped
                # buffer够长了，输出为段落
                if len(buffer) >= min_paragraph_len:
                    merged.append(buffer)
                    buffer = ""
            else:
                # 长行 → 直接输出
                if buffer:
                    merged.append(buffer)
                    buffer = ""
                merged.append(stripped)
        
        if buffer:
            merged.append(buffer)
        
        # === 阶段2：跨段合并 — 合并连续的单句短段落 ===
        # 提取所有段落（按双空行分割）
        raw_paras = [p.strip() for p in '\n'.join(merged).split('\n\n') if p.strip()]
        
        result_paras = []
        para_buffer = ""
        
        for para in raw_paras:
            # 对话段落 → 不合并，独立保留
            is_dialogue = any(q in para for q in '"""「」『』')
            # 场景切换 → 不合并
            is_break = para.strip() in ("……", "…", "---", "***")
            # 已经是足够长的段落 → 直接保留
            is_long = len(para) >= 60
            
            if is_dialogue or is_break or is_long:
                # flush buffer
                if para_buffer:
                    result_paras.append(para_buffer)
                    para_buffer = ""
                result_paras.append(para)
            else:
                # 短段落 → 加入合并队列
                if para_buffer:
                    if len(para_buffer) + len(para) > 150:
                        # buffer够长了，输出并开始新段落
                        result_paras.append(para_buffer)
                        para_buffer = para
                    else:
                        para_buffer += para
                else:
                    para_buffer = para
        
        if para_buffer:
            result_paras.append(para_buffer)
        
        # 构建最终输出
        output = '\n\n'.join(result_paras)
        if len(output) < len(content):
            logger.info(f"短行合并：{len(content)} → {len(output)} 字, "
                        f"{len(raw_paras)} 段 → {len(result_paras)} 段")
        return output

    def _replace_banned_patterns(self, content: str) -> str:
        """
        后处理替换AI高频禁止模式。
        
        即使prompt中禁止，LLM仍可能生成这些表达，
        通过后处理确保最终文本不含禁止模式。
        """
        replacements = [
            # (正则, 替换文本或函数)
            (r"眼中闪过一丝(\S{1,4})", lambda m: f"眸子里透出几分{m.group(1)}"),
            (r"嘴角勾起.{0,6}弧度", "唇角微扬"),
            # 嘴角扯出 — 覆盖所有变体（"一个狰狞的笑""一丝冷笑""一抹苦笑"等）
            (r"嘴角扯出(一个|一丝|一抹)(\S+)", lambda m: f"脸上浮起{m.group(1)}{m.group(2)}"),
            (r"嘴角溢出了?(一口)?", "唇边渗出"),
            (r"嘴角微微抽动", "唇角一紧"),
            # 嘴角 — 补全遗漏变体
            (r"嘴角微微上扬", "唇角微翘"),
            (r"嘴角抽搐了一下?", "唇角一紧"),
            (r"嘴角抽动了一下?", "脸上的肌肉一绷"),
            (r"嘴角上扬", "唇角微翘"),
            # 更多嘴角变体
            (r"嘴角扯动了一下?", "唇角一紧"),
            (r"嘴角咧开", "唇角微张"),
            (r"嘴角勾起", "唇角微扬"),
            (r"嘴角挂着一[丝抹]", "唇角带着"),
            (r"嘴角微[微]?动了一下?", "唇角轻抿"),
            # 猛地 — 扩大替换覆盖面（保留前2个，后续替换）
            (r"猛地(?=抬头|站起|转身|回头|抽[出回]|坐[起下]|扑[过上向]|冲[出过向]|跃起|翻[身转]|睁[开眼]|挥[动舞]|吸[了口]|闭[上眼]|缩[回]|咬[紧破住]|握[紧住]|摇[头晃]|咳|颤|震|窜|扑|弹|跳|蹲|跪|喝|吃|推|拉|抓|拍|踢|打)", "霍然"),
            # "在这个...的世界里" — AI 高频解释句式 → 具体化描述
            (r"在这个充满[^，。]{1,8}的世界里", lambda m: _replace_in_this_world(m)),
            (r"在这个[^，。]{1,8}的世界[里中]", lambda m: _replace_in_this_world(m)),
            (r"在这片[^，。]{1,8}的土地上", lambda m: _replace_in_this_world(m)),
        ]
        
        count = 0
        for pattern, replacement in replacements:
            new_content, n = re.subn(pattern, replacement, content)
            if n > 0:
                content = new_content
                count += n
        
        if count > 0:
            logger.info(f"禁止模式替换：共替换 {count} 处")
        return content

    def _fix_english_leaks(self, content: str) -> str:
        """
        修复正文中的裸英文词泄露。
        
        维护常见泄露词映射表进行替换，同时维护白名单（世界观内英文）。
        未映射且不在白名单的词记录日志并尝试替换。
        """
        # 常见泄露词映射表（持续扩充）
        replacements = {
            'momentum': '惯性',
            'impact': '冲击力',
            'buffer': '缓冲',
            'status': '状态',
            'critical': '危急',
            'lethal': '致命',
            'void': '虚空',
            'aura': '气场',
            'mana': '灵力',
            'combo': '连击',
            'damage': '伤害',
            'burst': '爆发',
            'shatter': '碎裂',
            'pulse': '脉冲',
            'surge': '涌动',
            'realm': '境界',
            # 新增：P11 英文泄露词
            'flesh': '血肉',
            'blindly': '盲目地',
            'Render': '渲染',
            'render': '渲染',
            'Failure': '崩溃',
            'failure': '崩溃',
            'Lazarus': '拉撒路',
            'corrupt': '损坏',
            'CORRUPTED': '数据损坏',
            'corrupted': '数据损坏',
            # P11 验证发现的新泄露词
            'Texture': '贴图',
            'texture': '贴图',
            'Missing': '缺失',
            'missing': '缺失',
            'Object': '对象',
            'object': '对象',
            'Memory': '内存',
            'memory': '内存',
            'Leak': '泄漏',
            'leak': '泄漏',
            'Detected': '检测到',
            'detected': '检测到',
            'Identity': '身份',
            'identity': '身份',
            'Fragmentation': '碎片化',
            'fragmentation': '碎片化',
            'Project': '项目',
            'project': '项目',
        }
        
        # 白名单：世界观内合理英文（系统面板、游戏术语、技术名词）
        # 这些词在末日/系统/科幻题材中属于世界观的一部分，不替换
        whitelist = {
            # 通用技术词
            'null', 'true', 'false', 'None', 'True', 'False',
            # 游戏/系统术语（末日系统题材合理）
            'BUG', 'Bug', 'bug', 'NPC', 'VIP', 'Debuff', 'debuff', 'Buff', 'buff',
            'BOSS', 'Boss', 'HP', 'MP', 'SP', 'EXP', 'LV', 'Lv',
            'ERROR', 'Error', 'error', 'SAVE', 'Save', 'save',
            'CPU', 'GPU', 'RAM', 'ROM', 'AI', 'UI', 'ID',
            'LOADING', 'Loading', 'loading',
            'ONLINE', 'Online', 'online',
            'OFFLINE', 'Offline', 'offline',
            'SALE', 'Sale', 'FEED', 'Feed',
            'POINT', 'Point', 'CORRUPTED',
            'NOT', 'FOUND', 'Not', 'Found',
            'Beta', 'BETA', 'beta',
            'APP', 'App', 'app',
            'MAX', 'Max', 'MIN', 'Min',
            'PASS', 'Pass', 'FAIL', 'Fail',
            # 编程/系统术语
            'PING', 'Ping', 'ping', 'LOG', 'Log', 'log',
            'DATA', 'Data', 'CORE', 'Core',
            'ROOT', 'Root', 'root', 'ADMIN', 'Admin',
            'PATCH', 'Patch', 'patch', 'CACHE', 'Cache',
            'RENDER', 'Render',
            # 版本号/编号类
            'v0', 'v1', 'v2', 'v3',
        }
        
        count = 0
        for eng, chn in replacements.items():
            new_content, n = re.subn(
                rf'(?<![a-zA-Z]){re.escape(eng)}(?![a-zA-Z])',
                chn, content, flags=re.IGNORECASE
            )
            if n > 0:
                content = new_content
                count += n
        
        # 兜底检测：剩余的裸英文词
        remaining = re.findall(r'(?<![a-zA-Z])([a-zA-Z]{3,})(?![a-zA-Z（(])', content)
        remaining_filtered = [w for w in remaining if w not in whitelist]
        if remaining_filtered:
            # 对于不在白名单且不在映射表的英文词，尝试音译或意译替换
            auto_replacements = self._auto_translate_english(remaining_filtered)
            for eng, chn in auto_replacements.items():
                new_content, n = re.subn(
                    rf'(?<![a-zA-Z]){re.escape(eng)}(?![a-zA-Z])',
                    chn, content
                )
                if n > 0:
                    content = new_content
                    count += n
        
        if count > 0:
            logger.info(f"英文泄露修复：共替换 {count} 处")
        return content
    
    def _auto_translate_english(self, words: List[str]) -> Dict[str, str]:
        """
        对未映射的英文词进行简单替换。
        
        常见词直接替换，罕见词用 [XX] 格式标注。
        """
        # 内置简单翻译表（应急用）
        simple_dict = {
            'lazarus': ' Lazarus ',  # 人名保留但加空格标记
            'flesh': '血肉',
            'blindly': '胡乱地',
        }
        
        result = {}
        for w in words:
            w_lower = w.lower()
            if w_lower in simple_dict:
                result[w] = simple_dict[w_lower]
            elif len(w) <= 3:
                # 3字母以内的缩写词，可能是合理的
                continue
            else:
                # 未知英文词 → 直接删除或标记
                logger.warning(f"未映射英文词需人工处理: {w}")
        
        return result

    def _diversify_actions(self, content: str) -> str:
        """
        对高频重复的动作词进行同义替换，提升词汇丰富度。
        
        同一动作词在章节中出现超过2次时，保留前2次，
        后续用同义词替换。
        """
        synonym_pools = {
            "咬紧牙关": ["攥紧拳头", "绷紧下颌", "死死撑住", "硬扛着"],
            "咬破舌尖": ["咬破嘴唇", "舌尖一痛", "嘴里泛起血腥味", "舌尖渗出血珠"],
            "深吸一口气": ["胸腔一扩", "鼻腔里灌进冷气", "猛吸一口浊气", "长长吐出一口浊气", "屏住呼吸"],
            "握紧拳头": ["攥紧五指", "指甲嵌入掌心", "拳头捏得咯咯响"],
            "猛地抬头": ["霍然抬首", "倏地仰头", "陡然抬眼"],
            "翻江倒海": ["一阵翻涌", "胃部翻腾", "胃里搅动", "恶心直往上涌", "一阵强烈的反胃"],
            "瞳孔收缩": ["瞳孔骤缩", "目光一凝", "眼底骤紧"],
            "指节泛白": ["指节发青", "手指攥得发白", "掌心被指甲硌出印痕"],
        }
        
        total = 0
        for original, alternatives in synonym_pools.items():
            count = content.count(original)
            if count <= 1:
                continue
            # 保留前1次，后续替换
            parts = content.split(original)
            rebuilt = parts[0]
            for i, part in enumerate(parts[1:]):
                if i < 1:
                    rebuilt += original + part
                else:
                    alt = alternatives[(i - 2) % len(alternatives)]
                    rebuilt += alt + part
                    total += 1
            content = rebuilt
        
        if total > 0:
            logger.info(f"动作词去重：共替换 {total} 处")
        return content

    def _reduce_similes(self, content: str) -> str:
        """
        降低"像"类比喻的密度。
        
        策略：
        - "像是" → 轮换替换为"仿佛""好似""犹如""宛如"（保留约33%）
        - "就像是" → 替换为更简洁的表达
        - 独立"像" → 轮换替换
        - 密度阈值 2.5/千字，超过即处理
        """
        total_xiang = len(re.findall(r'像(?:是)?', content))
        chars = len(content)
        density = total_xiang / (chars / 1000) if chars > 0 else 0
        
        if density < 2.5:
            # 密度可接受，不处理
            return content
        
        count = 0
        
        # 策略1: "像是" 轮换替换（保留每3个中的第1个 → 保留33%）
        xiangshi_alts = ["仿佛", "好似", "犹如", "宛如"]
        parts = content.split("像是")
        if len(parts) > 1:
            rebuilt = parts[0]
            for i, part in enumerate(parts[1:]):
                if i % 3 == 0:
                    # 保留原样
                    rebuilt += "像是" + part
                else:
                    alt = xiangshi_alts[(i - 1) % len(xiangshi_alts)]
                    rebuilt += alt + part
                    count += 1
            content = rebuilt
        
        # 策略2: 独立的"像"（非"像是"）在描述性语境中轮换替换
        # 匹配 "像+1-8字+逗号/句号" 的模式
        xiang_alts = ["仿佛", "好似", "犹如", "宛如", "恰似"]
        xiang_independent_count = 0
        
        def replace_xiang(match):
            nonlocal xiang_independent_count, count
            xiang_independent_count += 1
            if xiang_independent_count % 3 == 0:
                count += 1
                alt = xiang_alts[xiang_independent_count % len(xiang_alts)]
                return alt + match.group(1)
            return match.group(0)
        
        content = re.sub(
            r'(?<!就|好|佛|宛|犹|恰)像([^\n，。]{1,8}[，。])',
            replace_xiang, content
        )
        
        # 策略3: "像...一样" → 部分替换为暗喻
        yiyang_count = 0
        yiyang_alts = ["仿佛", "好似", "犹如"]
        
        def replace_yiyang(match):
            nonlocal yiyang_count, count
            yiyang_count += 1
            if yiyang_count % 2 == 0:
                count += 1
                alt = yiyang_alts[yiyang_count % len(yiyang_alts)]
                return alt + match.group(1) + "一般"
            return match.group(0)
        
        content = re.sub(
            r'(?<!就|好|佛|宛|犹|恰)像([^\n]{2,12})一样',
            replace_yiyang, content
        )
        
        if count > 0:
            logger.info(f"比喻降密度：共替换 {count} 处 '像'类表达 "
                       f"(原密度 {density:.1f}/千字)")
        return content

    def _reduce_shunjian(self, content: str) -> str:
        """
        降低"瞬间"的使用频率。
        
        "瞬间"是 LLM 极高频的 AI 标记词，本方法分三层处理：
        1. "一瞬间，" 作为段落/句子开头的时间过渡词 → 替换为多样化过渡
        2. "那一瞬间" → 替换为其他时间指代
        3. "瞬间" 作为副词修饰动作 → 仅保留第1次，后续用同义词替换
        """
        total = content.count('瞬间')
        if total <= 2:
            return content
        
        count = 0
        
        # 策略1: "一瞬间，" 开头过渡词 → 多样化替换（仅保留第1个）
        opener_alts = [
            "这一刻，", "下一秒，", "刹那间，", "紧接着，",
            "随即，", "几乎同时，", "就在那时，", "倏忽间，",
            "须臾，", "登时，",
        ]
        opener_count = 0
        
        def replace_opener(match):
            nonlocal opener_count, count
            opener_count += 1
            if opener_count <= 1:
                return match.group(0)  # 仅保留第1个
            count += 1
            return opener_alts[(opener_count - 2) % len(opener_alts)]
        
        content = re.sub(r'一瞬间，', replace_opener, content)
        
        # 策略2: "那一瞬间" → 大部分替换
        nayi_count = 0
        nayi_alts = ["那一刻", "那一刹", "就在那时", "彼时", "当是时"]
        
        def replace_nayi(match):
            nonlocal nayi_count, count
            nayi_count += 1
            if nayi_count <= 1:
                return match.group(0)
            count += 1
            return nayi_alts[(nayi_count - 2) % len(nayi_alts)]
        
        content = re.sub(r'那一瞬间', replace_nayi, content)
        
        # 策略3: 剩余的独立"瞬间"作为副词 → 仅保留第1次，后续替换
        adverb_alts = [
            "霎时", "陡然间", "倏地", "霍然", "登时",
            "蓦地", "忽地", "猝然", "骤然", "倏然",
        ]
        adverb_count = 0
        
        def replace_adverb(match):
            nonlocal adverb_count, count
            adverb_count += 1
            if adverb_count <= 1:
                return match.group(0)  # 仅保留第1个
            count += 1
            return adverb_alts[(adverb_count - 2) % len(adverb_alts)]
        
        content = re.sub(r'瞬间', replace_adverb, content)
        
        if count > 0:
            logger.info(f"瞬间降频：共替换 {count} 处 (原 {total} 处)")
        return content

    def _reduce_fangfu(self, content: str) -> str:
        """
        降低"仿佛"的使用频率。
        
        "仿佛"是 _reduce_similes 中 "像是" 的替换词之一，
        但如果原始文本就包含大量"仿佛"，会导致总量偏高。
        当"仿佛"密度超过 1.0/千字时，保留前3次，后续替换。
        """
        total = content.count('仿佛')
        chars = len(content)
        density = total / (chars / 1000) if chars > 0 else 0
        
        if density < 1.0:
            return content
        
        count = 0
        alts = ["好似", "犹如", "宛如", "恰似", "浑似", "一如"]
        keep = 0
        
        def replace_fangfu(match):
            nonlocal keep, count
            keep += 1
            if keep <= 3:
                return match.group(0)
            count += 1
            return alts[(keep - 4) % len(alts)]
        
        content = re.sub(r'仿佛', replace_fangfu, content)
        
        if count > 0:
            logger.info(f"仿佛降频：共替换 {count} 处 (原 {total} 处, 密度 {density:.1f}/千字)")
        return content

    def _check_dialogue_density(self, content: str):
        """
        检测对话密度，低于阈值时记录警告。
        
        不影响文本内容，仅作为质量评估的参考信号。
        """
        # 匹配多种引号格式
        dialogue_patterns = [
            r'["\u201c][^"\u201d]{1,200}["\u201d]',  # "" 和 ""
            r'[「『][^」』]{1,200}[」』]',              # 「」 和 『』
        ]
        
        dialogue_chars = 0
        for pattern in dialogue_patterns:
            matches = re.findall(pattern, content)
            dialogue_chars += sum(len(m) for m in matches)
        
        chars = len(content)
        ratio = dialogue_chars / chars * 100 if chars > 0 else 0
        
        if ratio < 15:
            logger.warning(
                f"对话密度偏低: {ratio:.1f}% (建议>20%)，"
                f"请在系统提示中加强对话要求"
            )
        else:
            logger.info(f"对话密度: {ratio:.1f}%")

    def _diversify_openings(self, content: str) -> str:
        """
        减少段落开头"他/林默"的重复频率。
        
        策略：对超过阈值的"他"开头段落进行句式变换，
        确保变换后的段落不再以"他"开头。
        """
        paras = content.split('\n\n')
        if len(paras) < 10:
            return content
        
        # 统计"他"开头的段落（简单匹配：段落以"他"开头）
        ta_openings = []
        for i, para in enumerate(paras):
            stripped = para.strip()
            if stripped and stripped[0] == '他' and len(stripped) > 1:
                ta_openings.append(i)
        
        # 统计"林默"开头的段落
        lin_openings = []
        for i, para in enumerate(paras):
            stripped = para.strip()
            if stripped.startswith("林默"):
                lin_openings.append(i)
        
        count = 0
        threshold_ta = 4  # "他"开头超过4次时开始变换
        
        # 变换"他"开头段落（保留前threshold_ta个，后续变换）
        if len(ta_openings) > threshold_ta:
            # 时间/场景前缀池
            time_prefixes = ["这一刻，", "紧接着，", "随即，", "下一秒，", 
                           "几乎同时，", "刹那间，", "一瞬间，", "须臾，"]
            
            for idx, para_idx in enumerate(ta_openings[threshold_ta:], start=0):
                para = paras[para_idx].strip()
                if not para or para[0] != '他':
                    continue
                
                strategy = idx % 3
                
                if strategy == 0:
                    # 策略1: 添加时间前缀 + 移除"他"
                    prefix = time_prefixes[idx % len(time_prefixes)]
                    new_para = prefix + para[1:]
                
                elif strategy == 1:
                    # 策略2: 省略主语"他"（直接以动词/副词开头）
                    new_para = para[1:]
                    # 确保首字符不是标点
                    if new_para and new_para[0] in '，。、；：':
                        new_para = new_para[1:]
                
                else:
                    # 策略3: 从段落中提取环境词前置 + 移除"他"
                    env_words = ["空气中", "走廊里", "房间里", "黑暗中", 
                               "寂静中", "灯光下", "冷风中", "阴影里"]
                    # 尝试找到段落中的环境词
                    env_found = None
                    for ew in env_words:
                        if ew in para:
                            env_found = ew
                            break
                    if env_found:
                        new_para = env_found + "，" + para[1:]
                    else:
                        # 找不到环境词，用时间前缀替代
                        prefix = time_prefixes[(idx + 3) % len(time_prefixes)]
                        new_para = prefix + para[1:]
                
                if new_para and new_para != para:
                    paras[para_idx] = new_para
                    count += 1
        
        # 变换"林默"开头段落（保留前3个，后续变换）
        if len(lin_openings) > 3:
            for idx, para_idx in enumerate(lin_openings[3:], start=0):
                para = paras[para_idx].strip()
                if not para.startswith("林默"):
                    continue
                
                if idx % 2 == 0:
                    # 替换为"他"
                    new_para = "他" + para[2:]
                else:
                    # 省略主语
                    rest = para[2:]
                    if rest and rest[0] not in '，。、；：':
                        new_para = rest
                    else:
                        new_para = "他" + para[2:]
                
                if new_para != para:
                    paras[para_idx] = new_para
                    count += 1
        
        if count > 0:
            content = '\n\n'.join(paras)
            logger.info(f"段首多样化：共变换 {count} 处重复开头")
        return content

    def _extract_scene_fingerprints(self, text: str) -> list:
        """
        提取段落中的场景指纹（角色名+视角切换），
        用于跨段重复检测。
        """
        fingerprints = []
        
        # 检测视角切换标记
        if re.search(r'与此同时|千里之外|另一[边处]|远处的', text):
            fingerprints.append("视角切换场景")
        
        # 检测主角醒来
        if re.search(r'猛地?睁开眼|从(昏迷|沉睡|黑暗)中(醒来|苏醒|恢复)', text):
            fingerprints.append("主角醒来/意识恢复")
        
        # 检测反派/配角出场（2-4字角色名 + 动作）
        villain_names = re.findall(
            r'(太一尊者|太一|赵虎|黑袍人|清道夫|尊者|执事|长老)',
            text
        )
        if villain_names:
            unique = list(set(villain_names))[:3]
            for name in unique:
                fingerprints.append(f"{name}出场片段")
        
        # 检测倒数/计数套路
        if re.search(r'一下[。\s\S]{0,30}两下', text):
            fingerprints.append("计数/倒数场景")
        
        return fingerprints[:6]  # 限制数量避免prompt过长

    def _generate_summary(self, content: str, chapter_number: int) -> str:
        """
        生成章节摘要

        Args:
            content: 章节正文
            chapter_number: 章节序号

        Returns:
            章节摘要文本
        """
        prompt = (
            f"请用200字以内概括以下第{chapter_number}章的核心内容，"
            f"包括：主要剧情、出场人物、关键事件、悬念/伏笔。\n\n"
            f"章节内容（前3000字）：\n{content[:3000]}"
        )

        try:
            summary = llm_client.generate(
                prompt=prompt,
                system_prompt="你是一位精准的文学分析师，善于提炼文章要点。",
                temperature=config.generation.evaluation_temperature,
                max_tokens=512,
            )
            return summary
        except Exception as e:
            logger.warning(f"章节摘要生成失败: {e}")
            return content[:200]
