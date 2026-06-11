"""
分层记忆管理器

实现四层记忆架构，为超长篇小说（100+ 章）提供连贯的创作上下文：

┌─────────────────────────────────────────────────┐
│  工作记忆 (Working)   ~3K tokens  每章注入      │
│  ├─ 上章结尾 500 字                              │
│  ├─ 最近 5 章摘要链                              │
│  ├─ 当前活跃悬念 (前 5 条)                       │
│  └─ 本章大纲 + 关键事件                          │
├─────────────────────────────────────────────────┤
│  短期记忆 (Short-term) ~4K tokens  语义检索      │
│  ├─ 向量检索: 本章相关历史片段 (top 3-5)         │
│  ├─ 角色关联检索: 出场角色的历史场景              │
│  └─ 物品关联检索: 涉及物品的历史                  │
├─────────────────────────────────────────────────┤
│  长期记忆 (Long-term)  ~3K tokens  定期压缩      │
│  ├─ 卷摘要 (每 10 章压缩为 200 字)               │
│  ├─ 角色弧线归档 (关键转折)                      │
│  ├─ 世界设定变更日志                             │
│  └─ 已解决悬念归档 (防止重复)                    │
├─────────────────────────────────────────────────┤
│  永久记忆 (Permanent)  ~2K tokens  始终注入      │
│  ├─ 世界观核心设定 (力量体系/势力)               │
│  ├─ 主角核心档案                                 │
│  └─ 主线悬念 (S 级)                              │
└─────────────────────────────────────────────────┘
"""

import logging
from typing import Dict, List, Optional

from novel_agent.database.mysql_client import db_client
from novel_agent.database.models import (
    Chapter, MemoryArchive, CharacterLibrary,
    SuspenseManager as SuspenseRecord,
    SuspenseStatusEnum, SuspenseLevelEnum,
)
from novel_agent.utils.llm_client import llm_client

logger = logging.getLogger(__name__)


class MemoryManager:
    """
    分层记忆管理器

    统一管理四层记忆的构建、压缩、检索和注入。
    """

    # Token 预算（字符数近似值，中文约 1.5 字符/token）
    BUDGET_WORKING = 4500     # ~3000 tokens
    BUDGET_SHORT_TERM = 6000  # ~4000 tokens
    BUDGET_LONG_TERM = 4500   # ~3000 tokens
    BUDGET_PERMANENT = 3000   # ~2000 tokens

    # 压缩参数
    VOLUME_SIZE = 10          # 每 N 章压缩为一个卷摘要
    MAX_VOLUME_SUMMARIES = 20 # 最多保留 N 条卷摘要
    MAX_CHARACTER_HISTORY = 20  # 角色变化历史最多 N 条

    def __init__(self, project_id: int, vector_store=None):
        """
        Args:
            project_id: 项目 ID
            vector_store: VectorStore 实例（用于短期记忆检索）
        """
        self.project_id = project_id
        self._vector_store = vector_store
        self._timeline: List[Dict] = []  # 运行时剧情时间线

    def set_vector_store(self, vector_store):
        """设置或更新向量存储引用"""
        self._vector_store = vector_store

    # ================================================================
    # 第一层：工作记忆 (Working Memory) — 每章注入
    # ================================================================

    def build_working_memory(
        self,
        current_chapter: int,
        chapter_outline: Dict,
        pending_suspense: List[Dict] = None,
    ) -> Dict[str, str]:
        """
        构建工作记忆上下文

        Args:
            current_chapter: 当前章节号
            chapter_outline: 本章大纲
            pending_suspense: 活跃悬念列表

        Returns:
            工作记忆字典 {key: text}
        """
        working = {}

        # 1. 多章滑动窗口（最近 5 章摘要链）
        summary_chain = self._get_summary_chain(current_chapter, window=5)
        if summary_chain:
            working["近期剧情"] = summary_chain

        # 2. 上章结尾（已在 pipeline 中处理，此处不重复）

        # 3. 当前活跃悬念（前 5 条，带描述）
        if pending_suspense:
            suspense_lines = []
            for s in pending_suspense[:5]:
                level = s.get("level", "B")
                title = s.get("title", "")
                desc = s.get("description", "")[:100]
                intro_ch = s.get("introduced_chapter", "?")
                suspense_lines.append(f"[{level}] {title} (第{intro_ch}章埋下): {desc}")
            working["活跃悬念"] = "\n".join(suspense_lines)

        # 4. 本章大纲（已在 chapter_generator 中处理）

        return working

    def _get_summary_chain(self, current_chapter: int, window: int = 5) -> str:
        """
        获取最近 N 章的摘要链

        比 pipeline 的 _get_recent_summaries 更完善：
        - 包含章节号、标题、摘要
        - 修复了截断 bug
        - 支持更大的窗口

        Args:
            current_chapter: 当前章节号
            window: 滑动窗口大小
        """
        records = db_client.get_all(Chapter, project_id=self.project_id)
        records.sort(key=lambda r: r.chapter_number, reverse=True)

        summaries = []
        for r in records:
            if r.chapter_number >= current_chapter:
                continue
            if r.chapter_number < current_chapter - window:
                break
            summary_text = (r.summary or "")[:180]
            if summary_text:
                summaries.append(
                    f"第{r.chapter_number}章「{r.title}」: {summary_text}"
                )

        summaries.reverse()  # 按时间正序
        return "\n".join(summaries) if summaries else ""

    # ================================================================
    # 第二层：短期记忆 (Short-term Memory) — 语义检索
    # ================================================================

    def build_short_term_memory(
        self,
        current_chapter: int,
        chapter_outline: Dict,
        character_names: List[str] = None,
    ) -> Dict[str, str]:
        """
        构建短期记忆：通过向量检索获取历史相关片段

        Args:
            current_chapter: 当前章节号
            chapter_outline: 本章大纲
            character_names: 本章出场的角色名列表

        Returns:
            短期记忆字典 {key: text}
        """
        short_term = {}

        if not self._vector_store:
            return short_term

        # 1. 基于大纲的语义检索
        query_parts = [
            chapter_outline.get("title", ""),
            chapter_outline.get("summary", ""),
            " ".join(chapter_outline.get("key_events", [])),
        ]
        query = " ".join(p for p in query_parts if p)

        if query:
            results = self._vector_store.search(
                query=query,
                top_k=8,
                filters={
                    "type": "chapter",
                    "chapter_number_lt": current_chapter - 1,
                },
            )

            # 过滤低相似度结果
            relevant = [
                r for r in results if r["similarity"] > 0.25
            ][:5]

            if relevant:
                chunks = []
                for r in relevant:
                    ch_num = r["metadata"].get("chapter_number", "?")
                    content = r["content"][:400]
                    sim = r["similarity"]
                    chunks.append(f"[第{ch_num}章 相关度{sim:.2f}] {content}")
                short_term["历史相关片段"] = "\n---\n".join(chunks)

        # 2. 角色关联检索
        if character_names:
            char_chunks = self._search_character_history(
                character_names, current_chapter
            )
            if char_chunks:
                short_term["角色历史"] = char_chunks

        # 3. 物品关联检索（基于大纲中的关键词）
        item_query = " ".join(chapter_outline.get("key_events", []))
        if item_query and any(kw in item_query for kw in ["法宝", "功法", "丹药", "装备", "武器", "阵法"]):
            item_results = self._vector_store.search(
                query=item_query,
                top_k=3,
                filters={
                    "type": "chapter",
                    "chapter_number_lt": current_chapter - 1,
                },
            )
            item_relevant = [r for r in item_results if r["similarity"] > 0.3][:2]
            if item_relevant:
                chunks = []
                for r in item_relevant:
                    ch_num = r["metadata"].get("chapter_number", "?")
                    chunks.append(f"[第{ch_num}章] {r['content'][:300]}")
                short_term["物品相关历史"] = "\n---\n".join(chunks)

        return short_term

    def _search_character_history(
        self, character_names: List[str], current_chapter: int
    ) -> str:
        """
        检索角色在历史章节中的关键场景

        Args:
            character_names: 角色名列表
            current_chapter: 当前章节号

        Returns:
            角色历史片段文本
        """
        if not self._vector_store or not character_names:
            return ""

        all_chunks = []
        for name in character_names[:3]:  # 最多检索 3 个角色
            results = self._vector_store.search(
                query=f"{name} 关键场景 对话 战斗",
                top_k=3,
                filters={
                    "type": "chapter",
                    "chapter_number_lt": current_chapter - 1,
                },
            )
            relevant = [r for r in results if r["similarity"] > 0.3][:2]
            for r in relevant:
                ch_num = r["metadata"].get("chapter_number", "?")
                all_chunks.append(f"[{name}@第{ch_num}章] {r['content'][:300]}")

        return "\n---\n".join(all_chunks[:5]) if all_chunks else ""

    # ================================================================
    # 第三层：长期记忆 (Long-term Memory) — 定期压缩
    # ================================================================

    def build_long_term_memory(self, current_chapter: int) -> Dict[str, str]:
        """
        构建长期记忆：从 memory_archive 表获取压缩后的历史摘要

        Args:
            current_chapter: 当前章节号

        Returns:
            长期记忆字典 {key: text}
        """
        long_term = {}

        # 1. 卷摘要（按时间正序，最多取最近的 N 条）
        volume_summaries = db_client.get_all(
            MemoryArchive,
            project_id=self.project_id,
            archive_type="volume_summary",
        )
        if volume_summaries:
            volume_summaries.sort(key=lambda v: v.chapter_start or 0)
            # 取最近的卷摘要，总量控制在 BUDGET_LONG_TERM 以内
            summaries = []
            total_chars = 0
            for v in volume_summaries[-self.MAX_VOLUME_SUMMARIES:]:
                if total_chars + len(v.content) > self.BUDGET_LONG_TERM:
                    break
                summaries.append(
                    f"第{v.chapter_start}-{v.chapter_end}章: {v.content}"
                )
                total_chars += len(v.content)
            if summaries:
                long_term["剧情时间线"] = "\n".join(summaries)

        # 2. 角色弧线归档
        char_arcs = db_client.get_all(
            MemoryArchive,
            project_id=self.project_id,
            archive_type="character_arc",
        )
        if char_arcs:
            arcs = []
            for arc in char_arcs[:10]:  # 最多 10 个角色弧线
                arcs.append(f"{arc.title}: {arc.content[:200]}")
            if arcs:
                long_term["角色弧线"] = "\n".join(arcs)

        # 3. 已解决悬念归档（防止 LLM 重复创造类似悬念）
        resolved_suspense = db_client.get_all(
            SuspenseRecord,
            project_id=self.project_id,
            status=SuspenseStatusEnum.RESOLVED,
        )
        if resolved_suspense:
            resolved_lines = []
            for s in resolved_suspense[-10:]:  # 最近 10 条已解决悬念
                resolved_lines.append(
                    f"[{s.level.value if s.level else 'B'}] {s.title} "
                    f"(第{s.introduced_chapter}章→第{s.actual_resolve_chapter}章): "
                    f"{(s.resolution or '')[:80]}"
                )
            if resolved_lines:
                long_term["已解决悬念"] = "\n".join(resolved_lines)

        return long_term

    def compress_volume(self, start_chapter: int, end_chapter: int):
        """
        将 N 章压缩为一个卷摘要，存入 memory_archive

        Args:
            start_chapter: 起始章节号
            end_chapter: 结束章节号
        """
        # 获取范围内所有章节的摘要
        records = db_client.get_all(Chapter, project_id=self.project_id)
        chapters_in_range = [
            r for r in records
            if start_chapter <= r.chapter_number <= end_chapter
        ]
        chapters_in_range.sort(key=lambda r: r.chapter_number)

        if not chapters_in_range:
            return

        # 构建压缩输入
        summaries_text = "\n".join(
            f"第{r.chapter_number}章「{r.title}」: {(r.summary or '')[:200]}"
            for r in chapters_in_range
        )

        # 获取范围内的剧情节点
        from novel_agent.database.models import PlotPoint
        plot_points = db_client.get_all(PlotPoint, project_id=self.project_id)
        pp_in_range = [
            pp for pp in plot_points
            if pp.chapter_number and start_chapter <= pp.chapter_number <= end_chapter
        ]
        events_text = "\n".join(
            f"- {pp.title}: {pp.description[:100]}"
            for pp in pp_in_range[:10]
        )

        # LLM 压缩
        prompt = (
            f"将以下 {len(chapters_in_range)} 章（第{start_chapter}-{end_chapter}章）的内容"
            f"压缩为一段 200 字以内的剧情摘要。\n\n"
            f"章节摘要：\n{summaries_text[:2000]}\n\n"
            f"关键事件：\n{events_text[:500]}\n\n"
            f"要求：\n"
            f"1. 保留核心剧情转折和角色变化\n"
            f"2. 保留重要的伏笔和悬念\n"
            f"3. 用时间线顺序叙述\n"
            f"4. 200 字以内，信息密度要高"
        )

        try:
            compressed = llm_client.generate(
                prompt=prompt,
                system_prompt="你是精确的剧情分析师，善于用最少的文字概括最多的剧情。",
                temperature=0.1,
                max_tokens=512,
            )
            compressed = compressed.strip()[:400]  # 安全截断

            # 存入 memory_archive
            archive = MemoryArchive(
                project_id=self.project_id,
                archive_type="volume_summary",
                title=f"第{start_chapter}-{end_chapter}章卷摘要",
                content=compressed,
                chapter_start=start_chapter,
                chapter_end=end_chapter,
                token_estimate=len(compressed) // 2,
            )
            db_client.add(archive)
            logger.info(
                f"卷摘要已归档: 第{start_chapter}-{end_chapter}章, "
                f"{len(compressed)} 字"
            )

        except Exception as e:
            logger.warning(f"卷摘要压缩失败: {e}")

    def archive_character_arc(self, character_name: str, current_chapter: int):
        """
        归档角色的关键弧线变化

        从角色的 history 字段中提取关键转折，生成弧线摘要。

        Args:
            character_name: 角色名
            current_chapter: 当前章节号
        """
        chars = db_client.get_all(CharacterLibrary, project_id=self.project_id)
        character = None
        for c in chars:
            if c.name == character_name:
                character = c
                break

        if not character or not character.history:
            return

        history = character.history
        if len(history) < 3:
            return  # 变化太少，不值得归档

        # 构建弧线文本
        arc_lines = []
        for h in history[-15:]:
            ch = h.get("chapter", "?")
            changes = h.get("changes", [])
            snapshot = h.get("snapshot", {})
            detail = ", ".join(f"{k}={v}" for k, v in snapshot.items())
            arc_lines.append(f"第{ch}章: {', '.join(changes)} → {detail}")

        arc_text = f"{character_name} 的变化轨迹:\n" + "\n".join(arc_lines)

        # 检查是否已有归档，有则更新
        existing = db_client.get_all(
            MemoryArchive,
            project_id=self.project_id,
            archive_type="character_arc",
        )
        found = None
        for arc in existing:
            if arc.title and character_name in arc.title:
                found = arc
                break

        if found:
            found.content = arc_text[:500]
            found.chapter_end = current_chapter
            db_client.update(found)
        else:
            archive = MemoryArchive(
                project_id=self.project_id,
                archive_type="character_arc",
                title=f"{character_name} 角色弧线",
                content=arc_text[:500],
                chapter_start=character.first_appearance,
                chapter_end=current_chapter,
                token_estimate=len(arc_text) // 3,
            )
            db_client.add(archive)

        logger.info(f"角色弧线归档: {character_name}, {len(history)} 条记录")

    def archive_resolved_suspense(self):
        """
        归档已解决的悬念（防止 LLM 重复创造类似悬念）

        将已解决悬念的标题和解决方式存入 memory_archive。
        """
        resolved = db_client.get_all(
            SuspenseRecord,
            project_id=self.project_id,
            status=SuspenseStatusEnum.RESOLVED,
        )
        if not resolved:
            return

        lines = []
        for s in resolved:
            resolution = (s.resolution or "未记录")[:100]
            lines.append(
                f"[{s.level.value if s.level else 'B'}] {s.title}: "
                f"第{s.introduced_chapter}章埋下 → 第{s.actual_resolve_chapter}章解决 "
                f"({resolution})"
            )

        archive_text = "\n".join(lines)

        # 更新或创建归档
        existing = db_client.get_all(
            MemoryArchive,
            project_id=self.project_id,
            archive_type="suspense_archive",
        )
        if existing:
            existing[0].content = archive_text
            db_client.update(existing[0])
        else:
            archive = MemoryArchive(
                project_id=self.project_id,
                archive_type="suspense_archive",
                title="已解决悬念归档",
                content=archive_text,
                token_estimate=len(archive_text) // 3,
            )
            db_client.add(archive)

    # ================================================================
    # 第四层：永久记忆 (Permanent Memory) — 始终注入
    # ================================================================

    def build_permanent_memory(self) -> Dict[str, str]:
        """
        构建永久记忆：世界观核心设定 + 主角档案 + 主线悬念

        这些内容始终注入，不随章节变化。

        Returns:
            永久记忆字典 {key: text}
        """
        permanent = {}

        # 1. 力量体系（从知识库获取）
        from novel_agent.database.models import WorldSetting
        power_records = db_client.get_all(
            WorldSetting,
            project_id=self.project_id,
            category="generated_power_system",
        )
        if power_records:
            power_text = "\n".join(r.content[:600] for r in power_records[:1])
            permanent["力量体系"] = power_text[:800]

        # 2. 势力分布
        faction_records = db_client.get_all(
            WorldSetting,
            project_id=self.project_id,
            category="generated_factions",
        )
        if faction_records:
            faction_text = "\n".join(r.content[:400] for r in faction_records[:1])
            permanent["势力分布"] = faction_text[:600]

        # 3. 主角档案（出场次数最多的角色）
        all_chars = db_client.get_all(CharacterLibrary, project_id=self.project_id)
        if all_chars:
            all_chars.sort(key=lambda c: c.appearance_count or 0, reverse=True)
            protagonist = all_chars[0]
            parts = [f"【{protagonist.name}】"]
            if protagonist.cultivation_level:
                parts.append(f"境界: {protagonist.cultivation_level}")
            if protagonist.personality:
                parts.append(f"性格: {', '.join(protagonist.personality[:5])}")
            if protagonist.skills:
                parts.append(f"功法: {', '.join(protagonist.skills[:5])}")
            if protagonist.core_items:
                parts.append(f"装备: {', '.join(protagonist.core_items[:5])}")
            if protagonist.relationships:
                rel = "; ".join(
                    f"{k}({v})" for k, v in list(protagonist.relationships.items())[:5]
                )
                parts.append(f"关系: {rel}")
            permanent["主角档案"] = " | ".join(parts)

        # 4. 主线悬念（S级）
        s_suspense = db_client.get_all(
            SuspenseRecord,
            project_id=self.project_id,
            level=SuspenseLevelEnum.S,
            status=SuspenseStatusEnum.ACTIVE,
        )
        if s_suspense:
            lines = []
            for s in s_suspense:
                lines.append(f"{s.title}: {s.description[:150]}")
            permanent["主线悬念"] = "\n".join(lines)

        return permanent

    # ================================================================
    # 统一接口：构建全层记忆上下文
    # ================================================================

    def build_full_context(
        self,
        current_chapter: int,
        chapter_outline: Dict,
        pending_suspense: List[Dict] = None,
    ) -> Dict[str, Dict[str, str]]:
        """
        构建完整的分层记忆上下文

        Args:
            current_chapter: 当前章节号
            chapter_outline: 本章大纲
            pending_suspense: 活跃悬念

        Returns:
            分层上下文 {
                "working": {key: text},
                "short_term": {key: text},
                "long_term": {key: text},
                "permanent": {key: text},
            }
        """
        character_names = chapter_outline.get("characters", [])

        context = {
            "working": self.build_working_memory(
                current_chapter, chapter_outline, pending_suspense
            ),
            "short_term": self.build_short_term_memory(
                current_chapter, chapter_outline, character_names
            ),
            "long_term": self.build_long_term_memory(current_chapter),
            "permanent": self.build_permanent_memory(),
        }

        # 日志输出各层 token 使用情况
        for layer_name, layer_data in context.items():
            total_chars = sum(len(v) for v in layer_data.values())
            budget = getattr(self, f"BUDGET_{layer_name.upper()}", 9999)
            logger.info(
                f"记忆层 [{layer_name}]: {len(layer_data)} 项, "
                f"{total_chars} 字 / {budget} 字预算"
            )

        return context

    def flatten_context(self, layered_context: Dict[str, Dict[str, str]]) -> Dict[str, str]:
        """
        将分层上下文扁平化为单一字典（兼容旧的 chapter_generator 接口）

        按优先级填充，超出预算时截断低优先级内容。

        优先级（从高到低）：
        1. permanent（永久记忆）
        2. working（工作记忆）
        3. short_term（短期记忆）
        4. long_term（长期记忆）

        Args:
            layered_context: build_full_context() 的返回值

        Returns:
            扁平化的上下文字典
        """
        flat = {}
        total_chars = 0
        total_budget = (
            self.BUDGET_PERMANENT + self.BUDGET_WORKING +
            self.BUDGET_SHORT_TERM + self.BUDGET_LONG_TERM
        )

        # 按优先级依次填充
        priority_order = ["permanent", "working", "short_term", "long_term"]
        prefixes = {
            "permanent": "★",
            "working": "◆",
            "short_term": "◇",
            "long_term": "○",
        }

        for layer in priority_order:
            layer_data = layered_context.get(layer, {})
            layer_budget = getattr(self, f"BUDGET_{layer.upper()}", 4500)
            layer_chars = 0
            prefix = prefixes.get(layer, "")

            for key, value in layer_data.items():
                if not value:
                    continue
                entry_key = f"{prefix}{key}" if prefix else key
                entry_chars = len(value)

                # 检查是否超出该层预算
                if layer_chars + entry_chars > layer_budget:
                    # 截断
                    remaining = layer_budget - layer_chars
                    if remaining > 50:
                        flat[entry_key] = value[:remaining] + "..."
                    break

                flat[entry_key] = value
                layer_chars += entry_chars
                total_chars += entry_chars

        logger.info(f"扁平化上下文: {len(flat)} 项, {total_chars} 字 / {total_budget} 字总预算")
        return flat

    # ================================================================
    # 时间线管理
    # ================================================================

    def append_timeline(self, chapter_data: Dict, suspense_result: Dict = None):
        """
        追加剧情时间线条目

        Args:
            chapter_data: 章节数据
            suspense_result: 悬念处理结果
        """
        entry = {
            "chapter": chapter_data.get("chapter_number", 0),
            "title": chapter_data.get("title", ""),
            "key_events": chapter_data.get("key_events", []),
            "characters": chapter_data.get("new_characters", []),
            "items": chapter_data.get("new_items", []),
            "suspense_new": (suspense_result or {}).get("new_suspense_titles", []),
            "suspense_resolved": (suspense_result or {}).get("resolved_suspense_ids", []),
        }
        self._timeline.append(entry)

    def get_timeline_summary(self, last_n: int = 10) -> str:
        """获取时间线最近 N 条的摘要文本"""
        recent = self._timeline[-last_n:]
        lines = []
        for e in recent:
            events = ", ".join(e.get("key_events", [])[:2])
            chars = ", ".join(e.get("characters", [])[:3])
            lines.append(
                f"第{e['chapter']}章「{e['title']}」: "
                f"人物[{chars}] 事件[{events}]"
            )
        return "\n".join(lines)

    # ================================================================
    # 定期维护
    # ================================================================

    def periodic_maintenance(self, current_chapter: int):
        """
        定期记忆维护（每 10 章执行一次）

        1. 压缩卷摘要
        2. 归档角色弧线
        3. 归档已解决悬念
        4. 清理向量索引
        """
        # 1. 卷摘要压缩
        if current_chapter % self.VOLUME_SIZE == 0:
            start = current_chapter - self.VOLUME_SIZE + 1
            self.compress_volume(start, current_chapter)

        # 2. 角色弧线归档（出场超过 5 章的角色）
        all_chars = db_client.get_all(CharacterLibrary, project_id=self.project_id)
        for char in all_chars:
            if (char.appearance_count or 0) >= 5:
                self.archive_character_arc(char.name, current_chapter)

        # 3. 已解决悬念归档
        self.archive_resolved_suspense()

        # 4. 向量索引清理
        if self._vector_store:
            self._vector_store.cleanup(max_documents=2000)

        logger.info(f"记忆维护完成 (第{current_chapter}章)")
