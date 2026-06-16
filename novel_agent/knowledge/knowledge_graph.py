"""
知识图谱基础模块

构建小说创作领域的知识图谱，增强实体关系理解能力。

核心功能:
├── 实体识别: 角色、物品、地点、事件
├── 关系抽取: 实体间的关系
├── 图谱存储: 内存图 + 持久化
└── 图谱查询: 基于关系的检索
"""

import json
import logging
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
from pathlib import Path

from novel_agent.config import config

logger = logging.getLogger(__name__)


@dataclass
class Entity:
    """实体节点"""
    id: str
    name: str
    entity_type: str  # character, item, location, event, concept
    properties: Dict = field(default_factory=dict)
    mentions: List[int] = field(default_factory=list)  # 出现的章节
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "entity_type": self.entity_type,
            "properties": self.properties,
            "mentions": self.mentions,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "Entity":
        return cls(**data)


@dataclass
class Relation:
    """关系边"""
    source_id: str
    target_id: str
    relation_type: str  # appears_with, owns, fights, loves, etc.
    properties: Dict = field(default_factory=dict)
    weight: float = 1.0
    
    def to_dict(self) -> Dict:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relation_type": self.relation_type,
            "properties": self.properties,
            "weight": self.weight,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "Relation":
        return cls(**data)


class KnowledgeGraph:
    """
    知识图谱
    
    使用内存图结构存储实体和关系，支持快速查询。
    """
    
    def __init__(self, project_id: int):
        """
        初始化知识图谱
        
        Args:
            project_id: 项目ID
        """
        self.project_id = project_id
        
        # 存储路径
        self.store_path = Path(config.vector_db.db_path) / f"project_{project_id}" / "knowledge_graph"
        self.store_path.mkdir(parents=True, exist_ok=True)
        
        # 实体和关系存储
        self._entities: Dict[str, Entity] = {}
        self._relations: List[Relation] = []
        
        # 索引
        self._entity_name_index: Dict[str, List[str]] = defaultdict(list)  # name -> [entity_ids]
        self._entity_type_index: Dict[str, List[str]] = defaultdict(list)  # type -> [entity_ids]
        self._relation_source_index: Dict[str, List[int]] = defaultdict(list)  # source_id -> [relation_indices]
        self._relation_target_index: Dict[str, List[int]] = defaultdict(list)  # target_id -> [relation_indices]
        
        # 加载已有数据
        self._load()
    
    def add_entity(self, entity: Entity) -> str:
        """
        添加实体
        
        Args:
            entity: 实体对象
            
        Returns:
            实体ID
        """
        # 检查是否已存在
        existing = self._find_entity_by_name(entity.name, entity.entity_type)
        if existing:
            # 合并信息
            existing.properties.update(entity.properties)
            existing.mentions = list(set(existing.mentions + entity.mentions))
            return existing.id
        
        # 生成ID
        if not entity.id:
            entity.id = f"{entity.entity_type}_{len(self._entities)}"
        
        # 存储
        self._entities[entity.id] = entity
        
        # 更新索引
        self._entity_name_index[entity.name].append(entity.id)
        self._entity_type_index[entity.entity_type].append(entity.id)
        
        return entity.id
    
    def add_relation(self, relation: Relation) -> None:
        """
        添加关系
        
        Args:
            relation: 关系对象
        """
        # 检查是否已存在
        existing = self._find_relation(
            relation.source_id, relation.target_id, relation.relation_type
        )
        if existing:
            # 增加权重
            existing.weight += 0.5
            existing.properties.update(relation.properties)
            return
        
        # 存储
        idx = len(self._relations)
        self._relations.append(relation)
        
        # 更新索引
        self._relation_source_index[relation.source_id].append(idx)
        self._relation_target_index[relation.target_id].append(idx)
    
    def get_entity(self, entity_id: str) -> Optional[Entity]:
        """获取实体"""
        return self._entities.get(entity_id)
    
    def get_entity_by_name(self, name: str, entity_type: Optional[str] = None) -> Optional[Entity]:
        """按名称获取实体"""
        entity_ids = self._entity_name_index.get(name, [])
        for eid in entity_ids:
            entity = self._entities.get(eid)
            if entity and (entity_type is None or entity.entity_type == entity_type):
                return entity
        return None
    
    def get_entities_by_type(self, entity_type: str) -> List[Entity]:
        """按类型获取实体"""
        entity_ids = self._entity_type_index.get(entity_type, [])
        return [self._entities[eid] for eid in entity_ids if eid in self._entities]
    
    def get_related_entities(
        self,
        entity_id: str,
        relation_type: Optional[str] = None,
        max_depth: int = 1,
    ) -> List[Tuple[Entity, str, float]]:
        """
        获取相关实体
        
        Args:
            entity_id: 实体ID
            relation_type: 关系类型（可选）
            max_depth: 最大深度
            
        Returns:
            [(实体, 关系类型, 权重), ...]
        """
        results = []
        visited = set()
        
        def _traverse(current_id: str, depth: int):
            if depth > max_depth or current_id in visited:
                return
            visited.add(current_id)
            
            # 获取出边
            for idx in self._relation_source_index.get(current_id, []):
                rel = self._relations[idx]
                if relation_type and rel.relation_type != relation_type:
                    continue
                
                target_entity = self._entities.get(rel.target_id)
                if target_entity:
                    results.append((target_entity, rel.relation_type, rel.weight))
                    _traverse(rel.target_id, depth + 1)
            
            # 获取入边
            for idx in self._relation_target_index.get(current_id, []):
                rel = self._relations[idx]
                if relation_type and rel.relation_type != relation_type:
                    continue
                
                source_entity = self._entities.get(rel.source_id)
                if source_entity:
                    results.append((source_entity, rel.relation_type, rel.weight))
                    _traverse(rel.source_id, depth + 1)
        
        _traverse(entity_id, 1)
        return results
    
    def find_path(
        self,
        source_id: str,
        target_id: str,
        max_depth: int = 3,
    ) -> Optional[List[Tuple[Entity, str]]]:
        """
        查找两个实体之间的路径
        
        Args:
            source_id: 起始实体ID
            target_id: 目标实体ID
            max_depth: 最大深度
            
        Returns:
            路径 [(实体, 关系), ...] 或 None
        """
        if source_id == target_id:
            return []
        
        # BFS
        queue = [(source_id, [])]
        visited = {source_id}
        
        while queue:
            current_id, path = queue.pop(0)
            
            if len(path) >= max_depth:
                continue
            
            # 获取所有邻居
            neighbors = []
            
            for idx in self._relation_source_index.get(current_id, []):
                rel = self._relations[idx]
                neighbors.append((rel.target_id, rel.relation_type))
            
            for idx in self._relation_target_index.get(current_id, []):
                rel = self._relations[idx]
                neighbors.append((rel.source_id, rel.relation_type))
            
            for neighbor_id, rel_type in neighbors:
                if neighbor_id in visited:
                    continue
                
                new_path = path + [(self._entities.get(neighbor_id), rel_type)]
                
                if neighbor_id == target_id:
                    return new_path
                
                visited.add(neighbor_id)
                queue.append((neighbor_id, new_path))
        
        return None
    
    def get_context_for_entity(
        self,
        entity_name: str,
        max_context_size: int = 500,
    ) -> str:
        """
        获取实体的上下文信息
        
        Args:
            entity_name: 实体名称
            max_context_size: 最大上下文大小
            
        Returns:
            上下文文本
        """
        entity = self.get_entity_by_name(entity_name)
        if not entity:
            return ""
        
        context_parts = []
        
        # 基本信息
        context_parts.append(f"【{entity.name}】")
        if entity.properties:
            for key, value in entity.properties.items():
                context_parts.append(f"{key}: {value}")
        
        # 相关实体
        related = self.get_related_entities(entity.id, max_depth=1)
        if related:
            context_parts.append("\n相关人物/物品:")
            for rel_entity, rel_type, weight in related[:5]:
                context_parts.append(f"- {rel_entity.name} ({rel_type})")
        
        context = "\n".join(context_parts)
        return context[:max_context_size]
    
    def get_chapter_context(
        self,
        chapter_number: int,
        max_size: int = 1000,
    ) -> str:
        """
        获取章节相关的图谱上下文
        
        Args:
            chapter_number: 章节号
            max_size: 最大大小
            
        Returns:
            上下文文本
        """
        # 找出本章出现的实体
        chapter_entities = []
        for entity in self._entities.values():
            if chapter_number in entity.mentions:
                chapter_entities.append(entity)
        
        if not chapter_entities:
            return ""
        
        context_parts = [f"【第{chapter_number}章 出场实体】"]
        
        # 按类型分组
        by_type = defaultdict(list)
        for entity in chapter_entities:
            by_type[entity.entity_type].append(entity)
        
        for entity_type, entities in by_type.items():
            type_name = {
                "character": "角色",
                "item": "物品",
                "location": "地点",
                "event": "事件",
            }.get(entity_type, entity_type)
            
            names = [e.name for e in entities[:5]]
            context_parts.append(f"{type_name}: {', '.join(names)}")
        
        # 实体间的关系
        relations_in_chapter = []
        entity_ids = {e.id for e in chapter_entities}
        
        for rel in self._relations:
            if rel.source_id in entity_ids or rel.target_id in entity_ids:
                source = self._entities.get(rel.source_id)
                target = self._entities.get(rel.target_id)
                if source and target:
                    relations_in_chapter.append(
                        f"{source.name} --{rel.relation_type}--> {target.name}"
                    )
        
        if relations_in_chapter:
            context_parts.append("\n实体关系:")
            context_parts.extend(relations_in_chapter[:10])
        
        context = "\n".join(context_parts)
        return context[:max_size]
    
    def _find_entity_by_name(self, name: str, entity_type: str) -> Optional[Entity]:
        """按名称和类型查找实体"""
        entity_ids = self._entity_name_index.get(name, [])
        for eid in entity_ids:
            entity = self._entities.get(eid)
            if entity and entity.entity_type == entity_type:
                return entity
        return None
    
    def _find_relation(
        self,
        source_id: str,
        target_id: str,
        relation_type: str,
    ) -> Optional[Relation]:
        """查找关系"""
        for idx in self._relation_source_index.get(source_id, []):
            rel = self._relations[idx]
            if rel.target_id == target_id and rel.relation_type == relation_type:
                return rel
        return None
    
    def _save(self):
        """保存到磁盘"""
        # 保存实体
        entities_file = self.store_path / "entities.json"
        entities_data = {eid: e.to_dict() for eid, e in self._entities.items()}
        with open(entities_file, "w", encoding="utf-8") as f:
            json.dump(entities_data, f, ensure_ascii=False, indent=2)
        
        # 保存关系
        relations_file = self.store_path / "relations.json"
        relations_data = [r.to_dict() for r in self._relations]
        with open(relations_file, "w", encoding="utf-8") as f:
            json.dump(relations_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"知识图谱已保存: {len(self._entities)} 实体, {len(self._relations)} 关系")
    
    def _load(self):
        """从磁盘加载"""
        # 加载实体
        entities_file = self.store_path / "entities.json"
        if entities_file.exists():
            try:
                with open(entities_file, "r", encoding="utf-8") as f:
                    entities_data = json.load(f)
                for eid, edata in entities_data.items():
                    entity = Entity.from_dict(edata)
                    self._entities[eid] = entity
                    self._entity_name_index[entity.name].append(eid)
                    self._entity_type_index[entity.entity_type].append(eid)
                logger.info(f"已加载 {len(self._entities)} 个实体")
            except Exception as e:
                logger.warning(f"加载实体失败: {e}")
        
        # 加载关系
        relations_file = self.store_path / "relations.json"
        if relations_file.exists():
            try:
                with open(relations_file, "r", encoding="utf-8") as f:
                    relations_data = json.load(f)
                for rdata in relations_data:
                    relation = Relation.from_dict(rdata)
                    idx = len(self._relations)
                    self._relations.append(relation)
                    self._relation_source_index[relation.source_id].append(idx)
                    self._relation_target_index[relation.target_id].append(idx)
                logger.info(f"已加载 {len(self._relations)} 个关系")
            except Exception as e:
                logger.warning(f"加载关系失败: {e}")
    
    @property
    def stats(self) -> Dict:
        """统计信息"""
        return {
            "entity_count": len(self._entities),
            "relation_count": len(self._relations),
            "entity_types": {
                t: len(ids) for t, ids in self._entity_type_index.items()
            },
        }


class EntityExtractor:
    """
    实体抽取器
    
    从文本中识别实体。
    """
    
    # 角色相关模式
    CHARACTER_PATTERNS = [
        r"(\w{2,4})(?:说|道|笑|怒|喝|问|叹|冷|哼)",
        r"(?:师父|师兄|师姐|师弟|师妹|长老|宗主|城主|国王)(\w{2,4})",
    ]
    
    # 物品相关模式
    ITEM_KEYWORDS = {
        "法宝": ["剑", "刀", "枪", "扇", "镜", "钟", "塔", "印"],
        "功法": ["诀", "法", "经", "典", "录"],
        "丹药": ["丹", "丸", "散", "膏"],
    }
    
    def __init__(self):
        """初始化实体抽取器"""
        import re
        self._patterns = [re.compile(p) for p in self.CHARACTER_PATTERNS]
    
    def extract(
        self,
        text: str,
        chapter_number: int = 0,
    ) -> Tuple[List[Entity], List[Relation]]:
        """
        从文本中抽取实体和关系
        
        Args:
            text: 文本内容
            chapter_number: 章节号
            
        Returns:
            (实体列表, 关系列表)
        """
        entities = []
        relations = []
        
        # 抽取角色
        characters = self._extract_characters(text, chapter_number)
        entities.extend(characters)
        
        # 抽取物品
        items = self._extract_items(text, chapter_number)
        entities.extend(items)
        
        # 抽取共现关系
        all_entity_names = [e.name for e in entities]
        co_occurrences = self._extract_co_occurrences(text, all_entity_names, chapter_number)
        relations.extend(co_occurrences)
        
        return entities, relations
    
    def _extract_characters(self, text: str, chapter_number: int) -> List[Entity]:
        """抽取角色实体"""
        characters = []
        seen = set()
        
        for pattern in self._patterns:
            matches = pattern.findall(text)
            for name in matches:
                if name and len(name) >= 2 and name not in seen:
                    seen.add(name)
                    entity = Entity(
                        id="",
                        name=name,
                        entity_type="character",
                        mentions=[chapter_number] if chapter_number else [],
                    )
                    characters.append(entity)
        
        return characters
    
    def _extract_items(self, text: str, chapter_number: int) -> List[Entity]:
        """抽取物品实体"""
        items = []
        seen = set()
        
        for item_type, keywords in self.ITEM_KEYWORDS.items():
            for keyword in keywords:
                # 查找 "XX keyword" 模式
                import re
                pattern = re.compile(rf'(\w{{2,6}}){keyword}')
                matches = pattern.findall(text)
                for name in matches:
                    full_name = name + keyword
                    if full_name not in seen:
                        seen.add(full_name)
                        entity = Entity(
                            id="",
                            name=full_name,
                            entity_type="item",
                            properties={"type": item_type},
                            mentions=[chapter_number] if chapter_number else [],
                        )
                        items.append(entity)
        
        return items
    
    def _extract_co_occurrences(
        self,
        text: str,
        entity_names: List[str],
        chapter_number: int,
    ) -> List[Relation]:
        """抽取共现关系"""
        relations = []
        
        # 将文本分句
        sentences = text.replace("。", ".").replace("！", ".").replace("？", ".").split(".")
        
        for sentence in sentences:
            # 找出本句中出现的实体
            present = [name for name in entity_names if name in sentence]
            
            # 创建共现关系
            for i in range(len(present)):
                for j in range(i + 1, len(present)):
                    relation = Relation(
                        source_id=present[i],
                        target_id=present[j],
                        relation_type="co_occurs",
                        properties={"chapter": chapter_number},
                    )
                    relations.append(relation)
        
        return relations


class GraphEnhancedRetriever:
    """
    图谱增强检索器
    
    结合知识图谱进行检索增强。
    """
    
    def __init__(
        self,
        knowledge_graph: KnowledgeGraph,
        vector_store=None,
    ):
        """
        初始化图谱增强检索器
        
        Args:
            knowledge_graph: 知识图谱
            vector_store: 向量存储
        """
        self.kg = knowledge_graph
        self.vector_store = vector_store
    
    def search(
        self,
        query: str,
        top_k: int = 8,
        context: Optional[Dict] = None,
    ) -> List[Dict]:
        """
        图谱增强搜索
        
        Args:
            query: 查询文本
            top_k: 返回结果数
            context: 上下文信息
            
        Returns:
            搜索结果列表
        """
        results = []
        
        # 1. 从查询中识别实体
        extracted_entities = self._extract_entities_from_query(query)
        
        # 2. 获取图谱上下文
        graph_context = self._get_graph_context(extracted_entities, context)
        
        # 3. 向量检索
        if self.vector_store:
            vector_results = self.vector_store.search(query, top_k)
            
            # 4. 图谱增强评分
            for result in vector_results:
                content = result.get("content", "")
                boost = self._calculate_graph_boost(content, extracted_entities)
                result["similarity"] = result.get("similarity", 0) * (1 + boost)
                result["graph_context"] = graph_context
                results.append(result)
        
        # 5. 排序
        results.sort(key=lambda x: x.get("similarity", 0), reverse=True)
        
        return results[:top_k]
    
    def _extract_entities_from_query(self, query: str) -> List[str]:
        """从查询中识别实体"""
        entities = []
        
        # 检查图谱中的实体
        for entity in self.kg._entities.values():
            if entity.name in query:
                entities.append(entity.name)
        
        return entities
    
    def _get_graph_context(
        self,
        entity_names: List[str],
        context: Optional[Dict],
    ) -> str:
        """获取图谱上下文"""
        if not entity_names:
            return ""
        
        context_parts = []
        
        for name in entity_names[:3]:  # 最多3个实体
            entity = self.kg.get_entity_by_name(name)
            if entity:
                # 获取实体上下文
                entity_context = self.kg.get_context_for_entity(name)
                if entity_context:
                    context_parts.append(entity_context)
        
        # 如果有章节信息，获取章节上下文
        if context and context.get("chapter_number"):
            chapter_context = self.kg.get_chapter_context(context["chapter_number"])
            if chapter_context:
                context_parts.append(chapter_context)
        
        return "\n\n".join(context_parts)[:1000]
    
    def _calculate_graph_boost(
        self,
        content: str,
        entity_names: List[str],
    ) -> float:
        """计算图谱增强分数"""
        boost = 0.0
        
        for name in entity_names:
            if name in content:
                # 内容包含实体，增加分数
                boost += 0.1
                
                # 检查实体的属性
                entity = self.kg.get_entity_by_name(name)
                if entity and entity.mentions:
                    # 实体在多个章节出现，增加分数
                    boost += min(0.1, len(entity.mentions) * 0.02)
        
        return min(0.5, boost)  # 限制最大增强
