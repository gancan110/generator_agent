"""
智能替换词引擎

提供多种替代方案解决当前硬编码替换词的问题：
1. 基于配置的动态同义词库
2. 基于LLM的上下文感知替换
3. 基于词向量的语义相似替换
4. 多策略融合方案
"""

import re
import json
import logging
from typing import Dict, List, Optional, Tuple, Callable
from pathlib import Path
from collections import defaultdict

logger = logging.getLogger(__name__)


# ============================================================
# 方案1: 可配置的动态同义词库
# ============================================================

class ConfigurableSynonymPool:
    """
    可配置的同义词池
    
    从JSON配置文件加载同义词，支持热更新和项目级覆盖。
    优点：易于维护、可扩展、支持多题材定制
    """
    
    DEFAULT_SYNONYMS = {
        # 动作类
        "猛地": ["霍然", "倏地", "陡然", "骤然", "忽地"],
        "咬紧牙关": ["攥紧拳头", "绷紧下颌", "死死撑住", "硬扛着"],
        "握紧拳头": ["攥紧五指", "指甲嵌入掌心", "拳头捏得咯咯响"],
        "深吸一口气": ["胸腔一扩", "鼻腔里灌进冷气", "屏住呼吸"],
        "瞳孔收缩": ["瞳孔骤缩", "目光一凝", "眼底骤紧"],
        
        # 表情类
        "嘴角勾起": ["唇角微扬", "嘴角微翘", "唇边泛起"],
        "眼中闪过": ["眸子里透出", "目光中掠过", "眼底闪过"],
        "冷冷道": ["淡漠开口", "声音冰冷", "语气淡然"],
        
        # 时间类
        "瞬间": ["刹那", "转瞬", "弹指间", "倏忽间", "须臾"],
        "一瞬间": ["这一刻", "下一秒", "刹那间", "紧接着"],
        "突然": ["骤然", "陡然", "猛地", "忽然"],
        
        # 比喻类
        "像是": ["仿佛", "好似", "犹如", "宛如", "恰似"],
        "就像": ["犹如", "仿佛", "好似", "宛如"],
        "仿佛": ["好像", "似乎", "宛如", "犹如"],
        
        # 描写类
        "嘴角微微上扬": ["唇角微翘", "唇边泛起笑意", "嘴角轻扬"],
        "嘴角抽搐": ["唇角一紧", "面部肌肉抽动", "脸上的肌肉一绷"],
    }
    
    def __init__(self, config_path: Optional[str] = None):
        """
        初始化同义词池
        
        Args:
            config_path: 配置文件路径（可选）
        """
        self.synonyms = dict(self.DEFAULT_SYNONYMS)
        self.custom_synonyms = {}
        
        if config_path and Path(config_path).exists():
            self._load_config(config_path)
    
    def _load_config(self, config_path: str):
        """从JSON文件加载配置"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            if 'synonyms' in config:
                self.custom_synonyms = config['synonyms']
                # 合并：自定义配置覆盖默认配置
                for key, values in self.custom_synonyms.items():
                    if key in self.synonyms:
                        self.synonyms[key].extend(values)
                    else:
                        self.synonyms[key] = values
            
            logger.info(f"已加载同义词配置: {config_path}")
        except Exception as e:
            logger.warning(f"加载同义词配置失败: {e}")
    
    def get_synonyms(self, word: str) -> List[str]:
        """获取词语的同义词列表"""
        return self.synonyms.get(word, [])
    
    def add_synonym(self, word: str, synonym: str):
        """动态添加同义词"""
        if word not in self.synonyms:
            self.synonyms[word] = []
        if synonym not in self.synonyms[word]:
            self.synonyms[word].append(synonym)
    
    def get_all_patterns(self) -> List[Tuple[str, List[str]]]:
        """获取所有替换模式"""
        return list(self.synonyms.items())


# ============================================================
# 方案2: 基于LLM的上下文感知替换
# ============================================================

class LLMContextualReplacer:
    """
    基于LLM的上下文感知替换
    
    利用LLM理解上下文语义，生成更自然的替换。
    优点：理解语境、生成多样、质量高
    缺点：速度慢、成本高
    """
    
    def __init__(self, llm_client=None):
        """
        初始化LLM替换器
        
        Args:
            llm_client: LLM客户端实例
        """
        self.llm_client = llm_client
        self._cache = {}  # 缓存已生成的替换
    
    def replace_with_context(
        self,
        content: str,
        target_words: List[str],
        max_replacements: int = 10,
    ) -> str:
        """
        基于上下文进行替换
        
        Args:
            content: 原文内容
            target_words: 需要替换的目标词列表
            max_replacements: 最大替换数量
            
        Returns:
            替换后的内容
        """
        if not self.llm_client:
            logger.warning("LLM客户端未初始化，跳过上下文替换")
            return content
        
        # 提取目标词出现的位置
        replacements_needed = []
        for word in target_words:
            count = content.count(word)
            if count > 2:  # 只处理高频词
                replacements_needed.append((word, count))
        
        if not replacements_needed:
            return content
        
        # 构建替换提示
        prompt = self._build_replacement_prompt(content, replacements_needed)
        
        try:
            response = self.llm_client.generate(
                prompt=prompt,
                system_prompt="你是一位中文写作专家，擅长用自然多样的表达替换重复词汇。",
                temperature=0.7,
                max_tokens=1024,
            )
            
            # 解析LLM返回的替换建议
            replacements = self._parse_replacement_suggestions(response)
            
            # 应用替换
            return self._apply_replacements(content, replacements, max_replacements)
            
        except Exception as e:
            logger.warning(f"LLM上下文替换失败: {e}")
            return content
    
    def _build_replacement_prompt(
        self,
        content: str,
        replacements_needed: List[Tuple[str, int]],
    ) -> str:
        """构建替换提示"""
        word_list = "、".join([f"{w}({c}次)" for w, c in replacements_needed])
        
        return f"""请对以下小说章节进行词汇替换，减少重复表达。

需要替换的高频词：{word_list}

要求：
1. 保持原文意思不变
2. 替换后的表达要自然流畅
3. 每个词提供2-3个替换方案
4. 根据上下文选择最合适的替换

原文（前2000字）：
{content[:2000]}

请以JSON格式输出替换建议：
{{
    "原词1": ["替换1", "替换2"],
    "原词2": ["替换1", "替换2"]
}}"""
    
    def _parse_replacement_suggestions(self, response: str) -> Dict[str, List[str]]:
        """解析LLM返回的替换建议"""
        try:
            # 提取JSON
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                return json.loads(json_match.group())
        except Exception as e:
            logger.warning(f"解析替换建议失败: {e}")
        
        return {}
    
    def _apply_replacements(
        self,
        content: str,
        replacements: Dict[str, List[str]],
        max_replacements: int,
    ) -> str:
        """应用替换"""
        count = 0
        for original, alternatives in replacements.items():
            if count >= max_replacements:
                break
            
            # 保留前1次，后续替换
            parts = content.split(original)
            if len(parts) <= 1:
                continue
            
            rebuilt = parts[0]
            for i, part in enumerate(parts[1:]):
                if i < 1:
                    rebuilt += original + part
                else:
                    alt = alternatives[(i - 1) % len(alternatives)]
                    rebuilt += alt + part
                    count += 1
            
            content = rebuilt
        
        return content


# ============================================================
# 方案3: 基于词向量的语义相似替换
# ============================================================

class SemanticSimilarityReplacer:
    """
    基于词向量的语义相似替换
    
    使用预训练的词向量模型找到语义相似的词进行替换。
    优点：无需LLM、速度快、可离线
    缺点：需要词向量模型、覆盖面有限
    """
    
    def __init__(self, embedding_model=None):
        """
        初始化语义替换器
        
        Args:
            embedding_model: 词向量模型
        """
        self.embedding_model = embedding_model
        self._word_cache = {}
    
    def find_similar_words(
        self,
        word: str,
        top_k: int = 5,
        exclude_words: Optional[List[str]] = None,
    ) -> List[str]:
        """
        查找语义相似的词
        
        Args:
            word: 目标词
            top_k: 返回数量
            exclude_words: 排除的词列表
            
        Returns:
            相似词列表
        """
        exclude_words = set(exclude_words or [])
        exclude_words.add(word)
        
        # 优先使用预定义的词库
        similar_words = self._get_predefined_similar(word)
        
        # 如果有embedding_model，可以进一步扩展
        if self.embedding_model and len(similar_words) < top_k:
            # 这里可以添加基于词向量的相似度计算
            pass
        
        return [w for w in similar_words if w not in exclude_words][:top_k]
    
    def _get_predefined_similar(self, word: str) -> List[str]:
        """获取预定义的相似词"""
        # 预定义的相似词映射（可以扩展）
        similar_map = {
            "猛地": ["霍然", "倏地", "陡然", "骤然"],
            "瞬间": ["刹那", "转瞬", "弹指间", "须臾"],
            "突然": ["骤然", "陡然", "忽然", "猛地"],
            "冷冷": ["淡漠", "冰冷", "淡然", "漠然"],
            "狠狠": ["重重", "使劲", "用力", "猛烈"],
            "轻轻": ["微微", "缓缓", "慢慢", "徐徐"],
            "紧紧": ["死死", "牢牢", "紧紧地"],
            "淡淡": ["轻轻", "微微", "浅浅"],
        }
        
        return similar_map.get(word, [])


# ============================================================
# 方案4: 多策略融合引擎
# ============================================================

class SmartReplacerEngine:
    """
    智能替换引擎 - 多策略融合
    
    融合多种替换策略，根据场景选择最佳方案：
    1. 高频固定模式 → 规则替换（快速）
    2. 中频变化模式 → 同义词轮换（平衡）
    3. 低频复杂模式 → LLM上下文替换（高质量）
    """
    
    def __init__(
        self,
        config_path: Optional[str] = None,
        llm_client=None,
        embedding_model=None,
    ):
        """
        初始化智能替换引擎
        
        Args:
            config_path: 同义词配置文件路径
            llm_client: LLM客户端
            embedding_model: 词向量模型
        """
        self.synonym_pool = ConfigurableSynonymPool(config_path)
        self.llm_replacer = LLMContextualReplacer(llm_client)
        self.semantic_replacer = SemanticSimilarityReplacer(embedding_model)
        
        # 替换策略优先级
        self.strategy_priority = ["rule", "synonym", "semantic", "llm"]
    
    def smart_replace(
        self,
        content: str,
        target_words: Optional[List[str]] = None,
        strategy: str = "auto",
        max_replacements: int = 20,
    ) -> str:
        """
        智能替换
        
        Args:
            content: 原文内容
            target_words: 目标词列表（可选）
            strategy: 策略选择 ("auto", "rule", "synonym", "llm", "semantic")
            max_replacements: 最大替换数量
            
        Returns:
            替换后的内容
        """
        if target_words is None:
            target_words = self._detect_high_frequency_words(content)
        
        if not target_words:
            return content
        
        count = 0
        
        for word in target_words:
            if count >= max_replacements:
                break
            
            word_count = content.count(word)
            if word_count <= 1:
                continue
            
            # 根据策略选择替换方法
            if strategy == "auto":
                # 自动策略：根据频率选择
                if word_count > 5:
                    # 高频：使用规则替换
                    content, n = self._apply_rule_replace(content, word)
                elif word_count > 2:
                    # 中频：使用同义词替换
                    content, n = self._apply_synonym_replace(content, word)
                else:
                    # 低频：使用语义替换
                    content, n = self._apply_semantic_replace(content, word)
            elif strategy == "rule":
                content, n = self._apply_rule_replace(content, word)
            elif strategy == "synonym":
                content, n = self._apply_synonym_replace(content, word)
            elif strategy == "semantic":
                content, n = self._apply_semantic_replace(content, word)
            elif strategy == "llm":
                content = self.llm_replacer.replace_with_context(
                    content, [word], max_replacements=5
                )
                n = 1
            else:
                n = 0
            
            count += n
        
        return content
    
    def _detect_high_frequency_words(
        self,
        content: str,
        threshold: int = 3,
    ) -> List[str]:
        """检测高频词"""
        # 常见AI高频词列表
        ai高频词 = [
            "猛地", "瞬间", "突然", "狠狠", "紧紧", "淡淡",
            "嘴角", "眼中", "瞳孔", "深吸一口气", "咬紧牙关",
            "像是", "就像", "仿佛", "冷冷道", "淡淡道",
        ]
        
        return [w for w in ai高频词 if content.count(w) > threshold]
    
    def _apply_rule_replace(
        self,
        content: str,
        word: str,
    ) -> Tuple[str, int]:
        """应用规则替换"""
        synonyms = self.synonym_pool.get_synonyms(word)
        if not synonyms:
            return content, 0
        
        # 保留前1次，后续替换
        parts = content.split(word)
        if len(parts) <= 1:
            return content, 0
        
        rebuilt = parts[0]
        count = 0
        for i, part in enumerate(parts[1:]):
            if i < 1:
                rebuilt += word + part
            else:
                alt = synonyms[(i - 1) % len(synonyms)]
                rebuilt += alt + part
                count += 1
        
        return rebuilt, count
    
    def _apply_synonym_replace(
        self,
        content: str,
        word: str,
    ) -> Tuple[str, int]:
        """应用同义词替换"""
        synonyms = self.semantic_replacer.find_similar_words(word, top_k=5)
        if not synonyms:
            synonyms = self.synonym_pool.get_synonyms(word)
        
        if not synonyms:
            return content, 0
        
        # 轮换替换
        parts = content.split(word)
        if len(parts) <= 1:
            return content, 0
        
        rebuilt = parts[0]
        count = 0
        for i, part in enumerate(parts[1:]):
            if i % 3 == 0:  # 保留33%
                rebuilt += word + part
            else:
                alt = synonyms[(i - 1) % len(synonyms)]
                rebuilt += alt + part
                count += 1
        
        return rebuilt, count
    
    def _apply_semantic_replace(
        self,
        content: str,
        word: str,
    ) -> Tuple[str, int]:
        """应用语义替换"""
        synonyms = self.semantic_replacer.find_similar_words(word, top_k=3)
        if not synonyms:
            return self._apply_synonym_replace(content, word)
        
        # 选择最合适的替换
        parts = content.split(word)
        if len(parts) <= 1:
            return content, 0
        
        rebuilt = parts[0]
        count = 0
        for i, part in enumerate(parts[1:]):
            if i < 2:  # 保留前2次
                rebuilt += word + part
            else:
                alt = synonyms[(i - 2) % len(synonyms)]
                rebuilt += alt + part
                count += 1
        
        return rebuilt, count


# ============================================================
# 方案5: 后处理链式引擎
# ============================================================

class PostProcessingChain:
    """
    后处理链式引擎
    
    将多个替换策略串联成处理链，按顺序执行。
    支持自定义链和预设链。
    """
    
    def __init__(self):
        self.chains = {}
        self._register_default_chains()
    
    def _register_default_chains(self):
        """注册默认处理链"""
        # 轻量级链：只做基础替换
        self.chains["light"] = [
            "rule_replace",
        ]
        
        # 标准链：规则 + 同义词
        self.chains["standard"] = [
            "rule_replace",
            "synonym_replace",
        ]
        
        # 完整链：规则 + 同义词 + 语义
        self.chains["full"] = [
            "rule_replace",
            "synonym_replace",
            "semantic_replace",
        ]
    
    def register_chain(self, name: str, steps: List[str]):
        """注册自定义处理链"""
        self.chains[name] = steps
    
    def execute(
        self,
        content: str,
        chain_name: str = "standard",
        engine: Optional[SmartReplacerEngine] = None,
    ) -> str:
        """
        执行处理链
        
        Args:
            content: 原文内容
            chain_name: 链名称
            engine: 替换引擎实例
            
        Returns:
            处理后的内容
        """
        if chain_name not in self.chains:
            logger.warning(f"未知的处理链: {chain_name}")
            return content
        
        if engine is None:
            engine = SmartReplacerEngine()
        
        steps = self.chains[chain_name]
        
        for step in steps:
            if step == "rule_replace":
                content = self._execute_rule_replace(content, engine)
            elif step == "synonym_replace":
                content = self._execute_synonym_replace(content, engine)
            elif step == "semantic_replace":
                content = self._execute_semantic_replace(content, engine)
            elif step == "llm_replace":
                content = self._execute_llm_replace(content, engine)
        
        return content
    
    def _execute_rule_replace(
        self,
        content: str,
        engine: SmartReplacerEngine,
    ) -> str:
        """执行规则替换"""
        for word, synonyms in engine.synonym_pool.get_all_patterns():
            content, _ = engine._apply_rule_replace(content, word)
        return content
    
    def _execute_synonym_replace(
        self,
        content: str,
        engine: SmartReplacerEngine,
    ) -> str:
        """执行同义词替换"""
        high_freq_words = engine._detect_high_frequency_words(content, threshold=2)
        for word in high_freq_words:
            content, _ = engine._apply_synonym_replace(content, word)
        return content
    
    def _execute_semantic_replace(
        self,
        content: str,
        engine: SmartReplacerEngine,
    ) -> str:
        """执行语义替换"""
        high_freq_words = engine._detect_high_frequency_words(content, threshold=3)
        for word in high_freq_words:
            content, _ = engine._apply_semantic_replace(content, word)
        return content
    
    def _execute_llm_replace(
        self,
        content: str,
        engine: SmartReplacerEngine,
    ) -> str:
        """执行LLM替换"""
        return engine.llm_replacer.replace_with_context(content, max_replacements=10)
