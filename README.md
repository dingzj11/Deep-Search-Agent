# Deep Search Agent

> 基于 LangChain DeepAgents 框架构建的多智能体深度搜索系统 | Multi-Agent Deep Search System

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)

**Deep Search Agent** 是一个多智能体协作的深度搜索系统，由一个主智能体编排器协调三个专家子智能体（网络搜索、数据库查询、知识库检索），通过 FastAPI 提供实时 Web 服务，支持 Markdown/PDF 文档生成，并内置了规划缓存（Planning Cache）优化模块，有效降低 LLM 调用成本与延迟。

---

## 架构概览

```
┌─────────────────────────────────────────────────────────┐
│                    FastAPI Web Server                    │
│              REST API + WebSocket (实时监控)              │
└────────────────────────┬────────────────────────────────┘
                         │
         ┌───────────────▼────────────────┐
         │       Main Agent (编排器)        │
         │   - 任务规划 & 子智能体调度       │
         │   - Planning Cache 缓存加速      │
         │   - 结果整合 & 文档生成           │
         └───────┬──────┬──────┬──────────┘
                 │      │      │
    ┌────────────▼┐ ┌───▼───┐ ┌▼────────────┐
    │ 网络搜索助手  │ │数据库  │ │ RAGFlow助手 │
    │ (Tavily API) │ │(MySQL) │ │ (内部知识库) │
    └──────────────┘ └────────┘ └─────────────┘
```

## 核心特性

- **多智能体协作**: 主 Agent 自动分解任务，调度 3 个子 Agent 并行/串行获取信息
- **多数据源融合**: 互联网搜索 (Tavily) + 关系数据库 (MySQL) + 企业内部知识库 (RAGFlow)
- **Planning Cache**: 基于 Agentic RAG 的规划缓存模块，同类问题跳过重复规划，降低 ~50% LLM 成本
- **冷启动模板**: 内置 15 个高频场景预置模板，系统从第 1 天起即可命中缓存
- **自动模板学习**: 未命中缓存时，执行后自动提取新模板，持续优化命中率
- **实时 WebSocket 监控**: 前端可实时查看每个 Agent 的执行进度、工具调用和中间结果
- **多格式文档生成**: 自动生成 Markdown 报告，并通过 Word COM 转换为 PDF
- **文件上传与分析**: 支持用户上传文件（txt/pdf/docx 等），Agent 可读取并分析

## 项目结构

```
deep_search_pro/
├── agent/                       # 智能体核心
│   ├── main_agent.py            # 主智能体编排器 + Planning Cache 集成
│   ├── planning_cache.py        # 规划缓存模块 (模板匹配/学习/持久化)
│   ├── cold_start_templates.py  # 15个冷启动预置模板
│   ├── llm.py                   # LLM 模型初始化 (主模型 + 轻量模型)
│   ├── prompts.py               # YAML 提示词加载器
│   └── subagents/               # 子智能体定义
│       ├── network_search_agent.py   # 网络搜索子智能体
│       ├── database_query_agent.py   # 数据库查询子智能体
│       └── knowledge_base_agent.py   # 知识库子智能体
├── api/                         # Web API 层
│   ├── server.py                # FastAPI 服务器 (REST + WebSocket)
│   ├── monitor.py               # WebSocket 实时监控 & 进度上报
│   └── context.py               # 会话级上下文隔离 (ContextVar)
├── tools/                       # Agent 工具集 (LangChain @tool)
│   ├── tavily_tool.py           # 网络搜索工具
│   ├── db_tools.py              # MySQL 数据库工具
│   ├── ragflow_tools.py         # RAGFlow 知识库工具
│   ├── markdown_tools.py        # Markdown 文件生成工具
│   ├── pdf_tools.py             # MD → PDF 转换工具
│   └── upload_file_read_tool.py # 多格式文件读取工具
├── prompt/
│   └── prompts.yml              # 主/子智能体提示词配置
├── rawflow/                     # RAGFlow 集成 & 工具脚本
│   ├── rag_config.py            # RAGFlow 环境变量加载
│   ├── knowledge_demo.py        # 知识库创建 & 文档上传
│   └── chat_assistant_demo.py   # 聊天助手独立测试脚本
├── utils/                       # 工具函数
│   ├── path_utils.py            # 统一路径解析 (含安全校验)
│   └── word_converter.py        # Word COM 自动化 (MD→PDF)
├── requirements.txt             # Python 依赖
├── .env.example                 # 环境变量模板
└── LICENSE                      # MIT License
```

## 快速开始

### 环境要求

- Python 3.10+
- MySQL 数据库 (可选，如需使用数据库查询助手)
- RAGFlow 服务 (可选，如需使用知识库助手)
- Windows 系统 (PDF 生成依赖 Word COM；其他功能跨平台)

### 1. 克隆仓库

```bash
git clone https://github.com/YOUR_USERNAME/deep-search-agent.git
cd deep-search-agent
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件，填入你的 API Key 和服务地址
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 启动服务

```bash
python api/server.py
```

服务启动后访问 `http://localhost:8000`。

### 5. API 使用

```bash
# 提交搜索任务
curl -X POST http://localhost:8000/api/task \
  -H "Content-Type: application/json" \
  -d '{"query": "分析2024年空调行业市场趋势"}'

# WebSocket 实时监控
ws://localhost:8000/ws/{thread_id}
```

## Planning Cache 规划缓存

本项目的核心优化模块，核心思路是 **缓存规划步骤而非缓存答案**：

| 环节 | 说明 |
|------|------|
| Step 1 - 意图提取 | 用轻量模型 (Qwen2.5-14B) 提取用户问题的高层意图 |
| Step 2 - 模板匹配 | 在缓存中查找相似规划模板，替换占位符后直接注入 |
| Step 3 - 自动学习 | 未命中时走完整规划流程，执行后自动提取新模板 |

**效果预期**：LLM 调用成本降低 ~50%，响应延迟降低 ~30%，输出质量维持不变。

详见 `agent/planning_cache.py` 和 `agent/cold_start_templates.py`。

## 技术栈

- **Agent 框架**: [LangChain DeepAgents](https://github.com/langchain-ai/deepagents)
- **LLM**: Qwen-Max (推理) + Qwen2.5-14B (轻量任务)
- **Web 框架**: FastAPI + WebSocket
- **搜索引擎**: Tavily Search API
- **知识库**: RAGFlow SDK
- **数据库**: MySQL (mysql-connector-python)
- **文件生成**: Markdown → Word COM → PDF

## License

MIT License - 详见 [LICENSE](LICENSE) 文件。

---

