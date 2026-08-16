"""
共享 LLM 客户端 — tool-call 循环抽象

消除 server.py / executor.py / plan.py / agent.py 中重复的
"发请求 → 检测 tool_calls → 执行工具 → 追加结果 → 循环" 模式。

提供:
- chat_with_tools(): 生成器，每步 yield 事件 dict（用于 SSE 流式）
- chat_with_tools_sync(): 同步版本，返回最终结果
"""

import json
import time

import requests as _requests

from . import tool_registry
from .config import get_config


def _default_session():
    """创建一个默认 HTTP session（当调用方未传入时使用）"""
    s = _requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _resolve_tools(tools, tool_names):
    """解析 tools 参数：tools 优先，否则从 tool_names 查找"""
    if tools:
        return tools
    if tool_names:
        return tool_registry.get_definitions_by_names(tool_names)
    return None


def chat_with_tools(
    messages,
    tools=None,
    tool_names=None,
    *,
    http_session=None,
    api_base=None,
    api_key=None,
    model=None,
    max_tokens=None,
    temperature=None,
    max_rounds=20,
    stream=False,
):
    """
    与 LLM 对话，自动处理 tool calls 循环。
    这是一个生成器，每一步 yield 一个事件 dict。

    参数:
        messages: 消息列表 [{"role": "...", "content": "..."}]
        tools: OpenAI tools 数组（优先于 tool_names）
        tool_names: 工具名称列表，从 tool_registry 查找定义
        http_session: requests.Session（复用连接池）
        api_base / api_key / model / max_tokens / temperature: LLM 参数
        max_rounds: 最大 tool-call 轮数
        stream: 是否使用 LLM 原生 streaming（True=逐 token yield content）

    Yield 事件:
        {"type": "content", "content": "文本增量"}     # stream=True 时逐 token
        {"type": "tool_call", "name": "...", "arguments": "...", "id": "..."}
        {"type": "tool_result", "name": "...", "result": "..."}
        {"type": "error", "error": "错误信息"}
        {"type": "done", "content": "完整文本"}
    """
    cfg = get_config()
    base = api_base or cfg["api_base"]
    key = api_key or cfg["api_key"]
    mdl = model or cfg["model"]
    mt = max_tokens if max_tokens is not None else cfg["max_tokens"]
    temp = temperature if temperature is not None else cfg["temperature"]

    session = http_session or _default_session()
    # headers 在循环外构建一次，避免每轮 tool-call 重复创建
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
    }

    resolved_tools = _resolve_tools(tools, tool_names)
    current_messages = list(messages)

    for _round in range(max_rounds):
        payload = {
            "model": mdl,
            "messages": current_messages,
            "max_tokens": mt,
            "temperature": temp,
            "stream": stream,
        }
        if resolved_tools:
            payload["tools"] = resolved_tools
            payload["tool_choice"] = "auto"

        resp = None
        try:
            resp = session.post(
                f"{base}/chat/completions",
                headers=headers,
                json=payload,
                timeout=180,
            )

            if resp.status_code != 200:
                error_msg = resp.text[:500]
                yield {"type": "error", "error": f"API 返回 {resp.status_code}: {error_msg}"}
                return

            if stream:
                # ── 原生流式模式 ──
                tool_calls_buffer = {}  # index -> {id, name, arguments}
                full_content = ""
                has_tool_calls = False  # 本轮触发了工具调用

                for line in resp.iter_lines(decode_unicode=True):
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    delta = data.get("choices", [{}])[0].get("delta", {})
                    finish_reason = data.get("choices", [{}])[0].get("finish_reason", "")

                    # 收集 tool_calls delta
                    tc_deltas = delta.get("tool_calls")
                    if tc_deltas:
                        for tc_delta in tc_deltas:
                            idx = tc_delta.get("index", 0)
                            if idx not in tool_calls_buffer:
                                tool_calls_buffer[idx] = {
                                    "id": tc_delta.get("id", ""),
                                    "name": "",
                                    "arguments": "",
                                }
                            buf = tool_calls_buffer[idx]
                            if tc_delta.get("id"):
                                buf["id"] = tc_delta["id"]
                            if tc_delta.get("function", {}).get("name"):
                                buf["name"] = tc_delta["function"]["name"]
                            if tc_delta.get("function", {}).get("arguments"):
                                buf["arguments"] += tc_delta["function"]["arguments"]

                    # 思考过程增量（DeepSeek Reasoner / OpenAI o1 等推理模型）
                    reasoning_delta = delta.get("reasoning_content", "")
                    if reasoning_delta:
                        yield {"type": "reasoning", "content": reasoning_delta}

                    # 文本增量
                    content_delta = delta.get("content", "")
                    if content_delta:
                        full_content += content_delta
                        yield {"type": "content", "content": content_delta}

                    # 流式中的 tool_calls 完成
                    if finish_reason == "tool_calls" and tool_calls_buffer:
                        has_tool_calls = True
                        tool_calls_list = [tool_calls_buffer[i] for i in sorted(tool_calls_buffer)]
                        for tc in tool_calls_list:
                            yield {
                                "type": "tool_call",
                                "id": tc["id"],
                                "name": tc["name"],
                                "arguments": tc["arguments"],
                            }

                        # 构建 assistant 消息
                        assistant_msg = {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": tc["id"],
                                    "type": "function",
                                    "function": {
                                        "name": tc["name"],
                                        "arguments": tc["arguments"],
                                    },
                                }
                                for tc in tool_calls_list
                            ],
                        }
                        current_messages.append(assistant_msg)

                        # 执行工具
                        for tc in tool_calls_list:
                            try:
                                tool_args = json.loads(tc["arguments"])
                            except json.JSONDecodeError:
                                tool_args = {}
                            try:
                                result = tool_registry.execute(tc["name"], tool_args)
                            except Exception as exc:
                                result = f"工具执行异常: {exc}"
                            yield {
                                "type": "tool_result",
                                "name": tc["name"],
                                "result": result[:1000],
                            }
                            current_messages.append({
                                "role": "tool",
                                "tool_call_id": tc["id"],
                                "content": result,
                            })

                        resp.close()
                        resp = None
                        break  # 跳出 iter_lines，进入下一轮 tool-call

                # for 循环结束后的处理
                if has_tool_calls:
                    # tool_calls 触发了 break → 进入下一轮（不 yield done）
                    pass
                else:
                    # 收到 [DONE] 或流自然结束 → 对话完成
                    yield {"type": "done", "content": full_content}
                    return

            else:
                # ── 非流式模式 ──
                body = resp.json()
                choice = body.get("choices", [{}])[0]
                message = choice.get("message", {})
                finish_reason = choice.get("finish_reason", "")

                tool_calls = message.get("tool_calls")
                if tool_calls and finish_reason == "tool_calls":
                    yield {
                        "type": "tool_call",
                        "calls": [
                            {"id": tc["id"], "name": tc["function"]["name"],
                             "arguments": tc["function"]["arguments"]}
                            for tc in tool_calls
                        ],
                    }
                    current_messages.append(message)

                    for tc in tool_calls:
                        tool_name = tc["function"]["name"]
                        try:
                            tool_args = json.loads(tc["function"]["arguments"])
                        except json.JSONDecodeError:
                            tool_args = {}

                        try:
                            result = tool_registry.execute(tool_name, tool_args)
                        except Exception as exc:
                            result = f"工具执行异常: {exc}"
                        yield {
                            "type": "tool_result",
                            "name": tool_name,
                            "result": result[:1000],
                        }
                        current_messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result,
                        })

                    resp.close()
                    resp = None
                    continue

                content = message.get("content", "")
                yield {"type": "done", "content": content}
                return

        except _requests.exceptions.ConnectionError:
            yield {"type": "error", "error": f"连接失败! 请检查 API 地址: {base}"}
            return
        except _requests.exceptions.Timeout:
            yield {"type": "error", "error": "请求超时，请重试"}
            return
        except Exception as e:
            yield {"type": "error", "error": str(e)}
            return
        finally:
            if resp is not None:
                resp.close()

    # 达到最大轮数
    yield {"type": "error", "error": "工具调用达到最大轮数限制，请简化问题"}


def chat_with_tools_sync(messages, tools=None, tool_names=None, **kwargs):
    """
    chat_with_tools 的同步版本。
    遍历所有事件，收集最终结果。

    返回:
        {
            "success": True/False,
            "content": "最终文本",
            "tool_calls_made": [{"name": "...", "arguments": "...", "result": "..."}],
            "messages": [...],  # 包含所有工具交互的完整消息列表
            "error": "错误信息"  # 仅在 success=False 时
        }
    """
    # 需要记录的消息列表（用于后续调用）
    messages_out = list(messages)
    tool_calls_made = []

    final_content = ""
    error = None

    for event in chat_with_tools(
        messages_out,
        tools=tools,
        tool_names=tool_names,
        **kwargs,
    ):
        if event["type"] == "content":
            final_content += event["content"]
        elif event["type"] == "tool_call":
            if "calls" in event:
                for tc in event["calls"]:
                    tool_calls_made.append({
                        "name": tc["name"],
                        "arguments": tc["arguments"],
                        "id": tc.get("id", ""),
                    })
            elif "name" in event:
                tool_calls_made.append({
                    "name": event["name"],
                    "arguments": event.get("arguments", ""),
                    "id": event.get("id", ""),
                })
        elif event["type"] == "tool_result":
            # 找到最近的 tool_call 并附加结果
            for tc in reversed(tool_calls_made):
                if tc.get("name") == event["name"] and "result" not in tc:
                    tc["result"] = event["result"]
                    break
        elif event["type"] == "error":
            error = event["error"]
            break
        elif event["type"] == "done":
            final_content = event.get("content", "") or final_content
            break

    return {
        "success": error is None,
        "content": final_content,
        "tool_calls_made": tool_calls_made,
        "error": error,
    }
