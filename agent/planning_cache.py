"""
=============================================================================
Planning Cache — Agentic RAG 规划缓存优化模块
=============================================================================

核心思路:
  同类问题的规划逻辑高度同质化, 将通用规划步骤提炼为模板缓存(而非缓存答案),
  以此跳过重复的大模型规划过程。

三步法:
  Step 1 (Intent Extract): 轻量模型提取用户问题的高层意图关键词
  Step 2 (Template Match):  匹配缓存模板, 若命中则由轻量模型替换占位符
  Step 3 (Fallback+Learn):  未命中则走完整大模型规划, 执行后自动提取新模板

效果预期:
  - 成本降低 ~50% (规划阶段从 Qwen-Max 降为 Qwen2.5-14B)
  - 延迟降低 ~30% (跳过 1-2 轮大模型规划调用)
  - 准确率维持 ~97% (同类问题规划逻辑同质化)

参考:
  视频 "规划缓存的 Agentic RAG 优化技巧"
=============================================================================
"""

import json
import time
import hashlib
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from collections import OrderedDict

from langchain_core.messages import HumanMessage, SystemMessage

# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class PlanningTemplate:
    """单个规划模板"""

    template_id: str                          # 唯一标识 (hash)
    intent_category: str                      # 意图类别
    intent_keywords: List[str]                # 匹配关键词
    description: str                          # 模板描述

    # 预计算的规划结果 (含占位符)
    todo_list_template: List[str] = field(default_factory=list)
    subagent_dispatch_order: List[Dict[str, str]] = field(default_factory=list)
    # e.g. [{"agent": "网络搜索助手", "purpose": "搜索{entity}的行业趋势"},
    #        {"agent": "数据库查询助手", "purpose": "查询{entity}的详细数据"}]

    output_strategy: str = "text"             # "text" | "markdown" | "pdf"

    # 统计信息
    hit_count: int = 0
    created_at: float = 0.0
    last_hit_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "template_id": self.template_id,
            "intent_category": self.intent_category,
            "intent_keywords": self.intent_keywords,
            "description": self.description,
            "todo_list_template": self.todo_list_template,
            "subagent_dispatch_order": self.subagent_dispatch_order,
            "output_strategy": self.output_strategy,
            "hit_count": self.hit_count,
            "created_at": self.created_at,
            "last_hit_at": self.last_hit_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PlanningTemplate":
        return cls(
            template_id=data["template_id"],
            intent_category=data["intent_category"],
            intent_keywords=data["intent_keywords"],
            description=data["description"],
            todo_list_template=data.get("todo_list_template", []),
            subagent_dispatch_order=data.get("subagent_dispatch_order", []),
            output_strategy=data.get("output_strategy", "text"),
            hit_count=data.get("hit_count", 0),
            created_at=data.get("created_at", 0.0),
            last_hit_at=data.get("last_hit_at", 0.0),
        )


@dataclass
class IntentResult:
    """意图提取结果"""
    category: str                             # 意图类别
    keywords: Dict[str, str]                  # 提取的关键词 (key→value)
    output_type: str                          # "text" | "markdown" | "pdf"
    original_query: str                       # 原始查询
    confidence: float = 1.0                   # 置信度


@dataclass
class CacheHitResult:
    """缓存命中结果"""
    hit: bool
    template: Optional[PlanningTemplate] = None
    filled_plan: Optional[Dict[str, Any]] = None  # 替换占位符后的完整规划
    match_score: float = 0.0
    skipped_llm_calls: int = 0                 # 跳过的LLM调用次数


# =============================================================================
# Intent Extractor — 基于轻量模型的意图提取
# =============================================================================

INTENT_EXTRACT_SYSTEM_PROMPT = """你是一个查询意图分类器。分析用户查询, 输出JSON格式的分类结果。

## 意图类别 (intent_category)
- web_search: 查询公开信息、行业趋势、新闻、竞品
- database_query: 查询企业数据库中的具体数据(药品信息/库存/销售)
- rag_query: 查询企业内部知识库中的文档(SOP/技术手册/内部策略)
- mixed_web_db: 需要网络搜索+数据库查询
- mixed_web_rag: 需要网络搜索+知识库查询
- mixed_all: 需要三种数据源全部使用
- document_generation: 用户明确要求生成文件(Markdown/PDF)
- file_analysis: 用户上传了文件需要分析

## 关键词提取规则
- entity: 核心实体(公司名/产品名/药品名/品牌名)
- topic: 查询主题(市场趋势/竞品分析/库存/安装/SOP)
- time_range: 时间范围(如有)
- filter_condition: 筛选条件(如有, 如"库存低于100")
- output_format: 输出格式要求(如有, 如"PDF"/"表格形式")

## 输出格式
```json
{
    "category": "意图类别",
    "keywords": {
        "entity": "实体名或空字符串",
        "topic": "主题或空字符串",
        "time_range": "时间范围或空字符串",
        "filter_condition": "筛选条件或空字符串",
        "output_format": "输出格式或空字符串"
    },
    "output_type": "text 或 markdown 或 pdf",
    "reasoning": "简短的分类理由"
}
```
"""


class IntentExtractor:
    """
    基于轻量模型的意图提取器。

    使用 Qwen2.5-14B 替代 Qwen-Max 进行意图分类和关键词提取,
    成本降低 ~90%, 延迟降低 ~70%。
    """

    def __init__(self, lightweight_model):
        self.model = lightweight_model

    def extract(self, user_query: str) -> IntentResult:
        """从用户查询中提取意图和关键词"""
        messages = [
            SystemMessage(content=INTENT_EXTRACT_SYSTEM_PROMPT),
            HumanMessage(content=f"用户查询: {user_query}")
        ]

        start = time.time()
        response = self.model.invoke(messages)
        elapsed = time.time() - start

        # 尝试多种解析策略
        content = response.content.strip()

        # 去除可能的 markdown 代码块标记
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            # 回退: 尝试从文本中提取JSON
            import re
            match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    data = self._fallback_parse(user_query)
            else:
                data = self._fallback_parse(user_query)

        keywords = data.get("keywords", {})
        # 确保必要字段存在
        for key in ["entity", "topic", "time_range", "filter_condition", "output_format"]:
            if key not in keywords:
                keywords[key] = ""

        return IntentResult(
            category=data.get("category", "web_search"),
            keywords=keywords,
            output_type=data.get("output_type", "text"),
            original_query=user_query,
            confidence=data.get("confidence", 0.85),
        )

    def _fallback_parse(self, user_query: str) -> dict:
        """规则回退: 当 JSON 解析失败时的简单意图推断"""
        query_lower = user_query.lower()

        # 简单的关键词匹配
        category = "web_search"
        if any(w in query_lower for w in ["库存", "销售", "价格", "药品", "药物", "查询", "sql"]):
            category = "database_query"
        if any(w in query_lower for w in ["sop", "安装", "手册", "规范", "知识库"]):
            category = "rag_query"
        if any(w in query_lower for w in ["生成", "报告", "pdf", "markdown", "文档", "文件"]):
            category = "document_generation"
        if any(w in query_lower for w in ["竞品", "对比", "比较", "优劣"]):
            category = "mixed_all"
        if any(w in query_lower for w in ["趋势", "市场", "行业", "动态"]):
            category = "web_search"

        return {
            "category": category,
            "keywords": {
                "entity": "",
                "topic": "",
                "time_range": "",
                "filter_condition": "",
                "output_format": "",
            },
            "output_type": "pdf" if "pdf" in query_lower else "text",
        }


# =============================================================================
# Template Cache — 模板存储与匹配
# =============================================================================

class TemplateCache:
    """
    规划模板缓存。

    特性:
    - LRU 淘汰策略 (max 100 个模板)
    - 基于关键词重合度的匹配算法
    - 持久化到 JSON 文件 (跨重启保持)
    - 线程安全
    """

    MAX_CACHE_SIZE = 100
    MATCH_THRESHOLD = 0.55       # 关键词重合度阈值

    def __init__(self, storage_path: Optional[Path] = None):
        self._lock = threading.Lock()
        self._cache: OrderedDict[str, PlanningTemplate] = OrderedDict()

        # 存储路径
        if storage_path is None:
            storage_path = Path(__file__).parent.parent / "data" / "planning_templates.json"
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        # 加载已有模板
        self._load_from_disk()

    # -------- CRUD --------

    def get(self, template_id: str) -> Optional[PlanningTemplate]:
        with self._lock:
            return self._cache.get(template_id)

    def put(self, template: PlanningTemplate):
        with self._lock:
            # LRU 淘汰
            if len(self._cache) >= self.MAX_CACHE_SIZE:
                self._cache.popitem(last=False)  # 淘汰最久未使用的
            self._cache[template.template_id] = template
            self._cache.move_to_end(template.template_id)

    def remove(self, template_id: str):
        with self._lock:
            self._cache.pop(template_id, None)

    def size(self) -> int:
        return len(self._cache)

    # -------- Matching --------

    def match(self, intent: IntentResult) -> CacheHitResult:
        """
        根据意图匹配最佳模板。

        匹配算法:
        1. 首先按 intent_category 过滤候选模板
        2. 计算关键词重合度 (Jaccard-like)
        3. 选择最高分且超过阈值的模板
        """
        with self._lock:
            candidates = [
                t for t in self._cache.values()
                if t.intent_category == intent.category
            ]

            if not candidates:
                return CacheHitResult(hit=False)

            best_template = None
            best_score = 0.0

            for template in candidates:
                score = self._calculate_match_score(intent, template)
                if score > best_score:
                    best_score = score
                    best_template = template

            if best_template and best_score >= self.MATCH_THRESHOLD:
                best_template.hit_count += 1
                best_template.last_hit_at = time.time()
                self._cache.move_to_end(best_template.template_id)

                # 估算跳过的 LLM 调用次数 (规划阶段通常 2-3 轮)
                skipped = 2 if intent.category == "document_generation" else 1

                return CacheHitResult(
                    hit=True,
                    template=best_template,
                    match_score=best_score,
                    skipped_llm_calls=skipped,
                )

            return CacheHitResult(hit=False, match_score=best_score)

    def _calculate_match_score(self, intent: IntentResult, template: PlanningTemplate) -> float:
        """计算意图与模板的匹配分数 (0-1)"""

        # 1. 类别精确匹配 (基础 0.3)
        score = 0.3 if intent.category == template.intent_category else 0.0

        # 2. 关键词重合度 (0-0.5)
        intent_keywords_set = set()
        for v in intent.keywords.values():
            if v:
                # 分词 (简单按空格和常见分隔符)
                for token in v.replace(",", " ").replace("，", " ").replace("、", " ").split():
                    if len(token) >= 2:
                        intent_keywords_set.add(token.lower())

        template_keywords_set = set(k.lower() for k in template.intent_keywords)

        if intent_keywords_set and template_keywords_set:
            intersection = intent_keywords_set & template_keywords_set
            union = intent_keywords_set | template_keywords_set
            keyword_score = len(intersection) / len(union) if union else 0
            score += keyword_score * 0.5

        # 3. 输出类型匹配 (0-0.2)
        if intent.output_type == template.output_strategy:
            score += 0.2

        return min(score, 1.0)

    # -------- Template Extraction --------

    def extract_template_from_execution(
        self,
        intent: IntentResult,
        agent_trace: Dict[str, Any],
    ) -> PlanningTemplate:
        """
        从一次完整的 Agent 执行中提取新的规划模板。

        输入:
        - intent: 意图提取结果
        - agent_trace: Agent 执行的完整记录, 包含:
            {
                "todo_list": ["步骤1", "步骤2", ...],
                "subagent_calls": [
                    {"agent": "网络搜索助手", "purpose": "搜索空调行业趋势"},
                    ...
                ],
                "output_type": "pdf" 或 "text" 或 "markdown"
            }
        """
        # 生成模板 ID
        raw_id = f"{intent.category}:{intent.keywords.get('topic','')}:{intent.output_type}"
        template_id = hashlib.md5(raw_id.encode()).hexdigest()[:12]

        # 提取关键词列表 (用于后续匹配)
        all_keywords = []
        for v in intent.keywords.values():
            if v:
                for token in v.replace(",", " ").replace("，", " ").replace("、", " ").split():
                    if len(token) >= 2:
                        all_keywords.append(token)

        # 泛化 todo-list (将具体实体名替换为占位符)
        todo_template = self._generalize_todo_list(
            agent_trace.get("todo_list", []),
            intent
        )

        # 泛化子Agent调度
        dispatch_template = self._generalize_dispatch_order(
            agent_trace.get("subagent_calls", []),
            intent
        )

        template = PlanningTemplate(
            template_id=template_id,
            intent_category=intent.category,
            intent_keywords=all_keywords,
            description=f"自动提取: {intent.category} - {intent.keywords.get('topic', 'general')}",
            todo_list_template=todo_template,
            subagent_dispatch_order=dispatch_template,
            output_strategy=intent.output_type,
            hit_count=0,
            created_at=time.time(),
            last_hit_at=time.time(),
        )

        return template

    def _generalize_todo_list(self, todo_list: List[str], intent: IntentResult) -> List[str]:
        """将 todo-list 中的具体实体替换为占位符"""
        generalized = []
        entity = intent.keywords.get("entity", "")
        topic = intent.keywords.get("topic", "")

        for step in todo_list:
            s = step
            if entity:
                s = s.replace(entity, "{entity}")
            if topic:
                s = s.replace(topic, "{topic}")
            # 通用模式替换
            import re
            s = re.sub(r'\d{4}年', '{year}年', s)
            s = re.sub(r'\d{4}-\d{4}年', '{year_range}年', s)
            generalized.append(s)

        return generalized if generalized else todo_list

    def _generalize_dispatch_order(
        self, dispatch_order: List[Dict[str, str]], intent: IntentResult
    ) -> List[Dict[str, str]]:
        """将调度顺序中的具体实体替换为占位符"""
        generalized = []
        entity = intent.keywords.get("entity", "")

        for item in dispatch_order:
            g_item = dict(item)
            if entity and "purpose" in g_item:
                g_item["purpose"] = g_item["purpose"].replace(entity, "{entity}")
            if "description" in g_item:
                if entity:
                    g_item["description"] = g_item["description"].replace(entity, "{entity}")
                import re
                g_item["description"] = re.sub(r'\d{4}年', '{year}年', g_item["description"])
            generalized.append(g_item)

        return generalized if generalized else dispatch_order

    # -------- Persistence --------

    def _load_from_disk(self):
        """从 JSON 文件加载模板"""
        if not self.storage_path.exists():
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                template = PlanningTemplate.from_dict(item)
                self._cache[template.template_id] = template
            # 按 hit_count 排序
            self._cache = OrderedDict(
                sorted(self._cache.items(), key=lambda x: x[1].hit_count)
            )
        except Exception as e:
            print(f"[PlanningCache] 加载模板失败: {e}")

    def save_to_disk(self):
        """持久化到 JSON 文件"""
        with self._lock:
            data = [t.to_dict() for t in self._cache.values()]
        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def get_stats(self) -> dict:
        """获取缓存统计"""
        with self._lock:
            return {
                "total_templates": len(self._cache),
                "total_hits": sum(t.hit_count for t in self._cache.values()),
                "categories": {
                    cat: len([t for t in self._cache.values() if t.intent_category == cat])
                    for cat in set(t.intent_category for t in self._cache.values())
                },
                "top_templates": sorted(
                    [{"id": t.template_id, "desc": t.description, "hits": t.hit_count}
                     for t in self._cache.values()],
                    key=lambda x: x["hits"], reverse=True
                )[:5],
            }


# =============================================================================
# Template Filler — 占位符填充
# =============================================================================

TEMPLATE_FILL_SYSTEM_PROMPT = """你是一个模板填充助手。根据用户查询中的具体信息, 填充规划模板中的占位符。

## 占位符说明
- {entity}: 用户查询中的核心实体 (公司名/产品名/药品名)
- {topic}: 查询主题
- {year}: 具体年份
- {year_range}: 年份范围
- {filter_condition}: 筛选条件
- {query}: 用户的原始查询

## 你只需要输出填充后的 JSON, 不要输出任何其他内容。
"""


class TemplateFiller:
    """
    模板占位符填充器。

    使用轻量模型将模板中的占位符替换为具体值,
    生成可直接执行的规划指令。
    """

    def __init__(self, lightweight_model):
        self.model = lightweight_model

    def fill(
        self, template: PlanningTemplate, intent: IntentResult
    ) -> Dict[str, Any]:
        """
        将模板占位符替换为具体值, 输出完整规划。
        """

        # 策略1: 简单字符串替换 (适用于大部分场景)
        replacements = {
            "{query}": intent.original_query,
            "{entity}": intent.keywords.get("entity", ""),
            "{topic}": intent.keywords.get("topic", ""),
            "{year}": intent.keywords.get("time_range", "").split("-")[0] if "-" in intent.keywords.get("time_range", "") else intent.keywords.get("time_range", ""),
            "{year_range}": intent.keywords.get("time_range", ""),
            "{filter_condition}": intent.keywords.get("filter_condition", ""),
            "{output_format}": intent.keywords.get("output_format", ""),
        }

        # 填充 todo-list
        filled_todo = []
        for step in template.todo_list_template:
            filled_step = step
            for placeholder, value in replacements.items():
                if value:
                    filled_step = filled_step.replace(placeholder, value)
            filled_todo.append(filled_step)

        # 填充调度顺序
        filled_dispatch = []
        for item in template.subagent_dispatch_order:
            filled_item = dict(item)
            for placeholder, value in replacements.items():
                if value:
                    for key in filled_item:
                        if isinstance(filled_item[key], str):
                            filled_item[key] = filled_item[key].replace(placeholder, value)
            filled_dispatch.append(filled_item)

        # 策略2: 若有复杂的未替换占位符, 用 LLM 补充
        has_unfilled = any(
            "{" in step for step in filled_todo
        ) or any(
            "{" in str(item.get("purpose", "")) for item in filled_dispatch
        )

        if has_unfilled:
            filled_todo, filled_dispatch = self._llm_fill(
                template, intent, filled_todo, filled_dispatch
            )

        return {
            "plan_type": "cached",
            "template_id": template.template_id,
            "intent_category": intent.category,
            "todo_list": filled_todo,
            "subagent_dispatch": filled_dispatch,
            "output_strategy": template.output_strategy,
        }

    def _llm_fill(self, template, intent, partial_todo, partial_dispatch):
        """当简单替换不够时, 使用轻量模型补充填充"""
        prompt = f"""填充以下模板中剩余的占位符。

## 原始查询
{intent.original_query}

## 当前 todo-list (可能仍含占位符)
{json.dumps(partial_todo, ensure_ascii=False, indent=2)}

## 当前调度计划 (可能仍含占位符)
{json.dumps(partial_dispatch, ensure_ascii=False, indent=2)}

## 提取的关键词
{json.dumps(intent.keywords, ensure_ascii=False)}

## 输出格式
```json
{{
    "todo_list": ["完整的步骤1", "完整的步骤2", ...],
    "subagent_dispatch": [...]
}}
```
"""
        messages = [
            SystemMessage(content=TEMPLATE_FILL_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        try:
            response = self.model.invoke(messages)
            content = response.content.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            data = json.loads(content)
            return data.get("todo_list", partial_todo), data.get("subagent_dispatch", partial_dispatch)
        except Exception:
            # 回退: 保留部分填充结果
            return partial_todo, partial_dispatch


# =============================================================================
# PlanningCacheMiddleware — 集成入口
# =============================================================================

class PlanningCacheMiddleware:
    """
    规划缓存中间件 — 对外统一接口。

    用法:
        from agent.planning_cache import PlanningCacheMiddleware, create_planning_cache

        cache = create_planning_cache()
        result = cache.process(user_query)

        if result.hit:
            # 直接使用 result.filled_plan 中的预计算规划
            # 跳过主模型规划阶段, 直接执行
            ...
        else:
            # 走正常流程: 主模型规划 → 执行 → 记录 trace
            trace = normal_agent_execution(user_query)
            cache.learn_from_execution(user_query, trace)
    """

    def __init__(
        self,
        extractor: IntentExtractor,
        template_cache: TemplateCache,
        filler: TemplateFiller,
    ):
        self.extractor = extractor
        self.cache = template_cache
        self.filler = filler

        # 统计
        self.total_queries = 0
        self.cache_hits = 0
        self.total_llm_calls_skipped = 0

    def process(self, user_query: str) -> Tuple[IntentResult, CacheHitResult]:
        """
        处理用户查询: 提取意图 → 匹配模板 → (命中则)填充占位符。

        Returns:
            (intent, cache_result)
        """
        self.total_queries += 1

        # Step 1: 轻量模型提取意图
        intent = self.extractor.extract(user_query)

        # Step 2: 匹配缓存模板
        cache_result = self.cache.match(intent)

        # Step 3: 若命中, 填充占位符
        if cache_result.hit and cache_result.template:
            filled_plan = self.filler.fill(cache_result.template, intent)
            cache_result.filled_plan = filled_plan
            self.cache_hits += 1
            self.total_llm_calls_skipped += cache_result.skipped_llm_calls

        return intent, cache_result

    def learn_from_execution(
        self, intent: IntentResult, agent_trace: Dict[str, Any]
    ) -> Optional[PlanningTemplate]:
        """
        从一次完整执行中学习新模板 (未命中时调用)。

        输入 agent_trace:
        {
            "todo_list": [...],
            "subagent_calls": [
                {"agent": "网络搜索助手", "purpose": "..."},
                ...
            ],
            "output_type": "pdf"
        }
        """
        new_template = self.cache.extract_template_from_execution(intent, agent_trace)
        self.cache.put(new_template)
        self.cache.save_to_disk()
        return new_template

    def get_stats(self) -> dict:
        """获取运行统计"""
        cache_stats = self.cache.get_stats()
        hit_rate = self.cache_hits / self.total_queries if self.total_queries > 0 else 0
        return {
            **cache_stats,
            "total_queries": self.total_queries,
            "cache_hits": self.cache_hits,
            "hit_rate": f"{hit_rate:.1%}",
            "llm_calls_skipped": self.total_llm_calls_skipped,
        }


# =============================================================================
# Factory
# =============================================================================

_planning_cache_instance: Optional[PlanningCacheMiddleware] = None


def create_planning_cache(
    lightweight_model=None,
    storage_path: Optional[Path] = None,
) -> PlanningCacheMiddleware:
    """
    创建或获取 PlanningCacheMiddleware 单例。

    首次调用会初始化:
    - IntentExtractor (轻量模型)
    - TemplateCache (内存缓存 + JSON 持久化)
    - TemplateFiller
    - 自动加载冷启动模板
    """
    global _planning_cache_instance

    if _planning_cache_instance is not None:
        return _planning_cache_instance

    if lightweight_model is None:
        from agent.llm import lightweight_model as lw_model
        lightweight_model = lw_model

    extractor = IntentExtractor(lightweight_model)
    template_cache = TemplateCache(storage_path=storage_path)
    filler = TemplateFiller(lightweight_model)

    middleware = PlanningCacheMiddleware(
        extractor=extractor,
        template_cache=template_cache,
        filler=filler,
    )

    # 加载冷启动模板 (如果缓存为空)
    if template_cache.size() == 0:
        from agent.cold_start_templates import load_cold_start_templates
        load_cold_start_templates(template_cache)

    _planning_cache_instance = middleware
    return middleware


def get_planning_cache() -> Optional[PlanningCacheMiddleware]:
    """获取已初始化的 PlanningCacheMiddleware 实例"""
    global _planning_cache_instance
    return _planning_cache_instance
