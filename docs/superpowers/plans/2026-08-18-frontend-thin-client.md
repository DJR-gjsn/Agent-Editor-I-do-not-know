# 前端轻量化重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 前端变轻量薄壳（业务逻辑后移后端）：组件/工具/模板/厂商元数据 API 化 + 对话编排后端化 + 设置预设后移，app.js 从 ~7775 行降至 ≤4000 行，功能等价（97 测试全绿 + 手工验证），界面外观不变。

**Architecture:** 三阶段增量重构。阶段 1：后端 `modules/meta.py` 提供 `GET /api/meta/components`（组件定义元数据 + renderKey + 工具映射 + 分类 + 快速模板 + 厂商预设），前端启动拉取并本地关联 renderKey→渲染函数，删除硬编码。阶段 2：后端 `modules/orchestrator.py` 复刻前端 buildChatPayload 编排链（布局连线→工具注入→payload），`POST /api/chat` 请求体演进为 layout+消息（SSE 响应不变，旧格式过渡兼容）。阶段 3：`GET /api/meta/settings` + 死代码清理。

**Tech Stack:** Python 3.14 + Flask + 原生 JS（无构建工具）+ stdlib unittest。

## Global Constraints

- **零新依赖**：只允许 stdlib + 已有依赖（Flask/requests/werkzeug）。
- **测试框架**：stdlib unittest，命令 `python -m unittest tests.test_<module> -v`。
- **界面外观不变**：任何前端改动不得改变画布/面板/对话页的可见行为；render 函数（96 个）与画布交互代码**不得删除**。
- **功能等价**：97 个既有测试必须保持全绿；每阶段独立提交可回滚。
- **renderKey 机制**：COMPONENT_DEFS 的 render 字段由函数引用改为字符串 renderKey；前端维护 `renderKey → 渲染函数` 映射（39 个被引用的 render 函数名，从 `render:\s*(render\w+)` 提取）。
- **SSE 契约不变**：阶段 2 的 `/api/chat` 响应事件流（tool-call/心跳/增量/DONE）与现有一致，chat.js 渲染层零改动。
- **过渡兼容**：`/api/chat` 旧请求体（直接 messages/tools 格式）保留过渡期，双格式由测试锁定。
- **元数据提取**：用一次性脚本从 app.js 提取（不是手写数据），保证与前端现状一致；提取后前端删除硬编码，后端成为唯一来源。
- 登录保护已生效：/api/meta/* 需要登录（白名单外），前端未登录 401 → 跳登录页（现有流程）。
- 测试临时文件放 `data/vector_store/.test_tmp/`（uuid + makedirs，**不用 tempfile.mkdtemp**）。
- UTF-8；node --check 验证前端语法。

---

## File Structure

| 文件 | 职责 | 动作 |
|---|---|---|
| `tools/extract_meta.py` | 一次性提取脚本：读 app.js 的 COMPONENT_DEFS/TOOL_NAME_MAP/COMPONENT_CATEGORIES/getAllProviders + index.html 快速模板 → 生成 Python 数据 | 新建（工具脚本，可保留或提交） |
| `modules/meta.py` | 元数据常量（提取生成）+ `GET /api/meta/components` 与 `GET /api/meta/settings` 路由 | 新建 |
| `tests/test_meta.py` | meta 端点结构/完整性测试 | 新建 |
| `modules/orchestrator.py` | Python 复刻 buildChatPayload 编排链 + 双格式兼容 | 新建 |
| `tests/test_orchestrator.py` | 布局→工具注入/SSE 兼容/旧格式测试 | 新建 |
| `modules/chat_routes.py` | /api/chat 支持新请求体（layout+消息） | 修改 |
| `static/app.js` | 删除元数据硬编码；启动拉取 meta；renderKey 映射；发送瘦身；fallback | 修改（重点瘦身） |
| `static/chat.js` | 阶段 2 发送格式切换（其余零改动） | 修改 |
| `templates/index.html` | 无（模板数据由脚本提取，HTML 结构不动） | — |
| `docs/api-contract.md` | 补充 /api/meta/* 与新 /api/chat 契约 | 修改 |
| `docs/PROJECT_BRIEF.md` | 功能记录更新 | 修改 |

---

### Task 1: 元数据提取脚本 + modules/meta.py + /api/meta/components

**Files:**
- Create: `tools/extract_meta.py`
- Create: `modules/meta.py`
- Create: `tests/test_meta.py`
- Modify: `modules/__init__.py`（register_all 加 meta 注册）

**Interfaces:**
- Produces:
  - `GET /api/meta/components` → `{success, data:{component_defs, tool_name_map, component_categories, quick_templates, provider_presets}}`
  - `meta.component_defs`：`{type: {icon,title,color,defaultSize,ports,description,renderKey,category}}`（render 字段转 renderKey 字符串）
  - `meta.register_routes(app)`

- [ ] **Step 1: 写提取脚本**

创建 `tools/extract_meta.py`。逻辑：用正则/括号配对从 `static/app.js` 提取 `COMPONENT_DEFS`、`TOOL_NAME_MAP`、`COMPONENT_CATEGORIES` 三个对象字面量与 `getAllProviders()` 返回的数组字面量，用 Node.js（若可用）或 Python 解析为 JSON，再转换成 `modules/meta.py` 的数据结构。快速模板从 `templates/index.html` 的预设模板区（约 94 行起）与 app.js 模板展开函数提取（若模板数据在 JS 中，一并提取）。

```python
# tools/extract_meta.py — 骨架（实现者补全提取细节）
"""从 app.js/index.html 提取前端元数据，生成 modules/meta.py 的数据部分"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "static" / "app.js"
INDEX = ROOT / "templates" / "index.html"


def extract_js_object(source: str, var_name: str) -> dict:
    """提取 JS 对象字面量（用 Node 求值最稳；无 Node 时用括号配对+ast-ish 解析）"""
    # 实现：定位 var_name 后的 { 开始，括号配对找到结束，交给 subprocess node -e 求值为 JSON
    ...


def extract_render_keys(defs: dict) -> dict:
    """COMPONENT_DEFS 中 render: renderXxxPanel → renderKey 字符串"""
    return {t: (d.get("render") or "") for t, d in defs.items()}


def main():
    src = APP_JS.read_text(encoding="utf-8")
    defs = extract_js_object(src, "COMPONENT_DEFS")
    tools = extract_js_object(src, "TOOL_NAME_MAP")
    cats = extract_js_object(src, "COMPONENT_CATEGORIES")
    providers = extract_js_object(src, "getAllProviders")  # 函数体 return [...]
    # render 引用 → renderKey；补 category（从 COMPONENT_CATEGORIES）
    out = {...}
    # 写入 modules/meta.py 的 _DATA 常量
    ...
```

**验收**：提取后 `component_defs` 含全部组件且 renderKey 与 app.js 中 render 引用一致（39 个不同函数名）；tool_name_map/component_categories 与 app.js 一致；provider_presets 非空。

- [ ] **Step 2: 生成 modules/meta.py**

运行提取脚本生成 `modules/meta.py`（数据部分 `_DATA = {...}` + 路由）：

```python
"""前端元数据单一来源：组件定义/工具映射/分类/模板/厂商预设"""
from flask import jsonify

_DATA = {
    "component_defs": {  # 由 tools/extract_meta.py 生成
        "llm": {"icon": "🔌", "title": "LLM API 设置", "color": "#4A90D9",
                "defaultSize": 6,
                "ports": {"outputs": [{"id": "llm-out", "label": "调用"}],
                          "inputs": [{"id": "llm-mem-in", "label": "记忆 ←"}]},
                "description": "...", "renderKey": "renderLLMPanel",
                "category": "core"},
        # ...全部组件
    },
    "tool_name_map": {"mcp_zip": ["zip_create", "zip_extract"], ...},
    "component_categories": {"mcp_word": ["MCP", "cat-mcp"], ...},
    "quick_templates": [{"name": "知识库问答", "layout": {...}}, ...],
    "provider_presets": [{"name": "OpenAI", "apiBase": "...", "model": "..."}, ...],
}


def register_routes(app):
    @app.route("/api/meta/components", methods=["GET"])
    def meta_components():
        return jsonify({"success": True, "data": _DATA})
```

- [ ] **Step 3: 写失败测试**

创建 `tests/test_meta.py`（完整内容）：

```python
"""meta 元数据端点测试"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask

from modules import meta


class TestMeta(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask(__name__)
        meta.register_routes(cls.app)
        cls.client = cls.app.test_client()

    def test_components_endpoint_structure(self):
        r = self.client.get("/api/meta/components")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()["data"]
        defs = data["component_defs"]
        self.assertGreater(len(defs), 40, "应有全部组件")
        self.assertIn("llm", defs)
        self.assertIn("mcp_external", defs)
        for t, d in defs.items():
            for key in ("icon", "title", "color", "defaultSize", "ports",
                        "description", "renderKey", "category"):
                self.assertIn(key, d, f"{t} 缺 {key}")
            # renderKey 必须是字符串（前端关联渲染函数用）
            self.assertIsInstance(d["renderKey"], str, f"{t} renderKey 非字符串")
        self.assertGreater(len(data["tool_name_map"]), 20)
        self.assertGreater(len(data["quick_templates"]), 0, "应有快速模板")
        self.assertGreater(len(data["provider_presets"]), 0, "应有厂商预设")

    def test_render_keys_are_function_names(self):
        """renderKey 应为合法 JS 函数名模式（前端本地映射用）"""
        import re
        data = self.client.get("/api/meta/components").get_json()["data"]
        for t, d in data["component_defs"].items():
            rk = d["renderKey"]
            self.assertTrue(re.match(r"^[A-Za-z_$][A-Za-z0-9_$]*$", rk),
                            f"{t} renderKey '{rk}' 非法")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: 运行测试确认失败**

Run: `python -m unittest tests.test_meta -v`
Expected: 全部 ERROR（`No module named 'modules.meta'`）

- [ ] **Step 5: 注册路由 + 跑通测试**

`modules/__init__.py` register_all 加 `from . import meta` 与 `meta.register_routes(app)`。重跑测试确认 2 个通过。

- [ ] **Step 6: 提交**

```bash
git add tools/extract_meta.py modules/meta.py tests/test_meta.py modules/__init__.py
git commit -m "feat: 前端元数据 API 化（/api/meta/components：组件定义/renderKey/工具映射/模板/厂商预设）+ 2 测试"
```

---

### Task 2: 前端启动拉取 + renderKey 映射 + 删除硬编码元数据

**Files:**
- Modify: `static/app.js`
- Test: 人工/冒烟验证（无前端测试框架；node --check + 页面行为）

**Interfaces:**
- Consumes: `GET /api/meta/components`（Task 1）
- Produces: 前端启动时从后端拉取元数据构建 COMPONENT_DEFS/TOOL_NAME_MAP/COMPONENT_CATEGORIES/QUICK_TEMPLATES/PROVIDERS

- [ ] **Step 1: 加启动拉取**

在 `static/app.js` 的 `init()` 首行（约 976 行，pullSettingsFromBackend 附近）加：

```javascript
    // 从后端拉取组件/工具/模板/厂商元数据（后端单一来源）
    const meta = await fetch('/api/meta/components').then(r => r.ok ? r.json() : null).catch(() => null);
    if (meta && meta.success && meta.data) applyMeta(meta.data);
```

在文件顶部（COMPONENT_DEFS 定义处）附近新增：

```javascript
// renderKey → 渲染函数 本地映射（渲染逻辑永留前端）
const RENDER_FN_MAP = { renderLLMPanel, renderMcpExternalPanel /* ...全部 39 个被引用的 render 函数 */ };

// 从后端元数据构建全局定义（fallback 到内置最小集）
const FALLBACK_COMPONENT_DEFS = { /* 最小集：llm + 画布必需组件 */ };
let COMPONENT_DEFS = { ...FALLBACK_COMPONENT_DEFS };
let TOOL_NAME_MAP = {};
let COMPONENT_CATEGORIES = {};
let QUICK_TEMPLATES = [];
let PROVIDERS = [];

function applyMeta(data) {
    COMPONENT_DEFS = {};
    for (const [type, d] of Object.entries(data.component_defs || {})) {
        COMPONENT_DEFS[type] = {
            ...d,
            render: RENDER_FN_MAP[d.renderKey] || (() => { /* 未知 renderKey 的空渲染 */ }),
        };
    }
    TOOL_NAME_MAP = data.tool_name_map || {};
    COMPONENT_CATEGORIES = data.component_categories || {};
    QUICK_TEMPLATES = data.quick_templates || [];
    PROVIDERS = data.provider_presets || [];
    // 分类筛选与面板重建依赖这些全局，重新初始化面板
    if (typeof setupPalletBadges === 'function') setupPalletBadges();
    if (typeof setupCategoryFilters === 'function') setupCategoryFilters();
    if (typeof renderPallet === 'function') renderPallet();
}
```

- [ ] **Step 2: 删除硬编码元数据**

删除 `static/app.js` 中的 `COMPONENT_DEFS`（254-1118 行）、`TOOL_NAME_MAP`（129-155 行）、`COMPONENT_CATEGORIES`（1119-1181 行）的**字面量定义**，替换为 Task 2 Step 1 的 `let` 声明 + fallback。`getAllProviders`（8373 行起）改为从 `PROVIDERS` 返回。

**注意**：`COMPONENT_DEFS` 定义处可能被其他代码在 DOMContentLoaded 前同步引用——检查所有 `COMPONENT_DEFS[...]` 读取点在 init 拉取之后执行（面板渲染在 init 流程内）。若存在启动期同步依赖，调整为异步就绪后渲染。

- [ ] **Step 3: 验证**

1. `node --check static/app.js` 通过
2. 启动 `python server.py`：登录后 GET /editor 200；`GET /api/meta/components` 返回数据
3. 手工/冒烟：页面加载后组件面板条目数量与重构前一致（56 条）、分类筛选可用、拖拽一个组件到画布正常渲染（render 函数经 renderKey 关联成功）
4. 记录 app.js 行数变化（目标：删 ~1200 行）

- [ ] **Step 4: 提交**

```bash
git add static/app.js
git commit -m "feat: 前端启动拉取元数据 API + renderKey 映射 + 删除硬编码（阶段1完成）"
```

---

### Task 3: 编排链后端化（modules/orchestrator.py）

**Files:**
- Create: `modules/orchestrator.py`
- Create: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `tool_registry`（动态工具名）、`chat_with_tools`（chat_routes/llm_client）
- Produces:
  - `orchestrator.build_payload(layout: dict, comp_id: str, message: str, llm_config: dict) -> dict`（OpenAI messages/tools payload）
  - `orchestrator.resolve_tools(layout, comp_id) -> list[str]`（可达工具全名，含 mcp_external 动态）
  - `orchestrator.compose_messages(layout, comp_id, message) -> list`（含 system_prompt 组件注入）

- [ ] **Step 1: 写失败测试**

创建 `tests/test_orchestrator.py`（完整内容）：

```python
"""编排链测试：布局连线 → 工具注入 → payload"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import orchestrator
from modules import tool_registry


def _layout(components, connections):
    return {"components": components, "connections": connections}


class TestOrchestrator(unittest.TestCase):
    def setUp(self):
        tool_registry.register("_orch_test_tool", {"name": "_orch_test_tool"},
                               lambda args: "ok")
        self.addCleanup(tool_registry.unregister, "_orch_test_tool")

    def test_direct_llm_tool_connection(self):
        # LLM 直连一个工具组件 → 工具注入
        layout = _layout(
            [{"id": "llm1", "type": "llm"},
             {"id": "tz", "type": "mcp_zip"}],
            [{"sourceCompId": "llm1", "sourcePortId": "llm-out",
              "targetCompId": "tz", "targetPortId": "in"}])
        tools = orchestrator.resolve_tools(layout, "llm1")
        self.assertIn("zip_create", tools)
        self.assertIn("zip_extract", tools)

    def test_mcp_external_dynamic_tool(self):
        # mcp_external 组件：工具名来自 tool_registry 动态注册
        tool_registry.register("mcp_ext_git_echo", {"name": "mcp_ext_git_echo"},
                               lambda args: "ok")
        self.addCleanup(tool_registry.unregister, "mcp_ext_git_echo")
        layout = _layout(
            [{"id": "llm1", "type": "llm"},
             {"id": "ext", "type": "mcp_external", "serverId": "git"}],
            [{"sourceCompId": "llm1", "sourcePortId": "llm-out",
              "targetCompId": "ext", "targetPortId": "mcp-ext-in"}])
        tools = orchestrator.resolve_tools(layout, "llm1")
        self.assertIn("mcp_ext_git_echo", tools)

    def test_build_payload_shape(self):
        layout = _layout(
            [{"id": "llm1", "type": "llm"},
             {"id": "tz", "type": "calculator"}],
            [{"sourceCompId": "llm1", "sourcePortId": "llm-out",
              "targetCompId": "tz", "targetPortId": "in"}])
        payload = orchestrator.build_payload(
            layout, "llm1", "1+1=?", {"apiBase": "http://x", "model": "m"})
        self.assertIn("messages", payload)
        self.assertIn("tools", payload)
        self.assertEqual(payload["messages"][-1]["content"], "1+1=?")

    def test_system_prompt_injection(self):
        layout = _layout(
            [{"id": "llm1", "type": "llm"},
             {"id": "sp", "type": "system_prompt", "prompt": "你是测试助手"}],
            [{"sourceCompId": "llm1", "sourcePortId": "llm-out",
              "targetCompId": "sp", "targetPortId": "in"}])
        messages = orchestrator.compose_messages(layout, "llm1", "hi")
        self.assertTrue(any("测试助手" in str(m.get("content", "")) for m in messages))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m unittest tests.test_orchestrator -v`
Expected: 全部 ERROR（`No module named 'modules.orchestrator'`）

- [ ] **Step 3: 实现 orchestrator.py**

创建 `modules/orchestrator.py`。逻辑复刻前端 buildChatPayload（先读 `static/app.js` 2845-3150 行理解现有链，再 Python 化）：

```python
"""编排链：布局连线 → 可达工具 → OpenAI payload（后端单一来源）"""
import json

from . import tool_registry
from .config import get_config

# 组件类型 → 内置工具名（复刻前端 TOOL_NAME_MAP；mcp_external 动态除外）
TOOL_NAME_MAP = {
    "web_search": ["web_search"], "calculator": ["calculator"],
    "code_executor": ["code_executor"], "mcp_zip": ["zip_create", "zip_extract"],
    # ...全部（与 meta.tool_name_map 保持一致，从 Task 1 数据引用避免双源）
}
# 允许直接连 LLM 的工具组件类型（复刻前端 isToolComponent 集合）
TOOL_TYPES = set(TOOL_NAME_MAP.keys()) | {"mcp_external"}


def resolve_tools(layout, comp_id):
    """LLM 组件可达工具全名（含 mcp_external 动态注册名）"""
    tools = []
    for conn in layout.get("connections", []):
        if conn.get("sourceCompId") == comp_id:
            target = _find_comp(layout, conn.get("targetCompId"))
            if not target:
                continue
            ttype = target.get("type")
            if ttype == "mcp_external":
                # 动态工具：serverId 前缀 + tool_registry 已注册全名
                prefix = f"mcp_ext_{target.get('serverId')}_"
                for name in tool_registry.get_all_definitions():
                    fname = name["function"]["name"]
                    if fname.startswith(prefix):
                        tools.append(fname)
            elif ttype in TOOL_NAME_MAP:
                tools.extend(TOOL_NAME_MAP[ttype])
    return list(dict.fromkeys(tools))


def _find_comp(layout, comp_id):
    for c in layout.get("components", []):
        if c.get("id") == comp_id:
            return c
    return None


def compose_messages(layout, comp_id, message):
    """构造 messages：注入 system_prompt 组件内容"""
    messages = []
    for conn in layout.get("connections", []):
        if conn.get("sourceCompId") == comp_id:
            target = _find_comp(layout, conn.get("targetCompId"))
            if target and target.get("type") == "system_prompt" and target.get("prompt"):
                messages.append({"role": "system",
                                 "content": target["prompt"]})
                break
    messages.append({"role": "user", "content": message})
    return messages


def build_payload(layout, comp_id, message, llm_config=None):
    """构造 OpenAI payload（复刻前端 buildChatPayload 的 messages/tools 部分）"""
    cfg = llm_config or {}
    tools = resolve_tools(layout, comp_id)
    payload = {
        "model": cfg.get("model") or get_config()["model"],
        "messages": compose_messages(layout, comp_id, message),
        "max_tokens": cfg.get("maxTokens") or get_config()["max_tokens"],
        "temperature": cfg.get("temperature", get_config()["temperature"]),
    }
    if tools:
        payload["tools"] = tool_registry.get_definitions_by_names(tools)
    return payload
```

**注意**：TOOL_NAME_MAP 不要手写双源——优先从 Task 1 的 `modules/meta.py` 数据引用（`meta._DATA["tool_name_map"]`），或 import meta 后转义；实现者按实际代码选其一并记录。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m unittest tests.test_orchestrator -v`
Expected: 4 个测试全部 ok

- [ ] **Step 5: 提交**

```bash
git add modules/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: 编排链后端化（orchestrator：布局→工具注入→payload，含 mcp_external 动态）+ 4 测试"
```

---

### Task 4: /api/chat 双格式 + 前端发送瘦身

**Files:**
- Modify: `modules/chat_routes.py`
- Modify: `static/app.js`（发送逻辑瘦身）
- Modify: `static/chat.js`（发送格式切换，渲染零改动）
- Test: 追加 `tests/test_chat_route.py`

**Interfaces:**
- Consumes: `orchestrator.build_payload`（Task 3）
- Produces: `POST /api/chat` 同时接受旧格式（messages/tools）与新格式（layout/comp_id/message/llm_config）

- [ ] **Step 1: 写失败测试（追加到 tests/test_chat_route.py）**

```python
    def test_chat_new_format_layout(self):
        # 新请求体：layout + message（api_base 不可达 → SSE 错误事件，验证路由接受新格式）
        resp = self.client.post("/api/chat", json={
            "layout": {"components": [{"id": "llm1", "type": "llm"}],
                       "connections": []},
            "comp_id": "llm1",
            "message": "hi",
            "llm_config": {"api_base": "http://127.0.0.1:1", "max_tool_rounds": 1},
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/event-stream", resp.content_type)
        body = resp.get_data(as_text=True)
        self.assertIn("data:", body)
```

- [ ] **Step 2: 修改 chat_routes.py**

`/api/chat` 路由入口做格式分发：

```python
    data = request.get_json(force=True, silent=True) or {}
    if data.get("layout") is not None and data.get("comp_id"):
        # 新格式：后端编排
        from . import orchestrator
        llm_cfg = data.get("llm_config") or {}
        payload = orchestrator.build_payload(
            data["layout"], data["comp_id"],
            data.get("message", ""), llm_cfg)
        # 复用既有 chat_with_tools 流（工具/超时/SSE 心跳不变）
        ...
    else:
        # 旧格式：messages/tools 直接透传（过渡兼容）
        ...
```

**关键**：新格式的 SSE 事件流与旧格式完全一致（同一生成器），chat.js 渲染零改动。

- [ ] **Step 3: 前端发送瘦身**

`static/app.js` 的 chat 发送逻辑（renderChatTab 内）：改为发送新格式：

```javascript
    // 发送新格式：布局 + 消息（编排在后端）
    const payload = {
        layout: getLayoutSnapshot(),      // 现有布局收集函数
        comp_id: comp.id,
        message: text,
        llm_config: {
            apiBase: comp.apiSettings.apiBase,
            model: comp.apiSettings.model,
            maxToolRounds: comp.apiSettings.maxToolRounds,
        },
    };
```

删除 `buildChatPayload`（2845-3150 行）及前端工具名注入发送侧逻辑（mcpExternalToolNames 若仅发送用则删；若 meta 展示用则保留并注明）。`static/chat.js` 发送处同步切换新格式。

- [ ] **Step 4: 验证 + 全量回归**

1. `node --check static/app.js static/chat.js` 通过
2. `python -m unittest discover -s tests`（97 旧 + 1 新 = 98）OK
3. 冒烟：真实服务器对话触发工具调用（fixture stdio MCP server 或 calculator），确认 SSE 流与工具执行正常

- [ ] **Step 5: 提交**

```bash
git add modules/chat_routes.py static/app.js static/chat.js tests/test_chat_route.py
git commit -m "feat: /api/chat 新格式（layout+消息，后端编排）+ 前端发送瘦身 + 旧格式过渡兼容（阶段2完成）"
```

---

### Task 5: /api/meta/settings + 厂商预设并入 + 死代码清理

**Files:**
- Modify: `modules/meta.py`
- Modify: `static/app.js`
- Test: 追加 `tests/test_meta.py`

- [ ] **Step 1: settings 元数据端点**

`modules/meta.py` 加 `_SETTINGS_DATA`（主题色板/字号/行距滑块元数据，从 app.js 设置面板代码提取）+ 路由 `GET /api/meta/settings`。追加测试：端点返回结构（themes 非空等）。

- [ ] **Step 2: 厂商预设并入**

`getAllProviders`（app.js 8373 起）改为返回 `PROVIDERS`（Task 2 已从后端拉取）。删除前端硬编码厂商数组。

- [ ] **Step 3: 死代码清理**

清理重构暴露的死代码：未使用的 `_now()`、重复的工具名注入残骸、无引用函数（用 grep 确认无引用后删除）。**注意**：96 个 render 函数即使未被 COMPONENT_DEFS 引用（39 个被引用）也保留——它们是组件内部渲染辅助，删除前必须 grep 确认零引用。

- [ ] **Step 4: 验证 + 行数统计 + 提交**

1. 全量测试 OK；node --check 通过
2. 统计 `static/app.js` 行数（验收指标：≤4000 行）
3. 提交 `git commit -m "feat: /api/meta/settings + 厂商预设后端化 + 死代码清理（阶段3完成）"`

---

### Task 6: 收尾回归 + 文档 + 验收

- [ ] **Step 1: 全量回归**

Run: `python -m unittest discover -s tests`
Expected: 99（97 + meta 2 + orchestrator 4 + chat +1 等，以实测为准）全部 OK、exit 0

- [ ] **Step 2: app.js 行数验收**

`(Get-Content static\app.js | Measure-Object -Line).Lines` ≤ **4000**（核心验收指标）；若未达标，记录差距并评估是否继续瘦身（如 render 面板 HTML 模板字符串抽公共样式）。

- [ ] **Step 3: 手工功能等价验证（冒烟）**

启动服务器：登录 → 编辑器拖拽/连线/框选/模板/设置面板/对话工具调用全部走通（前端行为与重构前一致）；MCP 外部工具组件可用。

- [ ] **Step 4: 文档更新**

`docs/api-contract.md` 补充 `/api/meta/components`、`/api/meta/settings`、`/api/chat` 新格式契约；`docs/PROJECT_BRIEF.md` 加"9. 前端轻量化重构"条目 + 测试数更新。

- [ ] **Step 5: 提交 + 提示推送**

```bash
git add docs/api-contract.md
git commit -m "docs: 前端轻量化重构收尾（meta/chat 契约 + 简报）"
```

---

## Self-Review 记录

- **Spec 覆盖**：元数据 API（T1/T2）✓、编排后端化（T3/T4）✓、设置后移（T5）✓、验收回归（T6）✓
- **占位符扫描**：提取脚本骨架为"实现者补全"（提取逻辑需读实际 JS 结构，属合理开放点；数据本体由脚本生成而非手写）；其余代码完整
- **类型一致性**：renderKey/applyMeta/TOOL_NAME_MAP/QUICK_TEMPLATES/PROVIDERS、`orchestrator.resolve_tools/build_payload/compose_messages`、/api/chat 双格式在 T1-T6 间一致
- **已知限制**：前端无测试框架，T2/T4/T5 以 node --check + 冒烟 + 行数统计验证；阶段 2 的 SSE 契约不变是硬约束，T4 测试锁定
