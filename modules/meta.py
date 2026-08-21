"""前端元数据单一来源：组件定义/工具映射/分类/模板/厂商预设/设置面板

数据最初由 tools/extract_meta.py 从 static/app.js 提取（该工具已退役），此后人工维护。
"""
from flask import jsonify

_DATA = {
  "component_defs": {
    "llm": {
      "icon": "🔌",
      "title": "LLM API 设置",
      "color": "#4A90D9",
      "defaultSize": 6,
      "renderKey": "renderLLMPanel",
      "ports": {
        "outputs": [
          {
            "id": "llm-out",
            "label": "调用"
          }
        ],
        "inputs": [
          {
            "id": "llm-mem-in",
            "label": "记忆 ←"
          }
        ]
      },
      "description": "配置 API 连接 + 一次性对话。连线到功能模块以启用对应能力。接入 Memory 组件后可保留对话历史。",
      "category": [
        "核心",
        "cat-core"
      ]
    },
    "sequential_executor": {
      "icon": "🔀",
      "title": "Sequential 顺序",
      "color": "#eb6f2a",
      "defaultSize": 5,
      "renderKey": "renderSequentialExecutorPanel",
      "ports": {
        "inputs": [
          {
            "id": "seq-in",
            "label": "LLM 调用 →"
          }
        ],
        "outputs": [
          {
            "id": "seq-step-1",
            "label": "步骤 1"
          },
          {
            "id": "seq-step-2",
            "label": "步骤 2"
          },
          {
            "id": "seq-step-3",
            "label": "步骤 3"
          },
          {
            "id": "seq-step-4",
            "label": "步骤 4"
          },
          {
            "id": "seq-step-5",
            "label": "步骤 5"
          }
        ]
      },
      "description": "顺序执行器。LLM 的输出连接到此处，工具按步骤端口顺序依次执行。LLM 连接后只能按此组件上连接的功能顺序依次调用。",
      "category": [
        "流程",
        "cat-flow"
      ]
    },
    "plan": {
      "icon": "📋",
      "title": "Plan 规划",
      "color": "#389e0d",
      "defaultSize": 5,
      "renderKey": "renderPlanPanel",
      "ports": {
        "inputs": [
          {
            "id": "plan-in",
            "label": "LLM 接入"
          }
        ],
        "outputs": [
          {
            "id": "plan-out",
            "label": "计划 → 执行器"
          }
        ]
      },
      "description": "Agent 规划模块。分析任务 → 分解步骤 → 生成计划 → 执行后反思 → 自动重规划。连线到 Executor 形成 Plan-Execute-Reflect 循环。",
      "category": [
        "编排",
        "cat-orch"
      ]
    },
    "executor": {
      "icon": "▶",
      "title": "Executor 执行",
      "color": "#c41d7f",
      "defaultSize": 4,
      "renderKey": "renderExecutorPanel",
      "ports": {
        "inputs": [
          {
            "id": "exec-llm-in",
            "label": "LLM 驱动"
          },
          {
            "id": "exec-plan-in",
            "label": "Plan/Loop 驱动"
          }
        ],
        "outputs": [
          {
            "id": "exec-tool-1",
            "label": "工具 1"
          },
          {
            "id": "exec-tool-2",
            "label": "工具 2"
          },
          {
            "id": "exec-tool-3",
            "label": "工具 3"
          },
          {
            "id": "exec-tool-4",
            "label": "工具 4"
          },
          {
            "id": "exec-tool-5",
            "label": "工具 5"
          }
        ]
      },
      "description": "Agent 执行模块。接收单步任务，询问 LLM 决定用什么工具，执行并返回结果。由 Plan/Loop 驱动执行循环。",
      "category": [
        "流程",
        "cat-flow"
      ]
    },
    "skills_manager": {
      "icon": "🧠",
      "title": "Skills Manager",
      "color": "#a855f7",
      "defaultSize": 5,
      "renderKey": "renderSkillsManagerPanel",
      "ports": {
        "inputs": [
          {
            "id": "skm-llm-in",
            "label": "LLM 驱动"
          }
        ],
        "outputs": []
      },
      "description": "技能集中管理器。LLM 驱动（左绿），所有技能汇聚于此合并 System Prompt（右蓝）。技能不能直连其他模块。",
      "category": [
        "Skill",
        "cat-skills"
      ]
    },
    "skill_auto_call": {
      "icon": "🧠",
      "title": "Skill Auto Call",
      "color": "#7c3aed",
      "defaultSize": 4,
      "renderKey": "renderSkillAutoCallPanel",
      "ports": {
        "inputs": [
          {
            "id": "auto-llm-in",
            "label": "LLM 驱动"
          }
        ],
        "outputs": [
          {
            "id": "auto-skm-out",
            "label": "→ Skills Manager"
          }
        ]
      },
      "description": "智能技能调度器。介于 LLM 与 Skills Manager 之间，LLM 可自主选择调用哪些技能，而非全部注入。配合 AI 对话页\"智能模式\"使用。",
      "category": [
        "Skill",
        "cat-skills"
      ]
    },
    "loop": {
      "icon": "🔁",
      "title": "Loop 循环",
      "color": "#7b1fa2",
      "defaultSize": 4,
      "renderKey": "renderLoopPanel",
      "ports": {
        "inputs": [
          {
            "id": "loop-plan-in",
            "label": "Plan 接入"
          },
          {
            "id": "loop-exec-fb",
            "label": "执行反馈 ←"
          }
        ],
        "outputs": [
          {
            "id": "loop-exec-out",
            "label": "→ 执行器"
          },
          {
            "id": "loop-break",
            "label": "结束信号"
          }
        ]
      },
      "description": "循环控制器。连接 Plan 和 Executor，构建 Plan→Execute→Reflect→Replan 循环。Plan 决定继续或跳出循环。",
      "category": [
        "流程",
        "cat-flow"
      ]
    },
    "memory": {
      "icon": "🧠",
      "title": "Chat Memory",
      "color": "#8b5cf6",
      "defaultSize": 3,
      "renderKey": "renderMemoryPanel",
      "ports": {
        "outputs": [
          {
            "id": "mem-out",
            "label": "历史 →"
          }
        ],
        "inputs": [
          {
            "id": "mem-in",
            "label": "写入"
          }
        ]
      },
      "description": "存储对话历史。连线到 LLM 组件后，AI 会记住之前的对话内容。断开连线则每次都是全新对话。",
      "category": [
        "记忆",
        "cat-memory"
      ]
    },
    "token_counter": {
      "icon": "🧮",
      "title": "Token 计数器",
      "color": "#f5222d",
      "defaultSize": 3,
      "renderKey": "renderTokenCounterPanel",
      "ports": {
        "inputs": [
          {
            "id": "tc-llm-in",
            "label": "LLM 接入"
          }
        ],
        "outputs": []
      },
      "description": "连接 LLM 后，AI 对话页的输入框上方会实时显示本次对话的 Token 用量。只能连接 LLM。",
      "category": [
        "记忆",
        "cat-memory"
      ]
    },
    "system_prompt": {
      "icon": "🎭",
      "title": "System Prompt",
      "color": "#52c41a",
      "defaultSize": 5,
      "renderKey": "renderSystemPromptPanel",
      "ports": {
        "inputs": [
          {
            "id": "sp-in",
            "label": "人设 → LLM"
          }
        ],
        "outputs": []
      },
      "description": "定制 AI 角色、说话风格、回答方式。内置多套人设模板，也可自定义。只能连接到 LLM。",
      "category": [
        "核心",
        "cat-core"
      ]
    },
    "function_calling": {
      "icon": "🔧",
      "title": "Function Calling",
      "color": "#fa8c16",
      "defaultSize": 4,
      "renderKey": "renderFunctionCallingPanel",
      "ports": {
        "inputs": [
          {
            "id": "fc-in",
            "label": "Tools"
          }
        ],
        "outputs": []
      },
      "description": "定义工具 JSON Schema，让 AI 调用外部函数。",
      "category": [
        "核心",
        "cat-core"
      ]
    },
    "vision": {
      "icon": "👁",
      "title": "Vision 视觉",
      "color": "#eb2f96",
      "defaultSize": 4,
      "renderKey": "renderVisionPanel",
      "ports": {
        "inputs": [
          {
            "id": "vis-in",
            "label": "Vision"
          }
        ],
        "outputs": []
      },
      "description": "上传图片进行多模态理解与分析。",
      "category": [
        "Tools",
        "cat-tools"
      ]
    },
    "json_mode": {
      "icon": "🧬",
      "title": "JSON Mode",
      "color": "#722ed1",
      "defaultSize": 4,
      "renderKey": "renderJSONModePanel",
      "ports": {
        "inputs": [
          {
            "id": "jm-in",
            "label": "JSON Schema"
          }
        ],
        "outputs": []
      },
      "description": "强制 AI 按指定 JSON Schema 输出结构化数据。",
      "category": [
        "核心",
        "cat-core"
      ]
    },
    "embeddings": {
      "icon": "🧮",
      "title": "Embeddings",
      "color": "#13c2c2",
      "defaultSize": 3,
      "renderKey": "renderEmbeddingsPanel",
      "ports": {
        "inputs": [
          {
            "id": "emb-in",
            "label": "Embeddings"
          }
        ],
        "outputs": []
      },
      "description": "将文本转换为向量，用于语义搜索与相似度计算。",
      "category": [
        "核心",
        "cat-core"
      ]
    },
    "token_manager": {
      "icon": "🎯",
      "title": "Token Manager",
      "color": "#f5222d",
      "defaultSize": 3,
      "renderKey": "renderTokenManagerPanel",
      "ports": {
        "inputs": [
          {
            "id": "tm-in",
            "label": "Token"
          }
        ],
        "outputs": []
      },
      "description": "统计 Token 数量，管理上下文窗口长度。",
      "category": [
        "记忆",
        "cat-memory"
      ]
    },
    "agent": {
      "icon": "🤖",
      "title": "Agent 编排器",
      "color": "#667eea",
      "defaultSize": 6,
      "renderKey": "renderAgentPanel",
      "ports": {
        "inputs": [
          {
            "id": "agent-llm-in",
            "label": "LLM 大脑"
          },
          {
            "id": "agent-mem-in",
            "label": "记忆 ←"
          }
        ],
        "outputs": [
          {
            "id": "agent-tool-1",
            "label": "工具 1"
          },
          {
            "id": "agent-tool-2",
            "label": "工具 2"
          },
          {
            "id": "agent-tool-3",
            "label": "工具 3"
          },
          {
            "id": "agent-tool-4",
            "label": "工具 4"
          },
          {
            "id": "agent-tool-5",
            "label": "工具 5"
          }
        ]
      },
      "description": "Agent 主循环中枢：自动协调 Plan→Execute→Reflect 流程。连线 LLM 大脑 + 记忆 + 工具即可快速构建完整 Agent。一键启动自动循环。",
      "category": [
        "编排",
        "cat-orch"
      ]
    },
    "reflection": {
      "icon": "💬",
      "title": "Reflection 反思",
      "color": "#d48806",
      "defaultSize": 4,
      "renderKey": "renderReflectionPanel",
      "ports": {
        "inputs": [
          {
            "id": "refl-plan-in",
            "label": "Plan 结果"
          },
          {
            "id": "refl-exec-in",
            "label": "执行结果"
          }
        ],
        "outputs": [
          {
            "id": "refl-continue",
            "label": "继续 →"
          },
          {
            "id": "refl-replan",
            "label": "重规划 →"
          },
          {
            "id": "refl-complete",
            "label": "完成 ✓"
          }
        ]
      },
      "description": "自我评估模块。分析执行结果，判断任务完成度。输出三种信号：继续执行 / 需要重规划 / 任务完成。连接 Plan 和 Executor 形成闭环。",
      "category": [
        "编排",
        "cat-orch"
      ]
    },
    "vector_memory": {
      "icon": "🧮",
      "title": "Vector Memory",
      "color": "#13c2c2",
      "defaultSize": 4,
      "renderKey": "renderVectorMemoryPanel",
      "ports": {
        "inputs": [
          {
            "id": "vm-in",
            "label": "向量化写入"
          }
        ],
        "outputs": [
          {
            "id": "vm-out",
            "label": "搜索结果 →"
          }
        ]
      },
      "description": "长期语义记忆库。将文本转换为向量并存储，支持语义相似搜索。连线到 LLM 后可检索历史知识。",
      "category": [
        "记忆",
        "cat-memory"
      ]
    },
    "knowledge_base": {
      "icon": "📚",
      "title": "知识库",
      "color": "#fa541c",
      "defaultSize": 3,
      "renderKey": "renderKnowledgeBasePanel",
      "ports": {
        "outputs": [
          {
            "id": "kb-out",
            "label": "→ 向量记忆"
          }
        ],
        "inputs": []
      },
      "description": "从电脑导入文本文件或粘贴文本到知识库。只能连接到 Vector Memory，可自定义名称（拖出默认 知识库1/2…）。",
      "category": [
        "记忆",
        "cat-memory"
      ]
    },
    "working_memory": {
      "icon": "📝",
      "title": "Working Memory",
      "color": "#d4b106",
      "defaultSize": 3,
      "renderKey": "renderWorkingMemoryPanel",
      "ports": {
        "inputs": [
          {
            "id": "wm-in",
            "label": "写入"
          }
        ],
        "outputs": [
          {
            "id": "wm-out",
            "label": "读取 →"
          }
        ]
      },
      "description": "Agent 工作草稿板。Key-Value 临时存储，Agent 执行过程中存放中间计算结果和临时数据。任务结束后自动清空。",
      "category": [
        "记忆",
        "cat-memory"
      ]
    },
    "memory_summarizer": {
      "icon": "📝",
      "title": "记忆总结",
      "color": "#722ed1",
      "defaultSize": 3,
      "renderKey": "renderMemorySummarizerPanel",
      "ports": {
        "inputs": [
          {
            "id": "ms-in",
            "label": "记忆输入"
          }
        ],
        "outputs": [
          {
            "id": "ms-out",
            "label": "总结输出"
          }
        ]
      },
      "description": "通过 AI 压缩总结对话记忆。只能连接到记忆组件（Memory）。支持手动触发和自动触发（到达设定 token 数时自动总结）。",
      "category": [
        "记忆",
        "cat-memory"
      ]
    },
    "conditional": {
      "icon": "🔀",
      "title": "Conditional 条件",
      "color": "#389e0d",
      "defaultSize": 4,
      "renderKey": "renderConditionalPanel",
      "ports": {
        "inputs": [
          {
            "id": "cond-in",
            "label": "上一步结果"
          }
        ],
        "outputs": [
          {
            "id": "cond-true",
            "label": "True ✓"
          },
          {
            "id": "cond-false",
            "label": "False ✗"
          }
        ]
      },
      "description": "条件分支路由。根据上一步执行结果判断：成功走 True 分支，失败走 False 分支。实现 Agent 的 if/else 决策逻辑。",
      "category": [
        "流程",
        "cat-flow"
      ]
    },
    "skill_document": {
      "icon": "📄",
      "title": "Document Skill",
      "color": "#2b5797",
      "defaultSize": 5,
      "renderKey": "renderSkillPanel",
      "ports": {
        "inputs": [
          {
            "id": "skill-in",
            "label": "Skill Prompt -> LLM"
          }
        ],
        "outputs": [
          {
            "id": "skill-out",
            "label": "Skill -> Manager"
          }
        ]
      },
      "description": "文档处理专家：阅读分析、格式转换、创建生成、翻译校对。连接到 Skills Manager 后注入专业文档处理 System Prompt。",
      "category": [
        "Skill",
        "cat-skills"
      ]
    },
    "skill_frontend": {
      "icon": "🎨",
      "title": "Frontend Design",
      "color": "#ec4899",
      "defaultSize": 5,
      "renderKey": "renderSkillPanel",
      "ports": {
        "inputs": [
          {
            "id": "skill-in",
            "label": "Skill Prompt -> LLM"
          }
        ],
        "outputs": [
          {
            "id": "skill-out",
            "label": "Skill -> Manager"
          }
        ]
      },
      "description": "知名设计工作室主管视角。为每个项目打造独一无二的视觉身份：配色系统、字体搭配、布局概念、动效设计。拒绝模板化套路。",
      "category": [
        "Skill",
        "cat-skills"
      ]
    },
    "skill_uiux": {
      "icon": "🎨",
      "title": "UI/UX Pro Max",
      "color": "#8b5cf6",
      "defaultSize": 5,
      "renderKey": "renderSkillPanel",
      "ports": {
        "inputs": [
          {
            "id": "skill-in",
            "label": "Skill Prompt -> LLM"
          }
        ],
        "outputs": [
          {
            "id": "skill-out",
            "label": "Skill -> Manager"
          }
        ]
      },
      "description": "全方位 UI/UX 设计智能：84 种风格 + 192 套配色 + 74 组字体 + 98 条 UX 规范，覆盖 22 个技术栈。",
      "category": [
        "Skill",
        "cat-skills"
      ]
    },
    "skill_find": {
      "icon": "🔍",
      "title": "Find Skills",
      "color": "#06b6d4",
      "defaultSize": 4,
      "renderKey": "renderSkillPanel",
      "ports": {
        "inputs": [
          {
            "id": "skill-in",
            "label": "Skill Prompt -> LLM"
          }
        ],
        "outputs": [
          {
            "id": "skill-out",
            "label": "Skill -> Manager"
          }
        ]
      },
      "description": "从开放 Agent 技能生态中搜索和发现可安装的技能。验证安装量和来源信誉，筛选高质量技能。",
      "category": [
        "Skill",
        "cat-skills"
      ]
    },
    "skill_creator": {
      "icon": "⚡",
      "title": "Skill Creator",
      "color": "#f59e0b",
      "defaultSize": 5,
      "renderKey": "renderSkillPanel",
      "ports": {
        "inputs": [
          {
            "id": "skill-in",
            "label": "Skill Prompt -> LLM"
          }
        ],
        "outputs": [
          {
            "id": "skill-out",
            "label": "Skill -> Manager"
          }
        ]
      },
      "description": "从零创建、迭代改进和优化 Agent 技能。撰写 SKILL.md、编写测试用例、运行评测、优化触发描述。",
      "category": [
        "Skill",
        "cat-skills"
      ]
    },
    "skill_super": {
      "icon": "💪",
      "title": "Superpowers",
      "color": "#ef4444",
      "defaultSize": 4,
      "renderKey": "renderSkillPanel",
      "ports": {
        "inputs": [
          {
            "id": "skill-in",
            "label": "Skill Prompt -> LLM"
          }
        ],
        "outputs": [
          {
            "id": "skill-out",
            "label": "Skill -> Manager"
          }
        ]
      },
      "description": "元技能——强制在任何操作前先调用合适的技能。红旗检测杜绝合理化借口，流程类技能优先。",
      "category": [
        "Skill",
        "cat-skills"
      ]
    },
    "skill_pua": {
      "icon": "🔥",
      "title": "PUA Coach",
      "color": "#f97316",
      "defaultSize": 5,
      "renderKey": "renderSkillPanel",
      "ports": {
        "inputs": [
          {
            "id": "skill-in",
            "label": "Skill Prompt -> LLM"
          }
        ],
        "outputs": [
          {
            "id": "skill-out",
            "label": "Skill -> Manager"
          }
        ]
      },
      "description": "高绩效文化教练。三条红线（闭环/事实/穷尽）+ 方法论智能路由（华为/阿里/字节/Musk 等）+ L0-L4 压力升级。",
      "category": [
        "Skill",
        "cat-skills"
      ]
    },
    "web_search": {
      "icon": "🔍",
      "title": "Web Search",
      "color": "#1890ff",
      "defaultSize": 4,
      "renderKey": "renderWebSearchPanel",
      "ports": {
        "inputs": [
          {
            "id": "ws-in",
            "label": "搜索结果 → LLM"
          }
        ],
        "outputs": []
      },
      "description": "通过 DuckDuckGo 搜索网页。连线到 LLM 后，搜索结果会作为对话上下文。",
      "category": [
        "Tools",
        "cat-tools"
      ]
    },
    "calculator": {
      "icon": "🖩",
      "title": "Calculator",
      "color": "#2f54eb",
      "defaultSize": 3,
      "renderKey": "renderCalculatorPanel",
      "ports": {
        "inputs": [
          {
            "id": "calc-in",
            "label": "计算结果 → LLM"
          }
        ],
        "outputs": []
      },
      "description": "安全计算数学表达式。连线到 LLM 后，计算结果会作为对话上下文。",
      "category": [
        "Tools",
        "cat-tools"
      ]
    },
    "code_executor": {
      "icon": "💻",
      "title": "Code Executor",
      "color": "#531dab",
      "defaultSize": 4,
      "renderKey": "renderCodeExecutorPanel",
      "ports": {
        "inputs": [
          {
            "id": "code-in",
            "label": "执行结果 → LLM"
          }
        ],
        "outputs": []
      },
      "description": "沙箱执行 Python 代码。连线到 LLM 后，执行输出会作为对话上下文。",
      "category": [
        "Tools",
        "cat-tools"
      ]
    },
    "text_tools": {
      "icon": "📄",
      "title": "Text Tools",
      "color": "#08979c",
      "defaultSize": 4,
      "renderKey": "renderTextToolsPanel",
      "ports": {
        "inputs": [
          {
            "id": "txt-in",
            "label": "分析结果 → LLM"
          }
        ],
        "outputs": []
      },
      "description": "文本统计与格式化。连线到 LLM 后，分析结果会作为对话上下文。",
      "category": [
        "Tools",
        "cat-tools"
      ]
    },
    "time_query": {
      "icon": "🕐",
      "title": "时间查询",
      "color": "#595959",
      "defaultSize": 3,
      "renderKey": "renderSimpleToolPanel",
      "ports": {
        "inputs": [
          {
            "id": "tq-in",
            "label": "时间 → LLM"
          }
        ],
        "outputs": []
      },
      "description": "获取当前日期、时间、星期、Unix 时间戳。连线到 LLM 后 AI 可回答时间相关问题。",
      "category": [
        "Tools",
        "cat-tools"
      ]
    },
    "url_fetch": {
      "icon": "🌐",
      "title": "网页抓取",
      "color": "#096dd9",
      "defaultSize": 3,
      "renderKey": "renderSimpleToolPanel",
      "ports": {
        "inputs": [
          {
            "id": "uf-in",
            "label": "网页内容 → LLM"
          }
        ],
        "outputs": []
      },
      "description": "抓取指定 URL 的网页并提取纯文本。与 Web Search 互补：搜索找链接，抓取读内容。",
      "category": [
        "Tools",
        "cat-tools"
      ]
    },
    "file_ops": {
      "icon": "📂",
      "title": "文件操作",
      "color": "#d48806",
      "defaultSize": 3,
      "renderKey": "renderSimpleToolPanel",
      "ports": {
        "inputs": [
          {
            "id": "fo-in",
            "label": "文件内容 → LLM"
          }
        ],
        "outputs": []
      },
      "description": "工作区文件全套操作：file_read / file_write / glob_search / grep_search / file_edit。AI 可搜索、读写、编辑文件。",
      "category": [
        "Tools",
        "cat-tools"
      ]
    },
    "json_query": {
      "icon": "🔍",
      "title": "JSON 查询",
      "color": "#722ed1",
      "defaultSize": 3,
      "renderKey": "renderSimpleToolPanel",
      "ports": {
        "inputs": [
          {
            "id": "jq-in",
            "label": "查询结果 → LLM"
          }
        ],
        "outputs": []
      },
      "description": "对 JSON 数据执行路径查询（$.data.items[0].name）。适合解析 API 返回的 JSON。",
      "category": [
        "Tools",
        "cat-tools"
      ]
    },
    "mcp_zip": {
      "icon": "📦",
      "title": "压缩工具",
      "color": "#fa8c16",
      "defaultSize": 3,
      "renderKey": "renderSimpleToolPanel",
      "ports": {
        "inputs": [
          {
            "id": "zip-in",
            "label": "结果 → LLM"
          }
        ],
        "outputs": []
      },
      "description": "文件压缩打包与解压：zip_create 按文件/通配符打包，zip_extract 解压（内置 zip-slip 防护）。适合批量交付文件。",
      "category": [
        "Tools",
        "cat-tools"
      ]
    },
    "http_request": {
      "icon": "🌐",
      "title": "HTTP 请求",
      "color": "#13c2c2",
      "defaultSize": 3,
      "renderKey": "renderSimpleToolPanel",
      "ports": {
        "inputs": [
          {
            "id": "http-in",
            "label": "响应 → LLM"
          }
        ],
        "outputs": []
      },
      "description": "发送通用 HTTP 请求：支持 GET/POST/PUT/PATCH/DELETE、JSON 请求体、自定义头、查询参数。对接任意第三方 API。",
      "category": [
        "Tools",
        "cat-tools"
      ]
    },
    "image_tools": {
      "icon": "🖼",
      "title": "图片工具",
      "color": "#eb2f96",
      "defaultSize": 3,
      "renderKey": "renderSimpleToolPanel",
      "ports": {
        "inputs": [
          {
            "id": "img-in",
            "label": "结果 → LLM"
          }
        ],
        "outputs": []
      },
      "description": "图片全套处理：screenshot 截屏、image_info 查看信息、image_convert 格式转换、image_resize 缩放、image_compress 压缩。",
      "category": [
        "Tools",
        "cat-tools"
      ]
    },
    "mcp_external": {
      "icon": "🔗",
      "title": "外部 MCP 工具",
      "color": "#389e0d",
      "defaultSize": 5,
      "renderKey": "renderMcpExternalPanel",
      "ports": {
        "inputs": [
          {
            "id": "mcp-ext-in",
            "label": "LLM 接入"
          }
        ],
        "outputs": []
      },
      "description": "连接设置中配置的 MCP server，将其工具注入 LLM。可勾选要使用的工具子集。",
      "category": [
        "MCP",
        "cat-mcp"
      ]
    },
    "mcp_weather": {
      "icon": "🌤",
      "title": "Weather 天气",
      "color": "#1890ff",
      "defaultSize": 4,
      "renderKey": "renderMCPWeatherPanel",
      "ports": {
        "inputs": [
          {
            "id": "weather-in",
            "label": "天气数据 → LLM"
          }
        ],
        "outputs": []
      },
      "description": "查询实时天气和预报。需要 OpenWeatherMap API Key（免费注册）。支持全球城市天气查询。",
      "category": [
        "MCP",
        "cat-mcp"
      ]
    },
    "mcp_database": {
      "icon": "🗄",
      "title": "Database 数据库",
      "color": "#52c41a",
      "defaultSize": 4,
      "renderKey": "renderMCPDatabasePanel",
      "ports": {
        "inputs": [
          {
            "id": "db-in",
            "label": "查询结果 → LLM"
          }
        ],
        "outputs": []
      },
      "description": "连接 SQLite 数据库，执行 SELECT 查询、浏览表结构。设置 .sqlite/.db 文件路径即可使用。",
      "category": [
        "MCP",
        "cat-mcp"
      ]
    },
    "mcp_git": {
      "icon": "🔀",
      "title": "Git 版本控制",
      "color": "#fa8c16",
      "defaultSize": 4,
      "renderKey": "renderMCPGitPanel",
      "ports": {
        "inputs": [
          {
            "id": "git-in",
            "label": "Git 信息 → LLM"
          }
        ],
        "outputs": []
      },
      "description": "查看 Git 仓库状态、提交历史、代码差异和分支列表。设置仓库路径即可使用。",
      "category": [
        "MCP",
        "cat-mcp"
      ]
    },
    "mcp_clipboard": {
      "icon": "📋",
      "title": "Clipboard 剪贴板",
      "color": "#722ed1",
      "defaultSize": 3,
      "renderKey": "renderMCPSimplePanel",
      "ports": {
        "inputs": [
          {
            "id": "clip-in",
            "label": "剪贴板 → LLM"
          }
        ],
        "outputs": []
      },
      "description": "读取和写入系统剪贴板。AI 可以直接获取你复制的内容，或将结果写入剪贴板。",
      "category": [
        "MCP",
        "cat-mcp"
      ]
    },
    "mcp_encoding": {
      "icon": "🔐",
      "title": "编码实用工具",
      "color": "#2f54eb",
      "defaultSize": 4,
      "renderKey": "renderMCPSimplePanel",
      "ports": {
        "inputs": [
          {
            "id": "enc-in",
            "label": "工具结果 → LLM"
          }
        ],
        "outputs": []
      },
      "description": "Base64、哈希计算、密码生成、UUID、正则测试、文本差异对比、Markdown转换、单位换算、URL编解码。全部使用 Python 内置模块。",
      "category": [
        "MCP",
        "cat-mcp"
      ]
    },
    "mcp_system": {
      "icon": "💻",
      "title": "System 系统工具",
      "color": "#389e0d",
      "defaultSize": 4,
      "renderKey": "renderMCPSimplePanel",
      "ports": {
        "inputs": [
          {
            "id": "sys-in",
            "label": "系统信息 → LLM"
          }
        ],
        "outputs": []
      },
      "description": "系统资源监控、DNS查询、二维码生成、桌面通知、用默认程序打开文件。",
      "category": [
        "MCP",
        "cat-mcp"
      ]
    },
    "mcp_email": {
      "icon": "✉",
      "title": "Email 邮件",
      "color": "#c41d7f",
      "defaultSize": 4,
      "renderKey": "renderMCPEmailPanel",
      "ports": {
        "inputs": [
          {
            "id": "email-in",
            "label": "邮件结果 → LLM"
          }
        ],
        "outputs": []
      },
      "description": "通过 SMTP 发送邮件。支持 Gmail/Outlook/QQ/163 及自定义服务器。需要邮箱密码或授权码。",
      "category": [
        "MCP",
        "cat-mcp"
      ]
    },
    "mcp_translate": {
      "icon": "🌐",
      "title": "Translate 翻译",
      "color": "#096dd9",
      "defaultSize": 3,
      "renderKey": "renderMCPTranslatePanel",
      "ports": {
        "inputs": [
          {
            "id": "tr-in",
            "label": "翻译结果 → LLM"
          }
        ],
        "outputs": []
      },
      "description": "多语言文本翻译和语言检测。使用免费 deep-translator 库，无需 API Key。",
      "category": [
        "MCP",
        "cat-mcp"
      ]
    },
    "mcp_calendar": {
      "icon": "📅",
      "title": "Calendar 日历",
      "color": "#d4b106",
      "defaultSize": 3,
      "renderKey": "renderMCPSimplePanel",
      "ports": {
        "inputs": [
          {
            "id": "cal-in",
            "label": "日程 → LLM"
          }
        ],
        "outputs": []
      },
      "description": "创建和查看日程事件。数据存储在本地 JSON 文件，无需 Google 账号。",
      "category": [
        "MCP",
        "cat-mcp"
      ]
    },
    "mcp_pdf": {
      "icon": "📄",
      "title": "PDF 文档",
      "color": "#cf1322",
      "defaultSize": 3,
      "renderKey": "renderMCPSimplePanel",
      "ports": {
        "inputs": [
          {
            "id": "pdf-in",
            "label": "PDF 内容 → LLM"
          }
        ],
        "outputs": []
      },
      "description": "读取 PDF 提取文本、从 Markdown 创建 PDF、合并多个 PDF。需要 pypdf/fpdf 库。",
      "category": [
        "MCP",
        "cat-mcp"
      ]
    },
    "mcp_finance": {
      "icon": "💱",
      "title": "Finance 金融",
      "color": "#08979c",
      "defaultSize": 3,
      "renderKey": "renderMCPSimplePanel",
      "ports": {
        "inputs": [
          {
            "id": "fin-in",
            "label": "金融数据 → LLM"
          }
        ],
        "outputs": []
      },
      "description": "实时汇率转换、股票价格查询（Yahoo Finance）、加密货币价格（CoinGecko）。免费无需 API Key。",
      "category": [
        "MCP",
        "cat-mcp"
      ]
    },
    "mcp_geocode": {
      "icon": "📍",
      "title": "Geo 地理",
      "color": "#7b1fa2",
      "defaultSize": 3,
      "renderKey": "renderMCPSimplePanel",
      "ports": {
        "inputs": [
          {
            "id": "geo-in",
            "label": "地理数据 → LLM"
          }
        ],
        "outputs": []
      },
      "description": "地址↔坐标转换（OpenStreetMap）、IP归属地查询、两点距离计算。全部免费服务。",
      "category": [
        "MCP",
        "cat-mcp"
      ]
    },
    "mcp_navigation": {
      "icon": "🧭",
      "title": "Navigation 导航",
      "color": "#0050b3",
      "defaultSize": 5,
      "renderKey": "renderMCPNavPanel",
      "ports": {
        "inputs": [
          {
            "id": "nav-in",
            "label": "导航数据 → LLM"
          }
        ],
        "outputs": []
      },
      "description": "路线规划 + 地点搜索。支持高德/百度/Google Maps/OSRM(免费)。选择提供商并配置 API Key 即可使用。",
      "category": [
        "MCP",
        "cat-mcp"
      ]
    },
    "mcp_word": {
      "icon": "📝",
      "title": "Word 文档",
      "color": "#2b5797",
      "defaultSize": 4,
      "renderKey": "renderMCPWordPanel",
      "ports": {
        "inputs": [
          {
            "id": "word-in",
            "label": "Word 操作 → LLM"
          }
        ],
        "outputs": []
      },
      "description": "创建与编辑 Word (.docx) 文档。AI 可调用 word_create、word_add_paragraph、word_add_table、word_save 等工具生成专业文档。",
      "category": [
        "MCP",
        "cat-mcp"
      ]
    },
    "mcp_excel": {
      "icon": "📊",
      "title": "Excel 表格",
      "color": "#217346",
      "defaultSize": 4,
      "renderKey": "renderMCPExcelPanel",
      "ports": {
        "inputs": [
          {
            "id": "excel-in",
            "label": "Excel 操作 → LLM"
          }
        ],
        "outputs": []
      },
      "description": "创建与编辑 Excel (.xlsx) 工作簿。AI 可调用 excel_create、excel_write_cell、excel_read_cell、excel_save 等工具处理表格数据。",
      "category": [
        "MCP",
        "cat-mcp"
      ]
    },
    "mcp_ppt": {
      "icon": "📊",
      "title": "PowerPoint",
      "color": "#d24726",
      "defaultSize": 4,
      "renderKey": "renderMCPPPTPanel",
      "ports": {
        "inputs": [
          {
            "id": "ppt-in",
            "label": "PPT 操作 → LLM"
          }
        ],
        "outputs": []
      },
      "description": "创建与编辑 PowerPoint (.pptx) 演示文稿。AI 可调用 ppt_create、ppt_add_slide、ppt_add_text、ppt_add_bullet_list、ppt_save 等工具制作幻灯片。",
      "category": [
        "MCP",
        "cat-mcp"
      ]
    }
  },
  "tool_name_map": {
    "web_search": [
      "web_search"
    ],
    "calculator": [
      "calculator"
    ],
    "code_executor": [
      "code_executor"
    ],
    "text_tools": [
      "text_analyze",
      "text_format"
    ],
    "time_query": [
      "get_current_time"
    ],
    "url_fetch": [
      "url_fetch"
    ],
    "file_ops": [
      "file_read",
      "file_write",
      "glob_search",
      "grep_search",
      "file_edit"
    ],
    "json_query": [
      "json_query"
    ],
    "vector_memory": [
      "embeddings_search",
      "embeddings_index"
    ],
    "mcp_word": [
      "word_create",
      "word_add_heading",
      "word_add_paragraph",
      "word_add_table",
      "word_save"
    ],
    "mcp_excel": [
      "excel_create",
      "excel_write_cell",
      "excel_read_cell",
      "excel_add_sheet",
      "excel_save"
    ],
    "mcp_ppt": [
      "ppt_create",
      "ppt_add_slide",
      "ppt_add_text",
      "ppt_add_bullet_list",
      "ppt_save"
    ],
    "mcp_weather": [
      "weather_current",
      "weather_forecast"
    ],
    "mcp_database": [
      "db_query",
      "db_list_tables",
      "db_schema"
    ],
    "mcp_git": [
      "git_status",
      "git_log",
      "git_diff",
      "git_branch"
    ],
    "mcp_clipboard": [
      "clipboard_read",
      "clipboard_write"
    ],
    "mcp_encoding": [
      "base64_encode",
      "base64_decode",
      "hash_compute",
      "password_generate",
      "uuid_generate",
      "regex_test",
      "diff_text",
      "markdown_to_html",
      "html_to_markdown",
      "unit_convert",
      "url_encode"
    ],
    "mcp_system": [
      "system_info",
      "dns_lookup",
      "qr_generate",
      "open_file",
      "desktop_notify"
    ],
    "mcp_email": [
      "email_send"
    ],
    "mcp_translate": [
      "translate_text",
      "detect_language"
    ],
    "mcp_calendar": [
      "calendar_list",
      "calendar_create"
    ],
    "mcp_pdf": [
      "pdf_read",
      "pdf_create",
      "pdf_merge"
    ],
    "mcp_finance": [
      "currency_convert",
      "stock_price"
    ],
    "mcp_geocode": [
      "geocode_address",
      "reverse_geocode",
      "ip_geolocation",
      "distance_calc"
    ],
    "mcp_navigation": [
      "nav_route",
      "nav_search_place"
    ],
    "plan": [
      "plan_generate",
      "plan_execute_step"
    ],
    "memory_summarizer": [
      "memory_summarize"
    ],
    "mcp_zip": [
      "zip_create",
      "zip_extract"
    ],
    "http_request": [
      "http_request"
    ],
    "image_tools": [
      "screenshot",
      "image_info",
      "image_convert",
      "image_resize",
      "image_compress"
    ]
  },
  "component_categories": {
    "llm": [
      "核心",
      "cat-core"
    ],
    "system_prompt": [
      "核心",
      "cat-core"
    ],
    "function_calling": [
      "核心",
      "cat-core"
    ],
    "json_mode": [
      "核心",
      "cat-core"
    ],
    "embeddings": [
      "核心",
      "cat-core"
    ],
    "agent": [
      "编排",
      "cat-orch"
    ],
    "plan": [
      "编排",
      "cat-orch"
    ],
    "reflection": [
      "编排",
      "cat-orch"
    ],
    "executor": [
      "流程",
      "cat-flow"
    ],
    "sequential_executor": [
      "流程",
      "cat-flow"
    ],
    "skills_manager": [
      "Skill",
      "cat-skills"
    ],
    "skill_auto_call": [
      "Skill",
      "cat-skills"
    ],
    "loop": [
      "流程",
      "cat-flow"
    ],
    "conditional": [
      "流程",
      "cat-flow"
    ],
    "memory": [
      "记忆",
      "cat-memory"
    ],
    "token_counter": [
      "记忆",
      "cat-memory"
    ],
    "knowledge_base": [
      "记忆",
      "cat-memory"
    ],
    "vector_memory": [
      "记忆",
      "cat-memory"
    ],
    "working_memory": [
      "记忆",
      "cat-memory"
    ],
    "token_manager": [
      "记忆",
      "cat-memory"
    ],
    "memory_summarizer": [
      "记忆",
      "cat-memory"
    ],
    "skill_document": [
      "Skill",
      "cat-skills"
    ],
    "skill_frontend": [
      "Skill",
      "cat-skills"
    ],
    "skill_uiux": [
      "Skill",
      "cat-skills"
    ],
    "skill_find": [
      "Skill",
      "cat-skills"
    ],
    "skill_creator": [
      "Skill",
      "cat-skills"
    ],
    "skill_super": [
      "Skill",
      "cat-skills"
    ],
    "skill_pua": [
      "Skill",
      "cat-skills"
    ],
    "web_search": [
      "Tools",
      "cat-tools"
    ],
    "url_fetch": [
      "Tools",
      "cat-tools"
    ],
    "mcp_zip": [
      "Tools",
      "cat-tools"
    ],
    "http_request": [
      "Tools",
      "cat-tools"
    ],
    "image_tools": [
      "Tools",
      "cat-tools"
    ],
    "calculator": [
      "Tools",
      "cat-tools"
    ],
    "code_executor": [
      "Tools",
      "cat-tools"
    ],
    "text_tools": [
      "Tools",
      "cat-tools"
    ],
    "time_query": [
      "Tools",
      "cat-tools"
    ],
    "json_query": [
      "Tools",
      "cat-tools"
    ],
    "file_ops": [
      "Tools",
      "cat-tools"
    ],
    "vision": [
      "Tools",
      "cat-tools"
    ],
    "mcp_word": [
      "MCP",
      "cat-mcp"
    ],
    "mcp_excel": [
      "MCP",
      "cat-mcp"
    ],
    "mcp_ppt": [
      "MCP",
      "cat-mcp"
    ],
    "mcp_weather": [
      "MCP",
      "cat-mcp"
    ],
    "mcp_database": [
      "MCP",
      "cat-mcp"
    ],
    "mcp_git": [
      "MCP",
      "cat-mcp"
    ],
    "mcp_clipboard": [
      "MCP",
      "cat-mcp"
    ],
    "mcp_encoding": [
      "MCP",
      "cat-mcp"
    ],
    "mcp_system": [
      "MCP",
      "cat-mcp"
    ],
    "mcp_email": [
      "MCP",
      "cat-mcp"
    ],
    "mcp_translate": [
      "MCP",
      "cat-mcp"
    ],
    "mcp_calendar": [
      "MCP",
      "cat-mcp"
    ],
    "mcp_pdf": [
      "MCP",
      "cat-mcp"
    ],
    "mcp_finance": [
      "MCP",
      "cat-mcp"
    ],
    "mcp_geocode": [
      "MCP",
      "cat-mcp"
    ],
    "mcp_navigation": [
      "MCP",
      "cat-mcp"
    ],
    "mcp_external": [
      "MCP",
      "cat-mcp"
    ]
  },
  "render_args": {
    "time_query": ["get_current_time", "当前时间/日期/星期/时间戳"],
    "url_fetch": ["url_fetch", "抓取网页内容提取纯文本"],
    "file_ops": ["file_ops", "文件读写 / 搜索 / 编辑"],
    "json_query": ["json_query", "用路径语法提取 JSON 字段"],
    "mcp_zip": ["zip_create", "zip 压缩 / 解压"],
    "http_request": ["http_request", "通用 HTTP 请求（GET/POST/JSON）"],
    "image_tools": ["image_info", "截屏 / 图片信息 / 转换 / 缩放 / 压缩"],
    "mcp_clipboard": ["clipboard", "系统剪贴板读写", "已就绪"],
    "mcp_encoding": ["encoding", "编码/哈希/密码/UUID/正则/差异/换算", "已就绪"],
    "mcp_system": ["system", "系统信息/DNS/二维码/通知/打开文件", "已就绪"],
    "mcp_calendar": ["calendar", "日程管理 · 本地存储", "已就绪"],
    "mcp_pdf": ["pdf", "PDF 读取/创建/合并", "需安装 pypdf"],
    "mcp_finance": ["finance", "汇率/股票/加密货币", "已就绪"],
    "mcp_geocode": ["geocode", "地理编码/IP定位/距离计算", "已就绪"],
    "skill_document": ["document", ["pdf_read/create/merge", "word_create/add/save", "markdown_to_html", "html_to_markdown", "translate_text", "file_read/write/edit", "web_search", "url_fetch"]],
    "skill_frontend": ["frontend-design", ["web_search", "url_fetch", "file_read", "file_write", "file_edit", "glob_search", "grep_search"]],
    "skill_uiux": ["ui-ux-pro-max", ["web_search", "url_fetch", "file_read", "file_write", "file_edit", "file_search_tools"]],
    "skill_find": ["find-skills", ["web_search", "url_fetch"]],
    "skill_creator": ["skill-creator", ["file_read", "file_write", "file_edit", "glob_search", "grep_search", "web_search"]],
    "skill_super": ["superpowers", []],
    "skill_pua": ["pua", ["web_search", "url_fetch", "file_read", "glob_search", "grep_search", "calculator", "code_executor"]]
  },
  "quick_templates": [
    {
      "key": "search",
      "name": "🔍 搜索助手",
      "description": "LLM + Agent + Web Search + URL Fetch + Text Tools + File Ops + Memory",
      "components": [
        {
          "type": "llm",
          "size": 5,
          "x": 3,
          "y": 3,
          "apiSettings": {
            "apiBase": "https://api.deepseek.com/v1",
            "apiKey": "",
            "model": "deepseek-chat",
            "provider": "DeepSeek"
          }
        },
        {
          "type": "agent",
          "size": 6,
          "x": 3,
          "y": 35
        },
        {
          "type": "web_search",
          "size": 3,
          "x": 55,
          "y": 3,
          "toolEnabled": True
        },
        {
          "type": "url_fetch",
          "size": 3,
          "x": 72,
          "y": 3,
          "toolEnabled": True
        },
        {
          "type": "text_tools",
          "size": 3,
          "x": 55,
          "y": 28,
          "toolEnabled": True
        },
        {
          "type": "file_ops",
          "size": 3,
          "x": 72,
          "y": 28,
          "toolEnabled": True
        },
        {
          "type": "memory",
          "size": 3,
          "x": 3,
          "y": 73
        }
      ],
      "connections": [
        {
          "source": 0,
          "sourcePort": "llm-out",
          "target": 1,
          "targetPort": "agent-llm-in"
        },
        {
          "source": 1,
          "sourcePort": "agent-tool-1",
          "target": 2,
          "targetPort": "ws-in"
        },
        {
          "source": 1,
          "sourcePort": "agent-tool-2",
          "target": 3,
          "targetPort": "uf-in"
        },
        {
          "source": 1,
          "sourcePort": "agent-tool-3",
          "target": 4,
          "targetPort": "txt-in"
        },
        {
          "source": 1,
          "sourcePort": "agent-tool-4",
          "target": 5,
          "targetPort": "fo-in"
        },
        {
          "source": 6,
          "sourcePort": "mem-out",
          "target": 1,
          "targetPort": "agent-mem-in"
        }
      ]
    },
    {
      "key": "analyst",
      "name": "📊 数据分析师",
      "description": "LLM + Agent + Code + Excel + Calculator + Finance + HTTP 请求 + File Ops + Search + Memory",
      "components": [
        {
          "type": "llm",
          "size": 5,
          "x": 3,
          "y": 3,
          "apiSettings": {
            "apiBase": "https://api.deepseek.com/v1",
            "apiKey": "",
            "model": "deepseek-chat",
            "provider": "DeepSeek"
          }
        },
        {
          "type": "agent",
          "size": 6,
          "x": 3,
          "y": 35,
          "agentPortCount": 6
        },
        {
          "type": "code_executor",
          "size": 3,
          "x": 55,
          "y": 3,
          "toolEnabled": True
        },
        {
          "type": "mcp_excel",
          "size": 3,
          "x": 72,
          "y": 3,
          "toolEnabled": True
        },
        {
          "type": "calculator",
          "size": 3,
          "x": 55,
          "y": 28,
          "toolEnabled": True
        },
        {
          "type": "mcp_finance",
          "size": 3,
          "x": 72,
          "y": 28,
          "toolEnabled": True
        },
        {
          "type": "file_ops",
          "size": 3,
          "x": 55,
          "y": 53,
          "toolEnabled": True
        },
        {
          "type": "web_search",
          "size": 3,
          "x": 72,
          "y": 53,
          "toolEnabled": True
        },
        {
          "type": "http_request",
          "size": 3,
          "x": 55,
          "y": 76,
          "toolEnabled": True
        },
        {
          "type": "memory",
          "size": 3,
          "x": 3,
          "y": 73
        }
      ],
      "connections": [
        {
          "source": 0,
          "sourcePort": "llm-out",
          "target": 1,
          "targetPort": "agent-llm-in"
        },
        {
          "source": 1,
          "sourcePort": "agent-tool-1",
          "target": 2,
          "targetPort": "code-in"
        },
        {
          "source": 1,
          "sourcePort": "agent-tool-2",
          "target": 3,
          "targetPort": "excel-in"
        },
        {
          "source": 1,
          "sourcePort": "agent-tool-3",
          "target": 4,
          "targetPort": "calc-in"
        },
        {
          "source": 1,
          "sourcePort": "agent-tool-4",
          "target": 5,
          "targetPort": "fin-in"
        },
        {
          "source": 1,
          "sourcePort": "agent-tool-5",
          "target": 6,
          "targetPort": "fo-in"
        },
        {
          "source": 1,
          "sourcePort": "agent-tool-6",
          "target": 7,
          "targetPort": "ws-in"
        },
        {
          "source": 1,
          "sourcePort": "agent-tool-7",
          "target": 8,
          "targetPort": "http-in"
        },
        {
          "source": 9,
          "sourcePort": "mem-out",
          "target": 1,
          "targetPort": "agent-mem-in"
        }
      ]
    },
    {
      "key": "plan_exec",
      "name": "🧠 计划-执行 Agent",
      "description": "LLM + Plan 规划 -> Executor 执行 + Reflection 反思 + Memory",
      "components": [
        {
          "type": "llm",
          "size": 5,
          "x": 3,
          "y": 3,
          "apiSettings": {
            "apiBase": "https://api.deepseek.com/v1",
            "apiKey": "",
            "model": "deepseek-chat",
            "provider": "DeepSeek"
          }
        },
        {
          "type": "plan",
          "size": 5,
          "x": 3,
          "y": 38
        },
        {
          "type": "executor",
          "size": 4,
          "x": 50,
          "y": 20
        },
        {
          "type": "web_search",
          "size": 3,
          "x": 50,
          "y": 3,
          "toolEnabled": True
        },
        {
          "type": "code_executor",
          "size": 3,
          "x": 68,
          "y": 3,
          "toolEnabled": True
        },
        {
          "type": "calculator",
          "size": 3,
          "x": 50,
          "y": 50,
          "toolEnabled": True
        },
        {
          "type": "memory",
          "size": 3,
          "x": 3,
          "y": 70
        },
        {
          "type": "reflection",
          "size": 3,
          "x": 68,
          "y": 50
        }
      ],
      "connections": [
        {
          "source": 0,
          "sourcePort": "llm-out",
          "target": 1,
          "targetPort": "plan-in"
        },
        {
          "source": 1,
          "sourcePort": "plan-out",
          "target": 2,
          "targetPort": "exec-plan-in"
        },
        {
          "source": 0,
          "sourcePort": "llm-out",
          "target": 2,
          "targetPort": "exec-llm-in"
        },
        {
          "source": 2,
          "sourcePort": "exec-tool-1",
          "target": 3,
          "targetPort": "ws-in"
        },
        {
          "source": 2,
          "sourcePort": "exec-tool-2",
          "target": 4,
          "targetPort": "code-in"
        },
        {
          "source": 2,
          "sourcePort": "exec-tool-3",
          "target": 5,
          "targetPort": "calc-in"
        },
        {
          "source": 6,
          "sourcePort": "mem-out",
          "target": 0,
          "targetPort": "llm-mem-in"
        },
        {
          "source": 1,
          "sourcePort": "plan-out",
          "target": 7,
          "targetPort": "refl-plan-in"
        },
        {
          "source": 2,
          "sourcePort": "exec-tool-4",
          "target": 7,
          "targetPort": "refl-exec-in"
        }
      ]
    },
    {
      "key": "doc_pro",
      "name": "📝 文档专家",
      "description": "LLM + Skill Auto Call + Skills Manager(Document) + Word + PDF + Search + 压缩交付 + Memory",
      "components": [
        {
          "type": "llm",
          "size": 5,
          "x": 3,
          "y": 3,
          "apiSettings": {
            "apiBase": "https://api.deepseek.com/v1",
            "apiKey": "",
            "model": "deepseek-chat",
            "provider": "DeepSeek"
          }
        },
        {
          "type": "skill_auto_call",
          "size": 4,
          "x": 22,
          "y": 3
        },
        {
          "type": "skills_manager",
          "size": 5,
          "x": 3,
          "y": 35
        },
        {
          "type": "skill_document",
          "size": 4,
          "x": 55,
          "y": 5,
          "toolEnabled": True
        },
        {
          "type": "web_search",
          "size": 3,
          "x": 72,
          "y": 5,
          "toolEnabled": True
        },
        {
          "type": "mcp_word",
          "size": 3,
          "x": 55,
          "y": 38,
          "toolEnabled": True
        },
        {
          "type": "mcp_pdf",
          "size": 3,
          "x": 72,
          "y": 38,
          "toolEnabled": True
        },
        {
          "type": "mcp_zip",
          "size": 3,
          "x": 55,
          "y": 63,
          "toolEnabled": True
        },
        {
          "type": "memory",
          "size": 3,
          "x": 3,
          "y": 73
        }
      ],
      "connections": [
        {
          "source": 0,
          "sourcePort": "llm-out",
          "target": 1,
          "targetPort": "auto-llm-in"
        },
        {
          "source": 1,
          "sourcePort": "auto-skm-out",
          "target": 2,
          "targetPort": "skm-llm-in"
        },
        {
          "source": 2,
          "sourcePort": "skm-skill-1",
          "target": 3,
          "targetPort": "skill-in"
        },
        {
          "source": 0,
          "sourcePort": "llm-out",
          "target": 4,
          "targetPort": "ws-in"
        },
        {
          "source": 0,
          "sourcePort": "llm-out",
          "target": 5,
          "targetPort": "word-in"
        },
        {
          "source": 0,
          "sourcePort": "llm-out",
          "target": 6,
          "targetPort": "pdf-in"
        },
        {
          "source": 0,
          "sourcePort": "llm-out",
          "target": 7,
          "targetPort": "zip-in"
        },
        {
          "source": 8,
          "sourcePort": "mem-out",
          "target": 0,
          "targetPort": "llm-mem-in"
        }
      ]
    },
    {
      "key": "design_pro",
      "name": "🎨 设计专家",
      "description": "LLM + Skill Auto Call + Skills Manager(Frontend + UI/UX) + Search + 图片工具 + Memory",
      "components": [
        {
          "type": "llm",
          "size": 5,
          "x": 3,
          "y": 3,
          "apiSettings": {
            "apiBase": "https://api.deepseek.com/v1",
            "apiKey": "",
            "model": "deepseek-chat",
            "provider": "DeepSeek"
          }
        },
        {
          "type": "skill_auto_call",
          "size": 4,
          "x": 22,
          "y": 3
        },
        {
          "type": "skills_manager",
          "size": 5,
          "x": 3,
          "y": 38
        },
        {
          "type": "skill_frontend",
          "size": 4,
          "x": 50,
          "y": 5,
          "toolEnabled": True
        },
        {
          "type": "skill_uiux",
          "size": 4,
          "x": 68,
          "y": 5,
          "toolEnabled": True
        },
        {
          "type": "web_search",
          "size": 3,
          "x": 50,
          "y": 45,
          "toolEnabled": True
        },
        {
          "type": "url_fetch",
          "size": 3,
          "x": 68,
          "y": 45,
          "toolEnabled": True
        },
        {
          "type": "image_tools",
          "size": 3,
          "x": 50,
          "y": 68,
          "toolEnabled": True
        },
        {
          "type": "memory",
          "size": 3,
          "x": 3,
          "y": 73
        }
      ],
      "connections": [
        {
          "source": 0,
          "sourcePort": "llm-out",
          "target": 1,
          "targetPort": "auto-llm-in"
        },
        {
          "source": 1,
          "sourcePort": "auto-skm-out",
          "target": 2,
          "targetPort": "skm-llm-in"
        },
        {
          "source": 2,
          "sourcePort": "skm-skill-1",
          "target": 3,
          "targetPort": "skill-in"
        },
        {
          "source": 2,
          "sourcePort": "skm-skill-2",
          "target": 4,
          "targetPort": "skill-in"
        },
        {
          "source": 0,
          "sourcePort": "llm-out",
          "target": 5,
          "targetPort": "ws-in"
        },
        {
          "source": 0,
          "sourcePort": "llm-out",
          "target": 6,
          "targetPort": "uf-in"
        },
        {
          "source": 0,
          "sourcePort": "llm-out",
          "target": 7,
          "targetPort": "img-in"
        },
        {
          "source": 8,
          "sourcePort": "mem-out",
          "target": 0,
          "targetPort": "llm-mem-in"
        }
      ]
    },
    {
      "key": "skill_forge",
      "name": "⚡ 技能工坊",
      "description": "LLM + Skill Auto Call + Skills Manager(Find + Creator + Superpowers) + Search + Memory",
      "components": [
        {
          "type": "llm",
          "size": 5,
          "x": 3,
          "y": 3,
          "apiSettings": {
            "apiBase": "https://api.deepseek.com/v1",
            "apiKey": "",
            "model": "deepseek-chat",
            "provider": "DeepSeek"
          }
        },
        {
          "type": "skill_auto_call",
          "size": 4,
          "x": 22,
          "y": 3
        },
        {
          "type": "skills_manager",
          "size": 5,
          "x": 3,
          "y": 38
        },
        {
          "type": "skill_find",
          "size": 4,
          "x": 50,
          "y": 3,
          "toolEnabled": True
        },
        {
          "type": "skill_creator",
          "size": 4,
          "x": 68,
          "y": 3,
          "toolEnabled": True
        },
        {
          "type": "skill_super",
          "size": 4,
          "x": 50,
          "y": 38,
          "toolEnabled": True
        },
        {
          "type": "web_search",
          "size": 3,
          "x": 68,
          "y": 38,
          "toolEnabled": True
        },
        {
          "type": "memory",
          "size": 3,
          "x": 3,
          "y": 73
        }
      ],
      "connections": [
        {
          "source": 0,
          "sourcePort": "llm-out",
          "target": 1,
          "targetPort": "auto-llm-in"
        },
        {
          "source": 1,
          "sourcePort": "auto-skm-out",
          "target": 2,
          "targetPort": "skm-llm-in"
        },
        {
          "source": 2,
          "sourcePort": "skm-skill-1",
          "target": 3,
          "targetPort": "skill-in"
        },
        {
          "source": 2,
          "sourcePort": "skm-skill-2",
          "target": 4,
          "targetPort": "skill-in"
        },
        {
          "source": 2,
          "sourcePort": "skm-skill-3",
          "target": 5,
          "targetPort": "skill-in"
        },
        {
          "source": 0,
          "sourcePort": "llm-out",
          "target": 6,
          "targetPort": "ws-in"
        },
        {
          "source": 7,
          "sourcePort": "mem-out",
          "target": 0,
          "targetPort": "llm-mem-in"
        }
      ]
    },
    {
      "key": "dev_kit",
      "name": "🛠️ 开发工具包",
      "description": "LLM + Agent + Git + Database + Code + System + Encoding + HTTP 请求 + 压缩 + File Ops + Memory",
      "components": [
        {
          "type": "llm",
          "size": 5,
          "x": 3,
          "y": 3,
          "apiSettings": {
            "apiBase": "https://api.deepseek.com/v1",
            "apiKey": "",
            "model": "deepseek-chat",
            "provider": "DeepSeek"
          }
        },
        {
          "type": "agent",
          "size": 6,
          "x": 3,
          "y": 35,
          "agentPortCount": 7
        },
        {
          "type": "mcp_git",
          "size": 3,
          "x": 55,
          "y": 3,
          "toolEnabled": True
        },
        {
          "type": "mcp_database",
          "size": 3,
          "x": 72,
          "y": 3,
          "toolEnabled": True
        },
        {
          "type": "code_executor",
          "size": 3,
          "x": 55,
          "y": 28,
          "toolEnabled": True
        },
        {
          "type": "mcp_system",
          "size": 3,
          "x": 72,
          "y": 28,
          "toolEnabled": True
        },
        {
          "type": "mcp_encoding",
          "size": 3,
          "x": 55,
          "y": 53,
          "toolEnabled": True
        },
        {
          "type": "file_ops",
          "size": 3,
          "x": 72,
          "y": 53,
          "toolEnabled": True
        },
        {
          "type": "http_request",
          "size": 3,
          "x": 55,
          "y": 76,
          "toolEnabled": True
        },
        {
          "type": "mcp_zip",
          "size": 3,
          "x": 72,
          "y": 76,
          "toolEnabled": True
        },
        {
          "type": "memory",
          "size": 3,
          "x": 3,
          "y": 73
        }
      ],
      "connections": [
        {
          "source": 0,
          "sourcePort": "llm-out",
          "target": 1,
          "targetPort": "agent-llm-in"
        },
        {
          "source": 1,
          "sourcePort": "agent-tool-1",
          "target": 2,
          "targetPort": "git-in"
        },
        {
          "source": 1,
          "sourcePort": "agent-tool-2",
          "target": 3,
          "targetPort": "db-in"
        },
        {
          "source": 1,
          "sourcePort": "agent-tool-3",
          "target": 4,
          "targetPort": "code-in"
        },
        {
          "source": 1,
          "sourcePort": "agent-tool-4",
          "target": 5,
          "targetPort": "sys-in"
        },
        {
          "source": 1,
          "sourcePort": "agent-tool-5",
          "target": 6,
          "targetPort": "enc-in"
        },
        {
          "source": 1,
          "sourcePort": "agent-tool-6",
          "target": 7,
          "targetPort": "fo-in"
        },
        {
          "source": 1,
          "sourcePort": "agent-tool-7",
          "target": 8,
          "targetPort": "http-in"
        },
        {
          "source": 1,
          "sourcePort": "agent-tool-8",
          "target": 9,
          "targetPort": "zip-in"
        },
        {
          "source": 10,
          "sourcePort": "mem-out",
          "target": 1,
          "targetPort": "agent-mem-in"
        }
      ]
    },
    {
      "key": "research",
      "name": "🔬 深度研究",
      "description": "LLM + Skill Auto Call + Skills Manager(Find) + Agent + Search + URL Fetch + PDF + Translate + 压缩 + Memory",
      "components": [
        {
          "type": "llm",
          "size": 6,
          "x": 3,
          "y": 3,
          "apiSettings": {
            "apiBase": "https://api.deepseek.com/v1",
            "apiKey": "",
            "model": "deepseek-chat",
            "provider": "DeepSeek"
          }
        },
        {
          "type": "skill_auto_call",
          "size": 4,
          "x": 22,
          "y": 3
        },
        {
          "type": "skills_manager",
          "size": 4,
          "x": 50,
          "y": 3
        },
        {
          "type": "skill_find",
          "size": 3,
          "x": 70,
          "y": 3,
          "toolEnabled": True
        },
        {
          "type": "agent",
          "size": 6,
          "x": 3,
          "y": 35,
          "agentPortCount": 5
        },
        {
          "type": "web_search",
          "size": 3,
          "x": 55,
          "y": 45,
          "toolEnabled": True
        },
        {
          "type": "url_fetch",
          "size": 3,
          "x": 72,
          "y": 45,
          "toolEnabled": True
        },
        {
          "type": "mcp_pdf",
          "size": 3,
          "x": 55,
          "y": 70,
          "toolEnabled": True
        },
        {
          "type": "mcp_translate",
          "size": 3,
          "x": 72,
          "y": 70,
          "toolEnabled": True
        },
        {
          "type": "mcp_zip",
          "size": 3,
          "x": 55,
          "y": 88,
          "toolEnabled": True
        },
        {
          "type": "memory",
          "size": 3,
          "x": 3,
          "y": 73
        }
      ],
      "connections": [
        {
          "source": 0,
          "sourcePort": "llm-out",
          "target": 1,
          "targetPort": "auto-llm-in"
        },
        {
          "source": 1,
          "sourcePort": "auto-skm-out",
          "target": 2,
          "targetPort": "skm-llm-in"
        },
        {
          "source": 2,
          "sourcePort": "skm-skill-1",
          "target": 3,
          "targetPort": "skill-in"
        },
        {
          "source": 0,
          "sourcePort": "llm-out",
          "target": 4,
          "targetPort": "agent-llm-in"
        },
        {
          "source": 4,
          "sourcePort": "agent-tool-1",
          "target": 5,
          "targetPort": "ws-in"
        },
        {
          "source": 4,
          "sourcePort": "agent-tool-2",
          "target": 6,
          "targetPort": "uf-in"
        },
        {
          "source": 4,
          "sourcePort": "agent-tool-3",
          "target": 7,
          "targetPort": "pdf-in"
        },
        {
          "source": 4,
          "sourcePort": "agent-tool-4",
          "target": 8,
          "targetPort": "tr-in"
        },
        {
          "source": 4,
          "sourcePort": "agent-tool-5",
          "target": 9,
          "targetPort": "zip-in"
        },
        {
          "source": 10,
          "sourcePort": "mem-out",
          "target": 0,
          "targetPort": "llm-mem-in"
        }
      ]
    },
    {
      "key": "office",
      "name": "🏢 办公套件",
      "description": "LLM + Agent + Word + Excel + PPT + PDF + Email + Calendar + 压缩交付 + Memory",
      "components": [
        {
          "type": "llm",
          "size": 5,
          "x": 3,
          "y": 3,
          "apiSettings": {
            "apiBase": "https://api.deepseek.com/v1",
            "apiKey": "",
            "model": "deepseek-chat",
            "provider": "DeepSeek"
          }
        },
        {
          "type": "agent",
          "size": 6,
          "x": 3,
          "y": 35,
          "agentPortCount": 6
        },
        {
          "type": "mcp_word",
          "size": 3,
          "x": 55,
          "y": 3,
          "toolEnabled": True
        },
        {
          "type": "mcp_excel",
          "size": 3,
          "x": 72,
          "y": 3,
          "toolEnabled": True
        },
        {
          "type": "mcp_ppt",
          "size": 3,
          "x": 55,
          "y": 28,
          "toolEnabled": True
        },
        {
          "type": "mcp_pdf",
          "size": 3,
          "x": 72,
          "y": 28,
          "toolEnabled": True
        },
        {
          "type": "mcp_email",
          "size": 3,
          "x": 55,
          "y": 53,
          "toolEnabled": True
        },
        {
          "type": "mcp_calendar",
          "size": 3,
          "x": 72,
          "y": 53,
          "toolEnabled": True
        },
        {
          "type": "mcp_zip",
          "size": 3,
          "x": 55,
          "y": 76,
          "toolEnabled": True
        },
        {
          "type": "memory",
          "size": 3,
          "x": 3,
          "y": 73
        }
      ],
      "connections": [
        {
          "source": 0,
          "sourcePort": "llm-out",
          "target": 1,
          "targetPort": "agent-llm-in"
        },
        {
          "source": 1,
          "sourcePort": "agent-tool-1",
          "target": 2,
          "targetPort": "word-in"
        },
        {
          "source": 1,
          "sourcePort": "agent-tool-2",
          "target": 3,
          "targetPort": "excel-in"
        },
        {
          "source": 1,
          "sourcePort": "agent-tool-3",
          "target": 4,
          "targetPort": "ppt-in"
        },
        {
          "source": 1,
          "sourcePort": "agent-tool-4",
          "target": 5,
          "targetPort": "pdf-in"
        },
        {
          "source": 1,
          "sourcePort": "agent-tool-5",
          "target": 6,
          "targetPort": "email-in"
        },
        {
          "source": 1,
          "sourcePort": "agent-tool-6",
          "target": 7,
          "targetPort": "cal-in"
        },
        {
          "source": 1,
          "sourcePort": "agent-tool-7",
          "target": 8,
          "targetPort": "zip-in"
        },
        {
          "source": 9,
          "sourcePort": "mem-out",
          "target": 1,
          "targetPort": "agent-mem-in"
        }
      ]
    },
    {
      "key": "pua_coach",
      "name": "🔥 PUA 高压教练",
      "description": "LLM + Skill Auto Call + Skills Manager(PUA) + Search + Code + Calc + File Ops + Encoding + Memory",
      "components": [
        {
          "type": "llm",
          "size": 5,
          "x": 3,
          "y": 3,
          "apiSettings": {
            "apiBase": "https://api.deepseek.com/v1",
            "apiKey": "",
            "model": "deepseek-chat",
            "provider": "DeepSeek"
          }
        },
        {
          "type": "skill_auto_call",
          "size": 4,
          "x": 22,
          "y": 3
        },
        {
          "type": "skills_manager",
          "size": 5,
          "x": 3,
          "y": 38
        },
        {
          "type": "skill_pua",
          "size": 4,
          "x": 55,
          "y": 5,
          "toolEnabled": True
        },
        {
          "type": "web_search",
          "size": 3,
          "x": 72,
          "y": 5,
          "toolEnabled": True
        },
        {
          "type": "code_executor",
          "size": 3,
          "x": 55,
          "y": 38,
          "toolEnabled": True
        },
        {
          "type": "calculator",
          "size": 3,
          "x": 72,
          "y": 38,
          "toolEnabled": True
        },
        {
          "type": "file_ops",
          "size": 3,
          "x": 55,
          "y": 63,
          "toolEnabled": True
        },
        {
          "type": "mcp_encoding",
          "size": 3,
          "x": 72,
          "y": 63,
          "toolEnabled": True
        },
        {
          "type": "memory",
          "size": 3,
          "x": 3,
          "y": 73
        }
      ],
      "connections": [
        {
          "source": 0,
          "sourcePort": "llm-out",
          "target": 1,
          "targetPort": "auto-llm-in"
        },
        {
          "source": 1,
          "sourcePort": "auto-skm-out",
          "target": 2,
          "targetPort": "skm-llm-in"
        },
        {
          "source": 2,
          "sourcePort": "skm-skill-1",
          "target": 3,
          "targetPort": "skill-in"
        },
        {
          "source": 0,
          "sourcePort": "llm-out",
          "target": 4,
          "targetPort": "ws-in"
        },
        {
          "source": 0,
          "sourcePort": "llm-out",
          "target": 5,
          "targetPort": "code-in"
        },
        {
          "source": 0,
          "sourcePort": "llm-out",
          "target": 6,
          "targetPort": "calc-in"
        },
        {
          "source": 0,
          "sourcePort": "llm-out",
          "target": 7,
          "targetPort": "fo-in"
        },
        {
          "source": 0,
          "sourcePort": "llm-out",
          "target": 8,
          "targetPort": "enc-in"
        },
        {
          "source": 9,
          "sourcePort": "mem-out",
          "target": 0,
          "targetPort": "llm-mem-in"
        }
      ]
    },
    {
      "key": "full_agent",
      "name": "🤖 全能 Agent",
      "description": "LLM + Agent + Search + Code + Calc + Excel + Word + PDF + HTTP + 图片 + 压缩 + Memory + Reflection",
      "components": [
        {
          "type": "llm",
          "size": 6,
          "x": 3,
          "y": 3,
          "apiSettings": {
            "apiBase": "https://api.deepseek.com/v1",
            "apiKey": "",
            "model": "deepseek-chat",
            "provider": "DeepSeek"
          }
        },
        {
          "type": "agent",
          "size": 6,
          "x": 3,
          "y": 38,
          "agentPortCount": 9
        },
        {
          "type": "web_search",
          "size": 3,
          "x": 50,
          "y": 3,
          "toolEnabled": True
        },
        {
          "type": "code_executor",
          "size": 3,
          "x": 68,
          "y": 3,
          "toolEnabled": True
        },
        {
          "type": "calculator",
          "size": 3,
          "x": 50,
          "y": 28,
          "toolEnabled": True
        },
        {
          "type": "mcp_excel",
          "size": 3,
          "x": 68,
          "y": 28,
          "toolEnabled": True
        },
        {
          "type": "mcp_word",
          "size": 3,
          "x": 50,
          "y": 53,
          "toolEnabled": True
        },
        {
          "type": "mcp_pdf",
          "size": 3,
          "x": 68,
          "y": 53,
          "toolEnabled": True
        },
        {
          "type": "http_request",
          "size": 3,
          "x": 50,
          "y": 76,
          "toolEnabled": True
        },
        {
          "type": "image_tools",
          "size": 3,
          "x": 68,
          "y": 76,
          "toolEnabled": True
        },
        {
          "type": "mcp_zip",
          "size": 3,
          "x": 50,
          "y": 90,
          "toolEnabled": True
        },
        {
          "type": "memory",
          "size": 3,
          "x": 3,
          "y": 73
        },
        {
          "type": "reflection",
          "size": 3,
          "x": 30,
          "y": 73
        }
      ],
      "connections": [
        {
          "source": 0,
          "sourcePort": "llm-out",
          "target": 1,
          "targetPort": "agent-llm-in"
        },
        {
          "source": 1,
          "sourcePort": "agent-tool-1",
          "target": 2,
          "targetPort": "ws-in"
        },
        {
          "source": 1,
          "sourcePort": "agent-tool-2",
          "target": 3,
          "targetPort": "code-in"
        },
        {
          "source": 1,
          "sourcePort": "agent-tool-3",
          "target": 4,
          "targetPort": "calc-in"
        },
        {
          "source": 1,
          "sourcePort": "agent-tool-4",
          "target": 5,
          "targetPort": "excel-in"
        },
        {
          "source": 1,
          "sourcePort": "agent-tool-5",
          "target": 6,
          "targetPort": "word-in"
        },
        {
          "source": 1,
          "sourcePort": "agent-tool-6",
          "target": 7,
          "targetPort": "pdf-in"
        },
        {
          "source": 1,
          "sourcePort": "agent-tool-7",
          "target": 8,
          "targetPort": "http-in"
        },
        {
          "source": 1,
          "sourcePort": "agent-tool-8",
          "target": 9,
          "targetPort": "img-in"
        },
        {
          "source": 1,
          "sourcePort": "agent-tool-9",
          "target": 10,
          "targetPort": "zip-in"
        },
        {
          "source": 11,
          "sourcePort": "mem-out",
          "target": 1,
          "targetPort": "agent-mem-in"
        }
      ]
    }
  ],
  "provider_presets": [
    {
      "name": "OpenAI",
      "url": "https://api.openai.com/v1",
      "models": [
        "gpt-5",
        "gpt-5-mini",
        "gpt-5-nano",
        "gpt-5.2"
      ]
    },
    {
      "name": "Groq",
      "url": "https://api.groq.com/openai/v1",
      "models": [
        "llama-4-maverick-17b-128e-instruct",
        "llama-4-scout-17b-16e-instruct",
        "llama-3.3-70b-versatile"
      ]
    },
    {
      "name": "DeepSeek",
      "url": "https://api.deepseek.com/v1",
      "models": [
        "deepseek-chat",
        "deepseek-reasoner",
        "deepseek-v4-flash"
      ]
    },
    {
      "name": "智谱 (GLM)",
      "url": "https://open.bigmodel.cn/api/paas/v4",
      "models": [
        "glm-5",
        "glm-5-flash",
        "glm-4.5",
        "glm-4v-plus"
      ]
    },
    {
      "name": "通义千问",
      "url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
      "models": [
        "qwen-max",
        "qwen-plus",
        "qwen-turbo",
        "qwen3.8-max"
      ]
    },
    {
      "name": "Moonshot (Kimi)",
      "url": "https://api.moonshot.cn/v1",
      "models": [
        "kimi-k3",
        "kimi-k2-turbo-preview",
        "moonshot-v1-128k"
      ]
    },
    {
      "name": "Google Gemini",
      "url": "https://generativelanguage.googleapis.com/v1beta/openai",
      "models": [
        "gemini-2.5-pro",
        "gemini-2.5-flash"
      ]
    },
    {
      "name": "Ollama (本地)",
      "url": "http://localhost:11434/v1",
      "models": [
        "llama3.3",
        "qwen3",
        "mistral",
        "gemma3",
        "phi4"
      ]
    },
    {
      "name": "自定义",
      "url": "",
      "models": []
    }
  ]
}

# 设置面板元数据（从 static/app.js 设置面板代码 + templates/index.html 提取，人工维护）
_SETTINGS_DATA = {
  "themes": [
    {
      "key": "industrial",
      "name": "Industrial",
      "description": "机能风 · 亮黄+黑灰"
    },
    {
      "key": "blue",
      "name": "Professional",
      "description": "专业风 · 蓝+白"
    },
    {
      "key": "glass",
      "name": "Glassmorphism",
      "description": "玻璃态 · 紫蓝渐变+毛玻璃"
    }
  ],
  "fontSizes": {
    "min": 0.8,
    "max": 1.2,
    "step": 0.05,
    "default": 1.0
  },
  "lineHeights": {
    "min": 1.2,
    "max": 2.2,
    "step": 0.1,
    "default": 1.6
  }
}

def register_routes(app):
    @app.route("/api/meta/components", methods=["GET"])
    def meta_components():
        return jsonify({"success": True, "data": _DATA})

    @app.route("/api/meta/settings", methods=["GET"])
    def meta_settings():
        return jsonify({"success": True, "data": _SETTINGS_DATA})
