from dotenv import load_dotenv,find_dotenv
import os
from langchain.chat_models import init_chat_model

# 加载配置文件
# find_dotenv() 确保找到 .env文件 递归查询当前项目文件夹
load_dotenv(find_dotenv())

# ============================
# 主模型 (Qwen-Max) — 用于复杂推理、信息整合、文档生成
# ============================
model = init_chat_model(
    model=os.getenv("LLM_QWEN_MAX"),
    model_provider="openai"
)

# ============================
# 轻量模型 (Qwen2.5-14B) — 用于意图提取、模板匹配、占位符替换
# 成本约为 Qwen-Max 的 1/10，延迟约 1/3
# ============================
lightweight_model = init_chat_model(
    model=os.getenv("LLM_QWEN2.5", "qwen2.5-14b-instruct"),
    model_provider="openai"
)
