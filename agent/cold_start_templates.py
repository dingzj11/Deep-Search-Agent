"""
=============================================================================
冷启动模板库 — 15个高频场景的预置规划模板

这些模板覆盖了空调/医药企业的常见查询场景, 确保系统在第一天就有可用的缓存。
运行1-2周后, 自动学习的模板会逐步覆盖更多长尾场景。
=============================================================================
"""

import hashlib
import time
from .planning_cache import PlanningTemplate, TemplateCache


COLD_START_TEMPLATES = [
    # ============================================================
    # 类别 1: 网络搜索 (4个模板)
    # ============================================================

    # T1: 行业趋势搜索
    {
        "intent_category": "web_search",
        "intent_keywords": ["行业", "趋势", "发展", "市场", "规模", "前景", "2024", "2025", "空调"],
        "description": "搜索行业发展/市场趋势/规模/前景类信息",
        "todo_list_template": [
            "1. 分析用户查询, 确定搜索的关键词和时间范围",
            "2. 从至少3个角度搜索{entity}{topic}的相关信息",
            "3. 整合搜索结果, 提取市场规模、技术趋势、政策环境等关键数据",
            "4. 以结构化方式呈现搜索结果, 标注信息来源",
        ],
        "subagent_dispatch_order": [
            {"agent": "网络搜索助手", "purpose": "从市场规模角度搜索{entity}{topic}的最新数据"},
            {"agent": "网络搜索助手", "purpose": "从技术趋势角度搜索{entity}{topic}的发展"},
            {"agent": "网络搜索助手", "purpose": "从政策环境角度搜索{entity}{topic}的相关法规"},
        ],
        "output_strategy": "text",
    },

    # T2: 竞品信息搜索
    {
        "intent_category": "web_search",
        "intent_keywords": ["竞品", "对比", "对手", "格力", "美的", "海尔", "产品", "价格"],
        "description": "搜索竞品/竞争对手的产品信息和市场动态",
        "todo_list_template": [
            "1. 识别用户关注的竞品品牌/产品",
            "2. 搜索{entity}的产品信息、价格、技术参数",
            "3. 搜索{entity}的市场表现和用户评价",
            "4. 整理竞品信息, 标注信息来源",
        ],
        "subagent_dispatch_order": [
            {"agent": "网络搜索助手", "purpose": "搜索{entity}的最新产品信息和规格参数"},
            {"agent": "网络搜索助手", "purpose": "搜索{entity}的市场定价和渠道策略"},
            {"agent": "网络搜索助手", "purpose": "搜索{entity}的用户评价和口碑"},
        ],
        "output_strategy": "text",
    },

    # T3: 政策法规搜索
    {
        "intent_category": "web_search",
        "intent_keywords": ["政策", "法规", "标准", "能效", "环保", "补贴", "规定"],
        "description": "搜索行业政策/法规/标准类信息",
        "todo_list_template": [
            "1. 确定用户关注的政策/法规领域",
            "2. 搜索{entity}相关的最新政策法规",
            "3. 搜索政策对企业的影响分析",
            "4. 整理政策要点和影响评估",
        ],
        "subagent_dispatch_order": [
            {"agent": "网络搜索助手", "purpose": "搜索{entity}领域最新政策法规"},
            {"agent": "网络搜索助手", "purpose": "搜索政策对{entity}行业的影响分析"},
            {"agent": "网络搜索助手", "purpose": "搜索{entity}相关补贴和扶持政策"},
        ],
        "output_strategy": "text",
    },

    # T4: 综合行业信息搜索
    {
        "intent_category": "web_search",
        "intent_keywords": ["最新", "动态", "新闻", "技术", "创新", "突破", "发展"],
        "description": "搜索行业最新动态/新闻/技术进展",
        "todo_list_template": [
            "1. 确定用户关注的信息类型和时间范围",
            "2. 从至少3个角度搜索{entity}{topic}的最新动态",
            "3. 筛选高价值信息, 排除广告和无意义内容",
            "4. 按重要性/时效性整理搜索结果",
        ],
        "subagent_dispatch_order": [
            {"agent": "网络搜索助手", "purpose": "搜索{entity}{topic}最新新闻"},
            {"agent": "网络搜索助手", "purpose": "搜索{entity}{topic}技术突破"},
            {"agent": "网络搜索助手", "purpose": "搜索{entity}{topic}市场动态"},
        ],
        "output_strategy": "text",
    },

    # ============================================================
    # 类别 2: 数据库查询 (3个模板)
    # ============================================================

    # T5: 库存状态查询
    {
        "intent_category": "database_query",
        "intent_keywords": ["库存", "数量", "剩余", "库存量", "低于", "缺货", "不足"],
        "description": "查询药品/产品库存状态",
        "todo_list_template": [
            "1. 列出数据库可用表, 确定库存相关表",
            "2. 预览库存表结构, 了解字段含义",
            "3. 编写SQL查询{filter_condition}的库存数据",
            "4. 以表格形式呈现查询结果",
        ],
        "subagent_dispatch_order": [
            {"agent": "数据库查询助手", "purpose": "查询数据库中{entity}的库存信息, 筛选条件: {filter_condition}"},
        ],
        "output_strategy": "text",
    },

    # T6: 销售数据分析
    {
        "intent_category": "database_query",
        "intent_keywords": ["销售", "销量", "销售额", "卖", "收入", "业绩", "统计"],
        "description": "查询销售数据和统计分析",
        "todo_list_template": [
            "1. 列出数据库可用表, 确定销售相关表",
            "2. 预览销售表结构, 了解字段和关联关系",
            "3. 编写带JOIN的SQL查询销售数据",
            "4. 计算汇总统计(总量/趋势/排行)",
            "5. 以表格形式呈现分析结果",
        ],
        "subagent_dispatch_order": [
            {"agent": "数据库查询助手", "purpose": "查询{time_range}的销售数据, 按{entity}维度汇总分析"},
        ],
        "output_strategy": "text",
    },

    # T7: 产品详细信息查询
    {
        "intent_category": "database_query",
        "intent_keywords": ["药品", "药物", "产品", "规格", "价格", "信息", "详情", "分类"],
        "description": "查询产品/药品的详细信息",
        "todo_list_template": [
            "1. 列出数据库可用表, 确定产品信息表",
            "2. 预览产品表结构",
            "3. 编写SQL查询{entity}的详细信息",
            "4. 格式化呈现产品信息",
        ],
        "subagent_dispatch_order": [
            {"agent": "数据库查询助手", "purpose": "查询{entity}的详细信息(规格/价格/分类等)"},
        ],
        "output_strategy": "text",
    },

    # ============================================================
    # 类别 3: RAGFlow 知识库查询 (2个模板)
    # ============================================================

    # T8: SOP/操作规范查询
    {
        "intent_category": "rag_query",
        "intent_keywords": ["SOP", "规范", "标准", "流程", "操作", "安装", "维修", "施工", "步骤"],
        "description": "查询企业内部SOP/操作规范/技术标准",
        "todo_list_template": [
            "1. 获取RAGFlow可用助手列表",
            "2. 选择与{entity}最匹配的助手",
            "3. 从宏观角度提问: {entity}的整体流程是什么?",
            "4. 从细节角度提问: {entity}的关键步骤有哪些?",
            "5. 从规范角度提问: {entity}的技术标准和注意事项是什么?",
            "6. 整理三次提问的完整原始信息",
        ],
        "subagent_dispatch_order": [
            {"agent": "RAGFlow助手", "purpose": "查询{entity}相关的SOP/操作规范/技术标准"},
        ],
        "output_strategy": "text",
    },

    # T9: 内部知识/手册查询
    {
        "intent_category": "rag_query",
        "intent_keywords": ["手册", "指南", "说明", "文档", "知识", "内部", "企业"],
        "description": "查询企业内部知识库中的文档/手册",
        "todo_list_template": [
            "1. 获取RAGFlow可用助手列表",
            "2. 选择与{entity}最匹配的助手",
            "3. 从概述角度提问: {entity}的整体介绍",
            "4. 从具体内容角度提问: {entity}的详细说明",
            "5. 从应用角度提问: {entity}的实际应用和案例",
            "6. 整理三次提问的完整原始信息",
        ],
        "subagent_dispatch_order": [
            {"agent": "RAGFlow助手", "purpose": "查询{entity}相关的企业内部文档和手册"},
        ],
        "output_strategy": "text",
    },

    # ============================================================
    # 类别 4: 混合搜索 — 多源融合 (3个模板)
    # ============================================================

    # T10: 竞品分析 (Web + DB)
    {
        "intent_category": "mixed_web_db",
        "intent_keywords": ["竞品", "对比", "优劣", "分析", "优势", "劣势", "市场地位", "竞争力"],
        "description": "竞品对比分析: 本公司数据(DB) + 竞品信息(Web)",
        "todo_list_template": [
            "1. 数据库查询本公司{entity}的详细信息",
            "2. 网络搜索竞品的市场信息和产品参数",
            "3. 对比分析: 价格/规格/市场表现/优劣势",
            "4. 整合形成完整的竞品分析报告",
        ],
        "subagent_dispatch_order": [
            {"agent": "数据库查询助手", "purpose": "查询本公司{entity}的详细信息(规格/价格/销量/库存)"},
            {"agent": "网络搜索助手", "purpose": "搜索{entity}市场上同类竞品的产品信息和价格"},
            {"agent": "网络搜索助手", "purpose": "搜索{entity}相关市场的竞争格局和份额数据"},
            {"agent": "网络搜索助手", "purpose": "搜索{entity}竞品的用户评价和市场口碑"},
        ],
        "output_strategy": "text",
    },

    # T11: 综合分析 (三种全用)
    {
        "intent_category": "mixed_all",
        "intent_keywords": ["综合", "分析", "报告", "全面", "深度", "评估", "诊断"],
        "description": "三源融合的深度综合分析",
        "todo_list_template": [
            "1. 数据库查询本公司{entity}的内部数据",
            "2. 网络搜索{entity}的行业背景和外部信息",
            "3. RAGFlow查询{entity}相关的企业内部策略文档",
            "4. 三源信息交叉验证, 识别差异和一致性",
            "5. 综合形成完整的分析报告",
        ],
        "subagent_dispatch_order": [
            {"agent": "数据库查询助手", "purpose": "查询本公司{entity}的内部数据(产品/销售/库存)"},
            {"agent": "网络搜索助手", "purpose": "搜索{entity}的行业趋势和外部市场信息"},
            {"agent": "RAGFlow助手", "purpose": "查询{entity}相关的企业内部策略和SOP文档"},
            {"agent": "网络搜索助手", "purpose": "补充搜索{entity}的最新动态和政策信息"},
        ],
        "output_strategy": "text",
    },

    # T12: 行业分析 + 本公司定位 (Web + DB + RAG)
    {
        "intent_category": "mixed_all",
        "intent_keywords": ["行业", "市场", "定位", "份额", "排名", "占比", "预测"],
        "description": "行业分析结合本公司数据, 评估市场定位",
        "todo_list_template": [
            "1. 网络搜索{entity}行业的市场规模和发展趋势",
            "2. 数据库查询本公司相关产品的销售和市场份额数据",
            "3. RAGFlow查询企业内部的市场策略和定位文档",
            "4. 综合分析本公司在行业中的定位和竞争力",
        ],
        "subagent_dispatch_order": [
            {"agent": "网络搜索助手", "purpose": "搜索{entity}行业市场规模、增长率和主要玩家"},
            {"agent": "数据库查询助手", "purpose": "查询本公司{entity}相关产品的销售和市场数据"},
            {"agent": "RAGFlow助手", "purpose": "查询企业内部关于{entity}的市场策略文档"},
        ],
        "output_strategy": "text",
    },

    # ============================================================
    # 类别 5: 文档生成 (3个模板)
    # ============================================================

    # T13: Markdown 报告生成
    {
        "intent_category": "document_generation",
        "intent_keywords": ["生成", "Markdown", "MD", "报告", "文档", "写", "创建"],
        "description": "生成 Markdown 格式的分析报告",
        "todo_list_template": [
            "1. 分析报告需求, 确定报告主题和结构",
            "2. 检索所需信息(根据报告主题选择合适的数据源)",
            "3. 信息齐全后, 调用generate_markdown生成结构完整的Markdown文档",
            "4. 确保内容≥1000字, 结构完整(标题/表格/段落)",
            "5. 通知用户报告已生成",
        ],
        "subagent_dispatch_order": [
            {"agent": "数据库查询助手", "purpose": "查询报告所需的企业内部数据"},
            {"agent": "网络搜索助手", "purpose": "搜索报告所需的行业背景信息"},
        ],
        "output_strategy": "markdown",
    },

    # T14: PDF 报告生成
    {
        "intent_category": "document_generation",
        "intent_keywords": ["PDF", "pdf", "生成pdf", "导出", "报告pdf"],
        "description": "生成 PDF 格式的分析报告 (先MD后PDF)",
        "todo_list_template": [
            "1. 分析报告需求, 确定报告结构和内容范围",
            "2. 检索所需信息(根据报告主题选择合适的数据源)",
            "3. 信息齐全后, 先调用generate_markdown生成Markdown文档",
            "4. 再调用convert_md_to_pdf将Markdown转换为PDF",
            "5. 确保内容≥1000字, 无占位符",
            "6. 通知用户PDF报告已生成",
        ],
        "subagent_dispatch_order": [
            {"agent": "数据库查询助手", "purpose": "查询报告所需的企业内部数据"},
            {"agent": "网络搜索助手", "purpose": "搜索报告所需的行业背景和外部信息"},
            {"agent": "RAGFlow助手", "purpose": "查询报告所需的企业内部策略和规范文档"},
        ],
        "output_strategy": "pdf",
    },

    # T15: 数据驱动的分析报告生成
    {
        "intent_category": "document_generation",
        "intent_keywords": ["数据", "分析", "统计", "报表", "图表", "汇总"],
        "description": "基于数据库数据的统计分析报告生成",
        "todo_list_template": [
            "1. 确定需要分析的数据维度和指标",
            "2. 数据库查询原始数据",
            "3. 网络搜索行业基准数据做对比",
            "4. 整合分析, 形成数据驱动的报告",
            "5. 调用generate_markdown生成报告",
            "6. (如需PDF)调用convert_md_to_pdf转换",
        ],
        "subagent_dispatch_order": [
            {"agent": "数据库查询助手", "purpose": "查询{entity}的详细数据, 按{filter_condition}筛选"},
            {"agent": "网络搜索助手", "purpose": "搜索{entity}相关行业基准数据和对比参考"},
        ],
        "output_strategy": "markdown",
    },
]


# =============================================================================
# 加载函数
# =============================================================================

def load_cold_start_templates(cache: TemplateCache) -> int:
    """
    将冷启动模板加载到缓存中。

    Returns:
        加载的模板数量
    """
    count = 0
    for tmpl_data in COLD_START_TEMPLATES:
        template_id = hashlib.md5(
            f"cold:{tmpl_data['intent_category']}:{tmpl_data['description']}".encode()
        ).hexdigest()[:12]

        template = PlanningTemplate(
            template_id=template_id,
            intent_category=tmpl_data["intent_category"],
            intent_keywords=tmpl_data["intent_keywords"],
            description=tmpl_data["description"],
            todo_list_template=tmpl_data["todo_list_template"],
            subagent_dispatch_order=tmpl_data["subagent_dispatch_order"],
            output_strategy=tmpl_data["output_strategy"],
            hit_count=0,
            created_at=time.time(),
            last_hit_at=0.0,
        )

        cache.put(template)
        count += 1

    cache.save_to_disk()
    print(f"[ColdStart] 已加载 {count} 个冷启动模板到规划缓存")
    return count
