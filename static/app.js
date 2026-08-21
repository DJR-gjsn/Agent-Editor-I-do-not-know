/**
 * wybzd · 拖拽构建管理 — 前端逻辑
 * 组件管理、画布连线系统、LLM 对话、属性面板
 */

// ============================================================
// 状态管理
// ============================================================
const STATE = {
    components: [],
    connections: [],        // [{id, sourceCompId, sourcePortId, targetCompId, targetPortId}]
    nextId: 1,
    nextConnId: 1,
    model: '--',
    dragSource: null,
    dragCompId: null,
    selectedCompId: null,
    multiSelected: [],      // 框选/Ctrl 多选的组件 id 集合
    mcpSaveDir: null,       // FileSystemDirectoryHandle
    mcpSaveDirName: '',     // 目录名（用于显示）
    history: [],            // 撤回快照栈
    maxHistory: 50,         // 最多保留 50 步
};

// 卡片拖拽状态
const DRAG = {
    card: null, compId: null,
    startMouseX: 0, startMouseY: 0,
    origLeftPct: 0, origTopPct: 0,
    active: false, moved: false,
    group: null,            // 框选组拖动: [{id, card, origLeftPct, origTopPct}]
};

// ── 框选状态 ──
const SELBOX = {
    active: false,
    startX: 0, startY: 0,
    curX: 0, curY: 0,
    el: null,
    suppressClick: false,   // 框选结束后抑制下一次画布 click（防止清除选中）
};

// ── 撤回系统 ──
function pushHistory() {
    // 深拷贝当前 components + connections + ID 计数器
    const snap = {
        components: STATE.components.map(c => JSON.parse(JSON.stringify(c))),
        connections: STATE.connections.map(c => ({ ...c })),
        nextId: STATE.nextId,
        nextConnId: STATE.nextConnId,
    };
    STATE.history.push(snap);
    // 超过上限时移除最旧的快照
    while (STATE.history.length > STATE.maxHistory) {
        STATE.history.shift();
    }
}

function undo() {
    if (STATE.history.length === 0) {
        showToast('没有可撤回的操作', 'info');
        return;
    }
    const snap = STATE.history.pop();
    STATE.components = snap.components;
    STATE.connections = snap.connections;
    STATE.nextId = snap.nextId;
    STATE.nextConnId = snap.nextConnId;
    selectComponent(null);
    renderAll();
    updateUI();
    autoSaveConnections();
    showToast('↩ 已撤回', 'info');
}

// 连线拖拽状态
const WIRE = {
    active: false,
    sourceCompId: null, sourcePortId: null,
    startX: 0, startY: 0, currentX: 0, currentY: 0,
};

// 当前项目信息
const CURRENT_PROJECT = {
    id: null,
    name: '',
};

// 画布视图状态（缩放 & 平移）
const CANVAS_VIEW = {
    zoom: 1,
    panX: 0, panY: 0,
    panning: false,
    panStartX: 0, panStartY: 0,
    panStartPanX: 0, panStartPanY: 0,
};

// ============================================================
// 通用连接查询 & 工具收集
// ============================================================
function findConnTo(targetCompId, targetPortId) {
    const conn = STATE.connections.find(c => c.targetCompId === targetCompId && c.targetPortId === targetPortId);
    return conn ? { conn, source: STATE.components.find(x => x.id === conn.sourceCompId) } : null;
}
function findConnFrom(sourceCompId, sourcePortId) {
    const conn = STATE.connections.find(c => c.sourceCompId === sourceCompId && c.sourcePortId === sourcePortId);
    return conn ? { conn, target: STATE.components.find(x => x.id === conn.targetCompId) } : null;
}

// 获取任意 LLM 的 API 配置
function getLLMAPIConfig(preferredCompId) {
    if (preferredCompId) {
        const comp = STATE.components.find(c => c.id === preferredCompId);
        if (comp && comp.type === 'llm' && comp.apiSettings && (comp.apiSettings.apiBase || comp.apiSettings.apiKey || comp.apiSettings.model)) {
            return { api_base: comp.apiSettings.apiBase || undefined, api_key: comp.apiSettings.apiKey || undefined, model: comp.apiSettings.model || undefined };
        }
    }
    const llm = STATE.components.find(c => c.type === 'llm');
    if (llm && llm.apiSettings) {
        return { api_base: llm.apiSettings.apiBase || undefined, api_key: llm.apiSettings.apiKey || undefined, model: llm.apiSettings.model || undefined };
    }
    return {};
}

// 统一的工具名映射（启动时从后端 /api/meta/components 拉取，applyMeta 填充；拉取失败为空对象）
let TOOL_NAME_MAP = {};

// 外部 MCP 工具：把节点保存的工具名拼成注册全名（mcp_ext_<server_id>_<tool>），
// 供工具注入链（autoSaveConnections / getComponentToolNames）与
// collectToolsFromPorts 复用。toolNames 显式子集优先；null（=全部）用 mcpAllTools 快照；
// serverId 为空（未选 server）返回 []（不注入）。
// （buildChatPayload 已于 Task 4 删除；编排链后端化见 modules/orchestrator.py）
function mcpExternalToolNames(comp) {
    if (!comp || !comp.serverId) return [];
    const names = comp.toolNames != null ? comp.toolNames : (comp.mcpAllTools || []);
    return names.map(n => 'mcp_ext_' + comp.serverId + '_' + n);
}

// 从指定端口收集工具名称
function collectToolsFromPorts(compId, portIds) {
    const names = [];
    portIds.forEach(pid => {
        const hit = findConnFrom(compId, pid);
        if (hit && hit.target) {
            let tns = TOOL_NAME_MAP[hit.target.type];
            if (hit.target.type === 'mcp_external') {
                // 动态 MCP 工具：拼注册全名 mcp_ext_<server_id>_<tool>
                // （null = 全部用 server 工具；全部模式时工具名由 renderMcpToolList 快照到 mcpAllTools）
                tns = mcpExternalToolNames(hit.target);
            }
            if (tns) tns.forEach(n => names.push(n));
        }
    });
    return [...new Set(names)];
}

// 序列化组件状态（用于保存）
function serializeComponent(c) {
    return {
        id: c.id, type: c.type, size: c.size, x: c.x, y: c.y,
        name: c.name || null,
        // MCP 外部工具（只存引用，token/命令/URL 都在全局配置）
        serverId: c.serverId || null,
        toolNames: c.toolNames || null,
        messages: c.messages,
        // apiKey 不写入布局（安全：避免密钥进入 git 仓库/服务器存储）；
        // 密钥仅保留在组件内存与浏览器 localStorage 的 active-llm-config 中
        apiSettings: c.apiSettings ? {
            apiBase: c.apiSettings.apiBase,
            model: c.apiSettings.model,
            provider: c.apiSettings.provider,
            maxToolRounds: c.apiSettings.maxToolRounds || 50,
        } : c.apiSettings,
        activePromptId: c.activePromptId, activePromptContent: c.activePromptContent,
        jsonSchema: c.jsonSchema, jsonPrompt: c.jsonPrompt,
        visionImage: c.visionImage, visionPrompt: c.visionPrompt,
        searchHistory: c.searchHistory, toolEnabled: c.toolEnabled,
        maxSearchRounds: c.maxSearchRounds,
        calcHistory: c.calcHistory, codeHistory: c.codeHistory, textHistory: c.textHistory,
        orderedTools: c.orderedTools, strictMode: c.strictMode,
        currentPlan: c.currentPlan, planHistory: c.planHistory,
        execTools: c.execTools, execLastResult: c.execLastResult,
        execPortCount: c.execPortCount,
        loopStatus: c.loopStatus, loopIteration: c.loopIteration, loopLog: c.loopLog,
        agentStatus: c.agentStatus, agentIteration: c.agentIteration, agentLog: c.agentLog, agentTask: c.agentTask,
        reflHistory: c.reflHistory, reflLastResult: c.reflLastResult,
        vectorDocs: c.vectorDocs,
        wmStore: c.wmStore,
        condCondition: c.condCondition, condCustomRule: c.condCustomRule, condLastResult: c.condLastResult,
    };
}

// 反序列化组件状态（用于加载）
function deserializeComponent(cd, fallbackIndex) {
    if (!COMPONENT_DEFS[cd.type]) return null;
    const pos = (cd.x != null && cd.y != null) ? { x: cd.x, y: cd.y } : autoLayoutPosition(fallbackIndex);
    return {
        id: cd.id != null ? cd.id : STATE.nextId++, type: cd.type, size: cd.size,
        x: pos.x, y: pos.y,
        name: cd.name || null,
        serverId: cd.serverId || null,
        toolNames: cd.toolNames !== undefined ? cd.toolNames : null,
        messages: cd.messages || [], apiSettings: cd.apiSettings || { apiBase: '', apiKey: '', model: '', provider: '自定义' },
        activePromptId: cd.activePromptId || null, activePromptContent: cd.activePromptContent || null,
        jsonSchema: cd.jsonSchema || null, jsonPrompt: cd.jsonPrompt || null,
        visionImage: cd.visionImage || null, visionPrompt: cd.visionPrompt || null,
        searchHistory: cd.searchHistory || [], toolEnabled: cd.toolEnabled !== undefined ? cd.toolEnabled : true,
        maxSearchRounds: cd.maxSearchRounds,
        calcHistory: cd.calcHistory || [], codeHistory: cd.codeHistory || [], textHistory: cd.textHistory || [],
        orderedTools: cd.orderedTools || [], strictMode: cd.strictMode !== undefined ? cd.strictMode : true,
        currentPlan: cd.currentPlan || null, planHistory: cd.planHistory || [],
        execTools: cd.execTools || [], execLastResult: cd.execLastResult || null,
        execPortCount: cd.execPortCount || 5,
        loopStatus: cd.loopStatus || 'idle', loopIteration: cd.loopIteration || 0, loopLog: cd.loopLog || [],
        agentStatus: cd.agentStatus || 'idle', agentIteration: cd.agentIteration || 0, agentLog: cd.agentLog || [], agentTask: cd.agentTask || '',
        reflHistory: cd.reflHistory || [], reflLastResult: cd.reflLastResult || null,
        vectorDocs: cd.vectorDocs || [],
        wmStore: cd.wmStore || {},
        condCondition: cd.condCondition || 'auto', condCustomRule: cd.condCustomRule || '', condLastResult: cd.condLastResult !== undefined ? cd.condLastResult : null,
    };
}

// ============================================================
// 组件定义（元数据由后端 /api/meta/components 提供，见 applyMeta）
// ============================================================

// ── 工厂渲染参数（单一来源：后端 /api/meta/components 的 render_args，applyMeta 填充）──
// 显示参数随元数据下发，前端只保留"按类型取参 → 调工厂"的渲染包装；
// 元数据缺失时回退空参数（与后端无该项时行为一致）。
let RENDER_ARGS = {};

function simpleToolPanelRender(container, comp) {
    return renderSimpleToolPanel.apply(null, RENDER_ARGS[comp.type] || ['', ''])(container, comp);
}
function mcpSimplePanelRender(container, comp) {
    return renderMCPSimplePanel.apply(null, RENDER_ARGS[comp.type] || ['', '', ''])(container, comp);
}
function skillPanelRender(container, comp) {
    return renderSkillPanel.apply(null, RENDER_ARGS[comp.type] || ['', []])(container, comp);
}

// ── renderKey → 渲染函数 本地映射（渲染逻辑永留前端）──
const RENDER_FN_MAP = {
    renderLLMPanel,
    renderSequentialExecutorPanel,
    renderPlanPanel,
    renderExecutorPanel,
    renderSkillsManagerPanel,
    renderSkillAutoCallPanel,
    renderLoopPanel,
    renderMemoryPanel,
    renderTokenCounterPanel,
    renderSystemPromptPanel,
    renderFunctionCallingPanel,
    renderVisionPanel,
    renderJSONModePanel,
    renderEmbeddingsPanel,
    renderTokenManagerPanel,
    renderAgentPanel,
    renderReflectionPanel,
    renderVectorMemoryPanel,
    renderKnowledgeBasePanel,
    renderWorkingMemoryPanel,
    renderMemorySummarizerPanel,
    renderConditionalPanel,
    renderSkillPanel: skillPanelRender,
    renderWebSearchPanel,
    renderCalculatorPanel,
    renderCodeExecutorPanel,
    renderTextToolsPanel,
    renderSimpleToolPanel: simpleToolPanelRender,
    renderMcpExternalPanel,
    renderMCPWeatherPanel,
    renderMCPDatabasePanel,
    renderMCPGitPanel,
    renderMCPSimplePanel: mcpSimplePanelRender,
    renderMCPEmailPanel,
    renderMCPTranslatePanel,
    renderMCPNavPanel,
    renderMCPWordPanel,
    renderMCPExcelPanel,
    renderMCPPPTPanel,
};

// ── 内置最小集（后端拉取失败时兜底：llm + 画布常用组件，页面仍可渲染）──
const FALLBACK_COMPONENT_DEFS = {
    llm: {
        icon: '\u{1F50C}', title: 'LLM API 设置', color: '#4A90D9', defaultSize: 6,
        render: RENDER_FN_MAP.renderLLMPanel,
        ports: { outputs: [{ id: 'llm-out', label: '调用' }], inputs: [{ id: 'llm-mem-in', label: '记忆 ←' }] },
        description: '配置 API 连接 + 一次性对话。连线到功能模块以启用对应能力。接入 Memory 组件后可保留对话历史。',
    },
    agent: {
        icon: '\u{1F916}', title: 'Agent 编排器', color: '#667eea', defaultSize: 6,
        render: RENDER_FN_MAP.renderAgentPanel,
        ports: {
            inputs: [
                { id: 'agent-llm-in', label: 'LLM 大脑' },
                { id: 'agent-mem-in', label: '记忆 ←' },
            ],
            outputs: [
                { id: 'agent-tool-1', label: '工具 1' },
                { id: 'agent-tool-2', label: '工具 2' },
                { id: 'agent-tool-3', label: '工具 3' },
                { id: 'agent-tool-4', label: '工具 4' },
                { id: 'agent-tool-5', label: '工具 5' },
            ],
        },
        description: 'Agent 主循环中枢：自动协调 Plan→Execute→Reflect 流程。连线 LLM 大脑 + 记忆 + 工具即可快速构建完整 Agent。一键启动自动循环。',
    },
    executor: {
        icon: '▶', title: 'Executor 执行', color: '#c41d7f', defaultSize: 4,
        render: RENDER_FN_MAP.renderExecutorPanel,
        ports: {
            inputs: [
                { id: 'exec-llm-in', label: 'LLM 驱动' },
                { id: 'exec-plan-in', label: 'Plan/Loop 驱动' },
            ],
            outputs: [
                { id: 'exec-tool-1', label: '工具 1' },
                { id: 'exec-tool-2', label: '工具 2' },
                { id: 'exec-tool-3', label: '工具 3' },
                { id: 'exec-tool-4', label: '工具 4' },
                { id: 'exec-tool-5', label: '工具 5' },
            ],
        },
        description: 'Agent 执行模块。接收单步任务，询问 LLM 决定用什么工具，执行并返回结果。由 Plan/Loop 驱动执行循环。',
    },
    memory: {
        icon: '\u{1F9E0}', title: 'Chat Memory', color: '#8b5cf6', defaultSize: 3,
        render: RENDER_FN_MAP.renderMemoryPanel,
        ports: { outputs: [{ id: 'mem-out', label: '历史 →' }], inputs: [{ id: 'mem-in', label: '写入' }] },
        description: '存储对话历史。连线到 LLM 组件后，AI 会记住之前的对话内容。断开连线则每次都是全新对话。',
    },
    system_prompt: {
        icon: '\u{1F3AD}', title: 'System Prompt', color: '#52c41a', defaultSize: 5,
        render: RENDER_FN_MAP.renderSystemPromptPanel,
        ports: { inputs: [{ id: 'sp-in', label: '人设 → LLM' }], outputs: [] },
        description: '定制 AI 角色、说话风格、回答方式。内置多套人设模板，也可自定义。只能连接到 LLM。',
    },
    function_calling: {
        icon: '\u{1F527}', title: 'Function Calling', color: '#fa8c16', defaultSize: 4,
        render: RENDER_FN_MAP.renderFunctionCallingPanel,
        ports: { inputs: [{ id: 'fc-in', label: 'Tools' }], outputs: [] },
        description: '定义工具 JSON Schema，让 AI 调用外部函数。',
    },
    web_search: {
        icon: '\u{1F50D}', title: 'Web Search', color: '#1890ff', defaultSize: 4,
        render: RENDER_FN_MAP.renderWebSearchPanel,
        ports: { inputs: [{ id: 'ws-in', label: '搜索结果 → LLM' }], outputs: [] },
        description: '通过 DuckDuckGo 搜索网页。连线到 LLM 后，搜索结果会作为对话上下文。',
    },
    calculator: {
        icon: '\u{1F5A9}', title: 'Calculator', color: '#2f54eb', defaultSize: 3,
        render: RENDER_FN_MAP.renderCalculatorPanel,
        ports: { inputs: [{ id: 'calc-in', label: '计算结果 → LLM' }], outputs: [] },
        description: '安全计算数学表达式。连线到 LLM 后，计算结果会作为对话上下文。',
    },
    mcp_external: {
        icon: '\u{1F517}', title: '外部 MCP 工具', color: '#389e0d', defaultSize: 5,
        render: RENDER_FN_MAP.renderMcpExternalPanel,
        ports: { inputs: [{ id: 'mcp-ext-in', label: 'LLM 接入' }], outputs: [] },
        description: '连接设置中配置的 MCP server，将其工具注入 LLM。可勾选要使用的工具子集。',
    },
};

// 从后端元数据构建全局定义（fallback 到内置最小集）
let COMPONENT_DEFS = { ...FALLBACK_COMPONENT_DEFS };
let COMPONENT_CATEGORIES = {};
let QUICK_TEMPLATES = [];
let PROVIDERS = [{ name: '自定义', url: '', models: [] }];

function applyMeta(data) {
    COMPONENT_DEFS = {};
    for (const [type, d] of Object.entries(data.component_defs || {})) {
        COMPONENT_DEFS[type] = {
            ...d,
            render: RENDER_FN_MAP[d.renderKey] || (() => { /* 未知 renderKey 的空渲染 */ }),
        };
    }
    TOOL_NAME_MAP = data.tool_name_map || {};
    RENDER_ARGS = data.render_args || {};
    COMPONENT_CATEGORIES = data.component_categories || {};
    QUICK_TEMPLATES = data.quick_templates || [];
    // 厂商预设空兜底：至少保留"自定义"（防 renderAPIConfigTab 空数组崩溃）
    PROVIDERS = (data.provider_presets && data.provider_presets.length > 0)
        ? data.provider_presets
        : [{ name: '自定义', url: '', models: [] }];
    // 分类筛选与面板重建依赖这些全局，重新初始化面板
    if (typeof setupPalletBadges === 'function') setupPalletBadges();
    if (typeof setupCategoryFilters === 'function') setupCategoryFilters();
}

// ============================================================
// DOM 引用
// ============================================================
const canvas = document.getElementById('canvas');
const toolbarModel = document.getElementById('toolbar-model');
const toolbarCompCount = document.getElementById('toolbar-comp-count');
const propsContent = document.getElementById('props-content');

// ============================================================
// 技能提示词缓存
// ============================================================
const SKILL_PROMPT_CACHE = {};

async function preloadSkillPrompts() {
    try {
        const resp = await fetch('/api/skills');
        const skills = await resp.json();
        for (const s of skills) {
            SKILL_PROMPT_CACHE[s.id] = s.system_prompt || '';
            SKILL_PROMPT_CACHE[s.id + '_tools'] = s.recommended_tools || [];
            SKILL_PROMPT_CACHE[s.id + '_comps'] = s.recommended_components || [];
            SKILL_PROMPT_CACHE[s.id + '_name'] = s.name || s.id;
            SKILL_PROMPT_CACHE[s.id + '_desc'] = s.description || '';
        }
    } catch (e) {
        console.warn('技能提示词预加载失败:', e);
    }
}

// ============================================================
// 主题切换 & 显示设置
// ============================================================
const THEME_KEY = 'wybzd-theme';
const FONT_SIZE_KEY = 'wybzd-font-size';
const LINE_HEIGHT_KEY = 'wybzd-line-height';

// 滑块范围
const FONT_SIZE_MIN = 0.8, FONT_SIZE_MAX = 1.2, FONT_SIZE_DEFAULT = 1.0;
const LINE_HEIGHT_MIN = 1.2, LINE_HEIGHT_MAX = 2.2, LINE_HEIGHT_DEFAULT = 1.6;

function restoreTheme() {
    const saved = safeStorage.get(THEME_KEY) || 'industrial';
    applyTheme(saved);
}

function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    safeStorage.set(THEME_KEY, theme);
    // 更新设置面板中的选中状态
    document.querySelectorAll('.theme-option[data-theme]').forEach(opt => {
        opt.classList.toggle('active', opt.dataset.theme === theme);
    });
}

/** 恢复显示设置（字体大小/行距），编辑器与对话页共用 localStorage */
function restoreDisplaySettings() {
    applyFontSize(parseFloat(safeStorage.get(FONT_SIZE_KEY)) || FONT_SIZE_DEFAULT);
    applyLineHeight(parseFloat(safeStorage.get(LINE_HEIGHT_KEY)) || LINE_HEIGHT_DEFAULT);
}

function applyFontSize(scale) {
    scale = Math.min(FONT_SIZE_MAX, Math.max(FONT_SIZE_MIN, scale || FONT_SIZE_DEFAULT));
    // 仅在非默认值时设置 zoom：zoom:1 显式设置会与画布 transform:scale 合成层
    // 冲突（Chromium bug → 滚轮缩放时边缘组件变黑/色块、内容不重绘）
    if (Math.abs(scale - 1.0) < 0.001) {
        document.documentElement.style.zoom = '';
    } else {
        document.documentElement.style.zoom = scale;
    }
    // 非默认字号时摘掉画布视口的合成层（will-change:transform + zoom 是黑块 bug 的组合条件），
    // 避免滚轮缩放时边缘组件变黑/色块
    const vp = document.getElementById('canvas-viewport');
    if (vp) vp.style.willChange = (Math.abs(scale - 1.0) < 0.001) ? 'transform' : 'auto';
    safeStorage.set(FONT_SIZE_KEY, scale);
    const valEl = document.getElementById('fontsize-value');
    if (valEl) valEl.textContent = Math.round(scale * 100) + '%';
    const slider = document.getElementById('fontsize-slider');
    if (slider) slider.value = String(scale);
}

function applyLineHeight(lh) {
    lh = Math.min(LINE_HEIGHT_MAX, Math.max(LINE_HEIGHT_MIN, lh || LINE_HEIGHT_DEFAULT));
    document.documentElement.style.setProperty('--ui-lh', String(lh));
    safeStorage.set(LINE_HEIGHT_KEY, lh);
    const valEl = document.getElementById('lineheight-value');
    if (valEl) valEl.textContent = lh.toFixed(1);
    const slider = document.getElementById('lineheight-slider');
    if (slider) slider.value = String(lh);
}

function setupSettingsPanel() {
    const btnSettings = document.getElementById('btn-settings');
    const overlay = document.getElementById('settings-overlay');
    const btnClose = document.getElementById('settings-close');
    const themeOptions = document.getElementById('theme-options');
    const fontSizeSlider = document.getElementById('fontsize-slider');
    const lineHeightSlider = document.getElementById('lineheight-slider');

    if (!btnSettings || !overlay) return;

    // 打开设置
    btnSettings.addEventListener('click', () => {
        overlay.style.display = 'flex';
        renderMcpServers().catch(() => { const box = document.getElementById('mcp-server-list'); if (box) box.innerHTML = '<div style="color:#f5222d;padding:6px 0;">加载 MCP 配置失败</div>'; }); // 打开设置时刷新 MCP server 列表
        // 同步当前选中状态
        const current = document.documentElement.getAttribute('data-theme') || 'industrial';
        applyTheme(current);
        applyFontSize(parseFloat(safeStorage.get(FONT_SIZE_KEY)) || FONT_SIZE_DEFAULT);
        applyLineHeight(parseFloat(safeStorage.get(LINE_HEIGHT_KEY)) || LINE_HEIGHT_DEFAULT);
    });

    // 关闭设置
    btnClose.addEventListener('click', () => { overlay.style.display = 'none'; });
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) overlay.style.display = 'none';
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && overlay.style.display === 'flex') overlay.style.display = 'none';
    });

    // 切换主题
    themeOptions.querySelectorAll('.theme-option').forEach(btn => {
        btn.addEventListener('click', () => {
            applyTheme(btn.dataset.theme);
            const names = { industrial: 'Industrial', blue: 'Professional', glass: 'Glassmorphism' };
            showToast(`Theme: ${names[btn.dataset.theme] || btn.dataset.theme}`, 'success');
        });
    });

    // 字体大小（滑块）
    if (fontSizeSlider) {
        fontSizeSlider.addEventListener('input', () => {
            applyFontSize(parseFloat(fontSizeSlider.value));
        });
    }

    // 行距（滑块）
    if (lineHeightSlider) {
        lineHeightSlider.addEventListener('input', () => {
            applyLineHeight(parseFloat(lineHeightSlider.value));
        });
    }

    // MCP 添加按钮
    const btnMcpAdd = document.getElementById('btn-mcp-add');
    if (btnMcpAdd) btnMcpAdd.addEventListener('click', () => openMcpEditor(null));
}

// ============ MCP Server 管理 ============
async function fetchJson(url, options) {
    const resp = await fetch(url, options);
    return resp.json();
}

async function loadMcpServers() {
    const data = await fetchJson('/api/mcp/servers');
    return data.servers || [];
}

function mcpStatusBadge(s) {
    if (!s.enabled) return '<span style="color:#999;">已停用</span>';
    if (s.connected) return '<span style="color:#52c41a;">已连接</span>';
    return `<span style="color:#f5222d;" title="${escapeHtml(s.error || '')}">错误</span>`;
}

async function renderMcpServers() {
    const box = document.getElementById('mcp-server-list');
    if (!box) return;
    const servers = await loadMcpServers();
    window.__mcpServers = servers;
    if (!servers.length) {
        box.innerHTML = '<div style="color:#999;padding:6px 0;">尚未配置 MCP server。添加后即可在画布中使用"外部 MCP 工具"组件。</div>';
        return;
    }
    box.innerHTML = servers.map(s => `
        <div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid #f0f0f0;">
            <span style="flex:1;">${escapeHtml(s.name)} <span style="color:#999;">(${s.type}, ${s.tool_count} 工具)</span></span>
            ${mcpStatusBadge(s)}
            <button class="module-btn secondary" data-mcp-test="${s.id}" style="font-size:12px;padding:4px 8px;">测试</button>
            <button class="module-btn secondary" data-mcp-edit="${s.id}" style="font-size:12px;padding:4px 8px;">编辑</button>
            <button class="module-btn secondary" data-mcp-del="${s.id}" style="font-size:12px;padding:4px 8px;color:#f5222d;">删除</button>
        </div>`).join('');
    box.querySelectorAll('[data-mcp-test]').forEach(b => b.onclick = () => testMcpServer(b.dataset.mcpTest));
    box.querySelectorAll('[data-mcp-edit]').forEach(b => b.onclick = () => openMcpEditor(b.dataset.mcpEdit));
    box.querySelectorAll('[data-mcp-del]').forEach(b => b.onclick = () => deleteMcpServer(b.dataset.mcpDel));
}

function openMcpEditor(serverId) {
    const existing = (serverId && document.querySelector(`[data-mcp-editor="${serverId}"]`));
    // 简单实现：prompt 表单（与项目设置面板轻量风格一致）
    const servers = window.__mcpServers || [];
    const s = serverId ? servers.find(x => x.id === serverId) : null;
    const defaults = s ? s : { id: '', name: '', type: 'stdio', command: 'npx', args: '', enabled: true };
    const id = prompt('server id（字母数字-_，≤32，不可重复）', defaults.id || '');
    if (id === null) return;
    const name = prompt('显示名称', defaults.name || '');
    if (name === null) return;
    const type = prompt('类型（stdio / http）', defaults.type || 'stdio');
    if (type === null) return;
    let cfg = { id, name, type, enabled: true };
    if (type === 'stdio') {
        const cmd = prompt('命令（如 npx）', defaults.command || 'npx');
        if (cmd === null) return;
        const args = prompt('参数，空格分隔（如 -y @modelcontextprotocol/server-git）', (defaults.args || []).join(' ') || '');
        if (args === null) return;
        cfg.command = cmd;
        cfg.args = args.trim() ? args.trim().split(/\s+/) : [];
    } else {
        const url = prompt('HTTP URL', defaults.url || '');
        if (url === null) return;
        cfg.url = url;
        const token = prompt('可选 token（存后端全局配置，不回显）', defaults.token || '');
        if (token === null) return;
        if (token) cfg.token = token;
    }
    const opts = { method: serverId ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cfg) };
    fetchJson(serverId ? `/api/mcp/servers/${serverId}` : '/api/mcp/servers', opts).then(r => {
        if (!r.success) { alert('保存失败: ' + (r.error || '未知错误')); return; }
        renderMcpServers();
    });
}

async function deleteMcpServer(id) {
    if (!confirm(`确定删除 MCP server '${id}'？其工具将从画布中移除。`)) return;
    const r = await fetchJson(`/api/mcp/servers/${id}`, { method: 'DELETE' });
    if (!r.success) { alert('删除失败: ' + (r.error || '')); return; }
    renderMcpServers();
}

async function testMcpServer(id) {
    const r = await fetchJson(`/api/mcp/servers/${id}/test`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    if (r.success) renderMcpServers();
    alert(r.success ? `连接成功，共 ${r.tool_count} 个工具` : '连接失败: ' + (r.error || ''));
}

// ============================================================
// 初始化
// ============================================================
async function init() {
    // 从后端拉取组件/工具/模板/厂商元数据（后端单一来源）
    const meta = await fetch('/api/meta/components').then(r => r.ok ? r.json() : null).catch(() => null);
    if (meta && meta.success && meta.data) applyMeta(meta.data);
    // 组件库搜索/工具提示依赖 TOOL_NAME_MAP（applyMeta 已填充；拉取失败时为空对象，仅无工具提示）
    initCompSearch();
    // 登录后先从后端拉取设置合并到 localStorage（后端优先，loadActiveLLMConfig 之前）
    await pullSettingsFromBackend();
    // 恢复主题
    restoreTheme();
    // 恢复显示设置（字体大小/行距）
    restoreDisplaySettings();
    await loadConfig();
    preloadSkillPrompts();
    restoreMCPDir();

    // 检测 URL 参数：?project=<id> 或 ?project=new
    const urlParams = new URLSearchParams(window.location.search);
    const projectId = urlParams.get('project');

    if (projectId === 'new') {
        // 创建新项目
        try {
            const resp = await fetch('/api/projects', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: '新 Agent 项目' }),
            });
            const data = await resp.json();
            CURRENT_PROJECT.id = data.id;
            CURRENT_PROJECT.name = data.name;
            // 更新 URL 去掉 "new"
            window.history.replaceState(null, '', `/?project=${data.id}`);
        } catch (e) {
            console.error('创建项目失败:', e);
        }
    } else if (projectId) {
        // 加载已有项目
        CURRENT_PROJECT.id = projectId;
        await loadProjectFromServer(projectId);
    }

    setupPalletDrag();
    setupPalletBadges();
    setupCategoryFilters();
    setupPalletTooltips();
    setupCanvasDrop();
    setupCanvasClick();
    setupBoxSelection();
    setupCanvasZoomPan();
    setupDocumentHandlers();
    setupPresetButtons();

    if (!projectId) {
        // 无项目参数 → 保持原有 localStorage 行为
        loadLayout();
    }

    bindToolbarButtons();
    setupSettingsPanel();
    updateProjectBadge();
    window.addEventListener('resize', debounce(() => renderAll(), 150));
    window.addEventListener('beforeunload', () => {
        autoSaveConnections();
        if (CURRENT_PROJECT.id) autoSaveProject();
    });
}

async function loadConfig() {
    try {
        const resp = await fetch('/api/config');
        const config = await resp.json();
        STATE.model = config.model;
        toolbarModel.textContent = `模型: ${config.model}`;
    } catch (e) {
        toolbarModel.textContent = '模型: 未连接';
    }
}

// ============================================================
// 自动布局
// ============================================================
function autoLayoutPosition(index) {
    const gap = 1.5, cols = 5;
    const colW = (100 - gap * (cols + 1)) / cols;
    const col = index % cols;
    const row = Math.floor(index / cols);
    return { x: gap + col * (colW + gap), y: gap + row * 4.5 };
}

// ============================================================
// ============================================================
// 组件库搜索
// ============================================================
function initCompSearch() {
    const input = document.getElementById('comp-search');
    if (!input) return;
    const palletList = document.getElementById('pallet-list');
    if (!palletList) return;

    // 为每个组件项注入 data-tools 和 hover 提示
    palletList.querySelectorAll('.pallet-item[data-type]').forEach(item => {
        const type = item.dataset.type;
        const tools = TOOL_NAME_MAP[type] || [];
        if (tools.length > 0 && !item.dataset._titleSet) {
            item.dataset.tools = tools.join(',');
            const existingTitle = item.getAttribute('title') || '';
            const newTitle = '🔧 ' + tools.join('、');
            item.setAttribute('title', existingTitle ? existingTitle + '\n\n' + newTitle : newTitle);
            item.dataset._titleSet = '1';
        }
    });

    input.addEventListener('input', () => {
        const q = input.value.toLowerCase().trim();
        const presetSection = document.getElementById('preset-section');
        const catFilters = document.getElementById('category-filters');

        // 隐藏/显示预设和分类筛选
        if (presetSection) presetSection.style.display = q ? 'none' : '';
        if (catFilters) catFilters.style.display = q ? 'none' : '';

        // 遍历所有分类区块和组件
        const sections = palletList.querySelectorAll('.pallet-section-header');
        let prevHeader = null;

        // 收集所有 pallet-section-header 和它们后面的 pallet-item
        palletList.querySelectorAll('.pallet-section-header, .pallet-item').forEach(el => {
            if (el.classList.contains('pallet-section-header')) {
                prevHeader = el;
                el.style.display = q ? 'none' : '';
            } else if (el.classList.contains('pallet-item')) {
                const name = (el.querySelector('.pallet-name')?.textContent || '').toLowerCase();
                const desc = (el.querySelector('.pallet-desc')?.textContent || '').toLowerCase();
                const type = (el.dataset.type || '').toLowerCase();
                const tools = (el.dataset.tools || '').toLowerCase();
                const visible = !q || name.includes(q) || desc.includes(q) || type.includes(q) || tools.includes(q);
                el.style.display = visible ? '' : 'none';
                // 如果该项可见，显示其所属分类标题
                if (visible && q && prevHeader) {
                    prevHeader.style.display = '';
                }
            }
        });
    });
}


function setupPalletBadges() {
    document.querySelectorAll('.pallet-item[draggable]').forEach(item => {
        const type = item.dataset.type;
        const cat = COMPONENT_CATEGORIES[type];
        // 添加 data-cat 属性用于分类筛选
        if (cat) {
            item.dataset.cat = cat[1];
        }
        if (!cat || item.querySelector('.pallet-cat-badge')) return;
        const badge = document.createElement('span');
        badge.className = `pallet-cat-badge ${cat[1]}`;
        badge.textContent = cat[0];
        item.appendChild(badge);
    });
}

// 分类筛选
function setupCategoryFilters() {
    const filterBar = document.getElementById('category-filters');
    const palletList = document.getElementById('pallet-list');
    if (!filterBar || !palletList) return;
    // 幂等守卫：applyMeta 与 init 各调用一次，只绑一次监听
    if (filterBar.dataset.filtersBound) return;
    filterBar.dataset.filtersBound = '1';

    filterBar.querySelectorAll('.cat-filter-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            // 更新按钮状态
            filterBar.querySelectorAll('.cat-filter-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            const cat = btn.dataset.cat;
            if (cat === 'all') {
                palletList.classList.remove('pallet-list-filtering');
                return;
            }

            palletList.classList.add('pallet-list-filtering');
            palletList.querySelectorAll('.pallet-item').forEach(item => {
                if (item.dataset.cat === cat) {
                    item.classList.add('show-cat');
                } else {
                    item.classList.remove('show-cat');
                }
            });
        });
    });
}

function setupPalletDrag() {
    document.querySelectorAll('.pallet-item[draggable]').forEach(item => {
        item.addEventListener('dragstart', (e) => {
            STATE.dragSource = 'pallet';
            e.dataTransfer.setData('text/plain', item.dataset.type);
            e.dataTransfer.effectAllowed = 'copy';
            item.classList.add('dragging');
        });
        item.addEventListener('dragend', () => {
            item.classList.remove('dragging');
            STATE.dragSource = null;
        });
    });
}

function setupPalletTooltips() {
    const tooltipColors = {
        llm:      '#4A90D9',
        agent:    '#667eea',
        plan:     '#389e0d',
        reflection: '#d48806',
        sequential_executor: '#eb6f2a',
        executor: '#c41d7f',
        skills_manager: '#a855f7',
        skill_auto_call: '#7c3aed',
        loop:     '#7b1fa2',
        conditional: '#389e0d',
        memory:   '#722ed1',
        token_counter: '#f5222d',
        knowledge_base: '#fa541c',
        vector_memory: '#13c2c2',
        working_memory: '#d4b106',
        system_prompt: '#7cb305',
        function_calling: '#fa8c16',
        vision:   '#eb2f96',
        json_mode: '#722ed1',
        embeddings: '#13c2c2',
        token_manager: '#f5222d',
        web_search: '#1890ff',
        calculator: '#2f54eb',
        code_executor: '#531dab',
        text_tools: '#08979c',
        time_query: '#595959',
        url_fetch: '#096dd9',
        file_ops: '#d48806',
        json_query: '#722ed1',
        mcp_zip: '#fa8c16',
        http_request: '#13c2c2',
        image_tools: '#eb2f96',
        mcp_word: '#2b5797',
        mcp_excel: '#217346',
        mcp_ppt: '#d24726',
        mcp_weather: '#1890ff',
        mcp_database: '#52c41a',
        mcp_geocode: '#7b1fa2',
        mcp_clipboard: '#722ed1',
        mcp_encoding: '#2f54eb',
        mcp_system: '#389e0d',
        mcp_email: '#c41d7f',
        mcp_translate: '#096dd9',
        mcp_calendar: '#d4b106',
        mcp_pdf: '#cf1322',
        mcp_finance: '#08979c',
        mcp_navigation: '#0050b3',
        mcp_external: '#389e0d',
        skill_document: '#2b5797',
        skill_frontend:  '#ec4899',
        skill_uiux:      '#8b5cf6',
        skill_find:      '#06b6d4',
        skill_creator:   '#f59e0b',
        skill_super:     '#ef4444',
        skill_pua:       '#f97316',
    };

    document.querySelectorAll('.pallet-item[draggable]').forEach(item => {
        const type = item.dataset.type;
        const def = COMPONENT_DEFS[type];
        if (!def) return;

        let tooltip = null;
        let hideTimer = null;

        item.addEventListener('mouseenter', (e) => {
            clearTimeout(hideTimer);
            if (tooltip) return;

            tooltip = document.createElement('div');
            tooltip.className = 'pallet-tooltip';
            const color = tooltipColors[type] || '#4A90D9';
            const ports = [];
            if (def.ports) {
                if (def.ports.outputs && def.ports.outputs.length) ports.push(`${def.ports.outputs.length} 输出`);
                if (def.ports.inputs && def.ports.inputs.length) ports.push(`${def.ports.inputs.length} 输入`);
            }
            const portLabel = ports.length > 0 ? ports.join(' / ') : '无端口';

            // 获取该组件包含的工具
            const compTools = TOOL_NAME_MAP[type] || [];
            let toolsHTML = '';
            if (type === 'mcp_external') {
                toolsHTML = '<div class="pallet-tooltip-tools">🔌 连接外部 MCP server，工具动态可用</div>';
            } else if (compTools.length > 0) {
                toolsHTML = `<div class="pallet-tooltip-tools">🔧 ${compTools.map(t => `<code>${escapeHtml(t)}</code>`).join(' ')}</div>`;
            }

            tooltip.innerHTML = `
                <div class="pallet-tooltip-title">
                    <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${color};flex-shrink:0;"></span>
                    ${escapeHtml(def.icon)} ${escapeHtml(def.title)}
                </div>
                ${def.description ? `<div class="pallet-tooltip-body">${escapeHtml(def.description)}</div>` : ''}
                ${toolsHTML}
                <div class="pallet-tooltip-meta">
                    <span>📐 ${def.defaultSize}/12 格</span>
                    <span>🔌 ${portLabel}</span>
                </div>
            `;
            document.body.appendChild(tooltip);
            positionTooltip(tooltip, item);
        });

        item.addEventListener('mouseleave', () => {
            hideTimer = setTimeout(() => {
                if (tooltip) { tooltip.remove(); tooltip = null; }
            }, 120);
        });

        item.addEventListener('mousemove', () => {
            if (tooltip) positionTooltip(tooltip, item);
        });
    });

    // tooltip 自身 hover 时保持显示
    document.addEventListener('mouseover', (e) => {
        if (e.target.closest('.pallet-tooltip')) {
            clearTimeout(hideTimer);
        }
    });
}

function positionTooltip(tooltip, item) {
    const ir = item.getBoundingClientRect();
    const tw = tooltip.offsetWidth;
    const th = tooltip.offsetHeight;

    let left = ir.right + 14;
    let top = ir.top + (ir.height - th) / 2;

    // 右侧放不下时改到左侧
    if (left + tw > window.innerWidth - 10) {
        left = ir.left - tw - 14;
        tooltip.classList.add('arrow-right');
    } else {
        tooltip.classList.remove('arrow-right');
    }

    // 顶部/底部约束
    top = Math.max(8, Math.min(top, window.innerHeight - th - 8));

    tooltip.style.left = left + 'px';
    tooltip.style.top = top + 'px';
}

function setupCanvasDrop() {
    canvas.addEventListener('dragover', (e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = STATE.dragSource === 'pallet' ? 'copy' : 'move';
        canvas.classList.add('drag-over');
    });
    canvas.addEventListener('dragleave', (e) => {
        if (!canvas.contains(e.relatedTarget)) canvas.classList.remove('drag-over');
    });
    canvas.addEventListener('drop', (e) => {
        e.preventDefault();
        canvas.classList.remove('drag-over');
        if (STATE.dragSource === 'pallet') {
            const type = e.dataTransfer.getData('text/plain');
            if (type && COMPONENT_DEFS[type]) {
                const rect = canvas.getBoundingClientRect();
                // 考虑视口缩放和平移
                const vpLocal = screenToViewport(e.clientX, e.clientY);
                const x = (vpLocal.x / rect.width) * 100;
                const y = (vpLocal.y / rect.height) * 100;
                addComponent(type, null, null, x, y);
            }
        }
        STATE.dragSource = null;
        STATE.dragCompId = null;
        updateUI();
    });
}

function setupCanvasClick() {
    canvas.addEventListener('click', (e) => {
        // 框选刚结束时抑制本事件，避免清除刚选中的组
        if (SELBOX.suppressClick) {
            SELBOX.suppressClick = false;
            return;
        }
        if (e.target === canvas || e.target.id === 'canvas' || e.target.id === 'canvas-viewport' || e.target.id === 'connections-layer') {
            selectComponent(null);
        }
    });
}

// ============================================================
// 框选（左键在画布空白处拖拽）
// ============================================================
function setupBoxSelection() {
    canvas.addEventListener('mousedown', (e) => {
        if (e.button !== 0) return;
        if (e.target.closest('.component-card')) return;
        if (e.target.closest('.port-input') || e.target.closest('.port-output')) return;
        if (e.target.closest('#connections-layer')) return;
        // 只在画布/视口背景上开始
        const id = e.target.id;
        if (id !== 'canvas' && id !== 'canvas-viewport') return;
        e.preventDefault();
        const p = screenToViewport(e.clientX, e.clientY);
        SELBOX.startX = p.x; SELBOX.startY = p.y;
        SELBOX.curX = p.x; SELBOX.curY = p.y;
        SELBOX.active = true;
        if (!SELBOX.el) {
            SELBOX.el = document.createElement('div');
            SELBOX.el.className = 'selection-box';
            const vp = document.getElementById('canvas-viewport');
            if (vp) vp.appendChild(SELBOX.el);
        }
        SELBOX.el.style.display = 'block';
        _updateSelBox();
    });
}

function _updateSelBox() {
    if (!SELBOX.active || !SELBOX.el) return;
    const x = Math.min(SELBOX.startX, SELBOX.curX);
    const y = Math.min(SELBOX.startY, SELBOX.curY);
    const w = Math.abs(SELBOX.curX - SELBOX.startX);
    const h = Math.abs(SELBOX.curY - SELBOX.startY);
    SELBOX.el.style.left = x + 'px';
    SELBOX.el.style.top = y + 'px';
    SELBOX.el.style.width = w + 'px';
    SELBOX.el.style.height = h + 'px';

    // 高亮与选框相交的卡片
    const cr = canvas.getBoundingClientRect();
    canvas.querySelectorAll('.component-card').forEach(card => {
        const r = card.getBoundingClientRect();
        const l = (r.left - cr.left - CANVAS_VIEW.panX) / CANVAS_VIEW.zoom;
        const t = (r.top - cr.top - CANVAS_VIEW.panY) / CANVAS_VIEW.zoom;
        const cw = r.width / CANVAS_VIEW.zoom;
        const ch = r.height / CANVAS_VIEW.zoom;
        const hit = l < x + w && l + cw > x && t < y + h && t + ch > y;
        card.classList.toggle('box-selected', hit);
    });
}

function _finishSelBox() {
    if (!SELBOX.active) return;
    SELBOX.active = false;
    if (SELBOX.el) SELBOX.el.style.display = 'none';
    const ids = [];
    canvas.querySelectorAll('.component-card.box-selected').forEach(card => {
        ids.push(parseInt(card.dataset.compId));
    });
    if (ids.length > 0) {
        STATE.multiSelected = ids;
        STATE.selectedCompId = null;
        SELBOX.suppressClick = true;
        renderAll();   // 重绘以应用 box-selected 高亮
        renderPropsPanel(null);
    } else {
        STATE.multiSelected = [];
        selectComponent(null);
    }
}

// ============================================================
// 画布缩放 & 平移（滚轮缩放 + 中键拖动）
// ============================================================
function setupCanvasZoomPan() {
    // 缩放指示器
    const zoomIndicator = document.createElement('div');
    zoomIndicator.className = 'canvas-zoom-indicator';
    canvas.appendChild(zoomIndicator);
    let zoomHideTimer = null;

    function showZoom() {
        zoomIndicator.textContent = Math.round(CANVAS_VIEW.zoom * 100) + '%';
        zoomIndicator.classList.add('show');
        clearTimeout(zoomHideTimer);
        zoomHideTimer = setTimeout(() => zoomIndicator.classList.remove('show'), 800);
    }

    // 滚轮缩放（向光标位置缩放）
    canvas.addEventListener('wheel', (e) => {
        e.preventDefault();
        const rect = canvas.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;

        const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12;
        const newZoom = Math.max(0.2, Math.min(3, CANVAS_VIEW.zoom * factor));

        // 向光标位置缩放
        CANVAS_VIEW.panX = mx - (mx - CANVAS_VIEW.panX) * (newZoom / CANVAS_VIEW.zoom);
        CANVAS_VIEW.panY = my - (my - CANVAS_VIEW.panY) * (newZoom / CANVAS_VIEW.zoom);
        CANVAS_VIEW.zoom = newZoom;

        updateViewportTransform();
        showZoom();
    }, { passive: false });

    // 中键拖动平移（避免与浏览器右键手势导航冲突）
    canvas.addEventListener('mousedown', (e) => {
        if (e.button !== 1) return;
        // 不在组件卡片上时才能平移画布
        if (e.target.closest('.component-card')) return;
        e.preventDefault();
        CANVAS_VIEW.panning = true;
        CANVAS_VIEW.panStartX = e.clientX;
        CANVAS_VIEW.panStartY = e.clientY;
        CANVAS_VIEW.panStartPanX = CANVAS_VIEW.panX;
        CANVAS_VIEW.panStartPanY = CANVAS_VIEW.panY;
        canvas.classList.add('grabbing');
    });

    // 阻止中键点击的默认行为（浏览器自动滚动）
    canvas.addEventListener('auxclick', (e) => {
        if (e.button === 1) e.preventDefault();
    });

    document.addEventListener('mousemove', (e) => {
        if (!CANVAS_VIEW.panning) return;
        CANVAS_VIEW.panX = CANVAS_VIEW.panStartPanX + (e.clientX - CANVAS_VIEW.panStartX);
        CANVAS_VIEW.panY = CANVAS_VIEW.panStartPanY + (e.clientY - CANVAS_VIEW.panStartY);
        updateViewportTransform();
    });

    document.addEventListener('mouseup', () => {
        if (CANVAS_VIEW.panning) {
            CANVAS_VIEW.panning = false;
            canvas.classList.remove('grabbing');
        }
    });

    // Ctrl+0 重置视图
    document.addEventListener('keydown', (e) => {
        if (e.ctrlKey && e.key === '0') {
            e.preventDefault();
            CANVAS_VIEW.zoom = 1;
            CANVAS_VIEW.panX = 0;
            CANVAS_VIEW.panY = 0;
            updateViewportTransform();
            showZoom();
        }
    });
}

function updateViewportTransform() {
    const vp = document.getElementById('canvas-viewport');
    if (vp) {
        vp.style.transform = `translate(${CANVAS_VIEW.panX}px, ${CANVAS_VIEW.panY}px) scale(${CANVAS_VIEW.zoom})`;
    }
}

// 将屏幕坐标转换为视口本地坐标
function screenToViewport(screenX, screenY) {
    const vp = document.getElementById('canvas-viewport');
    const cr = canvas.getBoundingClientRect();
    if (!vp) {
        // 空画布时也用 pan/zoom 做正确转换（vr.left = cr.left + panX）
        return {
            x: (screenX - cr.left - CANVAS_VIEW.panX) / CANVAS_VIEW.zoom,
            y: (screenY - cr.top - CANVAS_VIEW.panY) / CANVAS_VIEW.zoom,
        };
    }
    const vr = vp.getBoundingClientRect();
    return {
        x: (screenX - vr.left) / CANVAS_VIEW.zoom,
        y: (screenY - vr.top) / CANVAS_VIEW.zoom,
    };
}

function selectComponent(compId) {
    STATE.selectedCompId = compId;
    if (compId === null) STATE.multiSelected = [];  // 单击空白清空多选
    document.querySelectorAll('.component-card').forEach(card => {
        const id = parseInt(card.dataset.compId);
        card.classList.toggle('selected', id === compId);
        card.classList.toggle('box-selected', STATE.multiSelected.includes(id));
    });
    renderPropsPanel(compId);
}

/** Ctrl/⌘+点击：把组件加入/移出多选组 */
function toggleMultiSelect(compId) {
    const idx = STATE.multiSelected.indexOf(compId);
    if (idx >= 0) {
        STATE.multiSelected.splice(idx, 1);
    } else {
        STATE.multiSelected.push(compId);
    }
    STATE.selectedCompId = null;
    renderAll();
    renderPropsPanel(null);
}

// ============================================================
// 全局事件处理（卡片拖拽 + 连线拖拽）
// ============================================================
// ── 边缘自动滚动 ──
const EDGE_SCROLL_THRESHOLD = 50;  // 距离边缘多少像素触发滚动
const EDGE_SCROLL_SPEED = 8;       // 每次滚动像素数

let _edgeScrollTimer = null;

function _checkEdgeScroll(e) {
    const cr = canvas.getBoundingClientRect();
    let dx = 0, dy = 0;

    // 鼠标靠近边缘 → 画布向反方向平移，露出该方向的内容
    if (e.clientX < cr.left + EDGE_SCROLL_THRESHOLD) {
        dx = EDGE_SCROLL_SPEED;   // 左边 → 画布右移，露出左侧内容
    } else if (e.clientX > cr.right - EDGE_SCROLL_THRESHOLD) {
        dx = -EDGE_SCROLL_SPEED;  // 右边 → 画布左移，露出右侧内容
    }
    if (e.clientY < cr.top + EDGE_SCROLL_THRESHOLD) {
        dy = EDGE_SCROLL_SPEED;   // 上边 → 画布下移，露出上方内容
    } else if (e.clientY > cr.bottom - EDGE_SCROLL_THRESHOLD) {
        dy = -EDGE_SCROLL_SPEED;  // 下边 → 画布上移，露出下方内容
    }

    if (dx !== 0 || dy !== 0) {
        CANVAS_VIEW.panX += dx;
        CANVAS_VIEW.panY += dy;
        updateViewportTransform();
    }
}

function _startEdgeScroll() {
    if (_edgeScrollTimer) return;
    _edgeScrollTimer = setInterval(() => {
        const dragging = WIRE.active || DRAG.active;
        if (!dragging) {
            _stopEdgeScroll();
            return;
        }
        // 使用最后一次已知的鼠标位置（由 mousemove 更新）
        const fakeEvent = { clientX: window._lastMouseX || 0, clientY: window._lastMouseY || 0 };
        _checkEdgeScroll(fakeEvent);
    }, 16);  // ~60fps
}

function _stopEdgeScroll() {
    if (_edgeScrollTimer) {
        clearInterval(_edgeScrollTimer);
        _edgeScrollTimer = null;
    }
}

function setupDocumentHandlers() {
    document.addEventListener('mousemove', (e) => {
        // 记录鼠标位置供边缘滚动定时器使用
        window._lastMouseX = e.clientX;
        window._lastMouseY = e.clientY;

        // --- 框选拖拽 ---
        if (SELBOX.active) {
            const p = screenToViewport(e.clientX, e.clientY);
            SELBOX.curX = p.x; SELBOX.curY = p.y;
            _updateSelBox();
            return;
        }

        // --- 连线拖拽 ---
        if (WIRE.active) {
            const vpLocal = screenToViewport(e.clientX, e.clientY);
            WIRE.currentX = vpLocal.x;
            WIRE.currentY = vpLocal.y;
            drawTempWire();
            _startEdgeScroll();
            return;
        }
        // --- 卡片拖拽 ---
        if (!DRAG.active) {
            _stopEdgeScroll();
            return;
        }
        _startEdgeScroll();
        const dx = e.clientX - DRAG.startMouseX;
        const dy = e.clientY - DRAG.startMouseY;
        if (!DRAG.moved && (Math.abs(dx) > 3 || Math.abs(dy) > 3)) {
            DRAG.moved = true;
            DRAG.card.classList.add('is-dragging');
        }
        if (!DRAG.moved) return;
        const cr = canvas.getBoundingClientRect();
        // 将屏幕像素位移转换为视口百分比位移（考虑缩放）
        const dxPct = (dx / CANVAS_VIEW.zoom / cr.width) * 100;
        const dyPct = (dy / CANVAS_VIEW.zoom / cr.height) * 100;
        if (DRAG.group) {
            // 框选组：所有卡片按各自起点同步位移
            DRAG.group.forEach(g => {
                g.card.style.left = (g.origLeftPct + dxPct) + '%';
                g.card.style.top = (g.origTopPct + dyPct) + '%';
            });
        } else {
            const comp = STATE.components.find(c => c.id === DRAG.compId);
            if (!comp) return;
            DRAG.card.style.left = (DRAG.origLeftPct + dxPct) + '%';
            DRAG.card.style.top = (DRAG.origTopPct + dyPct) + '%';
        }
        // 拖动时实时刷新连线
        refreshAllConnectionPaths();
    });

    document.addEventListener('mouseup', (e) => {
        _stopEdgeScroll();
        // --- 框选结束 ---
        if (SELBOX.active) {
            _finishSelBox();
            return;
        }
        // --- 连线拖拽结束 ---
        if (WIRE.active) {
            const targetEl = document.elementFromPoint(e.clientX, e.clientY);
            const portEl = targetEl?.closest?.('.port-input');
            if (portEl) {
                const card = portEl.closest('.component-card');
                const targetCompId = parseInt(card?.dataset?.compId);
                if (targetCompId && targetCompId !== WIRE.sourceCompId) {
                    // ── 连接限制：LLM 不能直接连工具，必须通过执行器 ──
                    const sourceComp = STATE.components.find(c => c.id === WIRE.sourceCompId);
                    const targetComp = STATE.components.find(c => c.id === targetCompId);
                    if (sourceComp && targetComp && !validateConnection(sourceComp, targetComp)) {
                        WIRE.active = false;
                        WIRE.sourceCompId = null;
                        WIRE.sourcePortId = null;
                        return;
                    }

                    const exists = STATE.connections.some(
                        c => c.sourceCompId === WIRE.sourceCompId
                            && c.sourcePortId === WIRE.sourcePortId
                            && c.targetCompId === targetCompId
                            && c.targetPortId === portEl.dataset.portId
                    );
                    if (!exists) {
                        pushHistory();
                        STATE.connections.push({
                            id: 'conn_' + STATE.nextConnId++,
                            sourceCompId: WIRE.sourceCompId,
                            sourcePortId: WIRE.sourcePortId,
                            targetCompId: targetCompId,
                            targetPortId: portEl.dataset.portId,
                        });
                    }
                }
            }
            WIRE.active = false;
            WIRE.sourceCompId = null;
            WIRE.sourcePortId = null;
            autoSaveConnections();
            renderAll();
            return;
        }
        // --- 卡片拖拽结束 ---
        if (!DRAG.active) return;
        if (DRAG.moved && DRAG.card) {
            const cr = canvas.getBoundingClientRect();
            // 整组或单卡统一提交坐标
            const targets = DRAG.group || [{ id: DRAG.compId, card: DRAG.card }];
            targets.forEach(t => {
                const g = STATE.components.find(c => c.id === t.id);
                if (!g || !t.card) return;
                const r = t.card.getBoundingClientRect();
                const localLeft = (r.left - cr.left - CANVAS_VIEW.panX) / CANVAS_VIEW.zoom;
                const localTop = (r.top - cr.top - CANVAS_VIEW.panY) / CANVAS_VIEW.zoom;
                g.x = (localLeft / cr.width) * 100;
                g.y = (localTop / cr.height) * 100;
            });
            renderAll();
            if (DRAG.group) {
                // 组拖动后保持多选高亮
                STATE.multiSelected.forEach(id => {
                    const c = canvas.querySelector(`[data-comp-id="${id}"]`);
                    if (c) c.classList.add('box-selected');
                });
            } else if (DRAG.compId === STATE.selectedCompId) {
                renderPropsPanel(DRAG.compId);
            }
        }
        if (DRAG.card) DRAG.card.classList.remove('is-dragging');
        DRAG.card = null; DRAG.compId = null;
        DRAG.active = false; DRAG.moved = false; DRAG.group = null;
    });
}

function bindCardDrag(card, comp) {
    const header = card.querySelector('.card-header');
    if (!header) return;
    header.addEventListener('mousedown', (e) => {
        if (e.target.closest('button')) return;
        if (e.button !== 0) return;
        e.preventDefault();
        const cr = canvas.getBoundingClientRect();
        const r = card.getBoundingClientRect();
        // 将屏幕坐标转换为视口本地坐标（取消缩放/平移的影响）
        const localLeft = (r.left - cr.left - CANVAS_VIEW.panX) / CANVAS_VIEW.zoom;
        const localTop = (r.top - cr.top - CANVAS_VIEW.panY) / CANVAS_VIEW.zoom;
        DRAG.card = card; DRAG.compId = comp.id;
        DRAG.startMouseX = e.clientX; DRAG.startMouseY = e.clientY;
        DRAG.origLeftPct = (localLeft / cr.width) * 100;
        DRAG.origTopPct = (localTop / cr.height) * 100;
        DRAG.active = true; DRAG.moved = false;
        // 框选组拖动：若该卡片在多选组内，记录整组起点
        if (STATE.multiSelected.includes(comp.id) && STATE.multiSelected.length > 1) {
            DRAG.group = STATE.multiSelected.map(gid => {
                const g = STATE.components.find(c => c.id === gid);
                const gCard = canvas.querySelector(`[data-comp-id="${gid}"]`);
                if (!g || !gCard) return null;
                const gr = gCard.getBoundingClientRect();
                const gl = (gr.left - cr.left - CANVAS_VIEW.panX) / CANVAS_VIEW.zoom;
                const gt = (gr.top - cr.top - CANVAS_VIEW.panY) / CANVAS_VIEW.zoom;
                return { id: gid, card: gCard, origLeftPct: (gl / cr.width) * 100, origTopPct: (gt / cr.height) * 100 };
            }).filter(Boolean);
        } else {
            DRAG.group = null;
        }
    });
}

// ============================================================
// 组件 CRUD
// ============================================================
function addComponent(type, size, id, x, y) {
    const def = COMPONENT_DEFS[type];
    if (!def) return;
    pushHistory();
    if (x == null || y == null) { const pos = autoLayoutPosition(STATE.components.length); x = pos.x; y = pos.y; }
    const comp = { id: id || STATE.nextId++, type, size: size || def.defaultSize, x, y, messages: [] };
    // 知识库组件自动命名：知识库1、知识库2…
    if (type === 'knowledge_base') {
        const nums = STATE.components
            .filter(c => c.type === 'knowledge_base')
            .map(c => { const m = /知识库(\d+)/.exec(c.name || ''); return m ? parseInt(m[1], 10) : 0; });
        comp.name = '知识库' + ((nums.length ? Math.max(...nums) : 0) + 1);
    }
    STATE.components.push(comp);
    renderAll(); updateUI();
    setTimeout(() => selectComponent(comp.id), 50);
    setTimeout(() => {
        const card = canvas.querySelector(`[data-comp-id="${comp.id}"]`);
        if (card) card.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 100);
}

function removeComponent(compId) {
    pushHistory();
    STATE.components = STATE.components.filter(c => c.id !== compId);
    STATE.connections = STATE.connections.filter(
        c => c.sourceCompId !== compId && c.targetCompId !== compId
    );
    if (STATE.selectedCompId === compId) selectComponent(null);
    renderAll(); updateUI();
}

/** 批量删除多个组件（含其全部连线） */
function removeComponents(ids) {
    if (!ids || ids.length === 0) return;
    pushHistory();
    const idSet = new Set(ids);
    STATE.components = STATE.components.filter(c => !idSet.has(c.id));
    STATE.connections = STATE.connections.filter(
        c => !idSet.has(c.sourceCompId) && !idSet.has(c.targetCompId)
    );
    STATE.multiSelected = [];
    if (STATE.selectedCompId != null && idSet.has(STATE.selectedCompId)) selectComponent(null);
    renderAll(); updateUI();
}

function resizeComponent(compId) {
    const comp = STATE.components.find(c => c.id === compId);
    if (!comp) return;
    const sizes = [3, 4, 6, 12];
    const idx = sizes.indexOf(comp.size);
    const newSize = sizes[(idx + 1) % sizes.length];
    comp.size = newSize;
    renderAll(); renderPropsPanel(compId);
}

// ============================================================
// 渲染画布
// ============================================================
function renderAll() {
    // 渲染前先刷新顺序执行器和执行器的工具列表
    STATE.components.filter(c => c.type === 'sequential_executor').forEach(c => updateSequentialTools(c));
    STATE.components.filter(c => c.type === 'executor').forEach(c => refreshExecutorTools(c));

    const selectedId = STATE.selectedCompId;

    // 清理框选元素（视口会被重建）
    if (SELBOX.el) { SELBOX.el.remove(); SELBOX.el = null; }
    SELBOX.active = false;

    // 清空画布并创建视口（比 innerHTML 更高效的 DOM 清除）
    while (canvas.firstChild) canvas.removeChild(canvas.firstChild);
    const vp = document.createElement('div');
    vp.id = 'canvas-viewport';
    canvas.appendChild(vp);

    // SVG 连线层（在视口内，viewBox 与画布像素尺寸一致）
    const cw = canvas.clientWidth;
    const ch = canvas.clientHeight;
    const svgNS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(svgNS, 'svg');
    svg.id = 'connections-layer';
    svg.setAttribute('viewBox', `0 0 ${cw} ${ch}`);
    svg.setAttribute('width', cw);
    svg.setAttribute('height', ch);
    svg.setAttribute('preserveAspectRatio', 'none');
    svg.setAttribute('style', 'position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:0;overflow:visible;');
    vp.appendChild(svg);

    // 缩放指示器（在画布层，不受视口缩放影响）
    const zi = document.createElement('div');
    zi.className = 'canvas-zoom-indicator';
    canvas.appendChild(zi);

    // 组件卡片
    STATE.components.forEach(comp => {
        try {
            const card = createComponentCard(comp);
            vp.appendChild(card);
        } catch (e) {
            console.error(`渲染组件 #${comp.id} (${comp.type}) 失败:`, e);
        }
    });

    // 恢复视口变换
    updateViewportTransform();

    // 绘制连线
    drawConnections(svg);

    if (selectedId && STATE.components.some(c => c.id === selectedId)) {
        STATE.selectedCompId = selectedId;
    }
}

function drawTempWire() {
    const svg = document.getElementById('connections-layer');
    if (!svg) return;
    let tmp = svg.querySelector('#temp-wire');
    if (!tmp) {
        tmp = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        tmp.id = 'temp-wire';
        tmp.setAttribute('fill', 'none');
        tmp.setAttribute('stroke', 'var(--primary)');
        tmp.setAttribute('stroke-width', '2.5');
        tmp.setAttribute('pointer-events', 'none');
        tmp.style.opacity = '0.6';
        svg.appendChild(tmp);
    }
    const sp = getPortCanvasPos(WIRE.sourceCompId, WIRE.sourcePortId);
    if (!sp) return;
    const d = bezierPath(sp, { x: WIRE.currentX, y: WIRE.currentY });
    tmp.setAttribute('d', d);
}

function createComponentCard(comp) {
    const def = COMPONENT_DEFS[comp.type];
    const card = document.createElement('div');
    card.className = 'component-card';
    card.dataset.compId = comp.id;
    const wPct = (comp.size / 12) * 100;
    card.style.width = wPct + '%';
    card.style.left = comp.x + '%';
    card.style.top = comp.y + '%';
    if (comp.id === STATE.selectedCompId) card.classList.add('selected');
    if (STATE.multiSelected.includes(comp.id)) card.classList.add('box-selected');

    // --- 头部 ---
    const header = document.createElement('div');
    header.className = 'card-header';
    const connCount = STATE.connections.filter(c => c.sourceCompId === comp.id || c.targetCompId === comp.id).length;
    header.innerHTML = `
        <span class="card-header-icon">${def.icon}</span>
        <span class="card-header-title">${escapeHtml(comp.name || def.title)}</span>
        ${connCount > 0 ? `<span class="card-header-badge" style="background:var(--primary-bg);color:var(--primary);">已连接 ${connCount}</span>` : ''}
        <span class="card-header-badge">w:${comp.size}/12</span>
        ${comp.type === 'mcp_external' ? '<span class="card-header-badge" style="background:#389e0d;color:#fff;" title="外部 MCP 工具">MCP</span>' : ''}
        <div class="card-header-actions">
            <button class="card-btn btn-resize" title="调整宽度">&harr;</button>
            <button class="card-btn btn-remove" title="移除">&times;</button>
        </div>
    `;
    header.querySelector('.btn-resize').addEventListener('click', (e) => { e.stopPropagation(); resizeComponent(comp.id); });
    header.querySelector('.btn-remove').addEventListener('click', (e) => { e.stopPropagation(); removeComponent(comp.id); });
    card.addEventListener('click', (e) => {
        e.stopPropagation();
        if (e.ctrlKey || e.metaKey) {
            toggleMultiSelect(comp.id);
        } else {
            selectComponent(comp.id);
        }
    });

    // --- 内容 ---
    const body = document.createElement('div');
    body.className = 'card-body';
    try {
        def.render(body, comp);
    } catch (e) {
        body.innerHTML = `<div class="placeholder-body"><span class="placeholder-desc">渲染失败: ${escapeHtml(e.message)}</span></div>`;
    }
    card.appendChild(header);
    card.appendChild(body);

    // --- 端口（沿卡片边缘均匀分布，避免重叠）---
    if (def.ports) {
        let inputPorts = def.ports.inputs || [];
        let outputPorts = def.ports.outputs || [];

        // Executor / Agent / SequentialExecutor / SkillsManager 支持动态端口数
        if (comp.type === 'executor') {
            const n = comp.execPortCount || 5;
            outputPorts = Array.from({length: n}, (_, i) => ({
                id: `exec-tool-${i + 1}`, label: `工具 ${i + 1}`
            }));
        }
        if (comp.type === 'skills_manager') {
            // LLM 驱动端口在左侧（input），技能端口在右侧（output）
            const n = comp.skmPortCount || 5;
            inputPorts = [
                { id: 'skm-llm-in', label: 'LLM 驱动' }
            ];
            outputPorts = [];
            for (let i = 1; i <= n; i++) {
                outputPorts.push({ id: `skm-skill-${i}`, label: `Skill ${i}` });
            }
            // 同时保留 def.ports.outputs 静态定义以防回退
            def.ports.outputs = outputPorts;
        }

        inputPorts.forEach((port, i, arr) => {
            const dot = document.createElement('div');
            // Skills Manager / Skill Auto Call：LLM 驱动端口用绿色
            if ((comp.type === 'skills_manager' && port.id === 'skm-llm-in') ||
                (comp.type === 'skill_auto_call' && port.id === 'auto-llm-in')) {
                dot.className = 'port port-input port-green';
            } else {
                dot.className = 'port port-input';
            }
            dot.dataset.portId = port.id;
            dot.title = port.label;
            dot.style.top = portTopPercent(i, arr.length);
            card.appendChild(dot);
        });
        outputPorts.forEach((port, i, arr) => {
            const dot = document.createElement('div');
            // Skills Manager：技能端口在右侧用蓝色；Skill Auto Call：输出端口用紫色
            if (comp.type === 'skills_manager' && port.id.startsWith('skm-skill-')) {
                dot.className = 'port port-output port-blue';
            } else if (comp.type === 'skill_auto_call' && port.id === 'auto-skm-out') {
                dot.className = 'port port-output port-purple';
            } else {
                dot.className = 'port port-output';
            }
            dot.dataset.portId = port.id;
            dot.title = port.label;
            dot.style.top = portTopPercent(i, arr.length);
            dot.addEventListener('mousedown', (e) => {
                e.stopPropagation(); e.preventDefault();
                WIRE.active = true;
                WIRE.sourceCompId = comp.id;
                WIRE.sourcePortId = port.id;
                const vpLocal = screenToViewport(e.clientX, e.clientY);
                WIRE.startX = vpLocal.x;
                WIRE.startY = vpLocal.y;
                WIRE.currentX = WIRE.startX;
                WIRE.currentY = WIRE.startY;
            });
            card.appendChild(dot);
        });
    }

    bindCardDrag(card, comp);
    return card;
}

// 计算端口在卡片边缘的垂直位置（避免同侧多端口重叠）
function portTopPercent(index, total) {
    if (total <= 1) return '50%';
    // 从 10% 到 90% 均匀分布
    return (10 + (80 * index) / (total - 1)) + '%';
}

// ============================================================
// 连线系统
// ============================================================
function getPortCanvasPos(compId, portId) {
    const card = canvas.querySelector(`[data-comp-id="${compId}"]`);
    if (!card) return null;
    const portEl = card.querySelector(`[data-port-id="${portId}"]`);
    if (!portEl) return null;
    const vp = document.getElementById('canvas-viewport');
    const vr = vp ? vp.getBoundingClientRect() : canvas.getBoundingClientRect();
    const pr = portEl.getBoundingClientRect();
    // 将屏幕坐标转换为视口本地坐标（SVG 坐标系）
    return {
        x: (pr.left + pr.width / 2 - vr.left) / CANVAS_VIEW.zoom,
        y: (pr.top + pr.height / 2 - vr.top) / CANVAS_VIEW.zoom,
    };
}

function bezierPath(start, end) {
    const dx = Math.abs(end.x - start.x) * 0.5;
    return `M ${start.x} ${start.y} C ${start.x + dx} ${start.y} ${end.x - dx} ${end.y} ${end.x} ${end.y}`;
}

function drawConnections(svg) {
    svg.querySelectorAll('.connection-group').forEach(g => g.remove());
    const svgNS = 'http://www.w3.org/2000/svg';

    STATE.connections.forEach(conn => {
        const sp = getPortCanvasPos(conn.sourceCompId, conn.sourcePortId);
        const ep = getPortCanvasPos(conn.targetCompId, conn.targetPortId);
        if (!sp || !ep) return;

        const group = document.createElementNS(svgNS, 'g');
        group.setAttribute('class', 'connection-group');
        group.dataset.connId = conn.id;

        // 实线路径
        const path = document.createElementNS(svgNS, 'path');
        const d = bezierPath(sp, ep);
        path.setAttribute('d', d);
        path.setAttribute('class', 'connection-path');
        path.setAttribute('fill', 'none');
        path.setAttribute('stroke', '#4A90D9');
        path.setAttribute('stroke-width', '2.5');
        path.setAttribute('pointer-events', 'stroke');
        group.appendChild(path);

        // 中间删除按钮
        const mx = (sp.x + ep.x) / 2;
        const my = (sp.y + ep.y) / 2;
        const btn = document.createElementNS(svgNS, 'g');
        btn.setAttribute('class', 'connection-delete-btn');
        btn.setAttribute('transform', `translate(${mx}, ${my})`);
        btn.innerHTML = '<circle cx="0" cy="0" r="10"/><text x="0" y="0">×</text>';
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            removeConnection(conn.id);
        });
        group.appendChild(btn);

        // 整条线点击也可删除
        path.addEventListener('click', (e) => {
            e.stopPropagation();
            removeConnection(conn.id);
        });

        svg.appendChild(group);
    });
}

// 拖动组件时实时刷新连线（原地更新，不重建 DOM）
function refreshAllConnectionPaths() {
    const svg = document.getElementById('connections-layer');
    if (!svg) return;

    // 保持 viewBox 与画布尺寸同步（窗口缩放后可能变化）
    const cw = canvas.clientWidth;
    const ch = canvas.clientHeight;
    if (svg.getAttribute('width') !== String(cw) || svg.getAttribute('height') !== String(ch)) {
        svg.setAttribute('viewBox', `0 0 ${cw} ${ch}`);
        svg.setAttribute('width', cw);
        svg.setAttribute('height', ch);
    }

    const groups = svg.querySelectorAll('.connection-group');
    groups.forEach(group => {
        const connId = group.dataset.connId;
        const conn = STATE.connections.find(c => c.id === connId);
        if (!conn) { group.remove(); return; }
        const sp = getPortCanvasPos(conn.sourceCompId, conn.sourcePortId);
        const ep = getPortCanvasPos(conn.targetCompId, conn.targetPortId);
        const path = group.querySelector('.connection-path');
        if (!path) return;
        if (!sp || !ep) { path.setAttribute('d', ''); return; }
        const d = bezierPath(sp, ep);
        path.setAttribute('d', d);
        // 同步更新删除按钮位置
        const btn = group.querySelector('.connection-delete-btn');
        if (btn) {
            const mx = (sp.x + ep.x) / 2;
            const my = (sp.y + ep.y) / 2;
            btn.setAttribute('transform', `translate(${mx}, ${my})`);
        }
    });
}

function removeConnection(connId) {
    pushHistory();
    STATE.connections = STATE.connections.filter(c => c.id !== connId);
    renderAll();
    autoSaveConnections();
}

// ============================================================
// 右侧属性面板
// ============================================================
function renderPropsPanel(compId) {
    if (!compId) {
        propsContent.innerHTML = `
            <div class="props-empty">
                <div class="props-empty-icon">
                    <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.4">
                        <circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>
                    </svg>
                </div>
                <div class="props-empty-text">点击画布中的组件<br>查看和编辑属性</div>
            </div>`;
        return;
    }
    const comp = STATE.components.find(c => c.id === compId);
    if (!comp) return;
    const def = COMPONENT_DEFS[comp.type];
    if (!def) return;
    const sizeName = { 3: '25% (3/12)', 4: '33% (4/12)', 6: '50% (6/12)', 12: '100% (12/12)' }[comp.size];

    const outConns = STATE.connections.filter(c => c.sourceCompId === compId);
    const inConns = STATE.connections.filter(c => c.targetCompId === compId);

    let connHtml = '';
    if (outConns.length > 0) {
        connHtml += '<div class="props-group"><span class="props-label">输出连线</span>';
        outConns.forEach(conn => {
            const tgt = STATE.components.find(c => c.id === conn.targetCompId);
            const portLabel = comp.type === 'sequential_executor'
                ? ` [${conn.sourcePortId.replace('seq-step-', '步骤')}]`
                : '';
            connHtml += `<span class="props-value" style="font-size:12px;">&rarr; ${tgt ? COMPONENT_DEFS[tgt.type].icon + ' ' + COMPONENT_DEFS[tgt.type].title : '(已删除)'}${portLabel}</span>`;
        });
        connHtml += '</div>';
    }
    if (inConns.length > 0) {
        connHtml += '<div class="props-group"><span class="props-label">输入连线</span>';
        inConns.forEach(conn => {
            const src = STATE.components.find(c => c.id === conn.sourceCompId);
            connHtml += `<span class="props-value" style="font-size:12px;">&larr; ${src ? COMPONENT_DEFS[src.type].icon + ' ' + COMPONENT_DEFS[src.type].title : '(已删除)'}</span>`;
        });
        connHtml += '</div>';
    }

    // 组件代码（序列化 JSON，用于调试/复制）
    const compCode = JSON.stringify(serializeComponent(comp), null, 2);

    propsContent.innerHTML = `
        <div class="props-form">
            <div class="props-group"><span class="props-label">组件类型</span><span class="props-value">${def.icon} ${def.title}</span></div>
            <div class="props-group"><span class="props-label">组件 ID</span><span class="props-value">#${comp.id}</span></div>
            <div class="props-group"><span class="props-label">当前位置</span><span class="props-value">X: ${comp.x.toFixed(1)}% / Y: ${comp.y.toFixed(1)}%</span></div>
            <div class="props-group"><span class="props-label">当前宽度</span><span class="props-value">${sizeName}</span></div>
            ${connHtml}
            <div class="props-group"><span class="props-label">描述</span><span class="props-value" style="color:var(--text-secondary);font-family:var(--font);font-size:12px;line-height:1.6;">${escapeHtml(def.description)}</span></div>
            <button class="props-btn" onclick="resizeComponent(${comp.id})">&harr; 切换宽度 (当前: ${sizeName})</button>
            <button class="props-btn danger" onclick="removeComponent(${comp.id})">&times; 移除此组件</button>
            <div class="props-group" style="margin-top:8px;">
                <div style="display:flex;justify-content:space-between;align-items:center;cursor:pointer;" id="props-code-toggle-${comp.id}">
                    <span class="props-label" style="margin:0;">📋 组件代码</span>
                    <span style="font-size:10px;color:var(--text-muted);" id="props-code-arrow-${comp.id}">▶</span>
                </div>
                <pre id="props-code-block-${comp.id}" style="display:none;margin-top:4px;padding:8px;background:var(--bg-input);border-radius:4px;font-size:10px;color:var(--text-secondary);max-height:200px;overflow:auto;white-space:pre-wrap;word-break:break-all;">${escapeHtml(compCode)}</pre>
            </div>
            <div class="props-group" style="margin-top:4px;">
                <div style="display:flex;justify-content:space-between;align-items:center;cursor:pointer;" id="props-backend-toggle-${comp.id}">
                    <span class="props-label" style="margin:0;">🐍 后端代码</span>
                    <span style="font-size:10px;color:var(--text-muted);" id="props-backend-arrow-${comp.id}">▶</span>
                </div>
                <pre id="props-backend-block-${comp.id}" style="display:none;margin-top:4px;padding:8px;background:var(--bg-input);border-radius:4px;font-size:10px;color:var(--text-secondary);max-height:200px;overflow:auto;white-space:pre-wrap;word-break:break-all;">点击加载后端源码</pre>
            </div>
        </div>
    `;

    // 代码块折叠交互
    setTimeout(() => {
        const toggle = document.getElementById(`props-code-toggle-${comp.id}`);
        const block = document.getElementById(`props-code-block-${comp.id}`);
        const arrow = document.getElementById(`props-code-arrow-${comp.id}`);
        if (toggle && block && arrow) {
            toggle.addEventListener('click', () => {
                const hidden = block.style.display === 'none';
                block.style.display = hidden ? 'block' : 'none';
                arrow.textContent = hidden ? '▼' : '▶';
            });
        }

        // 后端代码块（异步加载）
        const backendBlock = document.getElementById(`props-backend-block-${comp.id}`);
        const backendToggle = document.getElementById(`props-backend-toggle-${comp.id}`);
        const backendArrow = document.getElementById(`props-backend-arrow-${comp.id}`);
        if (backendBlock && backendToggle && backendArrow) {
            let loaded = false;
            backendToggle.addEventListener('click', async () => {
                const hidden = backendBlock.style.display === 'none';
                if (hidden && !loaded) {
                    backendBlock.textContent = '⏳ 加载中…';
                    backendBlock.style.display = 'block';
                    backendArrow.textContent = '▼';
                    try {
                        const resp = await fetch(`/api/component-source/${encodeURIComponent(comp.type)}`);
                        const data = await resp.json();
                        if (data.code) {
                            const truncated = data.truncated ? `\n\n; ... 共 ${data.total_lines} 行，仅显示前 300 行` : '';
                            backendBlock.textContent = `; 源文件: ${data.source_file} (${data.total_lines} 行)${truncated}\n\n${data.code}`;
                        } else {
                            backendBlock.textContent = `; 错误: ${data.error || '未知'}`;
                        }
                        loaded = true;
                    } catch (e) {
                        backendBlock.textContent = '; 加载失败: ' + e.message;
                    }
                } else {
                    backendBlock.style.display = hidden ? 'block' : 'none';
                    backendArrow.textContent = hidden ? '▼' : '▶';
                }
            });
        }
    }, 50);
}
// ============ 外部 MCP 工具组件 ============
async function renderMcpExternalPanel(container, comp) {
    if (!comp.serverId) comp.serverId = '';
    if (!comp.toolNames) comp.toolNames = null; // null = 全部工具
    const servers = await loadMcpServers().catch(() => []);
    const enabled = servers.filter(s => s.enabled);
    const opts = enabled.map(s => `<option value="${escapeHtml(s.id)}" ${comp.serverId === s.id ? 'selected' : ''}>${escapeHtml(s.name)} (${s.tool_count})</option>`).join('') || '<option value="">（请先在设置中配置 server）</option>';

    container.innerHTML = `
        <div style="padding:12px;">
            <label style="font-size:13px;color:#666;">MCP Server</label>
            <select id="mcp-sel-${comp.id}" style="width:100%;padding:6px;margin:6px 0 12px;border:1px solid #d9d9d9;border-radius:4px;">
                <option value="">（未选择）</option>
                ${opts}
            </select>
            <div id="mcp-tools-${comp.id}" style="max-height:180px;overflow-y:auto;border:1px solid #f0f0f0;border-radius:4px;padding:8px;font-size:13px;">
                ${comp.serverId ? '加载工具中…' : '选择 server 后显示可用工具'}
            </div>
        </div>
    `;
    const sel = container.querySelector(`#mcp-sel-${comp.id}`);
    sel.addEventListener('change', async () => {
        comp.serverId = sel.value;
        comp.toolNames = null;
        await renderMcpToolList(container, comp);
    });
    if (comp.serverId) await renderMcpToolList(container, comp);
}

async function renderMcpToolList(container, comp) {
    const box = container.querySelector(`#mcp-tools-${comp.id}`);
    if (!comp.serverId) { box.innerHTML = '<span style="color:#999;">未选择 server</span>'; comp.mcpAllTools = null; return; }
    const data = await fetchJson(`/api/mcp/servers/${comp.serverId}/tools`).catch(() => null);
    if (!data || !data.success) { box.innerHTML = '<span style="color:#f5222d;">无法获取工具列表</span>'; comp.mcpAllTools = null; return; }
    const tools = data.tools || [];
    // mcpAllTools 快照：toolNames 为 null（=全部）时，把该 server 当前工具名同步存入组件字段，
    // 供 collectToolsFromPorts（同步函数、无法 await）读取；server 工具变化时重新渲染会刷新快照
    if (comp.toolNames === null) comp.mcpAllTools = tools.map(t => t.name);
    else comp.mcpAllTools = null;
    const selected = comp.toolNames; // null = 全部
    box.innerHTML = tools.map(t => {
        const checked = selected === null ? 'checked' : (selected.includes(t.name) ? 'checked' : '');
        return `<label style="display:block;padding:3px 0;"><input type="checkbox" data-tool="${escapeHtml(t.name)}" ${checked}> ${escapeHtml(t.name)}</label>`;
    }).join('') || '<span style="color:#999;">该 server 没有可用工具</span>';
    box.querySelectorAll('input[data-tool]').forEach(cb => {
        cb.addEventListener('change', () => {
            const all = [...box.querySelectorAll('input[data-tool]')];
            if (all.every(x => x.checked)) { comp.toolNames = null; return; }
            comp.toolNames = all.filter(x => x.checked).map(x => x.dataset.tool);
        });
    });
}
// ============================================================
// LLM 组件（双 Tab：API 配置 + 对话）
// ============================================================
function renderLLMPanel(container, comp) {
    if (!comp.apiSettings) comp.apiSettings = { apiBase: '', apiKey: '', model: '', provider: '自定义' };
    if (!comp.messages) comp.messages = [];

    container.innerHTML = `
        <div class="llm-panel">
            <div class="llm-tabs">
                <button class="llm-tab active" data-tab="config">&#x2699; API 配置</button>
                <button class="llm-tab" data-tab="chat">&#x1F4AC; 对话</button>
            </div>
            <div class="llm-tab-body" id="llm-tab-config-${comp.id}"></div>
            <div class="llm-tab-body" id="llm-tab-chat-${comp.id}" style="display:none;"></div>
        </div>
    `;

    // --- Tab 切换 ---
    const tabs = container.querySelectorAll('.llm-tab');
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            tabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            const target = tab.dataset.tab;
            container.querySelector('#llm-tab-config-' + comp.id).style.display = target === 'config' ? '' : 'none';
            container.querySelector('#llm-tab-chat-' + comp.id).style.display = target === 'chat' ? '' : 'none';
        });
    });

    renderAPIConfigTab(container.querySelector('#llm-tab-config-' + comp.id), comp);
    renderChatTab(container.querySelector('#llm-tab-chat-' + comp.id), comp);
}

function renderAPIConfigTab(el, comp) {
    if (!comp.apiSettings) comp.apiSettings = { apiBase: '', apiKey: '', model: '', provider: '自定义' };
    if (!comp.apiSettings.maxToolRounds) comp.apiSettings.maxToolRounds = 50;

    const allProviders = getAllProviders();
    const providerOpts = allProviders
        .map(p => `<option value="${escapeHtml(p.name)}" ${comp.apiSettings.provider === p.name ? 'selected' : ''}>${escapeHtml(p.name)}</option>`)
        .join('');
    const curP = allProviders.find(p => p.name === comp.apiSettings.provider) || allProviders[allProviders.length - 1];
    const mlId = `ml-${comp.id}`;

    const savedResult = comp.apiSettings.verifyResult;
    const resultHtml = savedResult
        ? `<div class="api-verify-result ${savedResult.success ? 'success' : 'failure'} show" style="display:block;">${savedResult.html}</div>`
        : `<div class="api-verify-result" id="vr-${comp.id}"></div>`;

    const activeCfg = loadActiveLLMConfig();
    const isActive = activeCfg && activeCfg.apiBase === comp.apiSettings.apiBase && activeCfg.model === comp.apiSettings.model;

    el.innerHTML = `
        <div class="api-verify-panel">
            <div class="api-verify-field">
                <label>API 供应商</label>
                <div style="display:flex;gap:6px;">
                    <select class="api-verify-select" id="ap-${comp.id}" style="flex:1;">${providerOpts}</select>
                    <button class="module-btn secondary" id="btn-add-provider-${comp.id}" title="新增自定义接口" style="flex-shrink:0;padding:8px 12px;font-size:14px;">➕</button>
                </div>
            </div>
            <div class="api-verify-field">
                <label>API Base URL</label>
                <input class="api-verify-input" id="ab-${comp.id}" placeholder="https://api.openai.com/v1" value="${escapeHtml(comp.apiSettings.apiBase)}">
            </div>
            <div class="api-verify-field">
                <label>API Key</label>
                <div class="api-key-wrapper">
                    <input class="api-verify-input" id="ak-${comp.id}" type="password" placeholder="sk-..." value="${escapeHtml(comp.apiSettings.apiKey)}">
                    <button class="api-key-toggle" title="显示/隐藏">&#x1F441;</button>
                </div>
            </div>
            <div class="api-verify-field">
                <label>Model</label>
                <input class="api-verify-input" id="am-${comp.id}" placeholder="选择或输入模型" list="${mlId}" value="${escapeHtml(comp.apiSettings.model)}">
                <datalist id="${mlId}">${curP.models.map(m => `<option value="${escapeHtml(m)}"></option>`).join('')}</datalist>
            </div>
            <div class="api-verify-field">
                <label>最大工具调用轮数</label>
                <input class="api-verify-input" id="mr-${comp.id}" type="number" min="1" max="200" value="${comp.apiSettings.maxToolRounds}" style="width:80px;">
                <span style="font-size:10px;color:var(--text-muted);margin-left:6px;">LLM 调用工具的最大循环次数</span>
            </div>
            <div style="display:flex;gap:6px;">
                <button class="api-verify-btn" id="bv-${comp.id}" style="flex:1;">&#x1F50D; 测试连接</button>
                <button class="module-btn secondary" id="bsync-${comp.id}" title="将此配置同步到 AI 对话页面" style="flex:1;white-space:nowrap;">
                    ${isActive ? '&#x2705; 对话页已同步' : '&#x1F4E1; 同步到对话页'}
                </button>
            </div>
            ${resultHtml}
        </div>
    `;

    const prov = el.querySelector(`#ap-${comp.id}`);
    const base = el.querySelector(`#ab-${comp.id}`);
    const key = el.querySelector(`#ak-${comp.id}`);
    const model = el.querySelector(`#am-${comp.id}`);
    const maxRounds = el.querySelector(`#mr-${comp.id}`);
    const toggle = el.querySelector('.api-key-toggle');
    const dl = el.querySelector(`#${mlId}`);
    const syncBtn = el.querySelector(`#bsync-${comp.id}`);

    function saveActive() {
        // 收集当前连线中的工具名（TOOL_NAME_MAP 由后端 /api/meta/components 填充，单一来源）
        const connectedTools = [];
        STATE.connections.filter(c => c.sourceCompId === comp.id).forEach(c => {
            const tgt = STATE.components.find(x => x.id === c.targetCompId);
            if (!tgt) return;
            const tns = TOOL_NAME_MAP[tgt.type] || [];
            if (tns.length) connectedTools.push(...tns);
        });

        const cfg = {
            apiBase: comp.apiSettings.apiBase,
            apiKey: comp.apiSettings.apiKey,
            model: comp.apiSettings.model,
            provider: comp.apiSettings.provider,
            tool_names: connectedTools,
            savedAt: new Date().toISOString(),
        };
        safeStorage.set('active-llm-config', cfg);
        syncSettingsToBackend('llm_config', cfg);
    }

    // 新增自定义接口按钮
    const btnAddProv = el.querySelector(`#btn-add-provider-${comp.id}`);
    btnAddProv.addEventListener('click', () => {
        const name = prompt('接口名称（如 "硅基流动"）：');
        if (!name || !name.trim()) return;
        const url = prompt('API Base URL（如 https://api.siliconflow.cn/v1）：');
        if (!url || !url.trim()) return;
        const modelsStr = prompt('模型列表（逗号分隔，如 gpt-4o,claude-3-opus）：');
        const models = modelsStr ? modelsStr.split(',').map(s => s.trim()).filter(Boolean) : [];

        const custom = loadCustomProviders();
        // 避免重名
        const existing = [...PROVIDERS, ...custom].find(p => p.name === name.trim());
        if (existing) {
            showToast(`接口「${name.trim()}」已存在`, 'error');
            return;
        }
        custom.push({ name: name.trim(), url: url.trim(), models });
        saveCustomProviders(custom);

        // 重建下拉选项
        const all = getAllProviders();
        prov.innerHTML = all.map(p => `<option value="${escapeHtml(p.name)}">${escapeHtml(p.name)}</option>`).join('');
        prov.value = name.trim();
        comp.apiSettings.provider = name.trim();
        base.value = url.trim();
        comp.apiSettings.apiBase = url.trim();
        model.value = models[0] || '';
        comp.apiSettings.model = models[0] || '';
        dl.innerHTML = models.map(m => `<option value="${escapeHtml(m)}"></option>`).join('');
        saveActive();
        showToast(`✅ 已添加接口「${name.trim()}」`, 'success');
    });

    prov.addEventListener('change', () => {
        comp.apiSettings.provider = prov.value;
        const p = getAllProviders().find(x => x.name === prov.value);
        if (p && p.url) { base.value = p.url; comp.apiSettings.apiBase = p.url; }
        dl.innerHTML = (p ? p.models : []).map(m => `<option value="${escapeHtml(m)}"></option>`).join('');
        if (p && p.models.length > 0 && !p.models.includes(model.value)) {
            model.value = p.models[0]; comp.apiSettings.model = p.models[0];
        }
        saveActive();
        autoSaveConnections();
    });
    base.addEventListener('input', () => { comp.apiSettings.apiBase = base.value; saveActive(); autoSaveConnections(); });
    key.addEventListener('input', () => { comp.apiSettings.apiKey = key.value; saveActive(); autoSaveConnections(); });
    model.addEventListener('input', () => { comp.apiSettings.model = model.value; saveActive(); autoSaveConnections(); });
    maxRounds.addEventListener('input', () => { comp.apiSettings.maxToolRounds = parseInt(maxRounds.value) || 50; saveActive(); autoSaveConnections(); });
    toggle.addEventListener('click', () => {
        const isPw = key.type === 'password';
        key.type = isPw ? 'text' : 'password';
        toggle.textContent = isPw ? '\u{1F648}' : '\u{1F441}';
    });

    syncBtn.addEventListener('click', () => {
        saveActive();
        syncBtn.textContent = '✅ 已同步';
        syncBtn.classList.remove('secondary');
        syncBtn.style.background = '#52c41a';
        syncBtn.style.borderColor = '#52c41a';
        showToast('\u{1F4E1} API 配置已同步到 AI 对话页面', 'success');
        setTimeout(() => {
            syncBtn.textContent = '\u{1F4E1} 同步到对话页';
            syncBtn.classList.add('secondary');
            syncBtn.style.background = '';
            syncBtn.style.borderColor = '';
        }, 2000);
    });

    if (!comp.apiSettings._loaded) {
        fetch('/api/config').then(r => r.json()).then(config => {
            if (!comp.apiSettings.apiBase) { base.value = config.api_base || ''; comp.apiSettings.apiBase = config.api_base || ''; }
            if (!comp.apiSettings.apiKey) { key.value = config.has_api_key ? '****' : ''; comp.apiSettings.apiKey = config.has_api_key ? '****' : ''; }
            if (!comp.apiSettings.model) { model.value = config.model || ''; comp.apiSettings.model = config.model || ''; }
            comp.apiSettings._loaded = true;
            saveActive();
        }).catch(() => {});
    }

    const vBtn = el.querySelector(`#bv-${comp.id}`);
    const vRes = el.querySelector(`#vr-${comp.id}`) || el.querySelector('.api-verify-result');
    vBtn.addEventListener('click', async () => {
        vBtn.disabled = true; vBtn.textContent = '⏳ 测试中…';
        if (vRes) { vRes.className = 'api-verify-result'; vRes.style.display = 'none'; }
        try {
            const resp = await fetch('/api/verify', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ api_base: comp.apiSettings.apiBase || undefined, api_key: comp.apiSettings.apiKey || undefined, model: comp.apiSettings.model || undefined }),
            });
            const data = await resp.json();
            const resultHtml = data.success
                ? `<div style="font-weight:600;">✅ 连接成功</div><div style="margin-top:4px;">延迟: <strong>${data.latency_ms}ms</strong></div><div>模型: ${escapeHtml(data.model)}</div>`
                : `<div style="font-weight:600;">❌ 连接失败</div><div style="margin-top:4px;">${escapeHtml(data.error || '未知错误')}</div><div style="font-size:11px;color:var(--text-muted);margin-top:4px;">耗时: ${data.latency_ms}ms</div>`;
            comp.apiSettings.verifyResult = { success: data.success, html: resultHtml, at: new Date().toISOString() };
            if (vRes) {
                vRes.className = `api-verify-result ${data.success ? 'success' : 'failure'} show`;
                vRes.style.display = 'block';
                vRes.innerHTML = resultHtml;
            }
        } catch (e) {
            const errHtml = `<div style="font-weight:600;">❌ 请求失败</div><div style="margin-top:4px;">${escapeHtml(e.message)}</div>`;
            comp.apiSettings.verifyResult = { success: false, html: errHtml, at: new Date().toISOString() };
            if (vRes) {
                vRes.className = 'api-verify-result failure show';
                vRes.style.display = 'block';
                vRes.innerHTML = errHtml;
            }
        }
        vBtn.disabled = false; vBtn.textContent = '\u{1F50D} 测试连接';
    });
}

// ============================================================
// 读取活跃 LLM 配置
// ============================================================
function loadActiveLLMConfig() {
    try {
        const raw = safeStorage.getRaw('active-llm-config');
        return raw ? JSON.parse(raw) : null;
    } catch (e) { return null; }
}

// ============================================================
// 用户设置同步（多设备）：LLM 配置保存时同步到后端 /api/settings
// ============================================================
function syncSettingsToBackend(key, value) {
    // 避免明文 apiKey 落盘：浅拷贝后删除 apiKey 字段（多设备同步设计使然，但存储脱敏更安全）
    const v = { ...value };
    delete v.apiKey;
    fetch('/api/settings/' + encodeURIComponent(key), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value: v }),
    }).catch(() => {});
}

// 登录后拉取后端设置合并到 localStorage（后端优先：后端有的字段覆盖本地；后端脱敏未存的字段如 apiKey 保留本地）
async function pullSettingsFromBackend() {
    try {
        const resp = await fetch('/api/settings');
        if (!resp.ok) return;
        const data = await resp.json();
        if (data && data.success && data.settings && data.settings.llm_config) {
            const merged = { ...(loadActiveLLMConfig() || {}), ...data.settings.llm_config };
            safeStorage.set('active-llm-config', merged);
        }
    } catch (e) { /* 未登录/网络错误静默跳过 */ }
}

// ============================================================
// LLM 对话 Tab（使用共享 SSE 流解析）
// ============================================================
function renderChatTab(el, comp) {
    if (!comp.messages) comp.messages = [];

    const memComp = findConnectedMemory(comp.id);
    const hasMemory = !!memComp;

    el.innerHTML = `
        <div class="llm-mini-chat">
            <div class="llm-mini-msgs" id="lmm-${comp.id}">
                <div class="llm-mini-empty">${hasMemory ? '🧠 记忆已连接，发送消息开始对话' : '💬 发送消息（无记忆，每次独立对话）'}</div>
            </div>
            <div class="llm-mini-bar">
                <input class="llm-input" id="lmi-${comp.id}" placeholder="输入消息…" style="font-size:12px;">
                <button class="llm-send-btn" id="lmb-${comp.id}" style="font-size:12px;padding:6px 12px;">发送</button>
            </div>
        </div>
    `;

    // 自动从后端加载记忆（异步，不阻塞 UI）
    if (hasMemory) {
        loadMemoryFromBackend(comp).then(session => {
            if (session && session.messages) {
                // 刷新消息显示
                const msgsEl = el.querySelector(`#lmm-${comp.id}`);
                if (msgsEl) {
                    const empty = msgsEl.querySelector('.llm-mini-empty');
                    if (empty) empty.remove();
                    msgsEl.innerHTML = '';
                    session.messages.forEach(m => {
                        const b = document.createElement('div');
                        b.className = `chat-bubble ${m.role}`;
                        b.textContent = m.content;
                        msgsEl.appendChild(b);
                    });
                    msgsEl.scrollTop = msgsEl.scrollHeight;
                }
            }
        });
    }

    const msgs = el.querySelector(`#lmm-${comp.id}`);
    const input = el.querySelector(`#lmi-${comp.id}`);
    const btn = el.querySelector(`#lmb-${comp.id}`);

    // 如果有 Memory 连接，恢复历史消息
    if (hasMemory && memComp.messages.length > 0) {
        const empty = msgs.querySelector('.llm-mini-empty');
        if (empty) empty.remove();
        memComp.messages.forEach(m => {
            const b = document.createElement('div');
            b.className = `chat-bubble ${m.role}`;
            b.textContent = m.content;
            msgs.appendChild(b);
        });
    }

    const doSend = async () => {
        const text = input.value.trim();
        if (!text) return;
        input.value = '';

        const currentMem = findConnectedMemory(comp.id);  // 每次发送时重新查找（用户可能改了连线）
        const useMemory = !!currentMem;

        const empty = msgs.querySelector('.llm-mini-empty');
        if (empty) empty.remove();

        // 写入 Memory 或本地
        const userMsg = { role: 'user', content: text };
        if (useMemory) {
            currentMem.messages.push(userMsg);
        } else {
            comp.messages.push(userMsg);
        }

        const ub = document.createElement('div'); ub.className = 'chat-bubble user'; ub.textContent = text;
        msgs.appendChild(ub);

        const ab = document.createElement('div'); ab.className = 'chat-bubble assistant typing-cursor';
        msgs.appendChild(ab);
        msgs.scrollTop = msgs.scrollHeight;

        btn.disabled = true; input.disabled = true;

        // 发送新格式：布局 + 消息（编排在后端；buildChatPayload 已删，Task 4 前端发送瘦身）
        const payload = {
            layout: buildLayoutData(),      // 现有布局收集函数（serializeComponent 输出）
            comp_id: comp.id,
            message: text,
            llm_config: {
                apiBase: comp.apiSettings.apiBase,
                model: comp.apiSettings.model,
                maxToolRounds: comp.apiSettings.maxToolRounds,
            },
        };
        let full = '';

        try {
            const resp = await fetch('/api/chat', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });

            let contentAccum = '';
            const toolEvents = [];

            await readSSEStream(resp, {
                onData(delta) {
                    contentAccum += delta;
                    ab.textContent = contentAccum;
                    ab.classList.add('typing-cursor');
                    msgs.scrollTop = msgs.scrollHeight;
                },
                onToolCall(tc) {
                    toolEvents.push({ type: 'tool_call', ...tc });
                    ToolMonitor.logCall(tc.name, tc.arguments);
                },
                onToolResult(tr) {
                    toolEvents.push({ type: 'tool_result', ...tr });
                    ToolMonitor.logResult(tr.name, tr.result, false);
                },
                onError(error) {
                    contentAccum = '❌ ' + error;
                    ab.textContent = contentAccum;
                },
            });

            ab.classList.remove('typing-cursor');
            full = contentAccum || '（无回复）';
            const assistantMsg = { role: 'assistant', content: full.startsWith('❌ ') ? full.slice(2) : full, toolEvents: toolEvents.length > 0 ? toolEvents : undefined };

            // 重新查找（连线可能在对话中被改变）
            const finalMem = findConnectedMemory(comp.id);
            if (finalMem) {
                finalMem.messages.push(assistantMsg);
            } else {
                comp.messages.push(assistantMsg);
            }
        } catch (e) {
            ab.textContent = '❌ ' + e.message;
            ab.classList.remove('typing-cursor');
        }
        btn.disabled = false; input.disabled = false; input.focus();

        // 更新记忆面板
        updateMemoryPanelFromState();

        // 自动同步记忆到后端
        syncMemoryToBackend(comp);
    };

    btn.addEventListener('click', doSend);
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); doSend(); }
    });
}

// ── 从执行器收集工具名称 ──
function collectExecutorToolNames(execCompId) {
    const comp = STATE.components.find(c => c.id === execCompId);
    const count = comp ? (comp.execPortCount || 5) : 5;
    const names = [];

    for (let i = 1; i <= count; i++) {
        const portId = `exec-tool-${i}`;
        const conn = STATE.connections.find(
            c => c.sourceCompId === execCompId && c.sourcePortId === portId
        );
        if (conn) {
            const tgt = STATE.components.find(x => x.id === conn.targetCompId);
            if (tgt) {
                const toolNames = getComponentToolNames(tgt.type, tgt);
                toolNames.forEach(n => names.push(n));
            }
        }
    }

    return [...new Set(names)];
}

// ============================================================
// System Prompt 面板
// ============================================================
// ── 人设预设模板 ──
const PERSONA_PRESETS = [
    { name: '默认助手', icon: '🤖', content: '你是一个有帮助的AI助手。回答清晰、准确、简洁。' },
    { name: '编程专家', icon: '💻', content: '你是一名资深软件工程师。写代码时注重可读性、性能和边界情况。给出代码前先分析问题，代码附带注释。回答使用中文，代码和术语保留英文。' },
    { name: '语文老师', icon: '📚', content: '你是一名耐心的语文老师。回答问题时循循善诱，用通俗易懂的方式解释复杂概念。善于举例说明，鼓励学生思考。语气亲切温和。' },
    { name: '翻译官', icon: '🌐', content: '你是一名专业翻译。翻译准确、地道，保持原文风格和语气。对于专业术语给出注释。默认中英互译，也可根据需要翻译为其他语言。' },
    { name: '创意写手', icon: '✍️', content: '你是一名创意写手。文笔优美，善于用生动的语言描绘场景和情感。根据用户需求调整风格：正式公文、小说叙事、广告文案、社交媒体帖子等。' },
    { name: '数据分析师', icon: '📊', content: '你是一名数据分析师。面对数据问题时先理清分析目标，再选择合适的方法。输出包含数据解读、趋势分析和可操作建议。使用中文回复，保留专业术语的英文原名。' },
    { name: '产品经理', icon: '📱', content: '你是一名经验丰富的产品经理。思考问题从用户需求出发，善于拆解复杂需求为可执行的功能点。回复结构清晰、条理分明，用 PRD 思维组织内容。' },
    { name: '心理咨询师', icon: '🧘', content: '你是一名心理咨询师。倾听用户的问题，给予共情和支持。不急于给建议，先理解对方的感受。语气温暖、包容、不评判。' },
];

function renderSystemPromptPanel(container, comp) {
    if (!comp.prompts) comp.prompts = [];
    if (!comp.activePromptContent) comp.activePromptContent = null;
    container.className = 'module-panel';
    container.innerHTML = `
        <div style="padding:8px 12px;">
            <!-- 当前状态 -->
            <div style="font-size:12px;font-weight:600;color:var(--text-primary);margin-bottom:6px;">
                ${comp.activePromptContent ? '✅ 已激活人设' : '⚪ 未设置人设'}
            </div>
            ${comp.activePromptContent ? `<div style="font-size:10px;color:var(--text-muted);margin-bottom:8px;max-height:40px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(comp.activePromptContent.slice(0, 80))}</div>` : ''}

            <!-- 预设模板 -->
            <div style="font-size:11px;color:var(--text-secondary);margin-bottom:4px;">🎭 人设模板（点击即用）</div>
            <div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:10px;" id="persona-presets-${comp.id}">
                ${PERSONA_PRESETS.map(p => `
                    <button class="persona-preset-btn" data-name="${escapeHtml(p.name)}" data-content="${escapeHtml(p.content)}"
                        style="font-size:10px;padding:4px 8px;border:1px solid var(--border);border-radius:4px;background:var(--bg-input);color:var(--text);cursor:pointer;white-space:nowrap;"
                        title="${escapeHtml(p.content.slice(0, 60))}…">
                        ${p.icon} ${escapeHtml(p.name)}
                    </button>
                `).join('')}
            </div>

            <!-- 自定义编辑 -->
            <div style="font-size:11px;color:var(--text-secondary);margin-bottom:4px;">✏️ 自定义人设</div>
            <div class="module-field"><label>名称</label>
                <input class="module-input" id="spn-${comp.id}" placeholder="如：我的专属助手">
            </div>
            <div class="module-field"><label>内容</label>
                <textarea class="module-textarea" id="spc-${comp.id}" placeholder="描述 AI 的角色、说话风格、回答方式…" rows="3"></textarea>
            </div>
            <div style="display:flex;gap:6px;margin-bottom:10px;">
                <button class="module-btn" id="sps-${comp.id}">💾 保存并使用</button>
                <button class="module-btn secondary" id="spcl-${comp.id}">✕ 清空</button>
                ${comp.activePromptContent ? `<button class="module-btn danger" id="spclear-${comp.id}" style="font-size:11px;">❌ 取消人设</button>` : ''}
            </div>

            <!-- 已保存列表 -->
            <div style="font-size:11px;color:var(--text-secondary);margin-bottom:4px;">📁 已保存的人设</div>
            <div class="module-list" id="spl-${comp.id}" style="max-height:150px;overflow-y:auto;"></div>
        </div>
    `;

    const list = container.querySelector(`#spl-${comp.id}`);
    const nameInp = container.querySelector(`#spn-${comp.id}`);
    const contTa = container.querySelector(`#spc-${comp.id}`);

    function refreshList() {
        fetch('/api/system-prompt').then(r => r.json()).then(items => {
            comp.prompts = items;
            list.innerHTML = items.length === 0
                ? '<div style="font-size:10px;color:var(--text-muted);padding:6px;">暂无，保存后出现在这里</div>'
                : items.map(p => `
                    <div class="module-list-item ${comp.activePromptId === p.id ? 'active' : ''}" data-id="${p.id}">
                        <div style="flex:1;min-width:0;">
                            <div style="font-weight:600;font-size:11px;">${escapeHtml(p.name)}</div>
                            <div style="font-size:9px;color:var(--text-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(p.content_preview || '')}</div>
                        </div>
                        <button class="module-btn danger" style="padding:2px 6px;font-size:9px;" data-del="${p.id}">🗑</button>
                    </div>
                `).join('');

            list.querySelectorAll('.module-list-item').forEach(li => {
                li.addEventListener('click', (e) => {
                    if (e.target.closest('button')) return;
                    const pid = li.dataset.id;
                    comp.activePromptId = pid;
                    const p = comp.prompts.find(x => x.id === pid);
                    if (p) {
                        comp.activePromptContent = p.content;
                    }
                    renderSystemPromptPanel(container, comp);
                    autoSaveConnections();
                });
            });
            list.querySelectorAll('[data-del]').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    fetch(`/api/system-prompt/${btn.dataset.del}`, { method: 'DELETE' }).then(() => {
                        if (comp.activePromptId === btn.dataset.del) {
                            comp.activePromptId = null;
                            comp.activePromptContent = null;
                        }
                        renderSystemPromptPanel(container, comp);
                        autoSaveConnections();
                    });
                });
            });
        }).catch(() => {});
    }

    // 预设模板按钮
    container.querySelectorAll('.persona-preset-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const name = btn.dataset.name;
            const content = btn.dataset.content;
            fetch('/api/system-prompt', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, content }),
            }).then(r => r.json()).then(p => {
                if (p.error) { showToast(p.error, 'error'); return; }
                comp.activePromptId = p.id;
                comp.activePromptContent = p.content;
                renderSystemPromptPanel(container, comp);
                autoSaveConnections();
                showToast(`✅ 已激活人设：${name}`, 'success');
            });
        });
    });

    // 保存自定义
    container.querySelector(`#sps-${comp.id}`).addEventListener('click', () => {
        const name = nameInp.value.trim();
        const content = contTa.value.trim();
        if (!name || !content) { showToast('请填写名称和内容', 'error'); return; }
        fetch('/api/system-prompt', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, content }),
        }).then(r => r.json()).then(p => {
            if (p.error) { showToast(p.error, 'error'); return; }
            comp.activePromptId = p.id;
            comp.activePromptContent = p.content;
            renderSystemPromptPanel(container, comp);
            autoSaveConnections();
            showToast('✅ 人设已保存并激活', 'success');
        });
    });

    // 清空表单
    container.querySelector(`#spcl-${comp.id}`).addEventListener('click', () => {
        nameInp.value = ''; contTa.value = '';
    });

    // 取消人设
    const clearBtn = container.querySelector(`#spclear-${comp.id}`);
    if (clearBtn) {
        clearBtn.addEventListener('click', () => {
            comp.activePromptId = null;
            comp.activePromptContent = null;
            renderSystemPromptPanel(container, comp);
            autoSaveConnections();
            showToast('人设已取消', 'info');
        });
    }

    refreshList();
}

// ============================================================
// Function Calling 面板
// ============================================================
function renderFunctionCallingPanel(container, comp) {
    if (!comp.tools) comp.tools = [];
    container.className = 'module-panel';
    container.innerHTML = `
        <div class="module-field"><label>已注册的工具</label>
            <div class="module-list" id="fcl-${comp.id}"></div>
        </div>
        <div class="module-field"><label>工具名称</label>
            <input class="module-input" id="fcn-${comp.id}" placeholder="get_weather">
        </div>
        <div class="module-field"><label>描述</label>
            <input class="module-input" id="fcd-${comp.id}" placeholder="获取指定城市的天气">
        </div>
        <div class="module-field"><label>Parameters (JSON Schema)</label>
            <textarea class="module-textarea" id="fcp-${comp.id}" placeholder='{"type":"object","properties":{...}}' rows="4" style="font-size:10px;"></textarea>
        </div>
        <button class="module-btn" id="fcs-${comp.id}">\u{1F527} 注册工具</button>
    `;

    const list = container.querySelector(`#fcl-${comp.id}`);

    function refreshList() {
        fetch('/api/functions').then(r => r.json()).then(items => {
            comp.tools = items;
            list.innerHTML = items.length === 0
                ? '<div style="font-size:11px;color:var(--text-muted);padding:8px;">暂无注册工具</div>'
                : items.map(t => `
                    <div class="module-list-item">
                        <div style="flex:1;min-width:0;">
                            <div style="font-weight:600;font-size:12px;">${escapeHtml(t.name)}</div>
                            <div style="font-size:10px;color:var(--text-muted);">${escapeHtml(t.description)}</div>
                            <div style="font-size:9px;color:var(--text-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${escapeHtml(JSON.stringify(t.parameters).slice(0, 80))}</div>
                        </div>
                        <button class="module-btn danger" style="padding:3px 8px;font-size:10px;" data-del="${t.name}">删除</button>
                    </div>
                `).join('');
            list.querySelectorAll('[data-del]').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    fetch(`/api/functions/${btn.dataset.del}`, { method: 'DELETE' }).then(() => refreshList());
                });
            });
        }).catch(() => {});
    }

    container.querySelector(`#fcs-${comp.id}`).addEventListener('click', () => {
        const name = container.querySelector(`#fcn-${comp.id}`).value.trim();
        const desc = container.querySelector(`#fcd-${comp.id}`).value.trim();
        const paramStr = container.querySelector(`#fcp-${comp.id}`).value.trim();
        if (!name || !desc || !paramStr) return;
        let params;
        try { params = JSON.parse(paramStr); } catch (e) { showToast('Parameters 不是合法 JSON', 'error'); return; }
        fetch('/api/functions', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, description: desc, parameters: params }),
        }).then(r => r.json()).then(data => {
            if (data.error) { showToast(data.error, 'error'); return; }
            container.querySelector(`#fcn-${comp.id}`).value = '';
            container.querySelector(`#fcd-${comp.id}`).value = '';
            container.querySelector(`#fcp-${comp.id}`).value = '';
            refreshList();
        });
    });

    refreshList();
}

// ============================================================
// Vision 面板
// ============================================================
function renderVisionPanel(container, comp) {
    if (!comp.visionImage) comp.visionImage = null;
    container.className = 'module-panel';
    container.innerHTML = `
        <div class="vision-drop-zone" id="vdz-${comp.id}">
            ${comp.visionImage
                ? `<img class="vision-preview" src="${comp.visionImage}" alt="preview">`
                : '\u{1F4F7} 点击或拖放图片到此处'}
        </div>
        <input type="file" accept="image/*" id="vfu-${comp.id}" style="display:none;">
        <div class="module-field"><label>分析提示</label>
            <input class="module-input" id="vpt-${comp.id}" placeholder="请描述这张图片" value="${escapeHtml(comp.visionPrompt || '')}">
        </div>
        <button class="module-btn" id="vsv-${comp.id}">\u{1F50D} 分析图片</button>
        <div class="module-result" id="vrs-${comp.id}" style="display:none;"></div>
    `;

    const dropZone = container.querySelector(`#vdz-${comp.id}`);
    const fileInput = container.querySelector(`#vfu-${comp.id}`);
    const result = container.querySelector(`#vrs-${comp.id}`);

    dropZone.addEventListener('click', () => fileInput.click());
    dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('drag-over'); });
    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
    dropZone.addEventListener('drop', (e) => {
        e.preventDefault(); dropZone.classList.remove('drag-over');
        const file = e.dataTransfer.files[0];
        if (file) loadImage(file);
    });
    fileInput.addEventListener('change', () => {
        const file = fileInput.files[0];
        if (file) loadImage(file);
    });

    function loadImage(file) {
        const reader = new FileReader();
        reader.onload = () => {
            comp.visionImage = reader.result;
            dropZone.innerHTML = `<img class="vision-preview" src="${reader.result}" alt="preview"><div style="font-size:10px;color:var(--text-muted);margin-top:4px;">点击更换图片</div>`;
        };
        reader.readAsDataURL(file);
    }

    container.querySelector(`#vsv-${comp.id}`).addEventListener('click', async () => {
        if (!comp.visionImage) return;
        const prompt = container.querySelector(`#vpt-${comp.id}`).value.trim() || '请描述这张图片';
        comp.visionPrompt = prompt;

        result.style.display = 'block';
        result.innerHTML = '⏳ 分析中…';

        try {
            const resp = await fetch('/api/vision', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ image: comp.visionImage, prompt }),
            });
            const data = await resp.json();
            if (data.success) {
                result.innerHTML = `<div style="font-weight:600;">✅ 分析结果</div><div style="margin-top:6px;">${escapeHtml(data.content)}</div><div style="font-size:10px;color:var(--text-muted);margin-top:4px;">延迟: ${data.latency_ms}ms</div>`;
            } else {
                result.innerHTML = `<div style="font-weight:600;color:var(--danger);">❌ ${escapeHtml(data.error || '分析失败')}</div>`;
            }
        } catch (e) {
            result.innerHTML = `<div style="color:var(--danger);">请求失败: ${escapeHtml(e.message)}</div>`;
        }
    });
}

// ============================================================
// JSON Mode 面板（修复双重 JSON.parse）
// ============================================================
function renderJSONModePanel(container, comp) {
    if (!comp.jsonSchema) comp.jsonSchema = null;
    container.className = 'module-panel';
    container.innerHTML = `
        <div class="module-field"><label>JSON Schema</label>
            <textarea class="module-textarea" id="jms-${comp.id}" placeholder='{"type":"object","properties":{"name":{"type":"string"}},"required":["name"]}' rows="5" style="font-size:10px;">${comp.jsonSchema ? escapeHtml(JSON.stringify(comp.jsonSchema, null, 2)) : ''}</textarea>
        </div>
        <div class="module-field"><label>提示内容</label>
            <input class="module-input" id="jmp-${comp.id}" placeholder="请输入提示词…" value="${escapeHtml(comp.jsonPrompt || '')}">
        </div>
        <button class="module-btn" id="jmv-${comp.id}">\u{1F9EC} 生成结构化数据</button>
        <div class="module-result" id="jmr-${comp.id}" style="display:none;"></div>
    `;

    const result = container.querySelector(`#jmr-${comp.id}`);

    container.querySelector(`#jmv-${comp.id}`).addEventListener('click', async () => {
        const schemaStr = container.querySelector(`#jms-${comp.id}`).value.trim();
        const prompt = container.querySelector(`#jmp-${comp.id}`).value.trim();
        if (!schemaStr) return;

        let schema;
        try { schema = JSON.parse(schemaStr); } catch (e) { showToast('JSON Schema 格式错误', 'error'); return; }
        comp.jsonSchema = schema;
        comp.jsonPrompt = prompt;

        result.style.display = 'block';
        result.innerHTML = '⏳ 生成中…';

        try {
            const resp = await fetch('/api/json-mode', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    messages: [{ role: 'user', content: prompt || '请按指定格式返回数据' }],
                    json_schema: schema,
                }),
            });
            const data = await resp.json();
            if (data.success) {
                // 修复：优先使用服务端已解析的 parsed，避免客户端二次 JSON.parse 失败
                const output = data.parsed || (() => { try { return JSON.parse(data.content); } catch (e) { return data.content; } })();
                result.innerHTML = `<div style="font-weight:600;">✅ 生成成功</div><pre style="margin-top:6px;">${escapeHtml(JSON.stringify(output, null, 2))}</pre><div style="font-size:10px;color:var(--text-muted);margin-top:4px;">延迟: ${data.latency_ms}ms</div>`;
            } else {
                result.innerHTML = `<div style="font-weight:600;color:var(--danger);">❌ ${escapeHtml(data.error || '生成失败')}</div>`;
            }
        } catch (e) {
            result.innerHTML = `<div style="color:var(--danger);">请求失败: ${escapeHtml(e.message)}</div>`;
        }
    });
}

// ============================================================
// Embeddings 面板
// ============================================================
function renderEmbeddingsPanel(container, comp) {
    container.className = 'module-panel';
    container.innerHTML = `
        <div class="module-field"><label>输入文本</label>
            <textarea class="module-textarea" id="etx-${comp.id}" placeholder="输入要向量化的文本…" rows="4"></textarea>
        </div>
        <div class="module-field"><label>模型</label>
            <select class="module-select" id="emo-${comp.id}">
                <option value="text-embedding-3-small">text-embedding-3-small</option>
                <option value="text-embedding-3-large">text-embedding-3-large</option>
                <option value="text-embedding-ada-002">text-embedding-ada-002</option>
            </select>
        </div>
        <button class="module-btn" id="evs-${comp.id}">\u{1F9EE} 生成向量</button>
        <div class="module-result" id="ers-${comp.id}" style="display:none;"></div>
    `;

    const result = container.querySelector(`#ers-${comp.id}`);

    container.querySelector(`#evs-${comp.id}`).addEventListener('click', async () => {
        const text = container.querySelector(`#etx-${comp.id}`).value.trim();
        const model = container.querySelector(`#emo-${comp.id}`).value;
        if (!text) return;

        result.style.display = 'block';
        result.innerHTML = '⏳ 生成中…';

        try {
            const resp = await fetch('/api/embeddings', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text, model }),
            });
            const data = await resp.json();
            if (data.success) {
                result.innerHTML = `
                    <div style="font-weight:600;">✅ 向量生成成功</div>
                    <div style="margin-top:6px;">维度: <strong>${data.dimensions}</strong></div>
                    <div>Tokens: <strong>${data.tokens_used}</strong></div>
                    <pre style="margin-top:6px;font-size:10px;">[${data.embedding_preview.join(', ')}, &hellip;]</pre>
                    <div style="font-size:10px;color:var(--text-muted);margin-top:4px;">延迟: ${data.latency_ms}ms | 模型: ${data.model}</div>
                `;
            } else {
                result.innerHTML = `<div style="font-weight:600;color:var(--danger);">❌ ${escapeHtml(data.error || '生成失败')}</div>`;
            }
        } catch (e) {
            result.innerHTML = `<div style="color:var(--danger);">请求失败: ${escapeHtml(e.message)}</div>`;
        }
    });
}

// ============================================================
// Token Manager 面板
// ============================================================
function renderTokenManagerPanel(container, comp) {
    container.className = 'module-panel';
    container.innerHTML = `
        <div class="module-field"><label>输入文本</label>
            <textarea class="module-textarea" id="ttx-${comp.id}" placeholder="输入要统计 Token 的文本…" rows="4"></textarea>
        </div>
        <div class="module-field"><label>模型</label>
            <select class="module-select" id="tmo-${comp.id}">
                <option value="gpt-5">gpt-5 (128K)</option>
                <option value="gpt-5-mini">gpt-5-mini (128K)</option>
                <option value="deepseek-chat">deepseek-chat (64K)</option>
                <option value="glm-5">glm-5 (128K)</option>
                <option value="qwen-max">qwen-max (128K)</option>
            </select>
        </div>
        <button class="module-btn" id="tvs-${comp.id}">\u{1F3AF} 统计 Token</button>
        <div class="module-result" id="trs-${comp.id}" style="display:none;"></div>
        <div class="module-result" id="tif-${comp.id}" style="margin-top:6px;"></div>
    `;

    const result = container.querySelector(`#trs-${comp.id}`);
    const infoBox = container.querySelector(`#tif-${comp.id}`);

    fetch('/api/token-manager/info').then(r => r.json()).then(info => {
        infoBox.innerHTML = `
            <div style="font-weight:600;font-size:11px;margin-bottom:4px;">\u{1F4CB} 模型上下文限制</div>
            ${Object.entries(info).slice(0, 6).map(([k, v]) =>
                `<div style="font-size:10px;display:flex;justify-content:space-between;"><span>${escapeHtml(k)}</span><span style="font-weight:600;">${(v.max_tokens / 1000).toFixed(0)}K</span></div>`
            ).join('')}
        `;
    }).catch(() => {});

    container.querySelector(`#tvs-${comp.id}`).addEventListener('click', async () => {
        const text = container.querySelector(`#ttx-${comp.id}`).value;
        const model = container.querySelector(`#tmo-${comp.id}`).value;
        if (!text) return;

        result.style.display = 'block';
        result.innerHTML = '⏳ 统计中…';

        try {
            const resp = await fetch('/api/token-manager/count', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text, model }),
            });
            const data = await resp.json();
            result.innerHTML = `
                <div style="font-weight:600;">✅ 统计结果</div>
                <div style="margin-top:6px;font-size:18px;font-weight:700;color:var(--primary);">${data.tokens} <span style="font-size:12px;">Tokens</span></div>
                <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">${data.characters} 字符 | 方法: ${data.method} | 模型: ${data.model}</div>
            `;
        } catch (e) {
            result.innerHTML = `<div style="color:var(--danger);">请求失败: ${escapeHtml(e.message)}</div>`;
        }
    });
}

// ============================================================
// Sequential Executor 面板 — 工具顺序执行约束
// ============================================================
function renderSequentialExecutorPanel(container, comp) {
    if (!comp.orderedTools) comp.orderedTools = [];
    if (comp.strictMode === undefined) comp.strictMode = true;

    container.className = 'module-panel';
    container.innerHTML = `
        <div class="seq-panel">
            <div class="seq-header">
                <span class="seq-icon">🔗</span>
                <span class="seq-title">顺序执行器</span>
                <span class="seq-badge ${comp.strictMode ? 'strict' : 'loose'}">${comp.strictMode ? '严格模式' : '建议模式'}</span>
            </div>
            <div class="seq-desc">
                LLM 连线到此组件后，只能按下方工具列表的顺序依次调用。
            </div>
            <div class="seq-mode-row">
                <label class="seq-mode-label">
                    <input type="checkbox" id="seq-strict-${comp.id}" ${comp.strictMode ? 'checked' : ''}>
                    严格模式（禁止跳过/并行）
                </label>
            </div>
            <div class="seq-tools-section">
                <div class="seq-tools-header">
                    <span>📋 工具执行序列</span>
                    <span class="seq-tools-count">${comp.orderedTools.length} 个工具</span>
                </div>
                <div class="seq-tools-list" id="stl-${comp.id}">
                    ${comp.orderedTools.length === 0
                        ? '<div class="seq-empty">将工具连接到右侧的输出端口（步骤1-5）来定义执行顺序</div>'
                        : comp.orderedTools.map((t, i) => `
                            <div class="seq-tool-row">
                                <span class="seq-step-num">${i + 1}</span>
                                <span class="seq-tool-name">${escapeHtml(t.label || t.name)}</span>
                                <span class="seq-tool-name-tag">${escapeHtml(t.name)}</span>
                            </div>
                        `).join('')
                    }
                </div>
            </div>
            <div class="seq-preview" id="seq-preview-${comp.id}">
                ${comp.orderedTools.length > 0
                    ? `<div class="seq-preview-title">📝 将注入的 System Prompt 约束:</div>
                       <pre class="seq-preview-text">${comp.orderedTools.map((t,i) => `第${i+1}步: ${t.name}`).join('\n')}</pre>`
                    : ''
                }
            </div>
        </div>
    `;

    // 严格模式切换
    const strictCb = container.querySelector(`#seq-strict-${comp.id}`);
    if (strictCb) {
        strictCb.addEventListener('change', () => {
            comp.strictMode = strictCb.checked;
            autoSaveConnections();
            renderSequentialExecutorPanel(container, comp);
        });
    }
}

function updateSequentialTools(comp, container) {
    // 收集连接到各个输出端口的工具
    const stepPorts = ['seq-step-1', 'seq-step-2', 'seq-step-3', 'seq-step-4', 'seq-step-5'];
    const ordered = [];

    stepPorts.forEach(portId => {
        const conn = STATE.connections.find(
            c => c.sourceCompId === comp.id && c.sourcePortId === portId
        );
        if (conn) {
            const tgt = STATE.components.find(x => x.id === conn.targetCompId);
            if (tgt) {
                const def = COMPONENT_DEFS[tgt.type];
                // 获取该组件对应的工具名
                const toolNames = getComponentToolNames(tgt.type, tgt);
                toolNames.forEach(tn => {
                    ordered.push({ name: tn, label: def ? def.title : tgt.type, compId: tgt.id, portId: portId });
                });
            }
        }
    });

    comp.orderedTools = ordered;
}

function getComponentToolNames(type, comp) {
    if (type === 'mcp_external') return mcpExternalToolNames(comp);
    const map = {
        web_search: ['web_search'],
        calculator: ['calculator'],
        code_executor: ['code_executor'],
        text_tools: ['text_analyze', 'text_format'],
        time_query: ['get_current_time'],
        url_fetch: ['url_fetch'],
        file_ops: ['file_read', 'file_write', 'glob_search', 'grep_search', 'file_edit'],
        json_query: ['json_query'],
        vector_memory: ['embeddings_search', 'embeddings_index'],
        mcp_word: ['word_create', 'word_add_heading', 'word_add_paragraph', 'word_add_table', 'word_save'],
        mcp_excel: ['excel_create', 'excel_write_cell', 'excel_read_cell', 'excel_add_sheet', 'excel_save'],
        mcp_ppt: ['ppt_create', 'ppt_add_slide', 'ppt_add_text', 'ppt_add_bullet_list', 'ppt_save'],
    };
    return map[type] || [];
}

// ── 判断是否为工具类组件（只能通过执行器调用）──
function isToolComponent(type) {
    const toolTypes = [
        'web_search', 'calculator', 'code_executor', 'text_tools',
        'time_query', 'url_fetch', 'file_ops', 'json_query',
        'mcp_word', 'mcp_excel', 'mcp_ppt',
        'mcp_weather', 'mcp_database', 'mcp_git',
        'mcp_clipboard', 'mcp_encoding', 'mcp_system',
        'mcp_email', 'mcp_translate', 'mcp_calendar',
        'mcp_pdf', 'mcp_finance', 'mcp_geocode', 'mcp_navigation',
        'vector_memory',
    ];
    return toolTypes.includes(type);
}

// ── 判断是否为技能组件 ──
function isSkillComponent(type) {
    return type === 'skill_document' || type === 'skill_frontend' || type === 'skill_uiux'
        || type === 'skill_find' || type === 'skill_creator' || type === 'skill_super' || type === 'skill_pua';
}

// ── 验证连线是否合法 ──
function validateConnection(sourceComp, targetComp) {
    // 规则：LLM 不能直接连接工具组件，必须通过执行器
    if (sourceComp.type === 'llm' && isToolComponent(targetComp.type)) {
        const toolDef = COMPONENT_DEFS[targetComp.type];
        showToast(
            `⚠️ LLM 不能直接连接工具「${toolDef ? toolDef.title : targetComp.type}」。\n请先将执行器（Executor / Sequential）连到 LLM，再将工具连到执行器的端口。`,
            'error'
        );
        return false;
    }
    // 规则：技能组件只能连接到 Skills Manager
    if (isSkillComponent(sourceComp.type) && targetComp.type !== 'skills_manager') {
        const tgtDef = COMPONENT_DEFS[targetComp.type];
        showToast(
            `⚠️ 技能组件「${COMPONENT_DEFS[sourceComp.type]?.title}」只能连接到 Skills Manager。\n不能直接连到「${tgtDef ? tgtDef.title : targetComp.type}」。`,
            'error'
        );
        return false;
    }
    // 规则：技能组件只能连接到 Skills Manager
    if (isSkillComponent(targetComp.type) && sourceComp.type !== 'skills_manager') {
        showToast(
            `⚠️ 技能组件只能由 Skills Manager 驱动。请将「${COMPONENT_DEFS[sourceComp.type]?.title}」先连到 Skills Manager。`,
            'error'
        );
        return false;
    }
    // 规则：Skill Auto Call 只能连在 LLM 和 Skills Manager 之间
    if (sourceComp.type === 'skill_auto_call' && targetComp.type !== 'skills_manager') {
        showToast(
            `⚠️ Skill Auto Call 只能连接到 Skills Manager。\n请将 Auto Call 的输出端连到 Skills Manager 的输入端。`,
            'error'
        );
        return false;
    }
    if (targetComp.type === 'skill_auto_call' && sourceComp.type !== 'llm') {
        showToast(
            `⚠️ Skill Auto Call 只能由 LLM 驱动。\n请将 LLM 的输出端连到 Auto Call 的输入端。`,
            'error'
        );
        return false;
    }
    // 规则：知识库只能连接 Vector Memory（纯输出组件，不可被连接）
    if (sourceComp.type === 'knowledge_base' && targetComp.type !== 'vector_memory') {
        showToast('⚠️ 知识库只能连接到 Vector Memory。\n请将知识库的输出端连到向量记忆的输入端。', 'error');
        return false;
    }
    if (targetComp.type === 'knowledge_base') {
        showToast('⚠️ 知识库是数据导入组件，不能被连接。\n请将知识库的输出端连到 Vector Memory。', 'error');
        return false;
    }
    // 规则：Token 计数器只能连接 LLM
    if (sourceComp.type === 'token_counter' && targetComp.type !== 'llm') {
        showToast('⚠️ Token 计数器只能连接到 LLM。\n请将 LLM 的输出端连到计数器的输入端。', 'error');
        return false;
    }
    if (targetComp.type === 'token_counter' && sourceComp.type !== 'llm') {
        showToast('⚠️ Token 计数器只能由 LLM 驱动。\n请将 LLM 的输出端连到计数器的输入端。', 'error');
        return false;
    }
    // 规则：LLM 通过 Skill Auto Call 后不能再直连 Skills Manager
    if (sourceComp.type === 'llm' && targetComp.type === 'skills_manager') {
        const hasAutoCall = STATE.connections.some(c =>
            c.sourceCompId === sourceComp.id && c.targetPortId === 'skm-llm-in'
        );
        // 允许直连，但检查是否已有 auto_call 在路径中
    }
    // 规则：System Prompt 只能连接到 LLM
    if (sourceComp.type === 'system_prompt' && targetComp.type !== 'llm') {
        showToast(
            `⚠️ System Prompt 只能连接到 LLM。\n请将 System Prompt 的输出端连到 LLM 的输入端。`,
            'error'
        );
        return false;
    }
    if (targetComp.type === 'system_prompt' && sourceComp.type !== 'llm') {
        showToast(
            `⚠️ System Prompt 只能由 LLM 连接。\n请将 LLM 连到 System Prompt 的输入端。`,
            'error'
        );
        return false;
    }
    // 规则：记忆总结组件只能连接到记忆组件
    if (sourceComp.type === 'memory_summarizer' && targetComp.type !== 'memory') {
        showToast(
            `⚠️ 记忆总结组件只能连接到 Chat Memory 组件。\n请将总结组件的输出/输入端连到记忆组件的端口。`,
            'error'
        );
        return false;
    }
    if (targetComp.type === 'memory_summarizer' && sourceComp.type !== 'memory') {
        showToast(
            `⚠️ 记忆总结组件只能从 Chat Memory 组件接收输入。\n请将记忆组件的端口连到总结组件的输入端。`,
            'error'
        );
        return false;
    }
    return true;
}

// ============================================================
// Plan 面板 — 任务规划与分步执行
// ============================================================
// ── 查找连接到指定组件的 LLM ──
function findConnectedLLM(compId) {
    // Plan input port is 'plan-in', other components vary
    const hit = findConnTo(compId, 'plan-in') || findConnTo(compId, 'exec-llm-in');
    return (hit && hit.source && hit.source.type === 'llm') ? hit.source : null;
}

// ── 获取 Plan 使用的 API 配置 ──
function getPlanAPIConfig(comp) {
    const llm = findConnectedLLM(comp.id);
    return getLLMAPIConfig(llm ? llm.id : null);
}

function renderPlanPanel(container, comp) {
    if (!comp.currentPlan) comp.currentPlan = null;
    if (!comp.planHistory) comp.planHistory = [];

    container.className = 'module-panel';
    const plan = comp.currentPlan;
    const llmComp = findConnectedLLM(comp.id);

    if (plan) {
        const steps = plan.steps || [];
        const progress = plan.current_step || 0;
        const total = steps.length;
        const statusLabel = { created: '未开始', running: '执行中', completed: '已完成', failed: '失败' }[plan.status] || plan.status;

        container.innerHTML = `
            <div class="plan-panel">
                <div class="plan-header-bar">
                    <span class="plan-icon">📋</span>
                    <span class="plan-title">${escapeHtml(plan.title || '执行计划')}</span>
                    <span class="plan-status ${plan.status || 'created'}">${statusLabel}</span>
                </div>
                <div class="plan-progress-bar">
                    <div class="plan-progress-fill" style="width:${total > 0 ? (progress / total) * 100 : 0}%"></div>
                </div>
                <div class="plan-progress-text">${progress} / ${total} 步</div>
                <div class="plan-steps-list" id="psl-${comp.id}">
                    ${steps.map((s, i) => {
                        const stepResult = plan.step_results ? plan.step_results[String(i)] : null;
                        let stepClass = 'pending';
                        if (stepResult) stepClass = 'done';
                        else if (i === progress && plan.status === 'running') stepClass = 'running';
                        else if (i < progress) stepClass = 'done';

                        return `
                            <div class="plan-step ${stepClass}" id="ps-${comp.id}-${i}">
                                <div class="plan-step-num">${stepClass === 'done' ? '✅' : stepClass === 'running' ? '⏳' : i + 1}</div>
                                <div class="plan-step-content">
                                    <div class="plan-step-title">${escapeHtml(s.title || `步骤 ${i + 1}`)}</div>
                                    <div class="plan-step-desc">${escapeHtml(s.description || '')}</div>
                                    ${s.suggested_tools && s.suggested_tools.length > 0
                                        ? `<div class="plan-step-tools">🔧 ${s.suggested_tools.map(t => `<code>${escapeHtml(t)}</code>`).join(' ')}</div>`
                                        : ''}
                                    ${stepResult
                                        ? `<div class="plan-step-output">📝 ${escapeHtml((stepResult.output || '').slice(0, 200))}</div>`
                                        : ''}
                                </div>
                                ${stepClass === 'pending' && plan.status !== 'completed' && plan.status !== 'failed'
                                    ? `<button class="plan-step-btn" data-step="${i}">▶ 执行</button>`
                                    : ''}
                            </div>
                        `;
                    }).join('')}
                </div>
                <div class="plan-actions">
                    ${plan.status !== 'completed' && plan.status !== 'failed'
                        ? `<button class="module-btn" id="pa-exec-all-${comp.id}">▶ 全部执行</button>`
                        : ''}
                    ${plan.step_results && Object.keys(plan.step_results).length > 0
                        ? `<button class="module-btn" id="pa-reflect-${comp.id}" style="background:#722ed1;border-color:#722ed1;">🔄 反思 & 重规划</button>`
                        : ''}
                    <button class="module-btn secondary" id="pa-clear-${comp.id}">✕ 清除计划</button>
                </div>
                ${plan.reflection
                    ? `<div class="plan-reflection">
                        <div class="plan-reflection-title">🔄 反思结果</div>
                        <div class="plan-reflection-analysis">${escapeHtml(plan.reflection.analysis || '')}</div>
                        <div class="plan-reflection-completion">状态: ${escapeHtml(plan.reflection.completion || '')}</div>
                        ${plan.reflection.need_replan
                            ? `<div class="plan-reflection-replan">⚠️ 建议重规划${plan.reflection.new_plan_id ? ' — 新计划已生成' : ''}</div>`
                            : ''}
                        ${plan.reflection.suggestion
                            ? `<div class="plan-reflection-suggestion">💡 ${escapeHtml(plan.reflection.suggestion)}</div>`
                            : ''}
                    </div>`
                    : ''}
            </div>
        `;

        // 绑定单步执行
        container.querySelectorAll('.plan-step-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const stepIdx = parseInt(btn.dataset.step);
                await executePlanStep(comp, plan, stepIdx, container);
            });
        });

        // 绑定全部执行
        const execAllBtn = container.querySelector(`#pa-exec-all-${comp.id}`);
        if (execAllBtn) {
            execAllBtn.addEventListener('click', async () => {
                await executeAllPlanSteps(comp, plan, container);
            });
        }

        // 绑定清除
        container.querySelector(`#pa-clear-${comp.id}`).addEventListener('click', () => {
            comp.currentPlan = null;
            renderPlanPanel(container, comp);
        });

        // 绑定反思 & 重规划
        const reflectBtn = container.querySelector(`#pa-reflect-${comp.id}`);
        if (reflectBtn) {
            reflectBtn.addEventListener('click', async () => {
                await reflectOnPlan(comp, plan, container);
            });
        }
    } else {
        // 无计划时 — 从 LLM 对话获取任务
        const apiCfg = getPlanAPIConfig(comp);

        // 获取 LLM 对话
        let conversationPreview = '';
        let taskFromChat = '';
        let hasLLM = !!llmComp;

        if (llmComp) {
            const memComp = findConnectedMemory(llmComp.id);
            const messages = memComp ? memComp.messages : (llmComp.messages || []);
            const lastUserMsg = [...messages].reverse().find(m => m.role === 'user');
            if (lastUserMsg) {
                taskFromChat = lastUserMsg.content || '';
                conversationPreview = `<div class="plan-chat-preview">
                    <div class="plan-chat-label">💬 对话中的任务</div>
                    <div class="plan-chat-msg user">👤 ${escapeHtml(taskFromChat.slice(0, 200))}${taskFromChat.length > 200 ? '…' : ''}</div>
                </div>`;
            } else {
                conversationPreview = `<div class="plan-chat-preview">
                    <div class="plan-chat-label">💬 LLM 对话</div>
                    <div class="plan-chat-empty">暂无消息，请在 LLM 中发送任务</div>
                </div>`;
            }
        } else {
            conversationPreview = `<div class="plan-chat-preview">
                <div class="plan-chat-label">⚠️ 未连接 LLM</div>
                <div class="plan-chat-empty">请将 LLM 的输出端口连线到 Plan 的输入端口</div>
            </div>`;
        }

        container.innerHTML = `
            <div class="plan-panel">
                <div class="plan-header-bar">
                    <span class="plan-icon">📋</span>
                    <span class="plan-title">Agent 规划器</span>
                </div>
                <div class="plan-api-source">${hasLLM ? `🔌 API 来源: LLM #${llmComp.id} (${escapeHtml(llmComp.apiSettings?.model || '未配置')})` : '⚠️ 未连接 LLM'}</div>
                ${conversationPreview}
                <div class="module-field">
                    <label>最大步骤数</label>
                    <select class="module-select" id="pms-${comp.id}">
                        <option value="3">3 步</option>
                        <option value="5" selected>5 步</option>
                        <option value="7">7 步</option>
                        <option value="10">10 步</option>
                    </select>
                </div>
                <button class="module-btn" id="pg-${comp.id}" ${!taskFromChat ? 'disabled' : ''}>
                    📋 从对话生成计划
                </button>
                <div class="plan-desc" style="font-size:11px;color:var(--text-muted);">任务自动取自 LLM 对话中的最后一条用户消息</div>
                <div class="module-result" id="pr-${comp.id}" style="display:none;"></div>
            </div>
        `;

        // 绑定生成计划
        const genBtn = container.querySelector(`#pg-${comp.id}`);
        const resultDiv = container.querySelector(`#pr-${comp.id}`);

        genBtn.addEventListener('click', async () => {
            // 重新获取最新的任务（用户可能在对话中发送了新消息）
            let task = taskFromChat;
            if (llmComp) {
                const memComp = findConnectedMemory(llmComp.id);
                const messages = memComp ? memComp.messages : (llmComp.messages || []);
                const lastUserMsg = [...messages].reverse().find(m => m.role === 'user');
                if (lastUserMsg) task = lastUserMsg.content || '';
            }
            if (!task) { showToast('请先在 LLM 中发送任务消息', 'error'); return; }

            const maxSteps = parseInt(container.querySelector(`#pms-${comp.id}`).value);
            const apiParams = getPlanAPIConfig(comp);

            genBtn.disabled = true;
            genBtn.textContent = '⏳ 生成中…';
            resultDiv.style.display = 'block';
            resultDiv.innerHTML = '⏳ 正在调用 AI 生成计划…';

            try {
                ToolMonitor.logCall('plan_generate', { task: task.slice(0, 200), max_steps: maxSteps });
                const resp = await fetch('/api/plan/generate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ task, max_steps: maxSteps, ...apiParams }),
                });
                const data = await resp.json();
                if (data.success) {
                    ToolMonitor.logResult('plan_generate', `✅ ${data.plan.steps?.length || 0} 个步骤`, false);
                    comp.currentPlan = data.plan;
                    comp.planHistory.push({
                        plan_id: data.plan.plan_id,
                        title: data.plan.title,
                        task: task,
                        created_at: data.plan.created_at,
                    });
                    renderPlanPanel(container, comp);
                    showToast('✅ 计划已生成', 'success');
                } else {
                    ToolMonitor.logResult('plan_generate', data.error || '生成失败', true);
                    resultDiv.innerHTML = `<div style="color:var(--danger);">❌ ${escapeHtml(data.error || '生成失败')}</div>`;
                }
            } catch (e) {
                ToolMonitor.logResult('plan_generate', e.message, true);
                resultDiv.innerHTML = `<div style="color:var(--danger);">请求失败: ${escapeHtml(e.message)}</div>`;
            }
            genBtn.disabled = false;
            genBtn.textContent = '📋 从对话生成计划';
        });
    }
}

async function executePlanStep(comp, plan, stepIdx, container) {
    const stepEl = container.querySelector(`#ps-${comp.id}-${stepIdx}`);
    if (stepEl) {
        stepEl.classList.add('running');
        const btn = stepEl.querySelector('.plan-step-btn');
        if (btn) { btn.disabled = true; btn.textContent = '⏳'; }
    }

    const apiParams = getPlanAPIConfig(comp);

    try {
        ToolMonitor.logCall('plan_execute_step', { plan_id: plan.plan_id, step: stepIdx, title: plan.steps?.[stepIdx]?.title || '' });
        const resp = await fetch(`/api/plan/${plan.plan_id}/execute/${stepIdx}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(apiParams),
        });
        const data = await resp.json();
        if (data.success) {
            ToolMonitor.logResult('plan_execute_step', `✅ ${(data.result?.output || '').slice(0, 300)}`, false);
            comp.currentPlan = data.plan;
            renderPlanPanel(container, comp);
        } else {
            ToolMonitor.logResult('plan_execute_step', data.error || '执行失败', true);
            showToast(`步骤执行失败: ${data.error}`, 'error');
            if (stepEl) stepEl.classList.remove('running');
        }
    } catch (e) {
        ToolMonitor.logResult('plan_execute_step', e.message, true);
        showToast(`请求失败: ${e.message}`, 'error');
        if (stepEl) stepEl.classList.remove('running');
    }
}

async function executeAllPlanSteps(comp, plan, container) {
    const execAllBtn = container.querySelector(`#pa-exec-all-${comp.id}`);
    if (execAllBtn) { execAllBtn.disabled = true; execAllBtn.textContent = '⏳ 执行中…'; }

    const stepEls = container.querySelectorAll('.plan-step');
    stepEls.forEach(el => el.classList.add('running'));

    const apiParams = getPlanAPIConfig(comp);

    try {
        const resp = await fetch(`/api/plan/${plan.plan_id}/execute-all`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(apiParams),
        });

        await readSSEStream(resp, {
            onData(delta) {},
            onToolCall(tc) { ToolMonitor.logCall(tc.name, tc.arguments); },
            onToolResult(tr) { ToolMonitor.logResult(tr.name, tr.result, false); },
        });

        const planResp = await fetch(`/api/plan/${plan.plan_id}`);
        const planData = await planResp.json();
        if (planData.success) {
            comp.currentPlan = planData.plan;
        }
        renderPlanPanel(container, comp);
        showToast('✅ 计划执行完成', 'success');
    } catch (e) {
        showToast(`执行失败: ${e.message}`, 'error');
    }
}

async function reflectOnPlan(comp, plan, container) {
    const reflectBtn = container.querySelector(`#pa-reflect-${comp.id}`);
    if (reflectBtn) { reflectBtn.disabled = true; reflectBtn.textContent = '⏳ 反思中…'; }

    const apiParams = getPlanAPIConfig(comp);

    try {
        ToolMonitor.logCall('plan_reflect', { plan_id: plan.plan_id });
        const resp = await fetch(`/api/plan/${plan.plan_id}/reflect`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(apiParams),
        });
        const data = await resp.json();
        if (data.success) {
            ToolMonitor.logResult('plan_reflect', `${data.reflection.completion || ''}: ${(data.reflection.analysis || '').slice(0, 300)}`, false);
            comp.currentPlan = data.plan;
            renderPlanPanel(container, comp);
            if (data.reflection.need_replan && data.reflection.new_plan_id) {
                showToast('🔄 反思完成，已生成调整后的新计划', 'success');
            } else {
                showToast('✅ 反思完成: ' + (data.reflection.analysis || '').slice(0, 50), 'info');
            }
        } else {
            ToolMonitor.logResult('plan_reflect', data.error || '反思失败', true);
            showToast(`反思失败: ${data.error}`, 'error');
        }
    } catch (e) {
        ToolMonitor.logResult('plan_reflect', e.message, true);
        showToast(`请求失败: ${e.message}`, 'error');
    }
    if (reflectBtn) { reflectBtn.disabled = false; reflectBtn.textContent = '🔄 反思 & 重规划'; }
}

// ============================================================
// Loop 循环面板 — Plan ↔ Execute 循环控制
// ============================================================
function renderLoopPanel(container, comp) {
    if (!comp.loopStatus) comp.loopStatus = 'idle'; // idle | running | done
    if (!comp.loopIteration) comp.loopIteration = 0;
    if (!comp.loopMaxIterations) comp.loopMaxIterations = 30;
    if (!comp.loopLog) comp.loopLog = [];

    container.className = 'module-panel';

    // 查找连接的 Plan 和 Executor
    const planConn = STATE.connections.find(c => c.targetCompId === comp.id && c.targetPortId === 'loop-plan-in');
    const execConn = STATE.connections.find(c => c.sourceCompId === comp.id && c.targetPortId && c.targetPortId.startsWith('exec-plan-in'));

    let planInfo = '', execInfo = '';
    if (planConn) {
        const planComp = STATE.components.find(x => x.id === planConn.sourceCompId);
        planInfo = planComp ? `Plan #${planConn.sourceCompId}${planComp.currentPlan ? ' (有活跃计划)' : ''}` : 'Plan (已连接)';
    } else {
        planInfo = '⚠️ 未连接 Plan';
    }
    if (execConn) {
        const execComp = STATE.components.find(x => x.id === execConn.targetCompId);
        execInfo = execComp ? `Executor #${execConn.targetCompId}` : 'Executor (已连接)';
    } else {
        execInfo = '⚠️ 未连接 Executor';
    }

    const canStart = planConn && execConn && comp.loopStatus !== 'running';

    container.innerHTML = `
        <div class="loop-panel">
            <div class="loop-header">
                <span class="loop-icon">🔄</span>
                <span class="loop-title">循环控制器</span>
                <span class="loop-badge ${comp.loopStatus}">${
                    { idle: '待命', running: '运行中', done: '已完成' }[comp.loopStatus] || comp.loopStatus
                }</span>
            </div>
            <div class="loop-connections">
                <div class="loop-conn-row">📋 ${planInfo}</div>
                <div class="loop-conn-row">⚡ ${execInfo}</div>
            </div>
            <div class="loop-desc">Plan → Executor → Reflect → Replan 循环。Plan 决定继续或跳出。</div>

            <!-- 循环状态 -->
            <div class="loop-stats">
                <div class="loop-stat">
                    <span class="loop-stat-label">迭代</span>
                    <span class="loop-stat-value">${comp.loopIteration}</span>
                </div>
                <div class="loop-stat">
                    <span class="loop-stat-label">最大</span>
                    <input class="loop-iter-input" id="loop-max-${comp.id}" type="number" min="1" max="200" value="${comp.loopMaxIterations}" style="width:50px;text-align:center;font-size:16px;font-weight:700;border:1px solid var(--border-input);border-radius:4px;padding:2px;">
                </div>
            </div>

            <!-- 循环控制 -->
            <div class="loop-actions">
                <button class="module-btn" id="loop-start-${comp.id}" ${canStart ? '' : 'disabled'}>
                    ▶ 开始循环
                </button>
                <button class="module-btn secondary" id="loop-reset-${comp.id}" ${comp.loopStatus === 'running' ? 'disabled' : ''}>
                    ✕ 重置
                </button>
            </div>

            <!-- 循环日志 -->
            ${comp.loopLog.length > 0
                ? `<div class="loop-log">
                    <div class="loop-log-header">📜 循环日志</div>
                    ${comp.loopLog.slice(-5).map(entry => `
                        <div class="loop-log-entry ${entry.type}">
                            <span class="loop-log-icon">${entry.type === 'step' ? '▶' : entry.type === 'reflect' ? '🔄' : entry.type === 'break' ? '⏹' : 'ℹ'}</span>
                            <span class="loop-log-msg">${escapeHtml(entry.msg)}</span>
                        </div>
                    `).join('')}
                </div>`
                : ''}
        </div>
    `;

    // 最大迭代数输入
    const loopMaxInput = container.querySelector(`#loop-max-${comp.id}`);
    if (loopMaxInput) {
        loopMaxInput.addEventListener('input', () => {
            comp.loopMaxIterations = parseInt(loopMaxInput.value) || 30;
        });
    }

    // 绑定开始循环
    const startBtn = container.querySelector(`#loop-start-${comp.id}`);
    if (startBtn) {
        startBtn.addEventListener('click', () => startLoopCycle(comp, container));
    }

    // 绑定重置
    const resetBtn = container.querySelector(`#loop-reset-${comp.id}`);
    if (resetBtn) {
        resetBtn.addEventListener('click', () => {
            comp.loopStatus = 'idle';
            comp.loopIteration = 0;
            comp.loopLog = [];
            renderLoopPanel(container, comp);
        });
    }
}

async function startLoopCycle(comp, container) {
    // 查找连接的组件
    const planConn = STATE.connections.find(c => c.targetCompId === comp.id && c.targetPortId === 'loop-plan-in');
    const execOutConn = STATE.connections.find(c => c.sourceCompId === comp.id && c.sourcePortId === 'loop-exec-out');

    if (!planConn || !execOutConn) {
        showToast('请先连接 Plan 和 Executor', 'error');
        return;
    }

    const planComp = STATE.components.find(x => x.id === planConn.sourceCompId);
    const execComp = STATE.components.find(x => x.id === execOutConn.targetCompId);

    if (!planComp || !execComp) {
        showToast('Plan 或 Executor 组件未找到', 'error');
        return;
    }

    if (!planComp.currentPlan || !planComp.currentPlan.steps) {
        showToast('Plan 还没有生成计划', 'error');
        return;
    }

    comp.loopStatus = 'running';
    comp.loopIteration = 0;
    comp.loopLog = [{ type: 'info', msg: `循环开始 (最大 ${comp.loopMaxIterations} 次迭代)` }];
    renderLoopPanel(container, comp);

    // 获取 API 配置
    const apiParams = getPlanAPIConfig(planComp);
    const availableTools = collectExecutorToolNames(execComp.id);

    let currentPlan = planComp.currentPlan;

    while (comp.loopStatus === 'running' && comp.loopIteration < comp.loopMaxIterations) {
        comp.loopIteration++;
        comp.loopLog.push({ type: 'info', msg: `--- 第 ${comp.loopIteration} 次迭代 ---` });
        renderLoopPanel(container, comp);

        const steps = currentPlan.steps || [];
        let allStepResults = [];

        // 执行当前计划的所有步骤
        for (let i = 0; i < steps.length; i++) {
            const step = steps[i];
            comp.loopLog.push({ type: 'step', msg: `执行步骤: ${step.title || `步骤${i+1}`}` });
            renderLoopPanel(container, comp);

            const result = await executeSingleStep(execComp, {
                title: step.title || `步骤 ${i + 1}`,
                description: step.description || '',
            }, apiParams, availableTools, true);

            allStepResults.push(result);
            comp.loopLog.push({
                type: 'step',
                msg: `${result.success ? '✅' : '❌'} ${step.title}: ${(result.output || result.error || '').slice(0, 60)}`,
            });
            renderLoopPanel(container, comp);
            renderExecutorPanel(document.getElementById('props-content'), execComp);

            // 保存步骤结果到 Plan
            if (!currentPlan.step_results) currentPlan.step_results = {};
            currentPlan.step_results[String(i)] = result;
            currentPlan.current_step = i + 1;
        }

        currentPlan.status = 'completed';
        planComp.currentPlan = currentPlan;

        // 反思
        comp.loopLog.push({ type: 'reflect', msg: '执行完毕，进行反思…' });
        renderLoopPanel(container, comp);

        try {
            ToolMonitor.logCall('plan_reflect', { plan_id: currentPlan.plan_id });
            const reflectResp = await fetch(`/api/plan/${currentPlan.plan_id}/reflect`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(apiParams),
            });
            const reflectData = await reflectResp.json();

            if (reflectData.success) {
                planComp.currentPlan = reflectData.plan;
                const reflection = reflectData.reflection;
                ToolMonitor.logResult('plan_reflect', `${reflection.completion || ''}: ${(reflection.analysis || '').slice(0, 300)}`, false);
                comp.loopLog.push({
                    type: 'reflect',
                    msg: `反思: ${(reflection.analysis || '').slice(0, 60)} — ${reflection.completion || ''}`,
                });

                // Plan 决定：继续还是跳出？
                if (reflection.need_replan && reflection.adjusted_steps && reflection.adjusted_steps.length > 0) {
                    comp.loopLog.push({ type: 'info', msg: 'Plan 决定继续，加载调整后的计划…' });
                    if (reflection.new_plan_id) {
                        // 获取新计划
                        const newPlanResp = await fetch(`/api/plan/${reflection.new_plan_id}`);
                        const newPlanData = await newPlanResp.json();
                        if (newPlanData.success) {
                            currentPlan = newPlanData.plan;
                            planComp.currentPlan = currentPlan;
                        }
                    }
                    renderLoopPanel(container, comp);
                    continue; // 继续循环
                } else {
                    comp.loopLog.push({ type: 'break', msg: `循环结束: ${reflection.completion || 'Plan 判断任务完成'}` });
                    break; // 跳出循环
                }
            } else {
                ToolMonitor.logResult('plan_reflect', reflectData.error || '反思失败', true);
                comp.loopLog.push({ type: 'break', msg: `反思失败: ${reflectData.error}` });
                break;
            }
        } catch (e) {
            ToolMonitor.logResult('plan_reflect', e.message, true);
            comp.loopLog.push({ type: 'break', msg: `反思请求失败: ${e.message}` });
            break;
        }
    }

    if (comp.loopIteration >= comp.loopMaxIterations) {
        comp.loopLog.push({ type: 'break', msg: `达到最大迭代次数 (${comp.loopMaxIterations})` });
    }

    comp.loopStatus = 'done';
    renderLoopPanel(container, comp);
    showToast('🔄 循环执行完成', 'success');
}

// ============================================================
// Executor 执行器面板 — 单步执行
// ============================================================
// ── Skills Manager 面板（仿 Executor 风格）──
function renderSkillsManagerPanel(container, comp) {
    if (!comp.skmSkills) comp.skmSkills = [];
    if (!comp.skmStatus) comp.skmStatus = 'idle';

    container.className = 'module-panel';
    refreshSkillsManagerSkills(comp);

    const llmInConn = STATE.connections.find(
        c => c.targetCompId === comp.id && c.targetPortId === 'skm-llm-in'
    );

    const skills = comp.skmSkills || [];

    container.innerHTML = `
        <div class="exec-panel">
            <div class="exec-header">
                <span class="exec-icon">🧠</span>
                <span class="exec-title">Skills Manager</span>
                ${comp.skmStatus === 'active'
                    ? '<span class="exec-badge running">已激活</span>'
                    : '<span class="exec-badge idle">待命</span>'
                }
            </div>
            <div class="exec-desc" style="font-size:11px;color:var(--text-muted);padding:4px 0;">
                所有技能汇聚于此，合并 Prompt 后统一注入 LLM
            </div>

            ${llmInConn
                ? `<div class="exec-driver-info">🔌 驱动: LLM #${llmInConn.sourceCompId} -> 注入组合 System Prompt</div>`
                : `<div class="exec-driver-info" style="border-color:var(--warning);background:var(--warning-bg);color:var(--warning);">⚠️ 未连接 LLM — 将 LLM 输出连到「LLM 驱动」端口</div>`
            }

            <!-- 已连接技能 -->
            <div class="exec-tools-section">
                <div class="exec-tools-header">
                    <span>🎯 已连接技能</span>
                    <span class="exec-tools-count">${skills.length} 个</span>
                </div>
                <div class="exec-tools-list" id="skml-${comp.id}">
                    ${skills.length === 0
                        ? '<div class="exec-empty">将技能组件连接到左侧输入端口</div>'
                        : skills.map((s, i) => {
                            const tools = SKILL_PROMPT_CACHE[s.skillId + '_tools'] || [];
                            const comps = SKILL_PROMPT_CACHE[s.skillId + '_comps'] || [];
                            return `
                            <div class="exec-tool-row" style="flex-direction:column;align-items:flex-start;gap:2px;padding:8px 10px;">
                                <div style="display:flex;align-items:center;gap:6px;width:100%;">
                                    <span class="exec-tool-num">${i + 1}</span>
                                    <span class="exec-tool-label">${escapeHtml(s.label || s.name)}</span>
                                    <code class="exec-tool-name">${escapeHtml(s.skillId || '')}</code>
                                </div>
                                ${tools.length > 0 ? `<div style="font-size:10px;color:var(--text-muted);padding-left:22px;">🔧 ${tools.slice(0, 6).join(', ')}${tools.length > 6 ? ' +' + (tools.length - 6) + ' more' : ''}</div>` : ''}
                                ${comps.length > 0 ? `<div style="font-size:10px;color:#8b5cf6;padding-left:22px;">📦 需连接: ${comps.map(c => c.name).join('、')}</div>` : ''}
                            </div>`;
                        }).join('')
                    }
                </div>
                <button class="module-btn secondary" id="btn-add-skm-port-${comp.id}" style="width:100%;margin-top:8px;font-size:12px;">
                    ➕ 添加输入端口（当前 ${comp.skmPortCount || 5} 个）
                </button>
            </div>
        </div>
    `;

    const addPortBtn = container.querySelector(`#btn-add-skm-port-${comp.id}`);
    if (addPortBtn) {
        addPortBtn.addEventListener('click', () => {
            comp.skmPortCount = (comp.skmPortCount || 5) + 1;
            renderAll();
            selectComponent(comp.id);
            autoSaveConnections();
        });
    }
}

// ── 技能自动调用面板 ──
function renderSkillAutoCallPanel(container, comp) {
    if (comp.smartMode === undefined) comp.smartMode = true;
    if (comp.toolEnabled === undefined) comp.toolEnabled = true;
    container.className = 'module-panel';

    // 查找下游 skills_manager 获取已连接的技能列表
    const skmConn = findConnFrom(comp.id, 'auto-skm-out');
    let connectedSkills = [];
    if (skmConn && skmConn.target && skmConn.target.type === 'skills_manager') {
        refreshSkillsManagerSkills(skmConn.target);
        connectedSkills = skmConn.target.skmSkills || [];
    }

    container.innerHTML = `
        <div class="tool-toggle-row">
            <span class="tool-status-dot ${comp.toolEnabled ? 'on' : 'off'}"></span>
            <span style="font-size:12px;font-weight:600;">${comp.toolEnabled ? '已激活' : '已关闭'}</span>
            <button class="tool-toggle-btn ${comp.toolEnabled ? 'on' : 'off'}" id="actog-${comp.id}">${comp.toolEnabled ? '关闭' : '开启'}</button>
        </div>
        <div style="padding:8px 12px;">
            <div style="font-size:13px;font-weight:700;color:var(--text-primary);margin-bottom:4px;">🧠 技能自动调用</div>
            <div style="font-size:11px;color:var(--text-muted);line-height:1.5;margin-bottom:8px;">
                智能模式下 LLM 自主选择技能。LLM 会收到可用技能列表作为工具，按需调用而非全部注入 Prompt。
            </div>

            <!-- 智能模式开关 -->
            <div style="display:flex;align-items:center;justify-content:space-between;padding:8px 10px;background:var(--bg-input);border-radius:6px;margin-bottom:8px;">
                <div>
                    <div style="font-size:11px;font-weight:600;color:var(--text-primary);">🤖 智能模式</div>
                    <div style="font-size:9px;color:var(--text-muted);">LLM 自行判断何时调用哪个技能</div>
                </div>
                <button id="smart-tog-${comp.id}" class="tool-toggle-btn ${comp.smartMode ? 'on' : 'off'}" style="font-size:11px;padding:3px 10px;">
                    ${comp.smartMode ? '✅ 开启' : '⏸ 关闭'}
                </button>
            </div>

            <!-- 已连接技能列表 -->
            <div style="font-size:10px;color:var(--text-secondary);margin-bottom:4px;">
                📋 可用技能 (${connectedSkills.length})
            </div>
            <div style="display:flex;flex-wrap:wrap;gap:3px;margin-bottom:6px;">
                ${connectedSkills.length === 0
                    ? '<span style="font-size:9px;color:var(--text-muted);">未连接技能 — 请将 Skills Manager 连接到输出端口</span>'
                    : connectedSkills.map(s => {
                        const tools = SKILL_PROMPT_CACHE[s.skillId + '_tools'] || [];
                        return `<span style="background:#f3f0ff;border:1px solid #d3c5f5;padding:2px 6px;border-radius:3px;font-size:9px;color:#722ed1;" title="🔧 ${tools.slice(0, 6).join(', ')}">${escapeHtml(s.label || s.name)}</span>`;
                    }).join('')
                }
            </div>

            <div style="font-size:9px;color:var(--primary);margin-top:8px;">
                ${comp.smartMode
                    ? '💡 智能模式：LLM 拥有 <code style="font-size:9px;">use_skill</code> 工具，可自主选择技能'
                    : '💡 普通模式：所有技能 Prompt 自动注入（同 Skills Manager 直连）'}
            </div>
        </div>
    `;

    // 智能模式切换
    const smartTog = container.querySelector(`#smart-tog-${comp.id}`);
    if (smartTog) {
        smartTog.addEventListener('click', () => {
            comp.smartMode = !comp.smartMode;
            smartTog.textContent = comp.smartMode ? '✅ 开启' : '⏸ 关闭';
            smartTog.className = `tool-toggle-btn ${comp.smartMode ? 'on' : 'off'}`;
            autoSaveConnections();
        });
    }

    // 开关切换
    const togBtn = container.querySelector(`#actog-${comp.id}`);
    if (togBtn) {
        const dot = container.querySelector('.tool-status-dot');
        togBtn.addEventListener('click', () => {
            comp.toolEnabled = !comp.toolEnabled;
            togBtn.textContent = comp.toolEnabled ? '关闭' : '开启';
            togBtn.className = `tool-toggle-btn ${comp.toolEnabled ? 'on' : 'off'}`;
            dot.className = `tool-status-dot ${comp.toolEnabled ? 'on' : 'off'}`;
            autoSaveConnections();
        });
    }
}

function refreshSkillsManagerSkills(comp) {
    // 组件类型 → 技能 API ID 映射（必须与 LLM 组件中的 skillIdMap 一致）
    const SKILL_TYPE_TO_ID = {
        skill_document: 'document',
        skill_frontend: 'frontend-design',
        skill_uiux: 'ui-ux-pro-max',
        skill_find: 'find-skills',
        skill_creator: 'skill-creator',
        skill_super: 'superpowers',
        skill_pua: 'pua',
    };

    const count = comp.skmPortCount || 5;
    const skills = [];

    for (let i = 1; i <= count; i++) {
        const portId = `skm-skill-${i}`;
        const conn = STATE.connections.find(
            c => c.sourceCompId === comp.id && c.sourcePortId === portId
        );
        if (conn) {
            const tgt = STATE.components.find(x => x.id === conn.targetCompId);
            if (tgt && isSkillComponent(tgt.type)) {
                const def = COMPONENT_DEFS[tgt.type];
                const skillId = SKILL_TYPE_TO_ID[tgt.type] || tgt.type.replace('skill_', '');
                skills.push({
                    name: def ? def.title : tgt.type,
                    label: def ? def.title : tgt.type,
                    skillId: skillId,
                    compId: tgt.id,
                    portId,
                });
            }
        }
    }

    comp.skmSkills = skills;
    comp.skmStatus = skills.length > 0 ? 'active' : 'idle';
}

function renderExecutorPanel(container, comp) {
    if (!comp.execLastResult) comp.execLastResult = null;
    if (!comp.execRunning) comp.execRunning = false;

    container.className = 'module-panel';

    // 刷新工具列表
    refreshExecutorTools(comp);

    const llmConn = STATE.connections.find(c => c.targetCompId === comp.id && c.targetPortId === 'exec-llm-in');
    const planConn = STATE.connections.find(c => c.targetCompId === comp.id && c.targetPortId === 'exec-plan-in');
    const loopConn = STATE.connections.find(c => c.targetCompId === comp.id && c.targetPortId === 'exec-plan-in');

    let driverInfo = '';
    if (loopConn) {
        const srcComp = STATE.components.find(x => x.id === loopConn.sourceCompId);
        if (srcComp && srcComp.type === 'loop') {
            driverInfo = '🔄 驱动: Loop 循环控制';
        } else if (srcComp && srcComp.type === 'plan') {
            driverInfo = `📋 驱动: Plan #${loopConn.sourceCompId}`;
        } else {
            driverInfo = '📋 驱动: Plan/Loop';
        }
    } else if (llmConn) {
        driverInfo = `🔌 驱动: LLM #${llmConn.sourceCompId} → 告知可用工具`;
    } else {
        driverInfo = '⚠️ 未连接驱动源';
    }

    const tools = comp.execTools || [];
    const lastResult = comp.execLastResult;

    container.innerHTML = `
        <div class="exec-panel">
            <div class="exec-header">
                <span class="exec-icon">⚡</span>
                <span class="exec-title">执行器</span>
                ${comp.execRunning
                    ? '<span class="exec-badge running">执行中</span>'
                    : '<span class="exec-badge idle">待命</span>'
                }
            </div>
            <div class="exec-driver-info">${driverInfo}</div>

            <!-- 可用工具 -->
            <div class="exec-tools-section">
                <div class="exec-tools-header">
                    <span>🔧 可用工具</span>
                    <span class="exec-tools-count">${tools.length} 个</span>
                </div>
                <div class="exec-tools-list" id="etl-${comp.id}">
                    ${tools.length === 0
                        ? '<div class="exec-empty">将工具连接到右侧输出端口</div>'
                        : tools.map((t, i) => `
                            <div class="exec-tool-row">
                                <span class="exec-tool-num">${i + 1}</span>
                                <span class="exec-tool-label">${escapeHtml(t.label || t.name)}</span>
                                <code class="exec-tool-name">${escapeHtml(t.name)}</code>
                            </div>
                        `).join('')
                    }
                </div>
                <button class="module-btn secondary" id="btn-add-port-${comp.id}" style="width:100%;margin-top:8px;font-size:12px;">➕ 添加连接端口（当前 ${comp.execPortCount || 5} 个）</button>
            </div>

            <!-- 当前/上一步执行结果 -->
            ${lastResult
                ? `<div class="exec-result">
                    <div class="exec-result-header">📝 执行结果</div>
                    <div class="exec-result-step">${escapeHtml(lastResult.title || '')}</div>
                    ${lastResult.success
                        ? `<div class="exec-result-output">${escapeHtml((lastResult.output || '').slice(0, 300))}</div>`
                        : `<div class="exec-result-error">❌ ${escapeHtml(lastResult.error || '')}</div>`
                    }
                    ${lastResult.llm_decision && lastResult.llm_decision.tool_calls
                        ? `<div class="exec-result-llm">🧠 LLM 决定调用: ${lastResult.llm_decision.tool_calls.map(tc => escapeHtml(tc.tool)).join(' → ')}</div>`
                        : ''}
                </div>`
                : `<div class="exec-empty">等待执行指令…</div>`
            }
        </div>
    `;

    // 添加端口按钮
    const addPortBtn = container.querySelector(`#btn-add-port-${comp.id}`);
    if (addPortBtn) {
        addPortBtn.addEventListener('click', () => {
            comp.execPortCount = (comp.execPortCount || 5) + 1;
            renderAll();
            selectComponent(comp.id);
            autoSaveConnections();
        });
    }
}

function refreshExecutorTools(comp) {
    const count = comp.execPortCount || 5;
    const tools = [];

    for (let i = 1; i <= count; i++) {
        const portId = `exec-tool-${i}`;
        const conn = STATE.connections.find(
            c => c.sourceCompId === comp.id && c.sourcePortId === portId
        );
        if (conn) {
            const tgt = STATE.components.find(x => x.id === conn.targetCompId);
            if (tgt) {
                const def = COMPONENT_DEFS[tgt.type];
                const toolNames = getComponentToolNames(tgt.type, tgt);
                toolNames.forEach(tn => {
                    tools.push({ name: tn, label: def ? def.title : tgt.type, compId: tgt.id, portId });
                });
            }
        }
    }

    comp.execTools = tools;
}

// ── 执行单个步骤（由 Loop 或外部调用）──
async function executeSingleStep(comp, step, apiParams, availableTools, needsLLMDecision) {
    comp.execRunning = true;
    comp.execLastResult = null;

    try {
        let result;
        if (needsLLMDecision && availableTools.length > 0) {
            ToolMonitor.logCall('executor_decide', { title: step.title, description: (step.description || '').slice(0, 200) });
            const resp = await fetch('/api/executor/decide-and-execute', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    step: { title: step.title, description: step.description },
                    tools: availableTools,
                    ...apiParams,
                }),
            });
            const data = await resp.json();
            if (data.success) {
                ToolMonitor.logResult('executor_decide', (data.summary || '完成').slice(0, 500), false);
                result = {
                    title: step.title,
                    success: true,
                    output: data.summary || '完成',
                    tool_results: data.tool_results || [],
                    llm_decision: data.llm_decision,
                };
            } else {
                ToolMonitor.logResult('executor_decide', data.error || '执行失败', true);
                result = { title: step.title, success: false, error: data.error || '执行失败' };
            }
        } else if (step.tool) {
            ToolMonitor.logCall('executor_run', { title: step.title, tool: step.tool, args: step.args });
            const resp = await fetch('/api/executor/run-simple', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ steps: [step] }),
            });
            const data = await resp.json();
            if (data.success && data.results && data.results[0]) {
                ToolMonitor.logResult('executor_run', (data.results[0].output || data.results[0].error || '').slice(0, 500), !data.results[0].success);
                result = data.results[0];
            } else {
                ToolMonitor.logResult('executor_run', data.error || '执行失败', true);
                result = { title: step.title, success: false, error: data.error || '执行失败' };
            }
        } else {
            result = { title: step.title, success: false, error: '无可用工具' };
        }

        comp.execLastResult = result;
        return result;
    } catch (e) {
        ToolMonitor.logResult('executor', e.message, true);
        comp.execLastResult = { title: step.title, success: false, error: e.message };
        return comp.execLastResult;
    } finally {
        comp.execRunning = false;
    }
}

// ============================================================
// Agent 编排器面板 — Plan → Execute → Reflect 主循环中枢
// ============================================================
function renderAgentPanel(container, comp) {
    if (!comp.agentStatus) comp.agentStatus = 'idle'; // idle | planning | executing | reflecting | done
    if (!comp.agentIteration) comp.agentIteration = 0;
    if (!comp.agentMaxIterations) comp.agentMaxIterations = 30;
    if (!comp.agentLog) comp.agentLog = [];
    if (!comp.agentTask) comp.agentTask = '';

    container.className = 'module-panel';

    // 查找连接的 LLM 组件获取任务
    const llmConn = STATE.connections.find(c => c.targetCompId === comp.id && c.targetPortId === 'agent-llm-in');
    const llmComp = llmConn ? STATE.components.find(x => x.id === llmConn.sourceCompId) : null;

    // 从 LLM 对话获取最后一条用户消息作为任务
    let taskFromChat = comp.agentTask || '';
    if (llmComp && !taskFromChat) {
        const memComp = findConnectedMemory(llmComp.id);
        const messages = memComp ? memComp.messages : (llmComp.messages || []);
        const lastUserMsg = [...messages].reverse().find(m => m.role === 'user');
        if (lastUserMsg) taskFromChat = lastUserMsg.content || '';
    }

    // 收集连接的工具
    const toolPorts = ['agent-tool-1', 'agent-tool-2', 'agent-tool-3', 'agent-tool-4', 'agent-tool-5'];
    const connectedTools = [];
    toolPorts.forEach(portId => {
        const conn = STATE.connections.find(c => c.sourceCompId === comp.id && c.sourcePortId === portId);
        if (conn) {
            const tgt = STATE.components.find(x => x.id === conn.targetCompId);
            if (tgt) {
                const names = getComponentToolNames(tgt.type, tgt);
                names.forEach(n => connectedTools.push(n));
            }
        }
    });

    const canStart = llmConn && connectedTools.length > 0 && comp.agentStatus !== 'running';
    const statusLabels = { idle: '待命', planning: '规划中', executing: '执行中', reflecting: '反思中', done: '已完成' };

    container.innerHTML = `
        <div class="agent-panel">
            <div class="agent-header">
                <span class="agent-icon">🤖</span>
                <span class="agent-title">Agent 编排器</span>
                <span class="agent-badge ${comp.agentStatus}">${statusLabels[comp.agentStatus] || comp.agentStatus}</span>
            </div>
            <div class="agent-desc">Plan → Execute → Reflect 自动循环</div>

            <div class="agent-connections">
                <div class="agent-conn-row">🧠 ${llmConn ? `LLM #${llmConn.sourceCompId}` : '⚠️ 未连接 LLM'}</div>
                <div class="agent-conn-row">🔧 ${connectedTools.length} 个工具已连接</div>
            </div>

            ${taskFromChat ? `<div class="agent-task-preview">
                <div class="agent-task-label">📋 任务</div>
                <div class="agent-task-text">${escapeHtml(taskFromChat.slice(0, 150))}${taskFromChat.length > 150 ? '…' : ''}</div>
            </div>` : `<div class="agent-task-empty">💡 在 LLM 对话中发送任务后自动获取</div>`}

            <div class="agent-stats">
                <div class="agent-stat">
                    <span class="agent-stat-label">迭代</span>
                    <span class="agent-stat-value">${comp.agentIteration}</span>
                </div>
                <div class="agent-stat">
                    <span class="agent-stat-label">最大</span>
                    <input class="agent-iter-input" id="agent-max-${comp.id}" type="number" min="1" max="200" value="${comp.agentMaxIterations}" style="width:50px;text-align:center;font-size:16px;font-weight:700;border:1px solid var(--border-input);border-radius:4px;padding:2px;">
                </div>
                <div class="agent-stat">
                    <span class="agent-stat-label">工具</span>
                    <span class="agent-stat-value">${connectedTools.length}</span>
                </div>
            </div>

            <div class="agent-actions">
                <button class="module-btn agent-run-btn" id="agent-start-${comp.id}" ${canStart ? '' : 'disabled'}>
                    ▶ 启动 Agent
                </button>
                <button class="module-btn secondary" id="agent-reset-${comp.id}">
                    ✕ 重置
                </button>
            </div>

            ${comp.agentLog.length > 0 ? `
                <div class="agent-log">
                    <div class="agent-log-header">📜 执行日志</div>
                    ${comp.agentLog.slice(-8).map(entry => `
                        <div class="agent-log-entry ${entry.type || 'info'}">
                            <span class="agent-log-icon">${entry.type === 'plan' ? '📋' : entry.type === 'execute' ? '⚡' : entry.type === 'reflect' ? '🔄' : entry.type === 'complete' ? '✅' : entry.type === 'error' ? '❌' : 'ℹ️'}</span>
                            <span class="agent-log-msg">${escapeHtml(entry.msg)}</span>
                        </div>
                    `).join('')}
                </div>
            ` : ''}
        </div>
    `;

    // 最大迭代数输入
    const maxIterInput = container.querySelector(`#agent-max-${comp.id}`);
    if (maxIterInput) {
        maxIterInput.addEventListener('input', () => {
            comp.agentMaxIterations = parseInt(maxIterInput.value) || 30;
        });
    }

    // 启动 Agent
    const startBtn = container.querySelector(`#agent-start-${comp.id}`);
    if (startBtn) {
        startBtn.addEventListener('click', () => startAgentCycle(comp, container, llmComp, connectedTools, taskFromChat));
    }

    // 重置
    const resetBtn = container.querySelector(`#agent-reset-${comp.id}`);
    if (resetBtn) {
        resetBtn.addEventListener('click', () => {
            comp.agentStatus = 'idle';
            comp.agentIteration = 0;
            comp.agentLog = [];
            renderAgentPanel(container, comp);
        });
    }
}

async function startAgentCycle(comp, container, llmComp, tools, task) {
    if (!task) {
        showToast('请先在 LLM 对话中发送任务消息', 'error');
        return;
    }

    comp.agentStatus = 'running';
    comp.agentIteration = 0;
    comp.agentLog = [{ type: 'info', msg: `Agent 启动 — 任务: ${task.slice(0, 80)}` }];
    renderAgentPanel(container, comp);

    const apiCfg = getLLMAPIConfig(llmComp ? llmComp.id : null);
    const maxIter = comp.agentMaxIterations || 30;

    // Phase 1: 规划
    comp.agentLog.push({ type: 'plan', msg: '🧠 正在分析任务并制定计划…' });
    renderAgentPanel(container, comp);

    let currentPlan = null;
    try {
        ToolMonitor.logCall('plan_generate', { task: task.slice(0, 200), max_steps: 5 });
        const planResp = await fetch('/api/plan/generate', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ task, max_steps: 5, ...apiCfg }),
        });
        const planData = await planResp.json();
        if (planData.success) {
            ToolMonitor.logResult('plan_generate', `✅ ${planData.plan.steps?.length || 0} 个步骤`, false);
            currentPlan = planData.plan;
            comp.agentLog.push({ type: 'plan', msg: `✅ 计划已生成: ${currentPlan.steps?.length || 0} 个步骤` });
            currentPlan.steps?.forEach((s, i) => {
                comp.agentLog.push({ type: 'plan', msg: `  步骤${i+1}: ${s.title || '未命名'}` });
            });
        } else {
            ToolMonitor.logResult('plan_generate', planData.error || '生成失败', true);
            comp.agentLog.push({ type: 'error', msg: `规划失败: ${planData.error}` });
            comp.agentStatus = 'done';
            renderAgentPanel(container, comp);
            return;
        }
    } catch (e) {
        ToolMonitor.logResult('plan_generate', e.message, true);
        comp.agentLog.push({ type: 'error', msg: `规划请求失败: ${e.message}` });
        comp.agentStatus = 'done';
        renderAgentPanel(container, comp);
        return;
    }

    // Phase 2: 执行 + 反思循环
    let steps = currentPlan.steps || [];
    let allResults = {};

    while (comp.agentIteration < maxIter) {
        comp.agentIteration++;
        comp.agentLog.push({ type: 'info', msg: `--- 第 ${comp.agentIteration} 次迭代 ---` });
        renderAgentPanel(container, comp);

        // 执行每个步骤
        for (let i = 0; i < steps.length; i++) {
            const step = steps[i];
            comp.agentLog.push({ type: 'execute', msg: `⚡ 执行: ${step.title || `步骤${i+1}`}` });
            renderAgentPanel(container, comp);

            // 使用 executor API
            try {
                ToolMonitor.logCall('executor_decide', { title: step.title, description: (step.description || '').slice(0, 200) });
                const execResp = await fetch('/api/executor/decide-and-execute', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        step: { title: step.title, description: step.description },
                        tools: tools,
                        ...apiCfg,
                    }),
                });
                const execData = await execResp.json();
                if (execData.success) {
                    ToolMonitor.logResult('executor_decide', (execData.summary || '完成').slice(0, 500), false);
                    allResults[String(i)] = { success: true, output: execData.summary || '完成' };
                    comp.agentLog.push({ type: 'execute', msg: `  ✅ 完成: ${(execData.summary || '').slice(0, 80)}` });
                } else {
                    ToolMonitor.logResult('executor_decide', execData.error || '执行失败', true);
                    allResults[String(i)] = { success: false, error: execData.error };
                    comp.agentLog.push({ type: 'execute', msg: `  ❌ 失败: ${execData.error}` });
                }
            } catch (e) {
                ToolMonitor.logResult('executor_decide', e.message, true);
                allResults[String(i)] = { success: false, error: e.message };
                comp.agentLog.push({ type: 'execute', msg: `  ❌ 异常: ${e.message}` });
            }
        }

        // 反思
        comp.agentLog.push({ type: 'reflect', msg: '🔄 正在反思评估…' });
        renderAgentPanel(container, comp);

        try {
            ToolMonitor.logCall('reflection_evaluate', { task: task.slice(0, 200) });
            const reflResp = await fetch('/api/reflection/evaluate', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    task, plan_steps: steps, step_results: allResults, ...apiCfg,
                }),
            });
            const reflData = await reflResp.json();
            if (reflData.success && reflData.evaluation) {
                const ev = reflData.evaluation;
                ToolMonitor.logResult('reflection_evaluate', `${ev.completion}: ${(ev.analysis || '').slice(0, 300)}`, false);
                comp.agentLog.push({ type: 'reflect', msg: `📊 评估: ${ev.completion} — ${(ev.analysis || '').slice(0, 80)}` });

                if (ev.completion === 'completed') {
                    comp.agentLog.push({ type: 'complete', msg: `✅ 任务完成！${ev.suggestion || ''}` });
                    comp.agentStatus = 'done';
                    renderAgentPanel(container, comp);
                    showToast('✅ Agent 任务完成', 'success');
                    return;
                } else if (ev.need_replan && ev.adjusted_steps && ev.adjusted_steps.length > 0) {
                    comp.agentLog.push({ type: 'reflect', msg: '🔄 需要重规划，加载调整后的步骤…' });
                    steps = ev.adjusted_steps.map((title, i) => ({
                        title: typeof title === 'string' ? title : (title.title || `步骤${i+1}`),
                        description: typeof title === 'string' ? '' : (title.description || ''),
                    }));
                    allResults = {};
                } else {
                    // partial — 继续但调整
                    steps = steps.filter((s, i) => !allResults[String(i)]?.success);
                    if (steps.length === 0) {
                        comp.agentLog.push({ type: 'complete', msg: '✅ 所有步骤已完成' });
                        comp.agentStatus = 'done';
                        renderAgentPanel(container, comp);
                        return;
                    }
                    comp.agentLog.push({ type: 'reflect', msg: `📋 剩余 ${steps.length} 个步骤需要重试` });
                    allResults = {};
                }
            } else {
                // 快速判断：成功率
                const total = Object.keys(allResults).length;
                const successCount = Object.values(allResults).filter(r => r.success).length;
                if (successCount / total >= 0.8) {
                    comp.agentLog.push({ type: 'complete', msg: `✅ ${successCount}/${total} 步骤成功，任务完成` });
                    comp.agentStatus = 'done';
                    renderAgentPanel(container, comp);
                    return;
                }
                steps = steps.filter((s, i) => !allResults[String(i)]?.success);
                allResults = {};
            }
        } catch (e) {
            comp.agentLog.push({ type: 'error', msg: `反思请求失败: ${e.message}` });
        }
    }

    if (comp.agentIteration >= maxIter) {
        comp.agentLog.push({ type: 'info', msg: `达到最大迭代次数 (${maxIter})` });
    }
    comp.agentStatus = 'done';
    renderAgentPanel(container, comp);
    showToast('⚠️ Agent 达到最大迭代次数', 'info');
}

// ============================================================
// Reflection 反思面板
// ============================================================
function renderReflectionPanel(container, comp) {
    if (!comp.reflHistory) comp.reflHistory = [];
    if (!comp.reflLastResult) comp.reflLastResult = null;

    container.className = 'module-panel';

    // 查找连接的 Plan
    const planConn = STATE.connections.find(c => c.targetCompId === comp.id && c.targetPortId === 'refl-plan-in');
    const planComp = planConn ? STATE.components.find(x => x.id === planConn.sourceCompId) : null;

    // 从 Plan 获取步骤结果用于分析
    const planResults = planComp?.currentPlan?.step_results || {};

    const last = comp.reflLastResult;

    container.innerHTML = `
        <div class="refl-panel">
            <div class="refl-header">
                <span class="refl-icon">💬</span>
                <span class="refl-title">反思评估器</span>
            </div>
            <div class="refl-desc">评估执行结果，决定下一步行动</div>

            <div class="refl-connections">
                <div class="refl-conn-row">📋 ${planConn ? `Plan #${planConn.sourceCompId}${planComp?.currentPlan ? ' (活跃)' : ''}` : '⚠️ 未连接 Plan'}</div>
                <div class="refl-conn-row">⚡ ${Object.keys(planResults).length} 个步骤结果可评估</div>
            </div>

            <div class="refl-ports-desc">
                <div class="refl-port-item continue">→ 继续: 任务进展中，继续执行</div>
                <div class="refl-port-item replan">→ 重规划: 需要调整计划</div>
                <div class="refl-port-item complete">→ 完成: 任务目标已达</div>
            </div>

            <div class="refl-actions">
                <button class="module-btn" id="refl-eval-${comp.id}" ${!planComp?.currentPlan ? 'disabled' : ''}>
                    🔍 评估当前结果
                </button>
                <button class="module-btn secondary" id="refl-quick-${comp.id}" ${!planComp?.currentPlan ? 'disabled' : ''}>
                    ⚡ 快速检查
                </button>
            </div>

            ${last ? `
                <div class="refl-result ${last.completion || ''}">
                    <div class="refl-result-header">📊 ${last.completion === 'completed' ? '✅ 已完成' : last.completion === 'partial' ? '⏳ 部分完成' : last.completion === 'failed' ? '❌ 失败' : '评估结果'}</div>
                    <div class="refl-result-analysis">${escapeHtml(last.analysis || '')}</div>
                    ${last.suggestion ? `<div class="refl-result-suggestion">💡 ${escapeHtml(last.suggestion)}</div>` : ''}
                    ${last.need_replan ? `<div class="refl-result-replan">🔄 建议重规划</div>` : ''}
                </div>
            ` : ''}

            ${comp.reflHistory.length > 0 ? `
                <div class="refl-history">
                    <div class="refl-history-header">📜 历史评估 (${comp.reflHistory.length})</div>
                    ${comp.reflHistory.slice(-3).map(h => `
                        <div class="refl-history-item ${h.completion || ''}">
                            <span>${h.completion === 'completed' ? '✅' : h.completion === 'partial' ? '⏳' : '❌'}</span>
                            <span>${escapeHtml((h.analysis || '').slice(0, 60))}</span>
                        </div>
                    `).join('')}
                </div>
            ` : ''}
        </div>
    `;

    // 绑定评估
    container.querySelector(`#refl-eval-${comp.id}`)?.addEventListener('click', async () => {
        if (!planComp?.currentPlan) return;
        const plan = planComp.currentPlan;
        const apiCfg = getPlanAPIConfig(planComp);

        const btn = container.querySelector(`#refl-eval-${comp.id}`);
        btn.disabled = true; btn.textContent = '⏳ 评估中…';

        try {
            ToolMonitor.logCall('reflection_evaluate', { task: (plan.task || '').slice(0, 200) });
            const resp = await fetch('/api/reflection/evaluate', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    task: plan.task || '',
                    plan_steps: plan.steps || [],
                    step_results: plan.step_results || {},
                    ...apiCfg,
                }),
            });
            const data = await resp.json();
            if (data.success) {
                ToolMonitor.logResult('reflection_evaluate', `${data.evaluation.completion}: ${(data.evaluation.analysis || '').slice(0, 300)}`, false);
                comp.reflLastResult = data.evaluation;
                comp.reflHistory.push(data.evaluation);
                renderReflectionPanel(container, comp);
                showToast(`评估完成: ${data.evaluation.completion}`, 'success');
            } else {
                ToolMonitor.logResult('reflection_evaluate', data.error || '评估失败', true);
                showToast(`评估失败: ${data.error}`, 'error');
            }
        } catch (e) {
            ToolMonitor.logResult('reflection_evaluate', e.message, true);
            showToast(`请求失败: ${e.message}`, 'error');
        }
        btn.disabled = false; btn.textContent = '🔍 评估当前结果';
    });

    // 快速检查
    container.querySelector(`#refl-quick-${comp.id}`)?.addEventListener('click', async () => {
        if (!planComp?.currentPlan) return;
        const results = planComp.currentPlan.step_results || {};
        try {
            ToolMonitor.logCall('reflection_quick_check', { steps_count: Object.keys(results).length });
            const resp = await fetch('/api/reflection/quick-check', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ step_results: results }),
            });
            const data = await resp.json();
            if (data.success) {
                ToolMonitor.logResult('reflection_quick_check', `${data.completion} (${Math.round(data.success_ratio * 100)}%)`, false);
                comp.reflLastResult = data;
                comp.reflHistory.push(data);
                renderReflectionPanel(container, comp);
                showToast(`快速检查: ${data.completion}`, 'info');
            }
        } catch (e) {
            ToolMonitor.logResult('reflection_quick_check', e.message, true);
            showToast(`检查失败: ${e.message}`, 'error');
        }
    });
}

// ============================================================
// Vector Memory 面板（升级版 Embeddings）
// ============================================================
function renderVectorMemoryPanel(container, comp) {
    if (!comp.vectorDocs) comp.vectorDocs = [];
    if (comp.toolEnabled === undefined) comp.toolEnabled = true;

    container.className = 'module-panel';
    container.innerHTML = `
        <div class="tool-toggle-row">
            <span class="tool-status-dot ${comp.toolEnabled ? 'on' : 'off'}"></span>
            <span style="font-size:12px;font-weight:600;">${comp.toolEnabled ? '已开启' : '已关闭'}</span>
            <button class="tool-toggle-btn ${comp.toolEnabled ? 'on' : 'off'}" id="tog-${comp.id}">
                ${comp.toolEnabled ? '关闭' : '开启'}
            </button>
        </div>

        <div class="vm-search-section">
            <div class="vm-search-header">🔍 语义搜索</div>
            <input class="module-input" id="vm-query-${comp.id}" placeholder="输入搜索内容…" style="font-size:11px;">
            <button class="module-btn" id="vm-search-${comp.id}" style="font-size:11px;width:100%;margin-top:4px;">搜索相似内容</button>
            <div class="module-result" id="vm-result-${comp.id}" style="display:none;"></div>
        </div>

        <div class="vm-doc-section">
            <div class="vm-doc-header">
                <span>📚 知识库</span>
                <span class="vm-doc-count">${comp.vectorDocs.length} 条</span>
            </div>
            <div class="vm-doc-add">
                <textarea class="module-textarea" id="vm-text-${comp.id}" placeholder="添加知识文档…" rows="3" style="font-size:11px;"></textarea>
                <button class="module-btn" id="vm-add-${comp.id}" style="font-size:11px;width:100%;margin-top:4px;">📥 添加到知识库</button>
            </div>
            <div class="module-list" id="vm-list-${comp.id}" style="max-height:150px;">
                ${comp.vectorDocs.length === 0
                    ? '<div style="font-size:11px;color:var(--text-muted);padding:8px;text-align:center;">知识库为空</div>'
                    : comp.vectorDocs.map((d, i) => `
                        <div class="module-list-item" style="flex-direction:column;align-items:flex-start;gap:3px;">
                            <div style="font-size:11px;font-weight:600;">📄 ${escapeHtml(d.title || `文档 ${i+1}`)}</div>
                            <div style="font-size:10px;color:var(--text-muted);">${escapeHtml((d.content || '').slice(0, 80))}</div>
                            <button class="module-btn danger" style="padding:2px 6px;font-size:9px;" data-vm-del="${i}">删除</button>
                        </div>
                    `).join('')
                }
            </div>
        </div>
    `;

    // 开关
    const togBtn = container.querySelector(`#tog-${comp.id}`);
    const dot = container.querySelector('.tool-status-dot');
    togBtn.addEventListener('click', () => {
        comp.toolEnabled = !comp.toolEnabled;
        togBtn.textContent = comp.toolEnabled ? '关闭' : '开启';
        togBtn.className = `tool-toggle-btn ${comp.toolEnabled ? 'on' : 'off'}`;
        dot.className = `tool-status-dot ${comp.toolEnabled ? 'on' : 'off'}`;
        autoSaveConnections();
    });

    // 添加到知识库
    container.querySelector(`#vm-add-${comp.id}`).addEventListener('click', async () => {
        const text = container.querySelector(`#vm-text-${comp.id}`).value.trim();
        if (!text) return;
        const title = text.slice(0, 30) + (text.length > 30 ? '…' : '');
        comp.vectorDocs.push({ title, content: text, addedAt: new Date().toISOString() });
        container.querySelector(`#vm-text-${comp.id}`).value = '';
        renderVectorMemoryPanel(container, comp);
        // 同步到后端向量库
        try {
            await fetch('/api/vector-memory/documents', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({text: text}),
            });
        } catch(e) { /* non-critical */ }
        showToast('✅ 已添加到知识库', 'success');
    });

    // 删除
    container.querySelectorAll('[data-vm-del]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const idx = parseInt(btn.dataset.vmDel);
            comp.vectorDocs.splice(idx, 1);
            renderVectorMemoryPanel(container, comp);
        });
    });

    // 语义搜索（调后端向量相似度）
    container.querySelector(`#vm-search-${comp.id}`).addEventListener('click', async () => {
        const query = container.querySelector(`#vm-query-${comp.id}`).value.trim();
        if (!query || comp.vectorDocs.length === 0) {
            showToast(comp.vectorDocs.length === 0 ? '知识库为空' : '请输入搜索内容', 'error');
            return;
        }

        const resultDiv = container.querySelector(`#vm-result-${comp.id}`);
        resultDiv.style.display = 'block';
        resultDiv.innerHTML = '⏳ 语义搜索中…';

        try {
            const resp = await fetch('/api/vector-memory/search', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({query: query, top_k: 5}),
            });
            const data = await resp.json();
            if (data.success) {
                resultDiv.innerHTML = `<pre style="font-size:11px;white-space:pre-wrap;color:var(--text);">${escapeHtml(data.result)}</pre>`;
            } else {
                resultDiv.innerHTML = `<div style="color:var(--danger);">搜索失败</div>`;
            }
        } catch(e) {
            // 回退到本地关键词匹配
            resultDiv.innerHTML = '⏳ 后端不可用，使用本地匹配…';
            const queryLower = query.toLowerCase();
            const scored = comp.vectorDocs.map((doc, i) => {
                const contentLower = (doc.content || '').toLowerCase();
                const titleLower = (doc.title || '').toLowerCase();
                let score = 0;
                if (contentLower.includes(queryLower)) score += 10;
                if (titleLower.includes(queryLower)) score += 5;
                queryLower.split(/\s+/).forEach(word => {
                    if (word.length > 1 && contentLower.includes(word)) score += 1;
                });
                return { ...doc, score, index: i };
            }).filter(d => d.score > 0).sort((a, b) => b.score - a.score).slice(0, 5);

            if (scored.length === 0) {
                resultDiv.innerHTML = '<div style=\"color:var(--text-muted);font-size:12px;\">未找到相关内容</div>';
            } else {
                resultDiv.innerHTML = '<div style=\"font-weight:600;font-size:11px;margin-bottom:6px;\">\u{1F50D} 找到 ' + scored.length + ' 条相关结果（本地匹配）</div>' +
                    scored.map(function(d) {
                        return '<div class=\"vm-search-result\">' +
                            '<div class=\"vm-search-title\">\u{1F4C4} ' + escapeHtml(d.title) + ' (相关度: ' + d.score + ')</div>' +
                            '<div class=\"vm-search-snippet\">' + escapeHtml(d.content.slice(0, 120)) + (d.content.length > 120 ? '…' : '') + '</div>' +
                            '</div>';
                    }).join('');
            }
        }
    });
}

// ============================================================
// Working Memory 面板 — 临时草稿板
// ============================================================
function renderWorkingMemoryPanel(container, comp) {
    if (!comp.wmStore) comp.wmStore = {};

    container.className = 'module-panel';
    const entries = Object.entries(comp.wmStore);
    container.innerHTML = `
        <div style="text-align:center;color:var(--text-muted);padding:8px 4px;">
            <div style="font-size:24px;margin-bottom:4px;">📝</div>
            <div style="font-size:12px;font-weight:600;">工作记忆</div>
            <div style="font-size:16px;font-weight:700;color:var(--primary);margin:4px 0;">${entries.length}</div>
            <div style="font-size:11px;">个临时键值对</div>
            <div style="font-size:10px;color:var(--text-muted);margin-top:2px;">Agent 执行期间存中间结果</div>
        </div>
        <div class="wm-add-section">
            <input class="module-input" id="wm-key-${comp.id}" placeholder="键名" style="font-size:11px;margin-bottom:3px;">
            <textarea class="module-textarea" id="wm-val-${comp.id}" placeholder="值" rows="2" style="font-size:11px;"></textarea>
            <button class="module-btn" id="wm-set-${comp.id}" style="font-size:11px;width:100%;margin-top:4px;">📥 存入</button>
        </div>
        <div class="module-list" id="wm-list-${comp.id}" style="max-height:160px;">
            ${entries.length === 0
                ? '<div style="font-size:11px;color:var(--text-muted);padding:8px;text-align:center;">暂无数据</div>'
                : entries.map(([k, v]) => `
                    <div class="module-list-item" style="flex-direction:column;align-items:flex-start;gap:2px;">
                        <div style="display:flex;justify-content:space-between;width:100%;">
                            <span style="font-weight:600;font-size:11px;">🔑 ${escapeHtml(k)}</span>
                            <button class="module-btn danger" style="padding:2px 6px;font-size:9px;" data-wm-del="${escapeHtml(k)}">×</button>
                        </div>
                        <div style="font-size:10px;color:var(--text-muted);">${escapeHtml(String(v).slice(0, 80))}</div>
                    </div>
                `).join('')
            }
        </div>
        ${entries.length > 0 ? `<button class="module-btn danger" id="wm-clear-${comp.id}" style="font-size:11px;width:100%;">🗑 清空全部</button>` : ''}
    `;

    container.querySelector(`#wm-set-${comp.id}`).addEventListener('click', () => {
        const key = container.querySelector(`#wm-key-${comp.id}`).value.trim();
        const val = container.querySelector(`#wm-val-${comp.id}`).value.trim();
        if (!key) return;
        comp.wmStore[key] = val;
        container.querySelector(`#wm-key-${comp.id}`).value = '';
        container.querySelector(`#wm-val-${comp.id}`).value = '';
        renderWorkingMemoryPanel(container, comp);
    });

    container.querySelectorAll('[data-wm-del]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            delete comp.wmStore[btn.dataset.wmDel];
            renderWorkingMemoryPanel(container, comp);
        });
    });

    const clearBtn = container.querySelector(`#wm-clear-${comp.id}`);
    if (clearBtn) {
        clearBtn.addEventListener('click', () => {
            comp.wmStore = {};
            renderWorkingMemoryPanel(container, comp);
        });
    }
}

// ============================================================
// 记忆总结面板
// ============================================================
function renderMemorySummarizerPanel(container, comp) {
    if (!comp.props) comp.props = {};
    if (comp.props.autoSummarize === undefined) comp.props.autoSummarize = true;
    if (!comp.props.threshold) comp.props.threshold = 14000;
    if (!comp.props.summaryPrompt) comp.props.summaryPrompt = '请将以下对话历史压缩为简洁的摘要，保留关键信息和上下文脉络。';

    container.className = 'module-panel';
    const enabled = comp.props.autoSummarize;
    const threshold = comp.props.threshold;

    container.innerHTML = `
        <div style="text-align:center;color:var(--text-muted);padding:8px 4px;">
            <div style="font-size:24px;margin-bottom:4px;">📝</div>
            <div style="font-size:12px;font-weight:600;">记忆总结</div>
            <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">AI 压缩对话历史</div>
        </div>
        <div style="padding: 6px 10px; display: flex; flex-direction: column; gap: 6px;">
            <label style="display:flex;align-items:center;gap:6px;font-size:11px;cursor:pointer;">
                <input type="checkbox" id="ms-auto-${comp.id}" ${enabled ? 'checked' : ''}>
                启用自动总结
            </label>
            <div style="display:flex;align-items:center;gap:6px;font-size:11px;">
                <span>阈值:</span>
                <input type="number" class="module-input" id="ms-threshold-${comp.id}" value="${threshold}"
                    style="width:70px;font-size:11px;padding:2px 4px;" min="1000" step="500">
                <span>tokens</span>
            </div>
            <button class="module-btn" id="ms-summarize-now-${comp.id}" style="font-size:11px;width:100%;">
                ⚡ 立即总结
            </button>
            <div id="ms-status-${comp.id}" style="font-size:10px;color:var(--text-muted);text-align:center;">
                ${comp.props.lastSummary ? '上次总结: ' + comp.props.lastSummary : '就绪'}
            </div>
        </div>
    `;

    container.querySelector(`#ms-auto-${comp.id}`).addEventListener('change', (e) => {
        comp.props.autoSummarize = e.target.checked;
        autoSaveConnections();
    });
    container.querySelector(`#ms-threshold-${comp.id}`).addEventListener('change', (e) => {
        comp.props.threshold = parseInt(e.target.value) || 14000;
        autoSaveConnections();
    });
    container.querySelector(`#ms-summarize-now-${comp.id}`).addEventListener('click', () => {
        triggerManualSummarize(comp);
    });
}

function triggerManualSummarize(comp) {
    // 找到连接的 Memory 组件
    const memConn = STATE.connections.find(
        c => c.sourceCompId === comp.id && c.sourcePortId === 'ms-out'
    );
    if (!memConn) {
        showToast('⚠️ 请先将记忆总结组件连接到 Chat Memory 组件', 'error');
        return;
    }
    const targetComp = STATE.components.find(c => c.id === memConn.targetCompId);
    if (!targetComp || targetComp.type !== 'memory') {
        showToast('⚠️ 未找到连接的 Memory 组件', 'error');
        return;
    }
    if (!targetComp.messages || targetComp.messages.length === 0) {
        showToast('⚠️ Memory 组件中没有对话历史', 'info');
        return;
    }

    // 触发总结 — 将当前 memory 的历史发给 LLM 进行总结
    const msgs = targetComp.messages;
    const prompt = comp.props.summaryPrompt || '请将以下对话历史压缩为简洁摘要。';

    // 找到连接到当前 memory 的 LLM 组件
    const llmConn = STATE.connections.find(
        c => (c.sourceCompId === targetComp.id && c.sourcePortId === 'mem-out')
    );
    if (!llmConn) {
        showToast('⚠️ 未找到驱动 Memory 的 LLM 组件', 'error');
        return;
    }
    const llmComp = STATE.components.find(c => c.id === llmConn.targetCompId && c.type === 'llm');
    if (!llmComp) {
        showToast('⚠️ 未找到驱动的 LLM 组件', 'error');
        return;
    }

    // 添加总结任务到 LLM 的对话中
    const summaryRequest = {
        role: 'user',
        content: `${prompt}\n\n待总结的历史消息（${msgs.length} 条）：\n${msgs.map(m => `[${m.role}]: ${typeof m.content === 'string' ? m.content.slice(0, 500) : ''}`).join('\n\n')}\n\n请用不超过 500 字总结以上对话，保留所有关键信息和决策。`
    };

    if (!llmComp.messages) llmComp.messages = [];
    llmComp.messages.push(summaryRequest);

    // 标记总结完成时间
    comp.props.lastSummary = new Date().toLocaleTimeString('zh-CN', { hour12: false });
    const statusEl = document.getElementById(`ms-status-${comp.id}`);
    if (statusEl) {
        statusEl.textContent = '总结请求已发送 — ' + comp.props.lastSummary;
        statusEl.style.color = 'var(--primary)';
    }
    showToast(`📝 已向 LLM 发送总结请求（${msgs.length} 条消息）`, 'info');
    autoSaveConnections();
}

// ============================================================
// Conditional 条件分支面板
// ============================================================
function renderConditionalPanel(container, comp) {
    if (!comp.condCondition) comp.condCondition = 'auto'; // auto | success_check | contains | custom
    if (!comp.condCustomRule) comp.condCustomRule = '';
    if (!comp.condLastInput) comp.condLastInput = null;
    if (!comp.condLastResult) comp.condLastResult = null;

    container.className = 'module-panel';

    // 查找上一个组件的执行结果
    const inConn = STATE.connections.find(c => c.targetCompId === comp.id && c.targetPortId === 'cond-in');
    const sourceComp = inConn ? STATE.components.find(x => x.id === inConn.sourceCompId) : null;

    container.innerHTML = `
        <div class="cond-panel">
            <div class="cond-header">
                <span class="cond-icon">🔀</span>
                <span class="cond-title">条件分支</span>
            </div>
            <div class="cond-desc">根据上一步结果选择路径</div>

            <div class="cond-source">
                ${sourceComp
                    ? `📥 输入: ${COMPONENT_DEFS[sourceComp.type]?.icon || ''} ${COMPONENT_DEFS[sourceComp.type]?.title || sourceComp.type}`
                    : '⚠️ 未连接输入源'}
            </div>

            <div class="module-field">
                <label>判断条件</label>
                <select class="module-select" id="cond-rule-${comp.id}">
                    <option value="auto" ${comp.condCondition === 'auto' ? 'selected' : ''}>自动判断（有输出=成功）</option>
                    <option value="success_check" ${comp.condCondition === 'success_check' ? 'selected' : ''}>检查 success 字段</option>
                    <option value="contains" ${comp.condCondition === 'contains' ? 'selected' : ''}>包含关键字</option>
                    <option value="custom" ${comp.condCondition === 'custom' ? 'selected' : ''}>自定义 JS 表达式</option>
                </select>
            </div>

            ${comp.condCondition === 'contains' || comp.condCondition === 'custom' ? `
                <div class="module-field">
                    <label>${comp.condCondition === 'contains' ? '关键字（逗号分隔）' : 'JS 表达式 (result = 上一步输出)'}</label>
                    <input class="module-input" id="cond-custom-${comp.id}" placeholder="${comp.condCondition === 'contains' ? '成功, 完成, ok' : 'result.includes("成功")'}" value="${escapeHtml(comp.condCustomRule)}" style="font-size:11px;">
                </div>
            ` : ''}

            <div class="cond-ports-desc">
                <div class="cond-port-item true">✅ True 分支: 条件满足时走此路</div>
                <div class="cond-port-item false">❌ False 分支: 条件不满足时走此路</div>
            </div>

            ${comp.condLastResult !== null ? `
                <div class="cond-result ${comp.condLastResult ? 'true' : 'false'}">
                    <span>上一次判断: ${comp.condLastResult ? '✅ True' : '❌ False'}</span>
                    ${comp.condLastInput ? `<div style="font-size:10px;margin-top:2px;">输入: ${escapeHtml(String(comp.condLastInput).slice(0, 80))}</div>` : ''}
                </div>
            ` : ''}
        </div>
    `;

    container.querySelector(`#cond-rule-${comp.id}`).addEventListener('change', (e) => {
        comp.condCondition = e.target.value;
        renderConditionalPanel(container, comp);
    });

    const customInput = container.querySelector(`#cond-custom-${comp.id}`);
    if (customInput) {
        customInput.addEventListener('input', () => {
            comp.condCustomRule = customInput.value;
        });
    }
}

// ============================================================
// Agent 预设模板系统（模板数据由后端 /api/meta/components 的 quick_templates 下发）
// ============================================================
function loadAgentPreset(presetName) {
    // 按键（与 index.html preset-btn 的 data-preset 对应）在 QUICK_TEMPLATES 中查找；
    // 元数据拉取失败时为空数组 → toast 提示（不再静默 no-op）
    const preset = QUICK_TEMPLATES.find(t => t.key === presetName);
    if (!preset) { showToast('⚠️ 模板数据未加载（元数据拉取失败），无法加载模板', 'error'); return; }

    // 确认覆盖
    if (STATE.components.length > 0) {
        if (!confirm(`加载「${preset.name}」模板将清空当前画布。\n\n${preset.description}\n\n确定要加载吗？`)) return;
    }

    pushHistory();
    // 清空画布
    STATE.components = [];
    STATE.connections = [];
    STATE.nextId = 1;
    STATE.nextConnId = 1;

    // 添加组件
    const idMap = []; // 临时ID → 实际ID
    preset.components.forEach((cd, i) => {
        const comp = deserializeComponent(cd, i);
        if (comp) {
            comp.id = STATE.nextId++;
            idMap.push(comp.id);
            STATE.components.push(comp);
        }
    });

    // 添加连线
    preset.connections.forEach(cd => {
        const sourceId = idMap[cd.source];
        const targetId = idMap[cd.target];
        if (sourceId && targetId) {
            STATE.connections.push({
                id: 'conn_' + STATE.nextConnId++,
                sourceCompId: sourceId,
                sourcePortId: cd.sourcePort,
                targetCompId: targetId,
                targetPortId: cd.targetPort,
            });
        }
    });

    renderAll();
    updateUI();
    selectComponent(null);
    saveLayout();
    showToast(`✅ 已加载「${preset.name}」模板 (${STATE.components.length} 组件, ${STATE.connections.length} 连线)`, 'success');
}

// 绑定预设模板按钮
function setupPresetButtons() {
    const presetList = document.getElementById('preset-list');
    if (!presetList) return;

    presetList.querySelectorAll('.preset-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const presetName = btn.dataset.preset;
            loadAgentPreset(presetName);
        });
    });
}

// ============================================================
// Memory 面板 — 独立的对话历史组件
// ============================================================
function renderMemoryPanel(container, comp) {
    if (!comp.messages) comp.messages = [];
    container.className = 'module-panel';
    const msgCount = comp.messages.length;
    const lastMsg = msgCount > 0 ? comp.messages[msgCount - 1] : null;

    // 查找使用此 Memory 的组件（LLM 直连 或 Agent 编排器）
    const llmUsing = STATE.components.find(c =>
        c.type === 'llm' && findConnectedMemory(c.id) === comp
    );
    // 也检查是否通过 Agent 编排器间接使用
    const agentUsing = !llmUsing ? STATE.components.find(c =>
        c.type === 'agent' && STATE.connections.some(
            conn => conn.sourceCompId === comp.id && conn.sourcePortId === 'mem-out'
                 && conn.targetCompId === c.id && conn.targetPortId === 'agent-mem-in'
        )
    ) : null;
    const effectiveLLM = llmUsing || (agentUsing ? STATE.components.find(c =>
        c.type === 'llm' && STATE.connections.some(
            conn => conn.sourceCompId === c.id && conn.sourcePortId === 'llm-out'
                 && conn.targetCompId === agentUsing.id && conn.targetPortId === 'agent-llm-in'
        )
    ) : null);
    const sessionId = effectiveLLM ? getMemorySessionId(effectiveLLM) : null;
    const connected = !!(llmUsing || agentUsing);

    container.innerHTML = `
        <div style="text-align:center;color:var(--text-muted);padding:8px 4px;">
            <div style="font-size:28px;margin-bottom:4px;">🧠</div>
            <div style="font-size:12px;font-weight:600;">对话记忆</div>
            <div style="font-size:20px;font-weight:700;color:var(--primary);margin:4px 0;">${msgCount}</div>
            <div style="font-size:11px;">条消息</div>
            ${lastMsg ? `<div style="font-size:10px;color:var(--text-muted);margin-top:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">最近: ${escapeHtml((lastMsg.content || '').slice(0, 40))}</div>` : ''}
            ${sessionId ? `<div style="font-size:9px;color:var(--text-muted);margin-top:4px;">💾 后端同步: <code style="font-size:9px;">${escapeHtml(sessionId)}</code></div>` : '<div style="font-size:9px;color:var(--warning);margin-top:4px;">⚠️ 未连线</div>'}
        </div>
        <div class="module-list" id="mem-list-${comp.id}" style="max-height:140px;"></div>
        <div style="display:flex;gap:4px;">
            <button class="module-btn secondary" id="mem-sync-${comp.id}" style="flex:1;font-size:10px;" ${!connected ? 'disabled' : ''}>🔄 手动同步</button>
            <button class="module-btn danger" id="mem-clear-${comp.id}" style="flex:1;font-size:10px;">🗑 清空</button>
        </div>
    `;

    function refreshMemList() {
        const list = container.querySelector(`#mem-list-${comp.id}`);
        if (!list) return;
        const msgs = comp.messages.slice(-10); // 最近 10 条
        list.innerHTML = msgs.map((m, i) => `
            <div class="mem-msg-row ${m.role}">
                <span class="mem-role">${m.role === 'user' ? '👤' : '🤖'}</span>
                <span class="mem-preview">${escapeHtml((m.content || '').slice(0, 50))}</span>
            </div>
        `).join('');
    }

    refreshMemList();

    container.querySelector(`#mem-clear-${comp.id}`).addEventListener('click', () => {
        comp.messages = [];
        refreshMemList();
        renderMemoryPanel(container, comp);
        // 同步清空到后端
        if (connected && effectiveLLM) {
            fetch('/api/memory/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: sessionId, messages: [], title: '' }),
            }).catch(() => {});
        }
        showToast('🗑 记忆已清空', 'info');
    });

    // 手动同步按钮
    const syncBtn = container.querySelector(`#mem-sync-${comp.id}`);
    if (syncBtn && effectiveLLM) {
        syncBtn.addEventListener('click', async () => {
            syncBtn.disabled = true;
            syncBtn.textContent = '⏳ 同步中…';
            await syncMemoryToBackend(effectiveLLM);
            syncBtn.textContent = '✅ 已同步';
            setTimeout(() => {
                syncBtn.disabled = false;
                syncBtn.textContent = '🔄 手动同步';
            }, 1500);
            showToast('✅ 记忆已同步到后端', 'success');
        });
    }
}

// ── 工具函数：查找连接到 LLM 的 Memory 组件（支持 LLM→Agent→Memory 间接连接）──
function findConnectedMemory(llmCompId) {
    // 1. 直连：Memory → LLM
    const conn = STATE.connections.find(
        c => c.targetCompId === llmCompId && c.targetPortId === 'llm-mem-in'
    );
    if (conn) {
        const memComp = STATE.components.find(c => c.id === conn.sourceCompId);
        if (memComp && memComp.type === 'memory') {
            if (!memComp.messages) memComp.messages = [];
            return memComp;
        }
    }

    // 2. 间接：LLM → Agent → Memory
    const agentConn = STATE.connections.find(
        c => c.sourceCompId === llmCompId && c.sourcePortId === 'llm-out'
    );
    if (agentConn) {
        const agentComp = STATE.components.find(c => c.id === agentConn.targetCompId);
        if (agentComp && agentComp.type === 'agent') {
            const memConn = STATE.connections.find(
                c => c.targetCompId === agentComp.id && c.targetPortId === 'agent-mem-in'
            );
            if (memConn) {
                const memComp = STATE.components.find(c => c.id === memConn.sourceCompId);
                if (memComp && memComp.type === 'memory') {
                    if (!memComp.messages) memComp.messages = [];
                    return memComp;
                }
            }
        }
    }

    return null;
}

// ── 记忆后端同步 ──
function getMemorySessionId(llmComp) {
    if (!llmComp._memSessionId) {
        // 尝试从 localStorage 恢复或生成新的
        const stored = safeStorage.get('mem-session-map') || {};
        const key = `llm-${llmComp.id}`;
        llmComp._memSessionId = stored[key] || ('mem_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6));
        stored[key] = llmComp._memSessionId;
        safeStorage.set('mem-session-map', stored);
    }
    return llmComp._memSessionId;
}

async function syncMemoryToBackend(llmComp) {
    const memComp = findConnectedMemory(llmComp.id);
    const messages = memComp ? memComp.messages : (llmComp.messages || []);
    if (messages.length === 0) return;

    const sessionId = getMemorySessionId(llmComp);

    try {
        await fetch('/api/memory/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: sessionId,
                messages: messages,
            }),
        });
    } catch (e) {
        // 静默失败，前端 localStorage 也有备份
        console.warn('记忆后端同步失败:', e);
    }
}

async function loadMemoryFromBackend(llmComp) {
    const sessionId = getMemorySessionId(llmComp);

    try {
        const resp = await fetch(`/api/memory/load/${sessionId}`);
        const data = await resp.json();
        if (data.success && data.session && data.session.messages && data.session.messages.length > 0) {
            const memComp = findConnectedMemory(llmComp.id);
            if (memComp) {
                // 合并：优先使用后端的消息（更新），但保留比后端多的消息
                const backendMsgs = data.session.messages;
                if (backendMsgs.length >= (memComp.messages || []).length) {
                    memComp.messages = backendMsgs;
                } else {
                    // 前端消息更多，同步到后端
                    syncMemoryToBackend(llmComp);
                }
            } else if (!llmComp.messages || llmComp.messages.length === 0) {
                // LLM 无 Memory 组件且本地无消息时从后端加载
                llmComp.messages = data.session.messages;
            }
            return data.session;
        }
    } catch (e) {
        console.warn('加载后端记忆失败:', e);
    }
    return null;
}

// Web Search 面板（AI 驱动，纯展示）
// ============================================================
function renderWebSearchPanel(container, comp) {
    if (!comp.searchHistory) comp.searchHistory = [];
    if (!comp.engineOrder) comp.engineOrder = [];
    if (comp.toolEnabled === undefined) comp.toolEnabled = true;
    if (comp.maxSearchRounds == null) {
        comp.maxSearchRounds = 10;
        safeStorage.set('wybzd-max-search-rounds', 10);
    }
    container.className = 'module-panel';
    container.innerHTML = `
        <div class="tool-toggle-row">
            <span class="tool-status-dot ${comp.toolEnabled ? 'on' : 'off'}"></span>
            <span style="font-size:12px;font-weight:600;">${comp.toolEnabled ? '已开启' : '已关闭'}</span>
            <button class="tool-toggle-btn ${comp.toolEnabled ? 'on' : 'off'}" id="tog-${comp.id}">
                ${comp.toolEnabled ? '关闭' : '开启'}
            </button>
        </div>
        <div class="search-rounds-row" style="margin:8px 0;display:flex;align-items:center;gap:6px;">
            <label for="sr-${comp.id}" style="font-size:11px;color:var(--text-muted);white-space:nowrap;">🔁 最大搜索轮数</label>
            <input id="sr-${comp.id}" type="number" min="1" max="50" value="${comp.maxSearchRounds}"
                   style="width:50px;padding:4px 6px;font-size:12px;border:1px solid var(--border);border-radius:4px;background:var(--bg-input);color:var(--text);text-align:center;">
            <button id="srcfm-${comp.id}" class="module-btn primary" style="font-size:11px;padding:4px 10px;">确认</button>
        </div>
        <div class="engine-order-section" id="eos-${comp.id}">
            <div class="engine-order-header">🔀 搜索引擎优先级</div>
            <div class="engine-order-list" id="eol-${comp.id}">加载中…</div>
        </div>
        <div class="module-list" id="wsh-${comp.id}" style="max-height:120px;margin-top:4px;"></div>
    `;

    // 开关
    const togBtn = container.querySelector(`#tog-${comp.id}`);
    const dot = container.querySelector('.tool-status-dot');
    togBtn.addEventListener('click', () => {
        comp.toolEnabled = !comp.toolEnabled;
        togBtn.textContent = comp.toolEnabled ? '关闭' : '开启';
        togBtn.className = `tool-toggle-btn ${comp.toolEnabled ? 'on' : 'off'}`;
        dot.className = `tool-status-dot ${comp.toolEnabled ? 'on' : 'off'}`;
        autoSaveConnections();
    });

    // 最大搜索轮数 — 点击确认后生效
    const srInput = container.querySelector(`#sr-${comp.id}`);
    const srCfmBtn = container.querySelector(`#srcfm-${comp.id}`);
    if (srInput && srCfmBtn) {
        srCfmBtn.addEventListener('click', () => {
            let val = parseInt(srInput.value) || 6;
            val = Math.max(1, Math.min(50, val));
            comp.maxSearchRounds = val;
            srInput.value = val;
            // 同步到 localStorage，供 /chat 独立页面使用
            safeStorage.set('wybzd-max-search-rounds', val);
            autoSaveConnections();
            srCfmBtn.textContent = '✓';
            srCfmBtn.style.background = '#52c41a';
            srCfmBtn.style.borderColor = '#52c41a';
            setTimeout(() => {
                srCfmBtn.textContent = '确认';
                srCfmBtn.style.background = '';
                srCfmBtn.style.borderColor = '';
            }, 800);
        });
    }

    // ── 引擎排序 ──
    async function loadEngineOrder() {
        const list = container.querySelector(`#eol-${comp.id}`);
        try {
            const resp = await fetch('/api/web-search/engines');
            const data = await resp.json();
            comp.engineOrder = data.engines || [];
            renderEngineList(list, comp);
        } catch (e) {
            list.innerHTML = '<div style="font-size:11px;color:var(--text-muted);">无法加载引擎列表</div>';
        }
    }

    function renderEngineList(list, comp) {
        const engines = comp.engineOrder;
        list.innerHTML = engines.map((eng, idx) => `
            <div class="engine-row ${eng.enabled ? '' : 'disabled'}">
                <span class="engine-idx">${idx + 1}</span>
                <span class="engine-icon">${eng.icon}</span>
                <span class="engine-name">${escapeHtml(eng.name)}</span>
                <div class="engine-actions">
                    <button class="engine-btn eng-toggle ${eng.enabled ? 'on' : 'off'}"
                            data-eid="${escapeHtml(eng.id)}" data-action="toggle"
                            title="${eng.enabled ? '关闭' : '开启'}">
                        ${eng.enabled ? '✓' : '✕'}
                    </button>
                    <button class="engine-btn eng-move" data-eid="${escapeHtml(eng.id)}"
                            data-action="up" title="上移" ${idx === 0 ? 'disabled' : ''}>▲</button>
                    <button class="engine-btn eng-move" data-eid="${escapeHtml(eng.id)}"
                            data-action="down" title="下移" ${idx === engines.length - 1 ? 'disabled' : ''}>▼</button>
                </div>
            </div>
        `).join('');

        // 绑定事件
        list.querySelectorAll('.engine-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const eid = btn.dataset.eid;
                const action = btn.dataset.action;
                const idx = engines.findIndex(e => e.id === eid);

                if (action === 'toggle') {
                    engines[idx].enabled = !engines[idx].enabled;
                } else if (action === 'up' && idx > 0) {
                    [engines[idx - 1], engines[idx]] = [engines[idx], engines[idx - 1]];
                } else if (action === 'down' && idx < engines.length - 1) {
                    [engines[idx], engines[idx + 1]] = [engines[idx + 1], engines[idx]];
                } else {
                    return;
                }

                comp.engineOrder = engines;
                // 提交到后端
                try {
                    const newOrder = engines.map(e => e.id);
                    const enabledMap = {};
                    engines.forEach(e => { enabledMap[e.id] = e.enabled; });
                    await fetch('/api/web-search/engines', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ order: newOrder, enabled: enabledMap }),
                    });
                } catch (e) { /* 忽略提交失败，前端已有状态 */ }

                renderEngineList(list, comp);
            });
        });
    }

    loadEngineOrder();

    // 搜索历史
    function refreshList() {
        const histList = container.querySelector('#wsh-' + comp.id);
        if (!comp.searchHistory.length) {
            histList.innerHTML = '<div style="font-size:11px;color:var(--text-muted);padding:8px;text-align:center;">暂无调用记录</div>';
            return;
        }
        histList.innerHTML = comp.searchHistory.slice().reverse().map(h => `
            <div class="module-list-item" style="flex-direction:column;align-items:flex-start;gap:4px;">
                <div style="font-weight:600;font-size:12px;">🔍 ${escapeHtml(h.query)}</div>
                <div style="font-size:10px;color:var(--text-muted);">${h.count} 条结果 · ${h.time}</div>
            </div>
        `).join('');
    }
    refreshList();
    comp._refreshSearchList = refreshList;
}

// ============================================================
// Calculator 面板（AI 驱动，纯展示）
// ============================================================
function renderCalculatorPanel(container, comp) {
    if (!comp.calcHistory) comp.calcHistory = [];
    if (comp.toolEnabled === undefined) comp.toolEnabled = true;
    container.className = 'module-panel';
    container.innerHTML = `
        <div class="tool-toggle-row">
            <span class="tool-status-dot ${comp.toolEnabled ? 'on' : 'off'}"></span>
            <span style="font-size:12px;font-weight:600;">${comp.toolEnabled ? '已开启' : '已关闭'}</span>
            <button class="tool-toggle-btn ${comp.toolEnabled ? 'on' : 'off'}" id="tog-${comp.id}">
                ${comp.toolEnabled ? '关闭' : '开启'}
            </button>
        </div>
        <div style="text-align:center;color:var(--text-muted);padding:16px 10px;">
            <div style="font-size:28px;margin-bottom:6px;">🖩</div>
            <div style="font-size:12px;">连线到 LLM 后，AI 自动计算</div>
        </div>
        <div class="module-list" id="chl-${comp.id}" style="max-height:180px;"></div>
    `;

    const togBtn = container.querySelector(`#tog-${comp.id}`);
    const dot = container.querySelector('.tool-status-dot');
    togBtn.addEventListener('click', () => {
        comp.toolEnabled = !comp.toolEnabled;
        togBtn.textContent = comp.toolEnabled ? '关闭' : '开启';
        togBtn.className = `tool-toggle-btn ${comp.toolEnabled ? 'on' : 'off'}`;
        dot.className = `tool-status-dot ${comp.toolEnabled ? 'on' : 'off'}`;
        autoSaveConnections();
    });

    function refreshList() {
        const list = container.querySelector('#chl-' + comp.id);
        if (!comp.calcHistory.length) {
            list.innerHTML = '<div style="font-size:11px;color:var(--text-muted);padding:8px;text-align:center;">暂无调用记录</div>';
            return;
        }
        list.innerHTML = comp.calcHistory.slice().reverse().map(h => `
            <div class="module-list-item" style="font-family:var(--font-mono);font-size:11px;">
                <span style="color:var(--text-muted);">${escapeHtml(h.expr)}</span>
                <span style="font-weight:700;color:var(--primary);">= ${h.result}</span>
            </div>
        `).join('');
    }
    refreshList();
    comp._refreshCalcList = refreshList;
}

// ============================================================
// Code Executor 面板（AI 驱动，纯展示）
// ============================================================
function renderCodeExecutorPanel(container, comp) {
    if (!comp.codeHistory) comp.codeHistory = [];
    if (comp.toolEnabled === undefined) comp.toolEnabled = true;
    container.className = 'module-panel';
    container.innerHTML = `
        <div class="tool-toggle-row">
            <span class="tool-status-dot ${comp.toolEnabled ? 'on' : 'off'}"></span>
            <span style="font-size:12px;font-weight:600;">${comp.toolEnabled ? '已开启' : '已关闭'}</span>
            <button class="tool-toggle-btn ${comp.toolEnabled ? 'on' : 'off'}" id="tog-${comp.id}">
                ${comp.toolEnabled ? '关闭' : '开启'}
            </button>
        </div>
        <div style="text-align:center;color:var(--text-muted);padding:16px 10px;">
            <div style="font-size:28px;margin-bottom:6px;">💻</div>
            <div style="font-size:12px;">连线到 LLM 后，AI 自动执行代码</div>
        </div>
        <div class="module-list" id="cdh-${comp.id}" style="max-height:200px;"></div>
    `;

    const togBtn = container.querySelector(`#tog-${comp.id}`);
    const dot = container.querySelector('.tool-status-dot');
    togBtn.addEventListener('click', () => {
        comp.toolEnabled = !comp.toolEnabled;
        togBtn.textContent = comp.toolEnabled ? '关闭' : '开启';
        togBtn.className = `tool-toggle-btn ${comp.toolEnabled ? 'on' : 'off'}`;
        dot.className = `tool-status-dot ${comp.toolEnabled ? 'on' : 'off'}`;
        autoSaveConnections();
    });

    function refreshList() {
        const list = container.querySelector('#cdh-' + comp.id);
        if (!comp.codeHistory.length) {
            list.innerHTML = '<div style="font-size:11px;color:var(--text-muted);padding:8px;text-align:center;">暂无调用记录</div>';
            return;
        }
        list.innerHTML = comp.codeHistory.slice().reverse().map(h => `
            <div class="module-list-item" style="flex-direction:column;align-items:flex-start;gap:3px;">
                <div style="font-weight:600;font-size:11px;color:${h.ok ? 'var(--success)' : 'var(--danger)'};">${h.ok ? '✅' : '❌'} ${h.ok ? '成功' : '失败'}</div>
                <pre style="font-size:10px;margin:0;max-height:60px;overflow:hidden;">${escapeHtml((h.stdout || h.stderr || '').slice(0, 200))}</pre>
            </div>
        `).join('');
    }
    refreshList();
    comp._refreshCodeList = refreshList;
}

// ============================================================
// Text Tools 面板（AI 驱动，纯展示）
// ============================================================
function renderTextToolsPanel(container, comp) {
    if (!comp.textHistory) comp.textHistory = [];
    if (comp.toolEnabled === undefined) comp.toolEnabled = true;
    container.className = 'module-panel';
    container.innerHTML = `
        <div class="tool-toggle-row">
            <span class="tool-status-dot ${comp.toolEnabled ? 'on' : 'off'}"></span>
            <span style="font-size:12px;font-weight:600;">${comp.toolEnabled ? '已开启' : '已关闭'}</span>
            <button class="tool-toggle-btn ${comp.toolEnabled ? 'on' : 'off'}" id="tog-${comp.id}">
                ${comp.toolEnabled ? '关闭' : '开启'}
            </button>
        </div>
        <div style="text-align:center;color:var(--text-muted);padding:16px 10px;">
            <div style="font-size:28px;margin-bottom:6px;">📄</div>
            <div style="font-size:12px;">连线到 LLM 后，AI 自动分析文本</div>
        </div>
        <div class="module-list" id="tth-${comp.id}" style="max-height:200px;"></div>
    `;

    const togBtn = container.querySelector(`#tog-${comp.id}`);
    const dot = container.querySelector('.tool-status-dot');
    togBtn.addEventListener('click', () => {
        comp.toolEnabled = !comp.toolEnabled;
        togBtn.textContent = comp.toolEnabled ? '关闭' : '开启';
        togBtn.className = `tool-toggle-btn ${comp.toolEnabled ? 'on' : 'off'}`;
        dot.className = `tool-status-dot ${comp.toolEnabled ? 'on' : 'off'}`;
        autoSaveConnections();
    });

    function refreshList() {
        const list = container.querySelector('#tth-' + comp.id);
        if (!comp.textHistory.length) {
            list.innerHTML = '<div style="font-size:11px;color:var(--text-muted);padding:8px;text-align:center;">暂无调用记录</div>';
            return;
        }
        list.innerHTML = comp.textHistory.slice().reverse().map(h => `
            <div class="module-list-item" style="flex-direction:column;align-items:flex-start;gap:3px;">
                <div style="font-weight:600;font-size:11px;">📝 ${escapeHtml(h.action || h.type)}</div>
                <div style="font-size:10px;color:var(--text-muted);">${escapeHtml((h.result || '').slice(0, 150))}</div>
            </div>
        `).join('');
    }
    refreshList();
    comp._refreshTextList = refreshList;
}

// ============================================================
// MCP 共享：存储目录选择 + 直接写入文件
// ============================================================
// 使用 IndexedDB 持久化 FileSystemDirectoryHandle（页面刷新后仍可恢复）
// ============================================================
const MCP_FILE_EXTS = { mcp_word: '.docx', mcp_excel: '.xlsx', mcp_ppt: '.pptx' };
const MCP_DB_NAME = 'mcp-file-system';
const MCP_STORE_NAME = 'handles';

function _openMCPDB() {
    return new Promise((resolve, reject) => {
        const req = indexedDB.open(MCP_DB_NAME, 1);
        req.onupgradeneeded = () => {
            if (!req.result.objectStoreNames.contains(MCP_STORE_NAME)) {
                req.result.createObjectStore(MCP_STORE_NAME);
            }
        };
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
    });
}

async function restoreMCPDir() {
    // 从 IndexedDB 恢复之前选择的目录句柄
    try {
        const db = await _openMCPDB();
        const tx = db.transaction(MCP_STORE_NAME, 'readonly');
        const store = tx.objectStore(MCP_STORE_NAME);
        const getReq = store.get('save-dir');

        const handle = await new Promise((resolve, reject) => {
            getReq.onsuccess = () => resolve(getReq.result);
            getReq.onerror = () => reject(getReq.error);
        });

        if (!handle) return;

        // 请求恢复权限：仅在权限已授予时自动恢复。
        // 注意：requestPermission 需要用户激活（点击手势），不能在 await 之后调用，
        // 否则浏览器抛 SecurityError。若权限处于 prompt 状态，跳过自动恢复，
        // 用户可通过"选择目录"按钮（新的点击手势）重新授权。
        const opts = { mode: 'readwrite' };
        const perm = await handle.queryPermission(opts);
        if (perm !== 'granted') {
            console.log('MCP 目录权限待确认（prompt），跳过自动恢复，用户可重新选择');
            return;
        }

        STATE.mcpSaveDir = handle;
        STATE.mcpSaveDirName = handle.name;
        console.log('MCP 目录已恢复:', handle.name);
        // 刷新面板显示已恢复的目录名
        if (STATE.components.length > 0) renderAll();
    } catch (e) {
        // IndexedDB 不可用或权限丢失，忽略
        console.warn('恢复 MCP 目录失败:', e);
        STATE.mcpSaveDir = null;
        STATE.mcpSaveDirName = '';
    }
}

async function pickMCPDir() {
    try {
        const handle = await window.showDirectoryPicker({ mode: 'readwrite' });
        STATE.mcpSaveDir = handle;
        STATE.mcpSaveDirName = handle.name;

        // 持久化到 IndexedDB
        try {
            const db = await _openMCPDB();
            const tx = db.transaction(MCP_STORE_NAME, 'readwrite');
            tx.objectStore(MCP_STORE_NAME).put(handle, 'save-dir');
            await new Promise((resolve, reject) => {
                tx.oncomplete = () => resolve();
                tx.onerror = () => reject(tx.error);
            });
        } catch (dbErr) {
            console.warn('IndexedDB 存储目录句柄失败:', dbErr);
        }

        // 同步到 localStorage（供 AI 对话页读取）
        safeStorage.set('mcp-storage-path', {
            name: handle.name,
            updatedAt: new Date().toISOString(),
        });

        // 同步到后端（供服务端记录）
        fetch('/api/config/storage-path', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: handle.name, path: handle.name }),
        }).catch(() => {});

        renderAll();
        showToast(`✅ 存储目录已设为: ${handle.name}`, 'success');
    } catch (e) {
        if (e.name !== 'AbortError') {
            showToast('此浏览器不支持直接存储，将使用浏览器下载', 'info');
        }
    }
}

async function saveMCPFilesToDir(fileExt, label) {
    // 如果选了目录 → 直接写入；否则 → 浏览器下载
    if (!STATE.mcpSaveDir) {
        // 尝试恢复
        await restoreMCPDir();
    }
    if (!STATE.mcpSaveDir) {
        await _legacyDownloadMCP(fileExt, label);
        return;
    }

    // 写入前重新确认权限（requestPermission 需用户激活，此处不自动请求）
    try {
        const perm = await STATE.mcpSaveDir.queryPermission({ mode: 'readwrite' });
        if (perm !== 'granted') {
            showToast('目录权限已失效，请重新点击"选择存储目录"授权', 'error');
            STATE.mcpSaveDir = null;
            STATE.mcpSaveDirName = '';
            renderAll();
            return;
        }
    } catch (e) {
        // 句柄失效，清除并提示重选
        showToast('存储目录已失效，请重新选择', 'error');
        STATE.mcpSaveDir = null;
        STATE.mcpSaveDirName = '';
        renderAll();
        return;
    }

    try {
        const resp = await fetch('/api/mcp/office/list-files/default');
        const data = await resp.json();
        const files = (data.files || []).filter(f => f.name.endsWith(fileExt));
        if (!files.length) { showToast(`暂无${label}文件`, 'info'); return; }

        let savedCount = 0;
        for (const f of files) {
            try {
                const fileResp = await fetch(`/api/mcp/office/download/default/${f.name}`);
                const blob = await fileResp.blob();
                const fileHandle = await STATE.mcpSaveDir.getFileHandle(f.name, { create: true });
                const writable = await fileHandle.createWritable();
                await writable.write(blob);
                await writable.close();
                savedCount++;
                // 保存成功后删除服务端原文件
                fetch(`/api/mcp/office/delete/default/${encodeURIComponent(f.name)}`, { method: 'DELETE' }).catch(() => {});
            } catch (e) {
                console.error(`写入 ${f.name} 失败:`, e);
            }
        }
        showToast(`✅ 已保存 ${savedCount} 个${label}文件到 ${STATE.mcpSaveDirName}`, 'success');
    } catch (e) {
        showToast('保存失败: ' + e.message, 'error');
    }
}

async function _legacyDownloadMCP(fileExt, label) {
    try {
        const resp = await fetch('/api/mcp/office/list-files/default');
        const data = await resp.json();
        const files = (data.files || []).filter(f => f.name.endsWith(fileExt));
        if (!files.length) { showToast(`暂无${label}文件`, 'info'); return; }
        let downloaded = 0;
        for (const f of files) {
            try {
                const fileResp = await fetch(`/api/mcp/office/download/default/${f.name}`);
                const blob = await fileResp.blob();
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url; a.download = f.name;
                document.body.appendChild(a); a.click(); a.remove();
                URL.revokeObjectURL(url);
                downloaded++;
                // 下载后删除服务端文件
                fetch(`/api/mcp/office/delete/default/${encodeURIComponent(f.name)}`, { method: 'DELETE' }).catch(() => {});
            } catch (e) { console.error(`下载 ${f.name} 失败:`, e); }
        }
        showToast(`📥 已下载 ${downloaded} 个${label}文件`, 'info');
    } catch (e) { showToast('获取文件列表失败', 'error'); }
}

// ============================================================
// MCP Word 面板
// ============================================================
function renderMCPWordPanel(container, comp) {
    if (!comp.wordHistory) comp.wordHistory = [];
    if (comp.toolEnabled === undefined) comp.toolEnabled = true;
    container.className = 'module-panel';
    const dirInfo = STATE.mcpSaveDirName
        ? `<div class="mcp-save-info">📁 ${escapeHtml(STATE.mcpSaveDirName)}</div>`
        : '<div class="mcp-save-info" style="color:var(--text-muted);">📁 未选择存储目录</div>';
    container.innerHTML = `
        <div class="tool-toggle-row">
            <span class="tool-status-dot ${comp.toolEnabled ? 'on' : 'off'}"></span>
            <span style="font-size:12px;font-weight:600;">${comp.toolEnabled ? '已开启' : '已关闭'}</span>
            <button class="tool-toggle-btn ${comp.toolEnabled ? 'on' : 'off'}" id="tog-${comp.id}">
                ${comp.toolEnabled ? '关闭' : '开启'}
            </button>
        </div>
        <div style="text-align:center;color:var(--text-muted);padding:10px 10px;">
            <div style="font-size:28px;margin-bottom:4px;">📝</div>
            <div style="font-size:12px;">连线到 LLM 后，AI 可调用 <b>5 个 Word 工具</b></div>
            <div style="font-size:11px;color:var(--text-muted);margin-top:4px;">
                word_create · word_add_heading · word_add_paragraph<br>
                word_add_table · word_save
            </div>
        </div>
        <div class="mcp-save-bar">
            ${dirInfo}
            <button class="module-btn secondary" id="wd-dir-${comp.id}" style="font-size:11px;">📂 选择目录</button>
            <button class="module-btn" id="wd-save-${comp.id}" style="font-size:11px;">📥 保存</button>
        </div>
    `;

    const togBtn = container.querySelector(`#tog-${comp.id}`);
    const dot = container.querySelector('.tool-status-dot');
    togBtn.addEventListener('click', () => {
        comp.toolEnabled = !comp.toolEnabled;
        togBtn.textContent = comp.toolEnabled ? '关闭' : '开启';
        togBtn.className = `tool-toggle-btn ${comp.toolEnabled ? 'on' : 'off'}`;
        dot.className = `tool-status-dot ${comp.toolEnabled ? 'on' : 'off'}`;
        autoSaveConnections();
    });

    container.querySelector(`#wd-dir-${comp.id}`).addEventListener('click', pickMCPDir);
    container.querySelector(`#wd-save-${comp.id}`).addEventListener('click', () => saveMCPFilesToDir('.docx', 'Word'));
}

// ============================================================
// MCP Excel 面板
// ============================================================
function renderMCPExcelPanel(container, comp) {
    if (!comp.excelHistory) comp.excelHistory = [];
    if (comp.toolEnabled === undefined) comp.toolEnabled = true;
    container.className = 'module-panel';
    const dirInfo = STATE.mcpSaveDirName
        ? `<div class="mcp-save-info">📁 ${escapeHtml(STATE.mcpSaveDirName)}</div>`
        : '<div class="mcp-save-info" style="color:var(--text-muted);">📁 未选择存储目录</div>';
    container.innerHTML = `
        <div class="tool-toggle-row">
            <span class="tool-status-dot ${comp.toolEnabled ? 'on' : 'off'}"></span>
            <span style="font-size:12px;font-weight:600;">${comp.toolEnabled ? '已开启' : '已关闭'}</span>
            <button class="tool-toggle-btn ${comp.toolEnabled ? 'on' : 'off'}" id="tog-${comp.id}">
                ${comp.toolEnabled ? '关闭' : '开启'}
            </button>
        </div>
        <div style="text-align:center;color:var(--text-muted);padding:10px 10px;">
            <div style="font-size:28px;margin-bottom:4px;">📊</div>
            <div style="font-size:12px;">连线到 LLM 后，AI 可调用 <b>5 个 Excel 工具</b></div>
            <div style="font-size:11px;color:var(--text-muted);margin-top:4px;">
                excel_create · excel_write_cell · excel_read_cell<br>
                excel_add_sheet · excel_save
            </div>
        </div>
        <div class="mcp-save-bar">
            ${dirInfo}
            <button class="module-btn secondary" id="xl-dir-${comp.id}" style="font-size:11px;">📂 选择目录</button>
            <button class="module-btn" id="xl-save-${comp.id}" style="font-size:11px;">📥 保存</button>
        </div>
    `;

    const togBtn = container.querySelector(`#tog-${comp.id}`);
    const dot = container.querySelector('.tool-status-dot');
    togBtn.addEventListener('click', () => {
        comp.toolEnabled = !comp.toolEnabled;
        togBtn.textContent = comp.toolEnabled ? '关闭' : '开启';
        togBtn.className = `tool-toggle-btn ${comp.toolEnabled ? 'on' : 'off'}`;
        dot.className = `tool-status-dot ${comp.toolEnabled ? 'on' : 'off'}`;
        autoSaveConnections();
    });

    container.querySelector(`#xl-dir-${comp.id}`).addEventListener('click', pickMCPDir);
    container.querySelector(`#xl-save-${comp.id}`).addEventListener('click', () => saveMCPFilesToDir('.xlsx', 'Excel'));
}

// ============================================================
// MCP PowerPoint 面板
// ============================================================
function renderMCPPPTPanel(container, comp) {
    if (!comp.pptHistory) comp.pptHistory = [];
    if (comp.toolEnabled === undefined) comp.toolEnabled = true;
    container.className = 'module-panel';
    const dirInfo = STATE.mcpSaveDirName
        ? `<div class="mcp-save-info">📁 ${escapeHtml(STATE.mcpSaveDirName)}</div>`
        : '<div class="mcp-save-info" style="color:var(--text-muted);">📁 未选择存储目录</div>';
    container.innerHTML = `
        <div class="tool-toggle-row">
            <span class="tool-status-dot ${comp.toolEnabled ? 'on' : 'off'}"></span>
            <span style="font-size:12px;font-weight:600;">${comp.toolEnabled ? '已开启' : '已关闭'}</span>
            <button class="tool-toggle-btn ${comp.toolEnabled ? 'on' : 'off'}" id="tog-${comp.id}">
                ${comp.toolEnabled ? '关闭' : '开启'}
            </button>
        </div>
        <div style="text-align:center;color:var(--text-muted);padding:10px 10px;">
            <div style="font-size:28px;margin-bottom:4px;">📽️</div>
            <div style="font-size:12px;">连线到 LLM 后，AI 可调用 <b>5 个 PPT 工具</b></div>
            <div style="font-size:11px;color:var(--text-muted);margin-top:4px;">
                ppt_create · ppt_add_slide · ppt_add_text<br>
                ppt_add_bullet_list · ppt_save
            </div>
        </div>
        <div class="mcp-save-bar">
            ${dirInfo}
            <button class="module-btn secondary" id="ppt-dir-${comp.id}" style="font-size:11px;">📂 选择目录</button>
            <button class="module-btn" id="ppt-save-${comp.id}" style="font-size:11px;">📥 保存</button>
        </div>
    `;

    const togBtn = container.querySelector(`#tog-${comp.id}`);
    const dot = container.querySelector('.tool-status-dot');
    togBtn.addEventListener('click', () => {
        comp.toolEnabled = !comp.toolEnabled;
        togBtn.textContent = comp.toolEnabled ? '关闭' : '开启';
        togBtn.className = `tool-toggle-btn ${comp.toolEnabled ? 'on' : 'off'}`;
        dot.className = `tool-status-dot ${comp.toolEnabled ? 'on' : 'off'}`;
        autoSaveConnections();
    });

    container.querySelector(`#ppt-dir-${comp.id}`).addEventListener('click', pickMCPDir);
    container.querySelector(`#ppt-save-${comp.id}`).addEventListener('click', () => saveMCPFilesToDir('.pptx', 'PPT'));
}

// ============================================================
// UI 更新
// ============================================================
function updateUI() {
    canvas.classList.toggle('empty', STATE.components.length === 0);
    toolbarCompCount.textContent = `组件: ${STATE.components.length}`;
    // 撤回按钮状态
    const undoBtn = document.getElementById('btn-undo');
    if (undoBtn) {
        undoBtn.disabled = STATE.history.length === 0;
        undoBtn.style.opacity = STATE.history.length === 0 ? '0.4' : '1';
    }
}

// ============================================================
// 布局持久化
// ============================================================
function buildLayoutData() {
    return {
        components: STATE.components.map(serializeComponent),
        connections: STATE.connections.map(c => ({ sourceCompId: c.sourceCompId, sourcePort: c.sourcePortId, targetCompId: c.targetCompId, targetPort: c.targetPortId })),
        nextId: STATE.nextId, nextConnId: STATE.nextConnId,
        savedAt: new Date().toISOString(),
    };
}

// ============================================================
// 项目管理 — 从服务器加载 / 自动保存
// ============================================================
async function loadProjectFromServer(projectId) {
    try {
        const resp = await fetch(`/api/projects/${encodeURIComponent(projectId)}`);
        if (!resp.ok) {
            showToast('项目加载失败，可能已被删除', 'error');
            CURRENT_PROJECT.id = null;
            loadLayout();
            return;
        }
        const data = await resp.json();
        CURRENT_PROJECT.name = data.name || '未命名';

        const layout = data.layout || {};
        STATE.nextId = layout.nextId || 1;
        STATE.nextConnId = layout.nextConnId || 1;
        STATE.components = [];
        STATE.connections = [];

        let skipped = 0;
        (layout.components || []).forEach((cd, i) => {
            const comp = deserializeComponent(cd, i - skipped);
            if (!comp) { skipped++; return; }
            STATE.components.push(comp);
        });
        STATE.nextId = STATE.components.reduce((m, c) => Math.max(m, c.id), 0) + 1;

        (layout.connections || []).forEach(cd => {
            if (STATE.components.some(c => c.id === cd.sourceCompId) && STATE.components.some(c => c.id === cd.targetCompId)) {
                STATE.connections.push({ id: 'conn_' + STATE.nextConnId++, sourceCompId: cd.sourceCompId, sourcePortId: cd.sourcePort, targetCompId: cd.targetCompId, targetPortId: cd.targetPort });
            }
        });

        renderAll(); updateUI(); selectComponent(null);
        syncAllLLMConfigsToActive();  // 恢复 API 设置到 active-llm-config
        updateMemoryPanelFromState();  // 更新记忆面板
        if (layout.components?.length) showToast(`📂 已加载「${CURRENT_PROJECT.name}」(${STATE.components.length} 组件)`, 'info');
    } catch (e) {
        console.error('加载项目失败:', e);
        loadLayout();
    }
}

const autoSaveProject = debounce(async () => {
    if (!CURRENT_PROJECT.id) return;
    try {
        const layout = buildLayoutData();
        const resp = await fetch('/api/projects', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                id: CURRENT_PROJECT.id,
                name: CURRENT_PROJECT.name,
                layout: layout,
            }),
        });
        if (!resp.ok) console.error('[自动保存] 服务器返回错误:', resp.status);
    } catch (e) { console.error('[自动保存] 失败:', e); }
}, 2000);

function updateProjectBadge() {
    let badge = document.getElementById('toolbar-project-badge');
    if (!CURRENT_PROJECT.id) {
        if (badge) badge.remove();
        return;
    }
    if (!badge) {
        badge = document.createElement('span');
        badge.id = 'toolbar-project-badge';
        badge.className = 'toolbar-badge';
        badge.style.cssText = 'background:#f6ffed;border:1px solid #b7eb8f;color:#389e0d;cursor:pointer;';
        badge.title = '点击返回项目列表';
        badge.addEventListener('click', () => { window.location.href = '/projects'; });
        const toolbarCenter = document.querySelector('.toolbar-center');
        if (toolbarCenter) toolbarCenter.appendChild(badge);
    }
    badge.textContent = `📁 ${CURRENT_PROJECT.name}`;
}

// 将当前所有 LLM 组件的 API 设置同步到 active-llm-config（确保页面刷新/重开不丢失）
function syncAllLLMConfigsToActive() {
    const llmComps = STATE.components.filter(c => c.type === 'llm');
    for (const llm of llmComps) {
        if (llm.apiSettings && (llm.apiSettings.apiBase || llm.apiSettings.apiKey || llm.apiSettings.model)) {
            const raw = safeStorage.getRaw('active-llm-config');
            const cfg = raw ? JSON.parse(raw) : {};
            cfg.apiBase = llm.apiSettings.apiBase;
            cfg.apiKey = llm.apiSettings.apiKey;
            cfg.model = llm.apiSettings.model;
            cfg.provider = llm.apiSettings.provider;
            cfg.maxToolRounds = llm.apiSettings.maxToolRounds || 50;
            cfg.savedAt = new Date().toISOString();
            safeStorage.set('active-llm-config', cfg);
            syncSettingsToBackend('llm_config', cfg);
            break;
        }
    }
}

function saveLayout() {
    // 保存前同步 API 设置
    syncAllLLMConfigsToActive();
    try {
        const data = buildLayoutData();
        const ok = safeStorage.set('dashboard-layout', data);
        if (ok) {
            showToast('布局已保存', 'success');
        } else {
            showToast('保存失败：本地存储空间不足', 'error');
        }
    } catch (e) {
        console.error('保存布局失败:', e);
        showToast('保存失败：' + (e.message || '未知错误'), 'error');
    }
    // 项目模式下同时保存到服务器
    if (CURRENT_PROJECT.id) {
        fetch('/api/projects', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                id: CURRENT_PROJECT.id,
                name: CURRENT_PROJECT.name,
                layout: buildLayoutData(),
            }),
        }).catch(() => {});
    }
}

function loadLayout() {
    try {
        const data = safeStorage.get('dashboard-layout');
        if (!data) return;
        STATE.nextId = data.nextId || 1;
        STATE.nextConnId = data.nextConnId || 1;
        STATE.components = [];
        STATE.connections = [];

        let skipped = 0;
        (data.components || []).forEach((cd, i) => {
            const comp = deserializeComponent(cd, i - skipped);
            if (!comp) { skipped++; return; }
            STATE.components.push(comp);
        });
        STATE.nextId = STATE.components.reduce((m, c) => Math.max(m, c.id), 0) + 1;

        (data.connections || []).forEach(cd => {
            if (STATE.components.some(c => c.id === cd.sourceCompId) && STATE.components.some(c => c.id === cd.targetCompId)) {
                STATE.connections.push({ id: 'conn_' + STATE.nextConnId++, sourceCompId: cd.sourceCompId, sourcePortId: cd.sourcePort, targetCompId: cd.targetCompId, targetPortId: cd.targetPort });
            }
        });

        renderAll(); updateUI(); selectComponent(null);
        syncAllLLMConfigsToActive();  // 恢复 API 设置到 active-llm-config
        updateMemoryPanelFromState();  // 更新记忆面板
        if (skipped > 0) showToast(`${skipped} 个旧版组件已跳过`, 'info');
        if (data.components?.length) showToast(`📂 已加载 (${STATE.components.length} 组件)`, 'info');
    } catch (e) { console.error('加载失败:', e); }
}

function clearCanvas() {
    if (STATE.components.length === 0) return;
    pushHistory();
    STATE.components = [];
    STATE.connections = [];
    selectComponent(null);
    renderAll(); updateUI();
    safeStorage.remove('dashboard-layout');
    autoSaveConnections();  // 清空连线同步
    showToast('🗑️ 画布已清空', 'info');
}

// ============================================================
// 连线自动保存（切换页面不丢失）
// ============================================================
const autoSaveConnections = debounce(() => {
    try {
        // 项目管理模式 — 自动保存到服务器
        if (CURRENT_PROJECT.id) autoSaveProject();

        // 保存工具名 + API 设置到 active-llm-config
        const raw = safeStorage.getRaw('active-llm-config');
        const cfg = raw ? JSON.parse(raw) : {};

        // 从第一个有 API 设置的 LLM 组件同步配置（确保 API 不丢失）
        const llmComps = STATE.components.filter(c => c.type === 'llm');
        for (const llm of llmComps) {
            if (llm.apiSettings && (llm.apiSettings.apiBase || llm.apiSettings.apiKey || llm.apiSettings.model)) {
                cfg.apiBase = llm.apiSettings.apiBase;
                cfg.apiKey = llm.apiSettings.apiKey;
                cfg.model = llm.apiSettings.model;
                cfg.provider = llm.apiSettings.provider;
                cfg.maxToolRounds = llm.apiSettings.maxToolRounds || 50;
                break;
            }
        }

        const toolNames = [];
        llmComps.forEach(llm => {
            STATE.connections.filter(c => c.sourceCompId === llm.id).forEach(c => {
                const tgt = STATE.components.find(x => x.id === c.targetCompId);
                if (!tgt) return;
                const names = TOOL_NAME_MAP[tgt.type];
                if (names) toolNames.push(...names);
                if (tgt.type === 'mcp_external') toolNames.push(...mcpExternalToolNames(tgt));
                if (tgt.type === 'executor' || tgt.type === 'sequential_executor' || tgt.type === 'agent') {
                    let portIds;
                    if (tgt.type === 'executor') {
                        const n = tgt.execPortCount || 5;
                        portIds = Array.from({length: n}, (_, i) => `exec-tool-${i + 1}`);
                    } else if (tgt.type === 'agent') {
                        const n = tgt.agentPortCount || 5;
                        portIds = Array.from({length: n}, (_, i) => `agent-tool-${i + 1}`);
                    } else {
                        portIds = ['seq-step-1','seq-step-2','seq-step-3','seq-step-4','seq-step-5'];
                    }
                    collectToolsFromPorts(tgt.id, portIds).forEach(n => toolNames.push(n));
                }
            });
        });
        cfg.tool_names = [...new Set(toolNames)];

        // 同步记忆组件连接状态到聊天页
        cfg.hasMemory = STATE.components.some(c => c.type === 'memory') &&
            STATE.connections.some(c => {
                const src = STATE.components.find(x => x.id === c.sourceCompId);
                const tgt = STATE.components.find(x => x.id === c.targetCompId);
                return (src && src.type === 'memory') || (tgt && tgt.type === 'memory');
            });

        // 同步记忆总结组件配置到聊天页
        const sumComps = STATE.components.filter(c => c.type === 'memory_summarizer');
        if (sumComps.length > 0) {
            const sumComp = sumComps[0];
            const hasMemConn = STATE.connections.some(
                c => c.sourceCompId === sumComp.id
            ) || STATE.connections.some(
                c => c.targetCompId === sumComp.id
            );
            if (hasMemConn) {
                cfg.summarizer = {
                    enabled: sumComp.props?.autoSummarize !== false,
                    threshold: sumComp.props?.threshold || 14000,
                };
            } else {
                delete cfg.summarizer;
            }
        } else {
            delete cfg.summarizer;
        }

        // 同步技能管理器中的活跃技能到聊天页
        const skmComps = STATE.components.filter(c => c.type === 'skills_manager');
        // 检测是否存在 skill_auto_call 以及其智能模式状态
        const autoCallComps = STATE.components.filter(c => c.type === 'skill_auto_call');
        if (autoCallComps.length > 0) {
            const autoCall = autoCallComps[0];
            cfg.smartMode = autoCall.smartMode !== false;  // 默认 true
        } else {
            cfg.smartMode = false;  // 无 auto_call 时 smartMode 为 false
        }
        if (skmComps.length > 0) {
            const activeSkills = [];
            for (const skm of skmComps) {
                refreshSkillsManagerSkills(skm);
                const skills = skm.skmSkills || [];
                for (const s of skills) {
                    if (s.skillId && !activeSkills.find(a => a.id === s.skillId)) {
                        activeSkills.push({ id: s.skillId, name: s.name || s.skillId });
                    }
                }
            }
            if (activeSkills.length > 0) {
                cfg.skills = activeSkills;
            } else {
                delete cfg.skills;
            }
        } else {
            delete cfg.skills;
        }

        // 同步 Token 计数器连接状态到聊天页（仅当连接到 LLM 且开启时生效）
        const tcComps = STATE.components.filter(c => c.type === 'token_counter' && c.toolEnabled !== false);
        cfg.tokenCounter = tcComps.length > 0 && STATE.connections.some(c => {
            const src = STATE.components.find(x => x.id === c.sourceCompId);
            const tgt = STATE.components.find(x => x.id === c.targetCompId);
            return (src && src.type === 'llm' && tgt && tgt.type === 'token_counter') ||
                   (tgt && tgt.type === 'llm' && src && src.type === 'token_counter');
        });

        cfg.savedAt = new Date().toISOString();
        safeStorage.set('active-llm-config', cfg);
        syncSettingsToBackend('llm_config', cfg);

        // 自动保存完整布局
        if (STATE.components.length > 0) {
            safeStorage.set('dashboard-layout', buildLayoutData());
        }
    } catch (e) { console.error('autoSaveConnections 失败:', e); }
}, 500);

// ============================================================
// MCP 服务面板（Weather / Database / Git）
// ============================================================
function renderMCPWeatherPanel(container, comp) {
    if (!comp.mcpConfig) comp.mcpConfig = { apiKey: '', city: 'Beijing', sessionId: 'weather_' + comp.id };
    if (comp.toolEnabled === undefined) comp.toolEnabled = true;
    const cfg = comp.mcpConfig;
    const connected = cfg._connected || false;

    container.className = 'module-panel';
    container.innerHTML = `
        <div class="tool-toggle-row">
            <span class="tool-status-dot ${comp.toolEnabled ? 'on' : 'off'}"></span>
            <span style="font-size:12px;font-weight:600;">${comp.toolEnabled ? '已开启' : '已关闭'}</span>
            <button class="tool-toggle-btn ${comp.toolEnabled ? 'on' : 'off'}" id="wtog-${comp.id}">${comp.toolEnabled ? '关闭' : '开启'}</button>
        </div>
        <div class="mcp-panel">
            <div class="mcp-field">
                <label>API Key</label>
                <input type="password" id="wapik-${comp.id}" placeholder="OpenWeatherMap API Key" value="${escapeHtml(cfg.apiKey)}">
                <span class="mcp-hint">免费注册: <a href="https://openweathermap.org/api" target="_blank" style="color:var(--primary);">openweathermap.org</a></span>
            </div>
            <div class="mcp-field">
                <label>默认城市</label>
                <input id="wcity-${comp.id}" placeholder="Beijing" value="${escapeHtml(cfg.city)}">
            </div>
            <div class="mcp-actions">
                <button class="mcp-test-btn ${connected ? 'connected' : ''}" id="wtest-${comp.id}">${connected ? '✅ 已连接' : '🔍 测试连接'}</button>
            </div>
            <div id="wresult-${comp.id}" class="mcp-result ${cfg._lastResult ? 'show ' + (cfg._lastSuccess ? 'success' : 'failure') : ''}">${cfg._lastResult || ''}</div>
            <div class="mcp-status"><span class="mcp-status-dot ${connected ? 'on' : 'off'}"></span>${connected ? '已连接' : '未连接'}</div>
        </div>
    `;

    bindMCPPanelEvents(container, comp, 'weather', ['apiKey', 'city']);
}

function renderMCPDatabasePanel(container, comp) {
    if (!comp.mcpConfig) comp.mcpConfig = { dbPath: '', sessionId: 'db_' + comp.id };
    if (comp.toolEnabled === undefined) comp.toolEnabled = true;
    const cfg = comp.mcpConfig;
    const connected = cfg._connected || false;

    container.className = 'module-panel';
    container.innerHTML = `
        <div class="tool-toggle-row">
            <span class="tool-status-dot ${comp.toolEnabled ? 'on' : 'off'}"></span>
            <span style="font-size:12px;font-weight:600;">${comp.toolEnabled ? '已开启' : '已关闭'}</span>
            <button class="tool-toggle-btn ${comp.toolEnabled ? 'on' : 'off'}" id="dtog-${comp.id}">${comp.toolEnabled ? '关闭' : '开启'}</button>
        </div>
        <div class="mcp-panel">
            <div class="mcp-field">
                <label>数据库文件路径</label>
                <input id="dbpath-${comp.id}" placeholder="C:/data/mydb.sqlite" value="${escapeHtml(cfg.dbPath)}">
                <span class="mcp-hint">SQLite 数据库文件 (.sqlite / .db)</span>
            </div>
            <div class="mcp-actions">
                <button class="mcp-test-btn ${connected ? 'connected' : ''}" id="dbtest-${comp.id}">${connected ? '✅ 已连接' : '🔍 测试连接'}</button>
            </div>
            <div id="dbresult-${comp.id}" class="mcp-result ${cfg._lastResult ? 'show ' + (cfg._lastSuccess ? 'success' : 'failure') : ''}">${cfg._lastResult || ''}</div>
            <div class="mcp-status"><span class="mcp-status-dot ${connected ? 'on' : 'off'}"></span>${connected ? '已连接' : '未连接'}</div>
        </div>
    `;

    bindMCPPanelEvents(container, comp, 'database', ['dbPath']);
}

function renderMCPGitPanel(container, comp) {
    if (!comp.mcpConfig) comp.mcpConfig = { repoPath: '', sessionId: 'git_' + comp.id };
    if (comp.toolEnabled === undefined) comp.toolEnabled = true;
    const cfg = comp.mcpConfig;
    const connected = cfg._connected || false;

    container.className = 'module-panel';
    container.innerHTML = `
        <div class="tool-toggle-row">
            <span class="tool-status-dot ${comp.toolEnabled ? 'on' : 'off'}"></span>
            <span style="font-size:12px;font-weight:600;">${comp.toolEnabled ? '已开启' : '已关闭'}</span>
            <button class="tool-toggle-btn ${comp.toolEnabled ? 'on' : 'off'}" id="gtog-${comp.id}">${comp.toolEnabled ? '关闭' : '开启'}</button>
        </div>
        <div class="mcp-panel">
            <div class="mcp-field">
                <label>Git 仓库路径</label>
                <input id="gpath-${comp.id}" placeholder="C:/projects/my-repo" value="${escapeHtml(cfg.repoPath)}">
                <span class="mcp-hint">包含 .git 目录的仓库根路径</span>
            </div>
            <div class="mcp-actions">
                <button class="mcp-test-btn ${connected ? 'connected' : ''}" id="gtest-${comp.id}">${connected ? '✅ 已连接' : '🔍 测试连接'}</button>
            </div>
            <div id="gresult-${comp.id}" class="mcp-result ${cfg._lastResult ? 'show ' + (cfg._lastSuccess ? 'success' : 'failure') : ''}">${cfg._lastResult || ''}</div>
            <div class="mcp-status"><span class="mcp-status-dot ${connected ? 'on' : 'off'}"></span>${connected ? '已连接' : '未连接'}</div>
        </div>
    `;

    bindMCPPanelEvents(container, comp, 'git', ['repoPath']);
}

// 通用简单 MCP 服务面板（clipboard/encoding/system/translate/calendar/pdf/finance/geocode）
function renderMCPSimplePanel(serviceName, desc, readyMsg) {
    return function(container, comp) {
        if (!comp.mcpConfig) comp.mcpConfig = { sessionId: serviceName + '_' + comp.id };
        if (comp.toolEnabled === undefined) comp.toolEnabled = true;
        const cfg = comp.mcpConfig;
        const connected = cfg._connected || false;

        container.className = 'module-panel';
        const testUrl = {
            clipboard: '/api/clipboard/test-connection',
            encoding: '/api/encoding/test-connection',
            system: '/api/system/test-connection',
            translate: '/api/translate/test-connection',
            calendar: '/api/calendar/test-connection',
            pdf: '/api/pdf/test-connection',
            finance: '/api/finance/test-connection',
            geocode: '/api/geocode/test-connection',
        };

        container.innerHTML = `
            <div class="tool-toggle-row">
                <span class="tool-status-dot ${comp.toolEnabled ? 'on' : 'off'}"></span>
                <span style="font-size:12px;font-weight:600;">${comp.toolEnabled ? '已开启' : '已关闭'}</span>
                <button class="tool-toggle-btn ${comp.toolEnabled ? 'on' : 'off'}" id="stog-${comp.id}">${comp.toolEnabled ? '关闭' : '开启'}</button>
            </div>
            <div class="mcp-panel">
                <div style="text-align:center;color:var(--text-muted);padding:8px;font-size:11px;">${escapeHtml(desc)}</div>
                <div class="mcp-actions">
                    <button class="mcp-test-btn ${connected ? 'connected' : ''}" id="stest-${comp.id}">${connected ? '✅ 已连接' : '🔍 测试连接'}</button>
                </div>
                <div id="sresult-${comp.id}" class="mcp-result ${cfg._lastResult ? 'show ' + (cfg._lastSuccess ? 'success' : 'failure') : ''}">${cfg._lastResult || ''}</div>
                <div class="mcp-status"><span class="mcp-status-dot ${connected ? 'on' : 'off'}"></span>${connected ? readyMsg : '未检测'}</div>
            </div>
        `;

        // Toggle
        const togBtn = container.querySelector(`#stog-${comp.id}`);
        if (togBtn) {
            const dot = container.querySelector('.tool-status-dot');
            togBtn.addEventListener('click', () => {
                comp.toolEnabled = !comp.toolEnabled;
                togBtn.textContent = comp.toolEnabled ? '关闭' : '开启';
                togBtn.className = `tool-toggle-btn ${comp.toolEnabled ? 'on' : 'off'}`;
                dot.className = `tool-status-dot ${comp.toolEnabled ? 'on' : 'off'}`;
                autoSaveConnections();
            });
        }

        // Test connection
        const testBtn = container.querySelector(`#stest-${comp.id}`);
        const resultDiv = container.querySelector(`#sresult-${comp.id}`);
        const statusDiv = container.querySelector('.mcp-status');
        const statusDot = statusDiv ? statusDiv.querySelector('.mcp-status-dot') : null;

        testBtn.addEventListener('click', async () => {
            testBtn.disabled = true; testBtn.textContent = '⏳ 测试中…';
            if (resultDiv) { resultDiv.className = 'mcp-result'; resultDiv.style.display = 'none'; }
            try {
                const controller = new AbortController();
                const timeoutId = setTimeout(() => controller.abort(), 10000);  // 10 秒超时
                const resp = await fetch(testUrl[serviceName], {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({session_id: cfg.sessionId}),
                    signal: controller.signal,
                });
                clearTimeout(timeoutId);
                const data = await resp.json();
                if (data.success) {
                    cfg._connected = true; cfg._lastSuccess = true; cfg._lastResult = data.message;
                    testBtn.textContent = '✅ 已连接'; testBtn.classList.add('connected');
                    if (resultDiv) { resultDiv.className = 'mcp-result success show'; resultDiv.style.display = 'block'; resultDiv.textContent = data.message; }
                    if (statusDot) statusDot.className = 'mcp-status-dot on';
                    if (statusDiv) statusDiv.innerHTML = '<span class="mcp-status-dot on"></span>' + readyMsg;
                } else {
                    cfg._connected = false; cfg._lastSuccess = false; cfg._lastResult = data.error;
                    testBtn.textContent = '❌ 失败'; testBtn.classList.remove('connected');
                    if (resultDiv) { resultDiv.className = 'mcp-result failure show'; resultDiv.style.display = 'block'; resultDiv.textContent = data.error; }
                }
            } catch (e) {
                cfg._connected = false; cfg._lastSuccess = false;
                const msg = e.name === 'AbortError' ? '连接测试超时（10 秒），请检查网络' : e.message;
                cfg._lastResult = msg;
                testBtn.textContent = '❌ 失败'; testBtn.classList.remove('connected');
                if (resultDiv) { resultDiv.className = 'mcp-result failure show'; resultDiv.style.display = 'block'; resultDiv.textContent = msg; }
                if (statusDot) statusDot.className = 'mcp-status-dot off';
                if (statusDiv) statusDiv.innerHTML = '<span class="mcp-status-dot off"></span>连接失败';
            }
            testBtn.disabled = false;
        });
    };
}

// Translate 面板（支持 detectlanguage API Key）
function renderMCPTranslatePanel(container, comp) {
    if (!comp.mcpConfig) comp.mcpConfig = { sessionId: 'translate_' + comp.id, apiKey: '' };
    if (comp.toolEnabled === undefined) comp.toolEnabled = true;
    const cfg = comp.mcpConfig;
    const connected = cfg._connected || false;

    container.className = 'module-panel';
    container.innerHTML = `
        <div class="tool-toggle-row">
            <span class="tool-status-dot ${comp.toolEnabled ? 'on' : 'off'}"></span>
            <span style="font-size:12px;font-weight:600;">${comp.toolEnabled ? '已开启' : '已关闭'}</span>
            <button class="tool-toggle-btn ${comp.toolEnabled ? 'on' : 'off'}" id="trtog-${comp.id}">${comp.toolEnabled ? '关闭' : '开启'}</button>
        </div>
        <div class="mcp-panel">
            <div style="text-align:center;color:var(--text-muted);padding:8px;font-size:11px;">多语言翻译 · 自动检测语种</div>
            <div style="padding:6px 8px;">
                <label style="font-size:10px;color:var(--text-muted);">detectlanguage API Key (可选，用于语种检测)</label>
                <div style="display:flex;gap:4px;margin-top:3px;">
                    <input id="trapi-${comp.id}" type="password" value="${escapeHtml(cfg.apiKey || '')}"
                           style="flex:1;padding:4px 6px;font-size:11px;border:1px solid var(--border);border-radius:4px;background:var(--bg-input);color:var(--text);"
                           placeholder="留空则使用启发式检测">
                    <button id="trsave-${comp.id}" class="module-btn primary" style="font-size:10px;padding:4px 8px;">保存</button>
                </div>
            </div>
            <div class="mcp-actions">
                <button class="mcp-test-btn ${connected ? 'connected' : ''}" id="trtest-${comp.id}">${connected ? '✅ 已连接' : '🔍 测试连接'}</button>
            </div>
            <div id="trresult-${comp.id}" class="mcp-result ${cfg._lastResult ? 'show ' + (cfg._lastSuccess ? 'success' : 'failure') : ''}">${cfg._lastResult || ''}</div>
            <div class="mcp-status"><span class="mcp-status-dot ${connected ? 'on' : 'off'}"></span>${connected ? '已就绪' : '未检测'}</div>
        </div>
    `;

    // Toggle
    const togBtn = container.querySelector(`#trtog-${comp.id}`);
    if (togBtn) {
        const dot = container.querySelector('.tool-status-dot');
        togBtn.addEventListener('click', () => {
            comp.toolEnabled = !comp.toolEnabled;
            togBtn.textContent = comp.toolEnabled ? '关闭' : '开启';
            togBtn.className = `tool-toggle-btn ${comp.toolEnabled ? 'on' : 'off'}`;
            dot.className = `tool-status-dot ${comp.toolEnabled ? 'on' : 'off'}`;
            autoSaveConnections();
        });
    }

    // Save API key
    const apiInput = container.querySelector(`#trapi-${comp.id}`);
    const saveBtn = container.querySelector(`#trsave-${comp.id}`);
    if (saveBtn && apiInput) {
        saveBtn.addEventListener('click', async () => {
            cfg.apiKey = apiInput.value.trim();
            // Sync to backend
            try {
                await fetch('/api/translate/api-key', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({api_key: cfg.apiKey}),
                });
            } catch (e) { /* non-critical */ }
            saveBtn.textContent = '✓';
            saveBtn.style.background = '#52c41a';
            autoSaveConnections();
            setTimeout(() => {
                saveBtn.textContent = '保存';
                saveBtn.style.background = '';
            }, 800);
        });
    }

    // Test connection
    const testBtn = container.querySelector(`#trtest-${comp.id}`);
    const resultDiv = container.querySelector(`#trresult-${comp.id}`);
    const statusDiv = container.querySelector('.mcp-status');
    const statusDot = statusDiv ? statusDiv.querySelector('.mcp-status-dot') : null;

    testBtn.addEventListener('click', async () => {
        testBtn.disabled = true; testBtn.textContent = '⏳ 测试中…';
        if (resultDiv) { resultDiv.className = 'mcp-result'; resultDiv.style.display = 'none'; }
        try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 10000);
            const resp = await fetch('/api/translate/test-connection', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({session_id: cfg.sessionId}),
                signal: controller.signal,
            });
            clearTimeout(timeoutId);
            const data = await resp.json();
            if (data.success) {
                cfg._connected = true; cfg._lastSuccess = true; cfg._lastResult = data.message;
                testBtn.textContent = '✅ 已连接'; testBtn.classList.add('connected');
                if (resultDiv) { resultDiv.className = 'mcp-result success show'; resultDiv.style.display = 'block'; resultDiv.textContent = data.message; }
                if (statusDot) statusDot.className = 'mcp-status-dot on';
                if (statusDiv) statusDiv.innerHTML = '<span class="mcp-status-dot on"></span>已就绪';
            } else {
                cfg._connected = false; cfg._lastSuccess = false; cfg._lastResult = data.error;
                testBtn.textContent = '❌ 失败'; testBtn.classList.remove('connected');
                if (resultDiv) { resultDiv.className = 'mcp-result failure show'; resultDiv.style.display = 'block'; resultDiv.textContent = data.error; }
            }
        } catch (e) {
            cfg._connected = false; cfg._lastSuccess = false;
            const msg = e.name === 'AbortError' ? '连接测试超时（10 秒）' : e.message;
            cfg._lastResult = msg;
            testBtn.textContent = '❌ 失败'; testBtn.classList.remove('connected');
            if (resultDiv) { resultDiv.className = 'mcp-result failure show'; resultDiv.style.display = 'block'; resultDiv.textContent = msg; }
            if (statusDot) statusDot.className = 'mcp-status-dot off';
            if (statusDiv) statusDiv.innerHTML = '<span class="mcp-status-dot off"></span>连接失败';
        }
        testBtn.disabled = false;
    });
}

// Email 面板（需要 SMTP 配置）
function renderMCPEmailPanel(container, comp) {
    if (!comp.mcpConfig) comp.mcpConfig = { smtpHost: '', smtpPort: 587, email: '', password: '', provider: 'gmail', sessionId: 'email_' + comp.id };
    if (comp.toolEnabled === undefined) comp.toolEnabled = true;
    const cfg = comp.mcpConfig;
    const connected = cfg._connected || false;
    const providers = [
        { id: 'gmail', name: 'Gmail' }, { id: 'outlook', name: 'Outlook' },
        { id: 'qq', name: 'QQ邮箱' }, { id: '163', name: '163邮箱' },
        { id: '126', name: '126邮箱' }, { id: 'custom', name: '自定义' },
    ];
    const provOpts = providers.map(p => `<option value="${p.id}" ${cfg.provider === p.id ? 'selected' : ''}>${p.name}</option>`).join('');

    container.className = 'module-panel';
    container.innerHTML = `
        <div class="tool-toggle-row">
            <span class="tool-status-dot ${comp.toolEnabled ? 'on' : 'off'}"></span>
            <span style="font-size:12px;font-weight:600;">${comp.toolEnabled ? '已开启' : '已关闭'}</span>
            <button class="tool-toggle-btn ${comp.toolEnabled ? 'on' : 'off'}" id="etog-${comp.id}">${comp.toolEnabled ? '关闭' : '开启'}</button>
        </div>
        <div class="mcp-panel">
            <div class="mcp-field">
                <label>邮箱类型</label>
                <select id="eprov-${comp.id}" style="width:100%;padding:6px;border-radius:4px;">${provOpts}</select>
            </div>
            <div class="mcp-field">
                <label>邮箱地址</label>
                <input id="eaddr-${comp.id}" placeholder="your@gmail.com" value="${escapeHtml(cfg.email)}">
            </div>
            <div class="mcp-field">
                <label>密码/授权码</label>
                <input type="password" id="epwd-${comp.id}" placeholder="应用专用密码或授权码" value="${escapeHtml(cfg.password)}">
                <span class="mcp-hint">Gmail: 需用<a href="https://myaccount.google.com/apppasswords" target="_blank" style="color:var(--primary);">应用专用密码</a>。QQ/163: SMTP授权码</span>
            </div>
            <div class="mcp-field" id="ecustom-fields-${comp.id}" style="display:${cfg.provider === 'custom' ? '' : 'none'};">
                <label>SMTP 服务器</label>
                <input id="ehost-${comp.id}" placeholder="smtp.example.com" value="${escapeHtml(cfg.smtpHost)}">
                <input id="eport-${comp.id}" type="number" placeholder="587" value="${cfg.smtpPort}" style="margin-top:4px;">
            </div>
            <div class="mcp-actions">
                <button class="mcp-test-btn ${connected ? 'connected' : ''}" id="etest-${comp.id}">${connected ? '✅ 已连接' : '🔍 测试连接'}</button>
            </div>
            <div id="eresult-${comp.id}" class="mcp-result ${cfg._lastResult ? 'show ' + (cfg._lastSuccess ? 'success' : 'failure') : ''}">${cfg._lastResult || ''}</div>
            <div class="mcp-status"><span class="mcp-status-dot ${connected ? 'on' : 'off'}"></span>${connected ? 'SMTP 已连接' : '未连接'}</div>
        </div>
    `;

    // Toggle
    const togBtn = container.querySelector(`#etog-${comp.id}`);
    if (togBtn) {
        const dot = container.querySelector('.tool-status-dot');
        togBtn.addEventListener('click', () => {
            comp.toolEnabled = !comp.toolEnabled;
            togBtn.textContent = comp.toolEnabled ? '关闭' : '开启';
            togBtn.className = `tool-toggle-btn ${comp.toolEnabled ? 'on' : 'off'}`;
            dot.className = `tool-status-dot ${comp.toolEnabled ? 'on' : 'off'}`;
            autoSaveConnections();
        });
    }

    // Provider selector
    const provSel = container.querySelector(`#eprov-${comp.id}`);
    const customFields = container.querySelector(`#ecustom-fields-${comp.id}`);
    provSel.addEventListener('change', () => { cfg.provider = provSel.value; customFields.style.display = provSel.value === 'custom' ? '' : 'none'; });

    // Input fields
    ['eaddr', 'epwd', 'ehost', 'eport'].forEach(id => {
        const el = container.querySelector(`#${id}-${comp.id}`);
        if (el) el.addEventListener('input', () => {
            if (id === 'eaddr') cfg.email = el.value;
            else if (id === 'epwd') cfg.password = el.value;
            else if (id === 'ehost') cfg.smtpHost = el.value;
            else if (id === 'eport') cfg.smtpPort = parseInt(el.value) || 587;
        });
    });

    // Test connection
    const testBtn = container.querySelector(`#etest-${comp.id}`);
    const resultDiv = container.querySelector(`#eresult-${comp.id}`);
    const statusDiv = container.querySelector('.mcp-status');
    const statusDot = statusDiv ? statusDiv.querySelector('.mcp-status-dot') : null;

    testBtn.addEventListener('click', async () => {
        testBtn.disabled = true; testBtn.textContent = '⏳ 测试中…';
        if (resultDiv) { resultDiv.className = 'mcp-result'; resultDiv.style.display = 'none'; }
        try {
            const resp = await fetch('/api/email/test-connection', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ provider: cfg.provider, email: cfg.email, password: cfg.password, smtp_host: cfg.smtpHost, smtp_port: cfg.smtpPort, session_id: cfg.sessionId }),
            });
            const data = await resp.json();
            if (data.success) {
                cfg._connected = true; cfg._lastSuccess = true; cfg._lastResult = data.message;
                testBtn.textContent = '✅ 已连接'; testBtn.classList.add('connected');
                if (resultDiv) { resultDiv.className = 'mcp-result success show'; resultDiv.style.display = 'block'; resultDiv.textContent = data.message; }
                if (statusDot) statusDot.className = 'mcp-status-dot on';
                if (statusDiv) statusDiv.innerHTML = '<span class="mcp-status-dot on"></span>SMTP 已连接';
            } else {
                cfg._connected = false; cfg._lastSuccess = false; cfg._lastResult = data.error;
                testBtn.textContent = '❌ 失败'; testBtn.classList.remove('connected');
                if (resultDiv) { resultDiv.className = 'mcp-result failure show'; resultDiv.style.display = 'block'; resultDiv.textContent = data.error; }
            }
        } catch (e) {
            cfg._connected = false; cfg._lastSuccess = false; cfg._lastResult = e.message;
            testBtn.textContent = '❌ 失败'; testBtn.classList.remove('connected');
            if (resultDiv) { resultDiv.className = 'mcp-result failure show'; resultDiv.style.display = 'block'; resultDiv.textContent = e.message; }
        }
        testBtn.disabled = false;
    });
}

// 导航面板（多提供商选择器 + API Key）
function renderMCPNavPanel(container, comp) {
    if (!comp.mcpConfig) comp.mcpConfig = { provider: 'amap', apiKey: '', sessionId: 'nav_' + comp.id };
    if (comp.toolEnabled === undefined) comp.toolEnabled = true;
    const cfg = comp.mcpConfig;
    const connected = cfg._connected || false;
    const providers = [
        { id: 'amap', name: '高德地图', hint: 'Web服务 Key', url: 'developer.amap.com' },
        { id: 'baidu', name: '百度地图', hint: '服务端 AK', url: 'lbsyun.baidu.com' },
        { id: 'google', name: 'Google Maps', hint: 'API Key', url: 'console.cloud.google.com' },
        { id: 'osrm', name: 'OSRM (免费)', hint: '无需 Key', url: null },
    ];
    const provOpts = providers.map(p => `<option value="${p.id}" ${cfg.provider === p.id ? 'selected' : ''}>${p.name}</option>`).join('');
    const selP = providers.find(p => p.id === cfg.provider) || providers[0];
    const showKey = selP.id !== 'osrm';

    container.className = 'module-panel';
    container.innerHTML = `
        <div class="tool-toggle-row">
            <span class="tool-status-dot ${comp.toolEnabled ? 'on' : 'off'}"></span>
            <span style="font-size:12px;font-weight:600;">${comp.toolEnabled ? '已开启' : '已关闭'}</span>
            <button class="tool-toggle-btn ${comp.toolEnabled ? 'on' : 'off'}" id="ntog-${comp.id}">${comp.toolEnabled ? '关闭' : '开启'}</button>
        </div>
        <div class="mcp-panel">
            <div class="mcp-field">
                <label>地图提供商</label>
                <select id="nprov-${comp.id}" style="width:100%;padding:6px;border-radius:4px;border:1px solid var(--border);">${provOpts}</select>
            </div>
            <div class="mcp-field" id="nkey-field-${comp.id}" style="display:${showKey ? '' : 'none'};">
                <label>${selP.hint}</label>
                <input id="napik-${comp.id}" placeholder="${selP.hint}" value="${escapeHtml(cfg.apiKey)}">
                <span class="mcp-hint">${selP.url ? '注册: ' + selP.url : '免费使用，无需 API Key'}</span>
            </div>
            <div class="mcp-actions">
                <button class="mcp-test-btn ${connected ? 'connected' : ''}" id="ntest-${comp.id}">${connected ? '已连接' : '测试连接'}</button>
            </div>
            <div id="nresult-${comp.id}" class="mcp-result ${cfg._lastResult ? 'show ' + (cfg._lastSuccess ? 'success' : 'failure') : ''}">${cfg._lastResult || ''}</div>
            <div class="mcp-status"><span class="mcp-status-dot ${connected ? 'on' : 'off'}"></span>${connected ? selP.name + ' 已连接' : '未连接'}</div>
        </div>
    `;

    // Toggle
    const togBtn = container.querySelector(`#ntog-${comp.id}`);
    if (togBtn) {
        const dot = container.querySelector('.tool-status-dot');
        togBtn.addEventListener('click', () => {
            comp.toolEnabled = !comp.toolEnabled;
            togBtn.textContent = comp.toolEnabled ? '关闭' : '开启';
            togBtn.className = `tool-toggle-btn ${comp.toolEnabled ? 'on' : 'off'}`;
            dot.className = `tool-status-dot ${comp.toolEnabled ? 'on' : 'off'}`;
            autoSaveConnections();
        });
    }

    // Provider selector
    const provSel = container.querySelector(`#nprov-${comp.id}`);
    const keyField = container.querySelector(`#nkey-field-${comp.id}`);
    const keyInput = container.querySelector(`#napik-${comp.id}`);
    const hintSpan = keyField ? keyField.querySelector('.mcp-hint') : null;

    provSel.addEventListener('change', () => {
        cfg.provider = provSel.value;
        const p = providers.find(pp => pp.id === provSel.value);
        if (p) {
            if (p.id === 'osrm') {
                keyField.style.display = 'none';
            } else {
                keyField.style.display = '';
                keyField.querySelector('label').textContent = p.hint;
                if (hintSpan) hintSpan.textContent = p.url ? '注册: ' + p.url : '免费使用';
                keyInput.placeholder = p.hint;
            }
        }
    });

    if (keyInput) keyInput.addEventListener('input', () => { cfg.apiKey = keyInput.value; });

    // Test connection
    const testBtn = container.querySelector(`#ntest-${comp.id}`);
    const resultDiv = container.querySelector(`#nresult-${comp.id}`);
    const statusDiv = container.querySelector('.mcp-status');
    const statusDot = statusDiv ? statusDiv.querySelector('.mcp-status-dot') : null;

    testBtn.addEventListener('click', async () => {
        testBtn.disabled = true; testBtn.textContent = 'testing...';
        if (resultDiv) { resultDiv.className = 'mcp-result'; resultDiv.style.display = 'none'; }
        try {
            const resp = await fetch('/api/navigation/test-connection', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ provider: cfg.provider, api_key: cfg.apiKey, session_id: cfg.sessionId }),
            });
            const data = await resp.json();
            if (data.success) {
                cfg._connected = true; cfg._lastSuccess = true; cfg._lastResult = data.message;
                testBtn.textContent = '已连接'; testBtn.classList.add('connected');
                if (resultDiv) { resultDiv.className = 'mcp-result success show'; resultDiv.style.display = 'block'; resultDiv.textContent = data.message; }
                if (statusDot) statusDot.className = 'mcp-status-dot on';
                const p = providers.find(pp => pp.id === cfg.provider);
                if (statusDiv) statusDiv.innerHTML = '<span class="mcp-status-dot on"></span>' + (p ? p.name : '') + ' 已连接';
            } else {
                cfg._connected = false; cfg._lastSuccess = false; cfg._lastResult = data.error;
                testBtn.textContent = '失败'; testBtn.classList.remove('connected');
                if (resultDiv) { resultDiv.className = 'mcp-result failure show'; resultDiv.style.display = 'block'; resultDiv.textContent = data.error; }
            }
        } catch (e) {
            cfg._connected = false; cfg._lastSuccess = false; cfg._lastResult = e.message;
            testBtn.textContent = '失败'; testBtn.classList.remove('connected');
            if (resultDiv) { resultDiv.className = 'mcp-result failure show'; resultDiv.style.display = 'block'; resultDiv.textContent = e.message; }
        }
        testBtn.disabled = false;
    });
}

// MCP 服务面板通用事件绑定（weather/database/git）
function bindMCPPanelEvents(container, comp, serviceName, fieldKeys) {
    const cfg = comp.mcpConfig;
    const prefixMap = { weather: 'w', database: 'db', git: 'g' };
    const pf = prefixMap[serviceName];
    const compId = comp.id;

    // 开关按钮
    const togBtn = container.querySelector(`#${pf}tog-${compId}`);
    if (togBtn) {
        const dot = container.querySelector('.tool-status-dot');
        togBtn.addEventListener('click', () => {
            comp.toolEnabled = !comp.toolEnabled;
            togBtn.textContent = comp.toolEnabled ? '关闭' : '开启';
            togBtn.className = `tool-toggle-btn ${comp.toolEnabled ? 'on' : 'off'}`;
            dot.className = `tool-status-dot ${comp.toolEnabled ? 'on' : 'off'}`;
            autoSaveConnections();
        });
    }

    // 输入字段
    const inputMap = {
        weather: { apiKey: `#wapik-${compId}`, city: `#wcity-${compId}` },
        database: { dbPath: `#dbpath-${compId}` },
        git: { repoPath: `#gpath-${compId}` },
    };
    const fields = inputMap[serviceName];
    if (fields) {
        Object.entries(fields).forEach(([key, sel]) => {
            const el = container.querySelector(sel);
            if (el) {
                el.addEventListener('input', () => { cfg[key] = el.value; });
            }
        });
    }

    // 测试连接按钮
    const testBtn = container.querySelector(`#${pf}test-${compId}`);
    const resultDiv = container.querySelector(`#${pf}result-${compId}`);
    const statusDiv = container.querySelector('.mcp-status');
    const statusDot = statusDiv ? statusDiv.querySelector('.mcp-status-dot') : null;
    const testUrls = {
        weather: '/api/weather/test-connection',
        database: '/api/database/test-connection',
        git: '/api/git/test-connection',
    };
    const testBodyMap = {
        weather: () => ({ api_key: cfg.apiKey, city: cfg.city, session_id: cfg.sessionId }),
        database: () => ({ db_path: cfg.dbPath, session_id: cfg.sessionId }),
        git: () => ({ repo_path: cfg.repoPath, session_id: cfg.sessionId }),
    };

    testBtn.addEventListener('click', async () => {
        testBtn.disabled = true;
        testBtn.textContent = '⏳ 测试中…';
        if (resultDiv) { resultDiv.className = 'mcp-result'; resultDiv.style.display = 'none'; }

        try {
            const resp = await fetch(testUrls[serviceName], {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(testBodyMap[serviceName]()),
            });
            const data = await resp.json();

            if (data.success) {
                cfg._connected = true;
                cfg._lastSuccess = true;
                cfg._lastResult = data.message;
                testBtn.textContent = '✅ 已连接';
                testBtn.classList.add('connected');
                if (resultDiv) { resultDiv.className = 'mcp-result success show'; resultDiv.style.display = 'block'; resultDiv.innerHTML = `<strong>${escapeHtml(data.message)}</strong><br><span style="font-size:10px;">延迟: ${data.latency_ms}ms</span>`; }
                if (statusDot) statusDot.className = 'mcp-status-dot on';
                if (statusDiv) statusDiv.innerHTML = '<span class="mcp-status-dot on"></span>已连接';
            } else {
                cfg._connected = false;
                cfg._lastSuccess = false;
                cfg._lastResult = data.error;
                testBtn.textContent = '❌ 连接失败';
                testBtn.classList.remove('connected');
                if (resultDiv) { resultDiv.className = 'mcp-result failure show'; resultDiv.style.display = 'block'; resultDiv.textContent = data.error; }
                if (statusDot) statusDot.className = 'mcp-status-dot off';
                if (statusDiv) statusDiv.innerHTML = '<span class="mcp-status-dot off"></span>未连接';
            }
        } catch (e) {
            cfg._connected = false;
            cfg._lastSuccess = false;
            cfg._lastResult = e.message;
            testBtn.textContent = '❌ 请求失败';
            testBtn.classList.remove('connected');
            if (resultDiv) { resultDiv.className = 'mcp-result failure show'; resultDiv.style.display = 'block'; resultDiv.textContent = e.message; }
        }
        testBtn.disabled = false;
    });
}

// ============================================================
// 技能面板
// ============================================================
function renderSkillPanel(skillId, tools) {
    return function(container, comp) {
        if (comp.toolEnabled === undefined) comp.toolEnabled = true;
        container.className = 'module-panel';

        // 收集当前画布中所有"已连线"的工具函数名
        const connectedToolNames = new Set();
        STATE.components.forEach(c => {
            const names = TOOL_NAME_MAP[c.type];
            if (names && names.length > 0) {
                const hasConn = STATE.connections.some(
                    conn => conn.sourceCompId === c.id || conn.targetCompId === c.id
                );
                if (hasConn) {
                    names.forEach(n => connectedToolNames.add(n));
                }
            }
        });

        // 判断推荐工具是否有连线：拆分速记名（如 pdf_read/create/merge），任意子项匹配即视为已连线
        function isToolConnected(toolLabel) {
            const parts = toolLabel.split('/');
            return parts.some(p => connectedToolNames.has(p.trim()));
        }

        fetch('/api/skills/' + skillId)
            .then(r => r.json())
            .then(skill => {
                const skillComps = skill.recommended_components || [];
                container.innerHTML = `
                    <div class="tool-toggle-row">
                        <span class="tool-status-dot ${comp.toolEnabled ? 'on' : 'off'}"></span>
                        <span style="font-size:12px;font-weight:600;">${comp.toolEnabled ? '已激活' : '已关闭'}</span>
                        <button class="tool-toggle-btn ${comp.toolEnabled ? 'on' : 'off'}" id="sktog-${comp.id}">${comp.toolEnabled ? '关闭' : '开启'}</button>
                    </div>
                    <div style="padding:8px 12px;">
                        <div style="font-size:13px;font-weight:700;color:var(--text-primary);margin-bottom:4px;">${escapeHtml(skill.name)}</div>
                        <div style="font-size:11px;color:var(--text-muted);line-height:1.5;margin-bottom:8px;">${escapeHtml(skill.description)}</div>
                        <div style="font-size:10px;color:var(--text-secondary);margin-bottom:4px;">推荐工具:</div>
                        <div style="display:flex;flex-wrap:wrap;gap:3px;margin-bottom:${skillComps.length > 0 ? '6px' : '0'};">
                            ${tools.map(t => {
                                const connected = isToolConnected(t);
                                const style = connected
                                    ? 'background:var(--bg-input);padding:2px 6px;border-radius:3px;font-size:9px;'
                                    : 'background:#fff0f0;border:1px solid #ff4d4f;color:#ff4d4f;padding:2px 6px;border-radius:3px;font-size:9px;';
                                const title = connected ? '' : ' title="未连接"';
                                return `<span style="${style}"${title}>${t}</span>`;
                            }).join('')}
                        </div>
                        ${skillComps.length > 0 ? `
                        <div style="font-size:10px;color:#8b5cf6;margin-bottom:4px;">📦 需连接组件:</div>
                        <div style="display:flex;flex-wrap:wrap;gap:3px;margin-bottom:6px;">
                            ${skillComps.map(c => `<span style="background:#f3f0ff;border:1px solid #d3c5f5;padding:2px 6px;border-radius:3px;font-size:9px;color:#722ed1;">${escapeHtml(c.name)}</span>`).join('')}
                        </div>
                        ` : ''}
                        <div style="font-size:9px;color:var(--primary);margin-top:8px;">💡 连线到 LLM 或 Agent 注入技能</div>
                    </div>
                `;

                const togBtn = container.querySelector(`#sktog-${comp.id}`);
                if (togBtn) {
                    const dot = container.querySelector('.tool-status-dot');
                    togBtn.addEventListener('click', () => {
                        comp.toolEnabled = !comp.toolEnabled;
                        togBtn.textContent = comp.toolEnabled ? '关闭' : '开启';
                        togBtn.className = `tool-toggle-btn ${comp.toolEnabled ? 'on' : 'off'}`;
                        dot.className = `tool-status-dot ${comp.toolEnabled ? 'on' : 'off'}`;
                        autoSaveConnections();
                    });
                }
            })
            .catch(() => {
                container.innerHTML = '<div style="padding:12px;text-align:center;color:var(--text-muted);">加载技能失败</div>';
            });
    };
}

// ============================================================
// 简单工具面板（通用：时间查询 / 网页抓取 / 文件操作 / JSON 查询）
// ============================================================
function renderTokenCounterPanel(container, comp) {
    if (comp.toolEnabled === undefined) comp.toolEnabled = true;
    container.className = 'module-panel';
    const connected = STATE.connections.some(c =>
        (c.targetCompId === comp.id || c.sourceCompId === comp.id));
    const on = comp.toolEnabled !== false;
    container.innerHTML = `
        <div class="tool-toggle-row">
            <span class="tool-status-dot ${on ? 'on' : 'off'}"></span>
            <span style="font-size:12px;font-weight:600;">${on ? '已开启' : '已关闭'}</span>
            <button class="tool-toggle-btn ${on ? 'on' : 'off'}" id="tctog-${comp.id}">${on ? '关闭' : '开启'}</button>
        </div>
        <div style="text-align:center;color:var(--text-muted);padding:16px 10px;">
            <div style="font-size:22px;">🧮</div>
            <div style="font-size:12px;margin-top:6px;color:${connected ? 'var(--success,#52c41a)' : 'var(--text-muted)'};">
                ${connected ? '已连接 LLM ✅' : '未连接 LLM'}
            </div>
            <div style="font-size:10px;margin-top:4px;">连接 LLM 后，对话页输入框上方显示本次对话 Token 用量</div>
        </div>
    `;
    const togBtn = container.querySelector(`#tctog-${comp.id}`);
    const dot = container.querySelector('.tool-status-dot');
    togBtn.addEventListener('click', () => {
        comp.toolEnabled = !on;
        togBtn.textContent = comp.toolEnabled === false ? '开启' : '关闭';
        togBtn.className = `tool-toggle-btn ${comp.toolEnabled === false ? 'off' : 'on'}`;
        dot.className = `tool-status-dot ${comp.toolEnabled === false ? 'off' : 'on'}`;
        autoSaveConnections();
    });
}

function renderKnowledgeBasePanel(container, comp) {
    if (!comp.vectorDocs) comp.vectorDocs = [];
    if (comp.toolEnabled === undefined) comp.toolEnabled = true;
    const docs = comp.vectorDocs || [];
    container.className = 'module-panel';
    container.innerHTML = `
        <div class="tool-toggle-row">
            <span class="tool-status-dot ${comp.toolEnabled ? 'on' : 'off'}"></span>
            <span style="font-size:12px;font-weight:600;">${comp.toolEnabled ? '已开启' : '已关闭'}</span>
            <button class="tool-toggle-btn ${comp.toolEnabled ? 'on' : 'off'}" id="kbtog-${comp.id}">${comp.toolEnabled ? '关闭' : '开启'}</button>
        </div>
        <div class="module-field">
            <label>📛 名称</label>
            <input class="module-input" id="kbname-${comp.id}" value="${escapeHtml(comp.name || '知识库')}" style="font-size:11px;">
        </div>
        <div class="module-field">
            <label>📄 导入文件（.txt / .md / .csv / .json / .pdf / .docx / .xlsx）</label>
            <button class="module-btn" id="kbfile-${comp.id}" style="font-size:11px;width:100%;">📂 从电脑选择文件</button>
            <input type="file" id="kbfileinput-${comp.id}" accept=".txt,.md,.csv,.json,.pdf,.docx,.xlsx,text/plain,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" style="display:none;">
        </div>
        <div class="module-field">
            <label>⌨️ 或直接粘贴文本</label>
            <textarea class="module-textarea" id="kbtext-${comp.id}" placeholder="粘贴要加入知识库的内容…" rows="4" style="font-size:11px;"></textarea>
            <button class="module-btn" id="kbadd-${comp.id}" style="font-size:11px;width:100%;margin-top:4px;">📥 导入知识库</button>
        </div>
        <div class="module-result" id="kbmsg-${comp.id}" style="display:none;"></div>
        <div class="vm-doc-header">
            <span>📚 知识库文档</span>
            <span class="vm-doc-count">${docs.length} 条</span>
        </div>
        <div class="module-list" id="kblist-${comp.id}" style="max-height:150px;">
            ${docs.length === 0
                ? '<div style="font-size:11px;color:var(--text-muted);padding:8px;text-align:center;">知识库为空，请导入文本</div>'
                : docs.map((d, i) => `
                    <div class="module-list-item" style="flex-direction:column;align-items:flex-start;gap:3px;">
                        <div style="font-size:11px;font-weight:600;">📄 ${escapeHtml(d.title || ('文档 ' + (i + 1)))}</div>
                        <div style="font-size:10px;color:var(--text-muted);">${escapeHtml((d.text || d.content || '').slice(0, 80))}</div>
                    </div>`).join('')
            }
        </div>
    `;

    // 开关
    const togBtn = container.querySelector(`#kbtog-${comp.id}`);
    const dot = container.querySelector('.tool-status-dot');
    togBtn.addEventListener('click', () => {
        comp.toolEnabled = !comp.toolEnabled;
        togBtn.textContent = comp.toolEnabled ? '关闭' : '开启';
        togBtn.className = `tool-toggle-btn ${comp.toolEnabled ? 'on' : 'off'}`;
        dot.className = `tool-status-dot ${comp.toolEnabled ? 'on' : 'off'}`;
        autoSaveConnections();
    });

    // 改名
    const nameInput = container.querySelector(`#kbname-${comp.id}`);
    nameInput.addEventListener('change', () => {
        const v = nameInput.value.trim();
        if (v && v !== comp.name) {
            comp.name = v;
            renderAll();
        }
    });

    // 从电脑导入文件（multipart 上传，后端按格式解析）
    const fileBtn = container.querySelector(`#kbfile-${comp.id}`);
    const fileInput = container.querySelector(`#kbfileinput-${comp.id}`);
    fileBtn.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', () => {
        const f = fileInput.files[0];
        if (!f) return;
        _kbImportFile(comp, f, container);
        fileInput.value = '';
    });

    // 粘贴文本导入
    const addBtn = container.querySelector(`#kbadd-${comp.id}`);
    const textarea = container.querySelector(`#kbtext-${comp.id}`);
    addBtn.addEventListener('click', () => {
        const text = (textarea.value || '').trim();
        _kbImport(comp, text, container, '');
        textarea.value = '';
    });
}

/** 导入文本到知识库（调用 /api/vector-memory/documents 向量化存储） */
function _kbImport(comp, text, container, title) {
    const msgEl = container.querySelector(`#kbmsg-${comp.id}`);
    if (!msgEl) return;
    if (!text) {
        msgEl.style.display = 'block';
        msgEl.textContent = '⚠️ 请选择文件或输入文本';
        return;
    }
    msgEl.style.display = 'block';
    msgEl.textContent = '⏳ 正在向量化导入…';
    fetch('/api/vector-memory/documents', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: text.slice(0, 20000) }),
    })
    .then(r => r.json())
    .then(d => {
        if (!d.success) {
            msgEl.textContent = '❌ ' + (d.error || '导入失败');
            return;
        }
        msgEl.textContent = '✅ ' + (d.result || '导入成功');
        // 刷新文档列表
        return fetch('/api/vector-memory/documents')
            .then(r => r.json())
            .then(dd => {
                if (dd.success) {
                    comp.vectorDocs = dd.documents || [];
                    if (title && dd.documents && dd.documents.length > 0) {
                        comp.vectorDocs[comp.vectorDocs.length - 1].title = title;
                    }
                }
                renderAll();
            });
    })
    .catch(e => { msgEl.textContent = '❌ ' + e.message; });
}

/** 上传文件到后端解析并导入知识库（支持 pdf/docx/xlsx/txt/md/csv/json） */
function _kbImportFile(comp, file, container) {
    const msgEl = container.querySelector(`#kbmsg-${comp.id}`);
    if (!msgEl) return;
    msgEl.style.display = 'block';
    msgEl.textContent = `⏳ 正在解析并导入 ${file.name} …`;
    const fd = new FormData();
    fd.append('file', file);
    fetch('/api/vector-memory/import-file', { method: 'POST', body: fd })
    .then(r => r.json())
    .then(d => {
        if (!d.success) {
            msgEl.textContent = '❌ ' + (d.error || '导入失败');
            return;
        }
        msgEl.textContent = '✅ ' + (d.result || '导入成功') + `（${d.chars || 0} 字符）`;
        return fetch('/api/vector-memory/documents')
            .then(r => r.json())
            .then(dd => {
                if (dd.success) {
                    comp.vectorDocs = dd.documents || [];
                    if (dd.documents && dd.documents.length > 0) {
                        comp.vectorDocs[comp.vectorDocs.length - 1].title = '📄 ' + file.name;
                    }
                }
                renderAll();
            });
    })
    .catch(e => { msgEl.textContent = '❌ ' + e.message; });
}

function renderSimpleToolPanel(toolName, desc) {
    return function(container, comp) {
        if (comp.toolEnabled === undefined) comp.toolEnabled = true;
        container.className = 'module-panel';
        container.innerHTML = `
            <div class="tool-toggle-row">
                <span class="tool-status-dot ${comp.toolEnabled ? 'on' : 'off'}"></span>
                <span style="font-size:12px;font-weight:600;">${comp.toolEnabled ? '已开启' : '已关闭'}</span>
                <button class="tool-toggle-btn ${comp.toolEnabled ? 'on' : 'off'}" id="tog-${comp.id}">
                    ${comp.toolEnabled ? '关闭' : '开启'}
                </button>
            </div>
            <div style="text-align:center;color:var(--text-muted);padding:16px 10px;">
                <div style="font-size:12px;">${escapeHtml(desc)}</div>
                <div style="font-size:10px;margin-top:4px;">连线到 LLM 后自动调用</div>
            </div>
        `;

        const togBtn = container.querySelector(`#tog-${comp.id}`);
        const dot = container.querySelector('.tool-status-dot');
        togBtn.addEventListener('click', () => {
            comp.toolEnabled = !comp.toolEnabled;
            togBtn.textContent = comp.toolEnabled ? '关闭' : '开启';
            togBtn.className = `tool-toggle-btn ${comp.toolEnabled ? 'on' : 'off'}`;
            dot.className = `tool-status-dot ${comp.toolEnabled ? 'on' : 'off'}`;
            autoSaveConnections();
        });
    };
}

// ============================================================
// 工具栏
// ============================================================
function bindToolbarButtons() {
    document.getElementById('btn-save').addEventListener('click', saveLayout);
    document.getElementById('btn-load').addEventListener('click', loadLayout);
    document.getElementById('btn-clear').addEventListener('click', clearCanvas);
    document.getElementById('btn-undo').addEventListener('click', undo);

    // 退出登录：登出后清本地 LLM 配置并回登录页
    const btnLogout = document.getElementById('btn-logout');
    if (btnLogout) btnLogout.addEventListener('click', async () => {
        try { await fetch('/api/auth/logout', { method: 'POST' }); } catch (e) {}
        try { localStorage.removeItem('active-llm-config'); } catch (e) {}
        location.href = '/login';
    });

    // Ctrl+Z 撤回快捷键
    document.addEventListener('keydown', (e) => {
        if (e.ctrlKey && e.key === 'z' && !e.shiftKey && !e.metaKey) {
            // 不在输入框中触发
            const tag = e.target.tagName;
            if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
            e.preventDefault();
            undo();
        }
        // Delete / Backspace 删除：优先多选组，其次单选
        if ((e.key === 'Delete' || e.key === 'Backspace') && !e.ctrlKey && !e.metaKey && !e.altKey) {
            const tag = e.target.tagName;
            if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
            e.preventDefault();
            if (STATE.multiSelected.length > 0) {
                removeComponents(STATE.multiSelected);
            } else if (STATE.selectedCompId != null) {
                removeComponent(STATE.selectedCompId);
            }
        }
    });

    const chatLink = document.getElementById('btn-chat-link');
    if (chatLink) {
        chatLink.addEventListener('click', (e) => {
            if (STATE.components.length > 0) {
                autoSaveConnections();  // 同步工具名到 storage，聊天页需要用到
                saveLayout();
            }
            // 传递项目 ID 到聊天页面，实现项目级对话隔离
            if (CURRENT_PROJECT.id) {
                chatLink.href = '/chat?project=' + encodeURIComponent(CURRENT_PROJECT.id);
            } else {
                chatLink.href = '/chat';
            }
        });
    }
}

// API provider presets (pulled from backend /api/meta/components provider_presets, see applyMeta)

// 自定义接口（从 localStorage 加载）
function loadCustomProviders() {
    try {
        const raw = localStorage.getItem('custom-api-providers');
        return raw ? JSON.parse(raw) : [];
    } catch (e) { return []; }
}
function saveCustomProviders(providers) {
    localStorage.setItem('custom-api-providers', JSON.stringify(providers));
}
function getAllProviders() {
    return [...PROVIDERS, ...loadCustomProviders()];
}

// 暴露到全局
window.resizeComponent = resizeComponent;
window.removeComponent = removeComponent;

// ============================================================
// 工具调用监控面板
// ============================================================
// ToolMonitor 定义在 common.js 中（与 chat.html 共享）

// ============================================================
// 启动
// ============================================================
// 从所有 LLM/Memory 组件统计 token 数
function updateMemoryPanelFromState() {
    let maxTokens = 0;
    STATE.components.forEach(c => {
        if ((c.type === 'llm' || c.type === 'memory') && c.messages) {
            const { tokens } = MemoryPanel.calcTokens(c.messages);
            maxTokens = Math.max(maxTokens, tokens);
        }
    });
    MemoryPanel.update(maxTokens);
}

document.addEventListener('DOMContentLoaded', () => { init(); ToolMonitor.init(); MemoryPanel.init(); });
