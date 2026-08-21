# 前端轻量化重构 设计文档

> 日期：2026-08-18 · 状态：已获用户批准（分两节确认）
> 目标：前后端职责再梳理——前端变轻量薄壳（业务逻辑后移后端），代码主要在后端运行

## 一、背景与目标

当前 `static/app.js` 约 **7775 行**，承载了组件定义元数据、工具映射、快速模板、对话编排（buildChatPayload）、设置定义等大量"数据/逻辑"，与渲染交互代码混杂，难以维护。用户目标：**理清架构**——前端拆为薄壳（渲染 + 交互），业务逻辑/元数据/编排后移后端做单一来源。

### 用户已确认的决策

| 决策点 | 选择 |
|---|---|
| 动机 | 代码难维护，理清架构（非性能/移动端/换框架） |
| 形态 | **分阶段增量重构**（每阶段独立提交、功能等价、可验证） |
| 界面 | **外观不变**，纯内部重构（无 UI 改动） |
| 验收 | 功能等价（97 测试全绿 + 手工验证）+ **app.js 从 7775 → ≤4000 行** |

### 非目标（YAGNI）

- ❌ 不换前端框架/不引入构建工具（保持原生 JS 无构建栈）
- ❌ 不改界面外观
- ❌ 画布交互（拖拽/连线/框选）与组件渲染（96 个 render 函数）不后移——浏览器交互本质，必须留前端
- ❌ 不做多端/移动端适配

## 二、目标架构

```
当前: 前端(7775行: 元数据硬编码+编排+渲染全在前端) → 后端(API/存储/执行)
重构: 前端(薄壳: 渲染+交互, ≤4000行)  ←API→ 后端(元数据+编排+执行+存储 单一来源)
```

**原则**：
1. 画布交互与组件渲染（96 个 render 函数）永远留前端
2. 一切"数据/定义/编排"后移后端做单一来源
3. 每阶段：独立提交、独立测试、功能等价、可回滚

## 三、阶段划分

| 阶段 | 内容 | 前端瘦身估计 | 风险 |
|---|---|---|---|
| **1. 元数据 API 化** | 组件定义元数据 / TOOL_NAME_MAP / 分类 / 快速模板 / 厂商预设 后端下发，前端启动拉取 | 删 ~1200 行 | 低（纯数据迁移，render 不动） |
| **2. 对话编排后端化** | buildChatPayload（连线解析→工具注入→payload 构造）移到后端，前端只发布局+消息 | 删 ~600 行 | 中（/api/chat 契约演进，SSE 行为不变） |
| **3. 设置/杂项后移** | 设置面板定义、主题/字号/行距预设后端化；清死代码 | 删 ~300 行 | 低 |

## 四、阶段 1：元数据 API 化

### 后端 `modules/meta.py` + `GET /api/meta/components`

数据从 app.js 提取为 Python 结构，后端成为元数据单一来源：

```json
{
  "component_defs": {
    "llm":   {"icon":"🔌","title":"LLM API 设置","color":"#4A90D9","defaultSize":6,
              "ports":{"outputs":[{"id":"llm-out","label":"调用"}],
                       "inputs":[{"id":"llm-mem-in","label":"记忆 ←"}]},
              "description":"...", "renderKey":"renderLLMPanel", "category":"core"},
    ...
  },
  "tool_name_map": {"mcp_zip": ["zip_create","zip_extract"], ...},
  "component_categories": {"mcp_word":["MCP","cat-mcp"], ...},
  "quick_templates": [{"name":"知识库问答","layout":{...}}, ...11个],
  "provider_presets": [{"name":"OpenAI","apiBase":"...","model":"..."}, ...]
}
```

关键点：
- **renderKey**：COMPONENT_DEFS 的 `render` 字段在前端原来是函数引用；后端下发 `renderKey`（字符串），前端维护 `renderKey → 渲染函数` 本地映射表（96 个 render 函数不移动）
- 每个组件带 `category`（原 COMPONENT_CATEGORIES 并入 component_defs）
- 工具映射（TOOL_NAME_MAP）、快速模板（11 个）、厂商预设（getAllProviders）一并下发

### 前端启动时序（init 首行，await 拉取）

```javascript
const meta = await fetch('/api/meta/components').then(r => r.json()).catch(() => null);
if (meta) {
    buildComponentDefs(meta);   // 元数据 + 本地 renderKey→函数 映射成 COMPONENT_DEFS
    TOOL_NAME_MAP = meta.tool_name_map;
    COMPONENT_CATEGORIES = meta.component_categories;
    QUICK_TEMPLATES = meta.quick_templates;
    PROVIDERS = meta.provider_presets;
}
// fallback：meta 拉取失败时用内置最小集（核心组件 + 无模板），页面仍可渲染
```

- 登录保护已生效：/api/meta/components 需登录，前端未登录会 401 → 跳登录页（与现有流程一致）

## 五、阶段 2：对话编排后端化（核心）

### 现状

`buildChatPayload`（app.js:2845 起 ~600 行）在前端做：布局连线解析 → 工具名注入（含 mcp_external 动态全名）→ payload 构造；后端 `/api/chat` 只是执行通道。

### 改造

`POST /api/chat` 请求体演进——前端只发**布局 + 消息 + LLM 配置**：

```json
{
  "layout": {"components": [...], "connections": [...]},
  "comp_id": "llm_abc",
  "message": "用 python 算一下 1+1",
  "llm_config": {"apiBase": "...", "model": "...", "maxToolRounds": 50}
}
```

响应：**SSE 流完全不变**（tool-call 事件/心跳/增量文本/DONE 与现有一致，chat.js 渲染层零改动）。

### 后端新增 `modules/orchestrator.py`

Python 复刻前端解析链：
- 组件连线 → 可达工具集合（LLM 直连工具 / executor / sequential / agent 中介 / **mcp_external 动态工具**——从 tool_registry 取注册全名 `mcp_ext_<server_id>_<tool>`）
- 系统提示注入（组件级 system_prompt 组件）
- payload 构造 → 复用现有 `chat_with_tools`（tool-call 循环/超时/SSE 心跳零改动）

### 兼容策略

旧请求体（直接传 messages/tools 的格式）**保留过渡期**，后端双格式兼容；前端切换后旧路径删除。过渡期的双格式由测试锁定。

## 六、阶段 3：设置与杂项后移

- 设置面板定义（主题色板/字体大小/行距滑块元数据）→ `GET /api/meta/settings` 下发
- 厂商预设（getAllProviders @ app.js:8373）→ 并入阶段 1 的 provider_presets
- 清理重构暴露的死代码（无用的 `_now()`、重复逻辑、未使用的 import 等）

## 七、接口契约（写入 docs/api-contract.md 补充）

| 接口 | 阶段 | 说明 |
|---|---|---|
| `GET /api/meta/components` | 1 | 组件元数据+工具映射+分类+模板+厂商预设（renderKey 关联前端渲染函数） |
| `GET /api/meta/settings` | 3 | 设置面板定义（主题/字号/行距元数据） |
| `POST /api/chat`（演进） | 2 | 请求体改为 layout+消息，SSE 响应不变；旧格式过渡兼容 |

## 八、测试与验收

| 阶段 | 测试 | 验收 |
|---|---|---|
| 1 | `tests/test_meta.py`：meta 端点结构完整——56 组件 renderKey 与前端 render 函数一一对应、11 模板、厂商预设非空；前端加载 fallback | 功能等价：编辑器拖拽/面板/模板正常（前端行为不变） |
| 2 | `tests/test_orchestrator.py`：给定布局 → 工具注入正确（LLM 直连/executor 中介/mcp_external 动态全名）；SSE 事件流兼容；旧请求体过渡兼容 | 97 测试全绿 + 新测试；对话功能等价 |
| 3 | 设置预设端点测试 | **app.js 7775 → ≤4000 行**（核心验收指标） |

**风险控制**：每阶段独立提交、独立测试、可回滚；阶段 2 的 SSE 契约不变是关键（chat.js 渲染层零改动）。

## 九、实现顺序（供 writing-plans 参考）

1. 阶段 1：提取 app.js 元数据 → `modules/meta.py` + `/api/meta/components` + 测试
2. 阶段 1：前端启动拉取 + renderKey 映射 + fallback + 删除硬编码元数据
3. 阶段 2：`modules/orchestrator.py`（Python 复刻编排链）+ 测试
4. 阶段 2：/api/chat 双格式 + 前端发送瘦身 + 旧路径删除
5. 阶段 3：`/api/meta/settings` + 厂商预设并入 + 死代码清理
6. 收尾：全量回归 + app.js 行数验收 + 简报更新
