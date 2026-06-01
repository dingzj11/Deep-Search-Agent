from agent.subagents.knowledge_base_agent import knowledge_base_agent
from agent.subagents.database_query_agent import database_query_agent
from agent.subagents.network_search_agent import network_search_agent
from langgraph.checkpoint.memory import InMemorySaver

# main_agent tool导入
from tools.markdown_tools import generate_markdown
from tools.pdf_tools import convert_md_to_pdf
from tools.upload_file_read_tool import read_file_content

from deepagents import create_deep_agent

from agent.llm import model
from agent.prompts import main_agent_content

from api.monitor import monitor
import shutil
import time
from pathlib import Path

from api.context import set_session_context, reset_session_context, set_thread_context

# ============================================================
# 规划缓存集成 (Planning Cache)
# ============================================================
from agent.planning_cache import create_planning_cache

# 模块加载时初始化规划缓存 (含冷启动模板)
planning_cache = create_planning_cache()

main_agent = create_deep_agent(
   model = model,
   system_prompt=main_agent_content['system_prompt'],
   tools= [generate_markdown,convert_md_to_pdf,read_file_content],
   checkpointer=InMemorySaver(),
   subagents=[
       database_query_agent,
       network_search_agent,
       knowledge_base_agent
   ]
)

# 执行
"""
  1. 执行主智能体 一定选异步，原因：对应多个客户端
  2. 什么时候触发我们智能体的调用或者执行？？？
  3. 客户端 -》 api/task -> fastapi 接口 -》 异步执行 -》 main_agent的运行 （异步方法）
  4. main_agent执行stream流式处理 -》 调用工具 -》 已经埋好了点
                                   调用子智能体 -》 结果解析 -》 name = task -> monitor -> 发送子智能体
                                   调用最终结果 -》 结果 -》 monitor -> 发送结果的方法
                                   开启调用以后 -》 当前会话 -》 文件夹地址 -》 推送到前端
"""



project_root_path = Path(__file__).parents[1].resolve() # 绝对 解析路径标识以及软连接
# project_root_path = Path(__file__).parents[1].absolute() # 绝对
# main_agent.invoke()
# main_agent.stream()
# main_agent.astream() [选他]


def _build_cache_plan_instruction(filled_plan: dict) -> str:
    """
    将缓存的规划结果构建为注入给主Agent的指令。

    当缓存命中时, 将预计算的todo-list和子Agent调度计划直接告知主Agent,
    使其跳过自己的规划阶段, 直接进入执行。
    """
    todo_text = "\n".join(f"  - {step}" for step in filled_plan.get("todo_list", []))
    dispatch_items = filled_plan.get("subagent_dispatch", [])
    dispatch_text = "\n".join(
        f"  - {item.get('agent','')}: {item.get('purpose','')}"
        for item in dispatch_items
    )

    instruction = f"""
【预计算规划 - 跳过自主规划阶段, 直接执行以下计划】

## 任务清单 (Todo List)
{todo_text}

## 子智能体调度计划
{dispatch_text}

## 执行要求
1. 严格按照上述 Todo List 和调度计划执行, 无需重新制定计划
2. 按调度计划依次(或并行)调用对应的子智能体
3. 获取全部信息后, 根据输出策略执行后续操作
4. 输出策略: {filled_plan.get('output_strategy', 'text')}

【用户查询】
"""
    return instruction


def _collect_execution_trace(
    todo_list: list,
    subagent_calls: list,
    output_type: str
) -> dict:
    """收集一次执行的trace, 用于后续模板提取"""
    return {
        "todo_list": todo_list,
        "subagent_calls": subagent_calls,
        "output_type": output_type,
    }


async def run_deep_agent(task_query, session_id):
    """
    定义流式+异步执行主智能体！！

    新增 (Planning Cache):
      执行前先通过轻量模型提取意图 + 匹配缓存模板。
      若命中 → 注入预计算规划, 跳过主模型规划阶段。
      若未命中 → 正常执行, 执行后自动学习新模板。

    task_query: 前端提问的问题
    session_id: 每个前端会话对应的标识
    """
    plan_start_time = time.time()
    print(f"当前会话的main_agent开始执行了！ 会话id:{session_id}")

    # ============================================================
    # Planning Cache — 尝试命中缓存
    # ============================================================
    intent, cache_result = planning_cache.process(task_query)

    cache_hit = cache_result.hit
    planning_time_ms = (time.time() - plan_start_time) * 1000

    if cache_hit:
        print(f"[PlanningCache] ✅ 缓存命中! 模板: {cache_result.template.description}")
        print(f"[PlanningCache]    匹配分数: {cache_result.match_score:.2f}")
        print(f"[PlanningCache]    意图提取耗时: {planning_time_ms:.0f}ms (轻量模型)")
        print(f"[PlanningCache]    预计跳过 {cache_result.skipped_llm_calls} 轮大模型规划调用")

        # 将预计算规划注入用户消息
        cache_instruction = _build_cache_plan_instruction(cache_result.filled_plan)
        effective_query = cache_instruction + task_query
    else:
        print(f"[PlanningCache] ❌ 缓存未命中 (类别: {intent.category}, "
              f"最高匹配分: {cache_result.match_score:.2f}, 阈值: 0.55)")
        print(f"[PlanningCache]    意图提取耗时: {planning_time_ms:.0f}ms (轻量模型)")
        print(f"[PlanningCache]    将走完整大模型规划流程...")
        effective_query = task_query

    # ============================================================
    # 原有逻辑 — 会话准备
    # ============================================================
    session_dir = project_root_path / "output" / f"session_{session_id}"
    session_dir.mkdir(parents=True, exist_ok=True)
    session_dir_str = str(session_dir).replace("\\","/")
    relative_session_dir_str = str(session_dir.relative_to(project_root_path)).replace("\\","/")

    # 处理上传文件
    updated_dir_path = project_root_path / "updated" / f"session_{session_id}"
    updated_info_prompt = ""
    if updated_dir_path.exists():
        files = [ f.name  for f in updated_dir_path.iterdir()  if f.is_file()]
        if files:
            for filename in files:
                shutil.copy2(updated_dir_path / filename, session_dir / filename)
            updated_info_prompt = (f"\n    [已上传文件] 已加载到工作目录:\n" +
                             "\n".join([f"    - {f}" for f in files]) +
                             "\n    请优先使用工具（read_file_content）读取并参考这些文件。")

    # 存储 ContextVars
    session_dir_token = set_session_context(session_dir_str)
    session_id_token = set_thread_context(session_id)

    monitor.report_session_dir(session_dir_str)

    # 构建环境指令
    path_instruction = f"""
    【工作环境指令】
    工作目录: {relative_session_dir_str}
    {updated_info_prompt}

    规则：
    1. 新生成文件必须保存到工作目录：'{relative_session_dir_str}/filename'
    2. 读取已上传的文件时，请直接将文件名（例如：'开篇.txt'）作为 filename 参数传入（read_file_content）读取工具，不要带上任何目录前缀。
    3. 使用相对路径，禁止使用绝对路径
    4. 若存在上传文件，请先分析内容
    """

    # ============================================================
    # 原有逻辑 — 执行Agent
    # ============================================================
    config = {
        "configurable":{
            "thread_id":session_id
        }
    }

    # Trace 收集 (用于模板学习)
    collected_todo = []
    collected_subagent_calls = []
    collected_output_type = "text"

    try:
        async for chunk in main_agent.astream({
            "messages":[
                {
                    "role":"user","content": effective_query + path_instruction
                }
            ]
        },config=config):
            for node_name,state in chunk.items():
                if not state or "messages" not in state: continue
                messages = state["messages"]
                if messages and isinstance(messages,list):
                    last_msg = messages[-1]
                    if node_name == 'model':
                        if last_msg.tool_calls:
                            for tool_call in last_msg.tool_calls:
                                if tool_call['name'] == 'task':
                                    # 收集子Agent调度信息
                                    subagent_type = tool_call['args'].get('subagent_type', '')
                                    description = tool_call['args'].get('description', '')
                                    collected_subagent_calls.append({
                                        "agent": subagent_type,
                                        "purpose": description,
                                    })
                                    monitor.report_assistant(subagent_type,
                                        {'description': description})
                        elif last_msg.content:
                            # 检测输出类型
                            content_lower = last_msg.content.lower()
                            if "pdf" in content_lower or "convert_md_to_pdf" in str(last_msg.tool_calls):
                                collected_output_type = "pdf"
                            elif "generate_markdown" in str(last_msg.tool_calls) or "markdown" in content_lower:
                                collected_output_type = "markdown"

                            print(f"主智能体执行结果，最终结果：{last_msg.content[:100]}")
                            monitor.report_task_result(last_msg.content)

    except Exception as e :
        monitor._emit("error",f"执行主智能发生异常信息：{str(e)}")
    finally:
        reset_session_context(session_dir_token, session_id_token)

    # ============================================================
    # Planning Cache — 未命中时自动学习
    # ============================================================
    if not cache_hit and collected_subagent_calls:
        try:
            trace = _collect_execution_trace(
                todo_list=collected_todo,
                subagent_calls=collected_subagent_calls,
                output_type=collected_output_type,
            )
            new_template = planning_cache.learn_from_execution(intent, trace)
            print(f"[PlanningCache] 📝 已从本次执行中学习新模板: {new_template.description}")
            print(f"[PlanningCache]    模板ID: {new_template.template_id}")
            print(f"[PlanningCache]    当前缓存总量: {planning_cache.cache.size()} 个模板")
        except Exception as e:
            print(f"[PlanningCache] ⚠️ 模板学习失败: {e}")

    # 定期输出缓存统计 (每20次查询)
    if planning_cache.total_queries % 20 == 0:
        stats = planning_cache.get_stats()
        print(f"\n[PlanningCache] 📊 统计: 总查询={stats['total_queries']}, "
              f"命中率={stats['hit_rate']}, 跳过LLM调用={stats['llm_calls_skipped']}")
