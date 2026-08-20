/**
 * wybzd · AI 对话 — 前端逻辑
 * SSE 流式聊天、消息管理、对话历史持久化
 * 自动读取后端管理页同步的 API 配置
 */

// ============================================================
// 状态
// ============================================================
const chatState = {
    messages: [],
    model: '--',
    apiBase: '',
    apiKey: '',
    toolNames: [],
    fromBackend: false,
    projectId: null,      // 当前项目 ID（URL 参数 ?project=xxx）
    projectName: '',      // 当前项目名称
    activeSkill: '',      // 当前选中的技能 ID
    skillPrompts: {},     // { skillId: systemPrompt }
    skillTools: {},       // { skillId: [toolNames] }
    skillComponents: {},  // { skillId: [{type, name, tools}] }
    smartMode: false,     // 智能模式：LLM 自主选择技能
    tokenCounter: false,  // Token 计数器：编辑器连接后对话页显示用量
};

// ============================================================
// DOM 引用
// ============================================================
const chatMessages = document.getElementById('chat-messages');
const chatEmpty = document.getElementById('chat-empty');
const chatInput = document.getElementById('chat-input');
const btnSend = document.getElementById('btn-send');
const btnClear = document.getElementById('btn-clear-chat');
const btnStop = document.getElementById('btn-stop');
let abortController = null;   // 当前请求的取消控制器
const modelBadge = document.getElementById('chat-model');

// ============================================================
// 主题 & 显示设置（与编辑器设置面板共享 localStorage）
// ============================================================
(function restoreTheme() {
    const saved = safeStorage.get('wybzd-theme') || 'industrial';
    document.documentElement.setAttribute('data-theme', saved);
})();

(function restoreDisplaySettings() {
    // 字体大小（zoom）与行距（--ui-lh），与编辑器设置面板共享数值。
    // 注意：仅在非默认字号时设置 zoom，避免与画布 transform 合成层冲突（Chromium bug）
    const fs = parseFloat(safeStorage.get('wybzd-font-size'));
    if (fs >= 0.5 && fs <= 2 && Math.abs(fs - 1) > 0.001) {
        document.documentElement.style.zoom = fs;
    } else {
        document.documentElement.style.zoom = '';
    }
    const lh = parseFloat(safeStorage.get('wybzd-line-height'));
    document.documentElement.style.setProperty('--ui-lh', String((lh >= 1.0 && lh <= 3) ? lh : 1.6));
})();

// ============================================================
// 项目上下文
// ============================================================
function parseProjectFromURL() {
    const params = new URLSearchParams(window.location.search);
    return params.get('project') || null;
}

function getHistoryKey() {
    const pid = chatState.projectId;
    return pid ? `chat-history-${pid}` : 'chat-history';
}

function getProjectSessionId() {
    const pid = chatState.projectId;
    return pid ? `chat_${pid}` : 'chat_noproject';
}

async function loadProjectInfo() {
    const pid = chatState.projectId;
    if (!pid) return;
    try {
        const resp = await fetch(`/api/projects/${encodeURIComponent(pid)}`);
        if (resp.ok) {
            const data = await resp.json();
            chatState.projectName = data.name || '';
        }
    } catch (e) { /* ignore */ }
    // 更新 header 显示
    const badge = document.getElementById('chat-project-badge');
    if (badge && chatState.projectName) {
        badge.textContent = '📁 ' + chatState.projectName;
        badge.style.display = '';
    }
}

// ============================================================
// 技能管理（仅显示编辑器中已连接到 Skills Manager 的技能）
// ============================================================
async function loadSkills() {
    const sel = document.getElementById('chat-skill-select');
    if (!sel) return;

    // 从编辑器同步的配置中读取可用技能列表和智能模式状态
    const raw = safeStorage.getRaw('active-llm-config');
    let allowedSkillIds = [];
    if (raw) {
        try {
            const cfg = JSON.parse(raw);
            if (cfg.skills && Array.isArray(cfg.skills)) {
                allowedSkillIds = cfg.skills.map(s => s.id);
            }
            // 读取智能模式状态
            chatState.smartMode = cfg.smartMode === true;
        } catch (e) { /* ignore */ }
    }

    // 如果没有配置技能，清空下拉框并隐藏智能模式选项
    if (allowedSkillIds.length === 0) {
        sel.innerHTML = '<option value="">🎯 通用模式（未配置技能）</option>';
        sel.title = '请在编辑器中连接技能到 Skills Manager 组件';
        sel.style.borderColor = '';
        // 有 smartMode 配置时仍显示智能模式选项
        if (chatState.smartMode) {
            sel.innerHTML += '<option value="__smart__" style="color:#7c3aed;">🧠 智能模式</option>';
            sel.title = '智能模式可用（需在编辑器中配置 Skill Auto Call）';
        }
        return;
    }

    // 构建选项：通用模式 + 智能模式 + 各技能
    sel.innerHTML = '<option value="">🎯 通用模式</option>';
    // 有 smartMode 配置时显示智能模式选项
    if (chatState.smartMode) {
        sel.innerHTML += '<option value="__smart__" style="color:#7c3aed;font-weight:500;">🧠 智能模式（自主选择）</option>';
    }

    // 一次请求获取所有技能数据（列表接口已包含 prompt）
    try {
        const resp = await fetch('/api/skills');
        if (resp.ok) {
            const allSkills = await resp.json();
            const allowedSet = new Set(allowedSkillIds);
            for (const s of allSkills) {
                if (!allowedSet.has(s.id)) continue;
                chatState.skillPrompts[s.id] = s.system_prompt || '';
                chatState.skillTools[s.id] = s.recommended_tools || [];
                chatState.skillComponents[s.id] = s.recommended_components || [];

                const opt = document.createElement('option');
                opt.value = s.id;
                opt.textContent = `${s.icon || '📋'} ${s.name}`;
                let tip = s.description || '';
                const comps = s.recommended_components || [];
                if (comps.length > 0) {
                    tip += '\n\n📦 推荐组件: ' + comps.map(c => c.name).join('、');
                }
                opt.title = tip;
                sel.appendChild(opt);
            }
        }
    } catch (e) { /* ignore */ }

    // 恢复上次选中的技能
    const savedSkill = safeStorage.get('wybzd-active-skill');
    if (savedSkill && savedSkill === '__smart__') {
        sel.value = '__smart__';
        chatState.smartMode = true;
        sel.style.borderColor = '#7c3aed';
    } else if (savedSkill && chatState.skillPrompts[savedSkill]) {
        sel.value = savedSkill;
        chatState.activeSkill = savedSkill;
        chatState.smartMode = false;
        checkSkillToolsWarning();
    } else if (chatState.smartMode && allowedSkillIds.length > 0) {
        // 编辑器配置了智能模式且无已保存的手动选择 → 默认智能模式
        sel.value = '__smart__';
        sel.style.borderColor = '#7c3aed';
    }
}

function onSkillChange() {
    const sel = document.getElementById('chat-skill-select');
    if (!sel) return;
    const val = sel.value;

    if (val === '__smart__') {
        // 智能模式
        chatState.activeSkill = '';
        chatState.smartMode = true;
        safeStorage.set('wybzd-active-skill', '__smart__');
        clearSkillWarning();
        sel.style.borderColor = '#7c3aed';
        showToast('🧠 智能模式 — LLM 将自主选择技能', 'info');
    } else {
        chatState.activeSkill = val;
        chatState.smartMode = false;
        safeStorage.set('wybzd-active-skill', val);
        sel.style.borderColor = '';
        if (val) {
            checkSkillToolsWarning();
        } else {
            clearSkillWarning();
        }
    }
}

function checkSkillToolsWarning() {
    const skillId = chatState.activeSkill;
    if (!skillId) return;
    const recommended = chatState.skillTools[skillId] || [];
    const components = chatState.skillComponents[skillId] || [];
    if (recommended.length === 0 && components.length === 0) return;

    // 收集当前配置中可用的工具
    const availableTools = new Set(chatState.toolNames || []);
    const raw = safeStorage.getRaw('active-llm-config');
    if (raw) {
        try {
            const cfg = JSON.parse(raw);
            (cfg.tool_names || []).forEach(t => availableTools.add(t));
        } catch (e) { /* ignore */ }
    }

    const missingTools = recommended.filter(t => !availableTools.has(t));
    // 检查哪些组件还没配齐（组件内任何一个工具缺失就算没配齐）
    const missingComps = components.filter(comp => {
        return comp.tools.some(t => !availableTools.has(t));
    });

    const sel = document.getElementById('chat-skill-select');

    if (missingTools.length > 0 || missingComps.length > 0) {
        sel.style.borderColor = '#faad14';
        const parts = [];
        if (missingTools.length > 0) parts.push('缺少工具: ' + missingTools.join(', '));
        if (missingComps.length > 0) {
            parts.push('需连接组件: ' + missingComps.map(c => c.name + ' (' + c.type + ')').join(', '));
        }
        sel.title = '⚠️ ' + parts.join(' | ') + '。请在编辑器中添加对应组件。';
        showSkillWarning(missingTools, missingComps);
    } else {
        sel.style.borderColor = '#52c41a';
        sel.title = '✅ 所有推荐工具和组件已配置';
        clearSkillWarning();
    }
}

function showSkillWarning(missingTools, missingComps) {
    let warnEl = document.getElementById('skill-warning');
    if (!warnEl) {
        warnEl = document.createElement('span');
        warnEl.id = 'skill-warning';
        warnEl.style.cssText = 'font-size:11px;color:#faad14;margin-left:4px;cursor:help;';
        const sel = document.getElementById('chat-skill-select');
        if (sel && sel.parentNode) {
            sel.parentNode.insertBefore(warnEl, sel.nextSibling);
        }
    }
    const parts = [];
    if (missingTools && missingTools.length > 0) parts.push('缺少工具: ' + missingTools.join(', '));
    if (missingComps && missingComps.length > 0) {
        parts.push('需连接组件: ' + missingComps.map(c => c.name).join(', '));
    }
    warnEl.textContent = '⚠️';
    warnEl.title = parts.join('\n') + '\n请在编辑器中添加对应组件并连线到 LLM。';
}

function clearSkillWarning() {
    const warnEl = document.getElementById('skill-warning');
    if (warnEl) warnEl.remove();
    const sel = document.getElementById('chat-skill-select');
    if (sel && !chatState.activeSkill) {
        sel.style.borderColor = '';
        sel.title = '';
    }
}

// ============================================================
// 初始化
// ============================================================
async function init() {
    chatState.projectId = parseProjectFromURL();
    // 登录后先从后端拉取设置合并到 localStorage（后端优先，loadActiveConfig 之前）
    await pullSettingsFromBackend();
    loadActiveConfig();
    await loadConfig();
    if (chatState.projectId) {
        await loadProjectInfo();
    }
    loadHistory();
    await loadSkills();
    updateTokenBar();
    bindEvents();
}

/**
 * 读取后端管理页同步的 API 配置
 */
function loadActiveConfig() {
    const raw = safeStorage.getRaw('active-llm-config');
    if (!raw) return;

    try {
        const cfg = JSON.parse(raw);
        if (cfg.apiBase) chatState.apiBase = cfg.apiBase;
        if (cfg.apiKey) chatState.apiKey = cfg.apiKey;
        if (cfg.model) chatState.model = cfg.model;
        if (cfg.tool_names) chatState.toolNames = cfg.tool_names;
        if (cfg.tokenCounter) chatState.tokenCounter = true;
        chatState.fromBackend = true;

        const toolInfo = chatState.toolNames.length > 0 ? ` · ${chatState.toolNames.length} tools` : '';
        modelBadge.textContent = `模型: ${cfg.model || cfg.provider || '自定义'}${toolInfo}`;
        modelBadge.style.background = '#e6fffb';
        modelBadge.style.border = '1px solid #87e8de';
        modelBadge.style.color = '#006d75';
    } catch (e) { /* ignore */ }
}

// 登录后拉取后端设置合并到 localStorage（后端优先，覆盖本地同 key 值）
async function pullSettingsFromBackend() {
    try {
        const resp = await fetch('/api/settings');
        if (!resp.ok) return;
        const data = await resp.json();
        if (data && data.success && data.settings && data.settings.llm_config) {
            safeStorage.set('active-llm-config', data.settings.llm_config);
        }
    } catch (e) { /* 未登录/网络错误静默跳过 */ }
}

async function loadConfig() {
    if (chatState.fromBackend) return;
    try {
        const resp = await fetch('/api/config');
        const config = await resp.json();
        chatState.model = config.model;
        modelBadge.textContent = `模型: ${config.model}`;
    } catch (e) {
        if (!chatState.model || chatState.model === '--') {
            chatState.model = 'gpt-3.5-turbo';
        }
        modelBadge.textContent = '模型: 未连接（使用默认）';
    }
}

/** 更新 Token 用量行（编辑器连接 Token 计数器组件后显示） */
function updateTokenBar() {
    const bar = document.getElementById('chat-token-bar');
    const countEl = document.getElementById('chat-token-count');
    if (!bar || !countEl) return;
    if (!chatState.tokenCounter) {
        bar.style.display = 'none';
        return;
    }
    bar.style.display = '';
    const { tokens } = MemoryPanel.calcTokens(chatState.messages);
    const maxK = Math.round(MemoryPanel.MAX_CHARS / MemoryPanel.CHARS_PER_TOKEN / 1000);
    countEl.textContent = `${formatTokens(tokens)} / ~${maxK}K`;
}

function bindEvents() {
    btnSend.addEventListener('click', sendMessage);
    btnClear.addEventListener('click', clearHistory);
    chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
    // 技能选择器
    const skillSelect = document.getElementById('chat-skill-select');
    if (skillSelect) {
        skillSelect.addEventListener('change', onSkillChange);
    }
    // 记忆面板清空按钮
    const memClearBtn = document.getElementById('mem-clear-btn');
    if (memClearBtn) {
        memClearBtn.addEventListener('click', clearHistory);
    }
    // 手动压缩记忆按钮 + 阈值输入 — 仅当编辑器中有总结组件连线时才显示
    const memSummBtn = document.getElementById('mem-summarize-btn');
    const thresholdRow = document.getElementById('mem-threshold-row');
    const thresholdInput = document.getElementById('mem-auto-threshold');

    const appCfg = getAppConfig();
    const summCfg = appCfg?.summarizer;
    if (summCfg && summCfg.enabled) {
        if (memSummBtn) {
            memSummBtn.style.display = '';
            memSummBtn.addEventListener('click', doSummarize);
        }
        if (thresholdRow) thresholdRow.style.display = '';
        if (thresholdInput) {
            thresholdInput.value = summCfg.threshold || 14000;
            thresholdInput.addEventListener('change', () => {
                const val = parseInt(thresholdInput.value) || 14000;
                MemoryPanel.setThreshold(val);
            });
            MemoryPanel.setThreshold(summCfg.threshold || 14000);
        }
    } else {
        if (memSummBtn) memSummBtn.style.display = 'none';
        if (thresholdRow) thresholdRow.style.display = 'none';
    }
}

function getAppConfig() {
    const raw = safeStorage.getRaw('active-llm-config');
    if (!raw) return null;
    try { return JSON.parse(raw); } catch (e) { return null; }
}

// ============================================================
// 消息渲染
// ============================================================
function appendBubble(role, content, reasoning) {
    hideEmpty();
    const bubble = document.createElement('div');
    bubble.className = `chat-bubble ${role}`;

    // 如果有思考过程，渲染折叠块
    if (reasoning) {
        const thinkingWrapper = document.createElement('div');
        thinkingWrapper.className = 'thinking-block';
        thinkingWrapper.innerHTML = `
            <div class="thinking-header">
                <span>💭 思考过程</span>
                <span class="thinking-toggle">▶</span>
            </div>
            <div class="thinking-body" style="display:none;">${escapeHtml(reasoning)}</div>
        `;
        const header = thinkingWrapper.querySelector('.thinking-header');
        const body = thinkingWrapper.querySelector('.thinking-body');
        const toggle = thinkingWrapper.querySelector('.thinking-toggle');
        header.addEventListener('click', () => {
            const isHidden = body.style.display === 'none';
            body.style.display = isHidden ? 'block' : 'none';
            toggle.textContent = isHidden ? '▼' : '▶';
        });
        bubble.appendChild(thinkingWrapper);
    }

    bubble.appendChild(document.createTextNode(content));
    chatMessages.appendChild(bubble);
    scrollToBottom();
}

function hideEmpty() { chatEmpty.style.display = 'none'; }
function showEmpty() { chatEmpty.style.display = ''; }
function scrollToBottom() { chatMessages.scrollTop = chatMessages.scrollHeight; }

function isNearBottom() {
    return chatMessages.scrollHeight - chatMessages.scrollTop - chatMessages.clientHeight < 80;
}

// ============================================================
// 发送消息（使用共享 SSE 流解析）
// ============================================================
async function sendMessage() {
    const text = chatInput.value.trim();
    if (!text) return;

    // 每次发送前重新读取工具列表（与编辑器标签页同步）
    try {
        const raw = safeStorage.getRaw('active-llm-config');
        if (raw) {
            const cfg = JSON.parse(raw);
            if (cfg.tool_names && cfg.tool_names.length > 0) {
                chatState.toolNames = cfg.tool_names;
            }
        }
    } catch (e) { /* ignore */ }

    chatInput.value = '';
    hideEmpty();

    chatState.messages.push({ role: 'user', content: text });
    appendBubble('user', text);

    const aiBubble = document.createElement('div');
    aiBubble.className = 'chat-bubble assistant typing-cursor';
    chatMessages.appendChild(aiBubble);
    scrollToBottom();

    setInputDisabled(true);

    abortController = new AbortController();
    btnSend.style.display = 'none';
    btnStop.style.display = '';
    btnStop.onclick = () => { if (abortController) abortController.abort(); };

    let fullContent = '';

    try {
        const body = {
            messages: chatState.messages,
            model: chatState.model || undefined,
            max_tool_rounds: chatState.maxToolRounds || 50,
            session_id: getChatSessionId(),  // 统一 session ID
        };
        // 智能模式：不注入技能 prompt，让 LLM 通过 use_skill 工具自行选择
        if (chatState.smartMode) {
            body.smart_mode = true;
            // 智能模式下，将可用技能列表传给后端
            const appCfg = getAppConfig();
            if (appCfg && appCfg.skills) {
                body.available_skills = appCfg.skills;
            }
        } else {
            // 普通模式：注入选中技能的 system prompt（工具需在编辑器中手动配置）
            if (chatState.activeSkill && chatState.skillPrompts[chatState.activeSkill]) {
                body.system_prompt = chatState.skillPrompts[chatState.activeSkill];
            }
        }
        // 从 localStorage 读取最大搜索轮数（编辑器端设置）
        const savedSearchRounds = safeStorage.get('wybzd-max-search-rounds');
        if (savedSearchRounds != null) body.max_search_rounds = savedSearchRounds;
        if (chatState.apiBase) body.api_base = chatState.apiBase;
        if (chatState.apiKey) body.api_key = chatState.apiKey;
        if (chatState.toolNames.length > 0) body.tool_names = chatState.toolNames;

        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
            signal: abortController.signal,
        });

        // 收集 tool 事件用于消息记录
        const toolEvents = [];
        let reasoningContent = '';

        // 思考区域的 DOM
        const thinkingWrapper = document.createElement('div');
        thinkingWrapper.className = 'thinking-block';
        thinkingWrapper.style.display = 'none';
        thinkingWrapper.innerHTML = `
            <div class="thinking-header" id="thinking-header-${aiBubble.id || 'ai'}">
                <span>💭 思考过程</span>
                <span class="thinking-toggle">▼</span>
            </div>
            <div class="thinking-body" id="thinking-body-${aiBubble.id || 'ai'}"></div>
        `;
        aiBubble.appendChild(thinkingWrapper);

        // rAF 批量渲染状态：累积增量，每帧合并渲染一次
        let pendingDelta = '';
        let rafId = null;
        const renderAI = () => {
            rafId = null;
            if (pendingDelta) {
                fullContent += pendingDelta;
                pendingDelta = '';
                aiBubble.textContent = fullContent;
                if (isNearBottom()) scrollToBottom();
            }
        };
        let pendingReasoning = '';
        let rafReasoningId = null;
        const renderReasoning = () => {
            rafReasoningId = null;
            if (pendingReasoning) {
                reasoningContent += pendingReasoning;
                pendingReasoning = '';
                thinkingWrapper.style.display = 'block';
                const body = thinkingWrapper.querySelector('.thinking-body');
                if (body) body.textContent = reasoningContent;
                if (isNearBottom()) scrollToBottom();
            }
        };

        await readSSEStream(response, {
            onReasoning(delta) {
                pendingReasoning += delta;
                if (rafReasoningId === null) rafReasoningId = requestAnimationFrame(renderReasoning);
            },
            onData(delta) {
                pendingDelta += delta;
                aiBubble.classList.add('typing-cursor');
                if (rafId === null) rafId = requestAnimationFrame(renderAI);
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
                fullContent = '❌ ' + error;
                aiBubble.textContent = fullContent;
            },
            onAbort() {
                fullContent = fullContent || '（已停止）';
                aiBubble.textContent = fullContent;
            },
        });

        aiBubble.classList.remove('typing-cursor');

        // 流结束：取消未触发的 rAF 并立即落盘剩余增量
        if (rafId !== null) { cancelAnimationFrame(rafId); renderAI(); }
        if (rafReasoningId !== null) { cancelAnimationFrame(rafReasoningId); renderReasoning(); }

        // 思考完成后，设置折叠交互
        if (reasoningContent) {
            const header = thinkingWrapper.querySelector('.thinking-header');
            const body = thinkingWrapper.querySelector('.thinking-body');
            const toggle = thinkingWrapper.querySelector('.thinking-toggle');
            if (header) {
                header.addEventListener('click', () => {
                    const isHidden = body.style.display === 'none';
                    body.style.display = isHidden ? 'block' : 'none';
                    toggle.textContent = isHidden ? '▼' : '▶';
                });
            }
        } else {
            thinkingWrapper.remove();
        }

        if (fullContent === '') fullContent = '（无回复）';

        const clean = fullContent.startsWith('❌ ') ? fullContent.slice(2) : fullContent;
        chatState.messages.push({
            role: 'assistant',
            content: clean,
            reasoning: reasoningContent || undefined,
            toolEvents: toolEvents.length > 0 ? toolEvents : undefined,
        });

    } catch (e) {
        if (e.name === 'AbortError') {
            aiBubble.textContent = fullContent || '（已停止）';
            aiBubble.classList.remove('typing-cursor');
        } else {
            aiBubble.textContent = '❌ 请求失败: ' + e.message;
            aiBubble.classList.remove('typing-cursor');
        }
    } finally {
        abortController = null;
        btnStop.style.display = 'none';
        btnSend.style.display = '';
    }

    setInputDisabled(false);
    chatInput.focus();
    saveHistory();
    updateTokenBar();
    // 检查是否需要自动总结
    checkAutoSummarize();
    // 刷新文件列表（可能有工具生成了新文件）
    FilesPanel.refresh();
}

function setInputDisabled(state) {
    btnSend.disabled = state;
    chatInput.disabled = state;
}

// ============================================================
// 对话历史持久化
// ============================================================
function updateMemoryPanel() {
    const { tokens } = MemoryPanel.calcTokens(chatState.messages);
    MemoryPanel.update(tokens);
}

function saveHistory() {
    const data = {
        messages: chatState.messages,
        savedAt: new Date().toISOString(),
    };
    safeStorage.set(getHistoryKey(), data);
    updateMemoryPanel();

    // 同步到后端（按项目隔离）
    const sessionId = getProjectSessionId();
    const pid = chatState.projectId || 'default';
    fetch('/api/memory/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            session_id: sessionId,
            project_id: pid,
            messages: chatState.messages,
        }),
    }).catch(() => {});
}

// 获取或创建聊天页面的 session ID（按项目隔离）
function getChatSessionId() {
    const key = chatState.projectId ? `chat-session-${chatState.projectId}` : 'chat-session-id';
    let sid = safeStorage.getRaw(key);
    if (!sid) {
        sid = getProjectSessionId();
        safeStorage.set(key, sid);
    }
    return sid;
}

function loadHistory() {
    try {
        const data = safeStorage.get(getHistoryKey());
        if (!data || !data.messages || !data.messages.length) return;

        chatState.messages = data.messages;
        hideEmpty();
        chatState.messages.forEach(m => appendBubble(m.role, m.content, m.reasoning));
        updateMemoryPanel();
    } catch (e) {
        console.error('加载对话历史失败:', e);
    }

    // 异步尝试从后端加载（按项目隔离，比 localStorage 更可靠）
    const sessionId = getProjectSessionId();
    const pid = chatState.projectId || 'default';
    fetch(`/api/memory/load/${encodeURIComponent(sessionId)}?project_id=${encodeURIComponent(pid)}`)
        .then(r => r.json())
        .then(data => {
            if (data.success && data.session && data.session.messages && data.session.messages.length > 0) {
                const backendMsgs = data.session.messages;
                if (backendMsgs.length > chatState.messages.length) {
                    // 后端消息更多，使用后端的
                    chatState.messages = backendMsgs;
                    chatMessages.querySelectorAll('.chat-bubble').forEach(b => b.remove());
                    hideEmpty();
                    chatState.messages.forEach(m => appendBubble(m.role, m.content, m.reasoning));
                    chatMessages.scrollTop = chatMessages.scrollHeight;
                    updateMemoryPanel();
                }
            }
        }).catch(() => {});
}

function clearHistory() {
    if (chatState.messages.length === 0) return;
    chatState.messages = [];
    chatMessages.querySelectorAll('.chat-bubble').forEach(b => b.remove());
    showEmpty();
    safeStorage.remove(getHistoryKey());
    updateMemoryPanel();
    updateTokenBar();

    // 同步清空后端项目记忆
    const pid = chatState.projectId || 'default';
    const sessionId = getProjectSessionId();
    // 先清空当前会话，再清空整个项目目录（确保彻底清理）
    fetch('/api/memory/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, project_id: pid, messages: [], title: '' }),
    })
    .then(() => {
        return fetch(`/api/memory/clear-project/${encodeURIComponent(pid)}`, { method: 'DELETE' });
    })
    .then(() => console.log('后端记忆已同步清空'))
    .catch(e => console.warn('清空后端记忆失败:', e));

    showToast('\u{1F5D1}️ 对话已清空', 'info');
}

// ============================================================
// 记忆总结
// ============================================================
async function checkAutoSummarize() {
    const appCfg = getAppConfig();
    if (!appCfg || !appCfg.summarizer || !appCfg.summarizer.enabled) return;
    if (chatState.messages.length < 6) return;

    const threshold = appCfg.summarizer.threshold || 14000;
    const { tokens } = MemoryPanel.calcTokens(chatState.messages);

    if (tokens >= threshold) {
        showToast('⏳ Token 达到阈值，正在自动压缩对话记忆...', 'info');
        await doSummarize();
    }
}

async function doSummarize() {
    const msgs = chatState.messages;
    if (msgs.length < 6) {
        showToast('消息数量不足，无需压缩', 'info');
        return;
    }

    // 保留最近 4 条，总结之前的
    const toSummarize = msgs.slice(0, -4);
    const toKeep = msgs.slice(-4);

    const body = {
        messages: toSummarize,
        max_keep: 4,
    };

    // 如果配置了自定义 API 设置，传递
    if (chatState.model && chatState.model !== '--') body.model = chatState.model;
    if (chatState.apiBase) body.api_base = chatState.apiBase;
    if (chatState.apiKey) body.api_key = chatState.apiKey;

    try {
        const resp = await fetch('/api/memory/summarize', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await resp.json();

        if (data.success && data.summary) {
            const summaryText = data.summary.summary || JSON.stringify(data.summary);
            const summaryMsg = {
                role: 'system',
                content: '📝 [对话历史摘要] ' + summaryText,
            };

            // 用摘要 + 最近消息替换原有消息
            chatState.messages = [summaryMsg, ...(data.kept_messages || toKeep)];

            // 重新渲染
            chatMessages.querySelectorAll('.chat-bubble').forEach(b => b.remove());
            chatState.messages.forEach(m => appendBubble(m.role, m.content));
            chatMessages.scrollTop = chatMessages.scrollHeight;

            updateMemoryPanel();
            saveHistory();

            const originalCount = data.summary.original_count || toSummarize.length;
            showToast(`✅ 已压缩 ${originalCount} 条消息为摘要`, 'success');
        } else if (data.message) {
            showToast(data.message, 'info');
        } else {
            showToast('❌ 总结失败: ' + (data.error || '未知错误'), 'error');
        }
    } catch (e) {
        showToast('❌ 总结请求失败: ' + e.message, 'error');
    }
}

// ============================================================
// 生成文件面板（左侧）
// ============================================================
const FilesPanel = {
    _body: null,
    _dirDisplay: null,
    _saveBtn: null,
    _saveDirHandle: null,
    _saveDirName: '',

    init() {
        this._body = document.getElementById('files-panel-body');
        this._dirDisplay = document.getElementById('files-save-dir');
        this._saveBtn = document.getElementById('files-save-btn');
        const refreshBtn = document.getElementById('files-refresh-btn');
        const clearBtn = document.getElementById('files-clear-btn');
        const dirBtn = document.getElementById('files-dir-btn');

        // 从 localStorage 恢复存储路径
        this._loadStoragePath();

        // 绑定事件
        if (refreshBtn) refreshBtn.addEventListener('click', () => this.refresh());
        if (clearBtn) clearBtn.addEventListener('click', () => this.clearAll());
        if (dirBtn) dirBtn.addEventListener('click', () => this.pickDir());
        if (this._saveBtn) this._saveBtn.addEventListener('click', () => this.saveAll());

        // 监听其他标签页的 storage 变更
        window.addEventListener('storage', (e) => {
            if (e.key === 'mcp-storage-path') {
                this._loadStoragePath();
            }
        });

        // 点击存储目录文字也可以重新选择
        if (this._dirDisplay) {
            this._dirDisplay.addEventListener('click', () => this.pickDir());
            this._dirDisplay.style.cursor = 'pointer';
        }

        // 初始化时立即刷新文件列表
        this.refresh();
    },

    _loadStoragePath() {
        const data = safeStorage.get('mcp-storage-path');
        if (data && data.name) {
            this._saveDirName = data.name;
            this._updateDirDisplay();
        }
    },

    _updateDirDisplay() {
        if (!this._dirDisplay) return;
        if (this._saveDirName) {
            this._dirDisplay.textContent = '📁 ' + this._saveDirName;
            this._dirDisplay.style.color = 'var(--success)';
        } else {
            this._dirDisplay.textContent = '📁 未选择目录';
            this._dirDisplay.style.color = '';
        }
    },

    /** 刷新文件列表 */
    async refresh() {
        const sessionId = getChatSessionId ? getChatSessionId() : 'chat_noproject';
        try {
            const resp = await fetch(`/api/chat/generated-files/${encodeURIComponent(sessionId)}`);
            const data = await resp.json();
            this.render(data.files || []);
        } catch (e) {
            console.error('获取文件列表失败:', e);
        }
    },

    /** 渲染文件列表 */
    render(files) {
        if (!this._body) return;

        if (!files || files.length === 0) {
            this._body.innerHTML = `
                <div class="files-empty">
                    <div class="files-empty-icon">📭</div>
                    <div class="files-empty-text">暂无生成文件</div>
                    <div class="files-empty-hint">AI 工具生成的文件<br>会显示在这里</div>
                </div>`;
            return;
        }

        // 文件类型图标映射
        const typeIcons = {
            word: '📝', excel: '📊', ppt: '📽️',
            pdf: '📄', image: '🖼️', csv: '📋',
            json: '📋', text: '📃', code: '💻',
            markdown: '📝', html: '🌐', other: '📎',
        };

        let html = '';
        for (const f of files) {
            const icon = typeIcons[f.type] || '📎';
            const name = escapeHtml(f.name);
            const size = f.size_display || '';
            const time = f.modified ? f.modified.slice(11, 16) : '';  // 只显示时分

            html += `
                <div class="file-item" title="${name}&#10;大小: ${size}&#10;修改: ${f.modified || ''}">
                    <span class="file-item-icon">${icon}</span>
                    <div class="file-item-info">
                        <div class="file-item-name">${name}</div>
                        <div class="file-item-meta">
                            <span class="file-item-size">${size}</span>
                            <span class="file-item-time">${time}</span>
                        </div>
                    </div>
                </div>`;
        }

        this._body.innerHTML = html;
    },

    /** 选择存储目录 */
    async pickDir() {
        try {
            const handle = await window.showDirectoryPicker({ mode: 'readwrite' });
            this._saveDirHandle = handle;
            this._saveDirName = handle.name;
            this._updateDirDisplay();

            // 同步到 localStorage
            safeStorage.set('mcp-storage-path', {
                name: handle.name,
                updatedAt: new Date().toISOString(),
            });

            // 同步到后端
            fetch('/api/config/storage-path', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: handle.name, path: handle.name }),
            }).catch(() => {});

            showToast('✅ 存储目录已设为: ' + handle.name, 'success');
        } catch (e) {
            if (e.name !== 'AbortError') {
                showToast('❌ 选择目录失败: ' + e.message, 'error');
            }
        }
    },

    /** 保存全部文件到选中目录 */
    async saveAll() {
        // 如果没有从 IndexedDB 恢复的 handle，尝试重新选择
        if (!this._saveDirHandle) {
            // 尝试从 IndexedDB 恢复（和编辑器页面共享同一个 DB）
            try {
                const db = await this._openSharedMCPDB();
                const handle = await new Promise((resolve, reject) => {
                    const tx = db.transaction('mcp-file-store', 'readonly');
                    const req = tx.objectStore('mcp-file-store').get('save-dir');
                    req.onsuccess = () => resolve(req.result);
                    req.onerror = () => reject(req.error);
                });
                if (handle) {
                    const perm = await handle.queryPermission({ mode: 'readwrite' });
                    // 仅在权限已授予时自动恢复；prompt 状态需用户点击"选择存储目录"重新授权
                    if (perm === 'granted') {
                        this._saveDirHandle = handle;
                        this._saveDirName = handle.name;
                        this._updateDirDisplay();
                    }
                }
            } catch (e) {
                // IndexedDB 恢复失败，继续走手动选择
            }
        }

        if (!this._saveDirHandle) {
            // showDirectoryPicker 同样需要用户激活，不能在 await 之后调用，
            // 提示用户先点击"选择存储目录"按钮
            showToast('⚠️ 请先点击"选择存储目录"按钮选择目录', 'info');
            return;
        }

        // 验证权限（requestPermission 需用户激活，此处不自动请求）
        try {
            const perm = await this._saveDirHandle.queryPermission({ mode: 'readwrite' });
            if (perm !== 'granted') {
                showToast('❌ 目录权限已失效，请重新点击"选择存储目录"授权', 'error');
                this._saveDirHandle = null;
                this._saveDirName = '';
                this._updateDirDisplay();
                return;
            }
        } catch (e) {
            showToast('❌ 存储目录已失效，请重新选择', 'error');
            this._saveDirHandle = null;
            this._saveDirName = '';
            this._updateDirDisplay();
            return;
        }

        // 获取文件列表
        const sessionId = getChatSessionId ? getChatSessionId() : 'chat_noproject';
        let files = [];
        try {
            const resp = await fetch(`/api/chat/generated-files/${encodeURIComponent(sessionId)}`);
            const data = await resp.json();
            files = data.files || [];
        } catch (e) {
            showToast('❌ 获取文件列表失败', 'error');
            return;
        }

        if (!files.length) {
            showToast('📭 暂无文件可保存', 'info');
            return;
        }

        // 逐个下载并写入
        let saved = 0;
        for (const f of files) {
            try {
                let downloadUrl;
                if (f.workspace === 'office') {
                    // 使用文件实际的 sub_session（来自 API 响应），确保路径正确
                    const fileSession = f.sub_session || sessionId || 'default';
                    downloadUrl = `/api/mcp/office/download/${encodeURIComponent(fileSession)}/${encodeURIComponent(f.name)}`;
                } else if (f.workspace === 'pdf') {
                    const pdfName = f.name.replace(/\.pdf$/i, '');
                    downloadUrl = `/api/pdf/download/${encodeURIComponent(pdfName)}`;
                } else {
                    console.warn('FilesPanel: skip unsupported workspace', f.workspace, f.name);
                    continue;
                }

                const fileResp = await fetch(downloadUrl);
                if (!fileResp.ok) continue;
                const blob = await fileResp.blob();

                const fileHandle = await this._saveDirHandle.getFileHandle(f.name, { create: true });
                const writable = await fileHandle.createWritable();
                await writable.write(blob);
                await writable.close();
                saved++;
            } catch (e) {
                console.error(`保存 ${f.name} 失败:`, e);
            }
        }

        showToast(`💾 已保存 ${saved} 个文件到 ${this._saveDirName}`, 'success');
        this.refresh();
    },

    /** 清空所有临时文件（仅删服务端 workspace，不影响用户本地文件夹） */
    async clearAll() {
        const sessionId = getChatSessionId ? getChatSessionId() : 'chat_noproject';
        try {
            const resp = await fetch(`/api/chat/generated-files/${encodeURIComponent(sessionId)}`, {
                method: 'DELETE',
            });
            const data = await resp.json();
            if (data.success) {
                showToast(`🗑️ 已清空 ${data.deleted} 个临时文件`, 'info');
            } else {
                showToast('清空失败', 'error');
            }
            this.refresh();
        } catch (e) {
            showToast('清空失败: ' + e.message, 'error');
        }
    },

    /** 打开共享的 MCP IndexedDB（与编辑器页面共享） */
    async _openSharedMCPDB() {
        return new Promise((resolve, reject) => {
            const req = indexedDB.open('mcp-file-system', 1);
            req.onupgradeneeded = () => {
                if (!req.result.objectStoreNames.contains('mcp-file-store')) {
                    req.result.createObjectStore('mcp-file-store');
                }
            };
            req.onsuccess = () => resolve(req.result);
            req.onerror = () => reject(req.error);
        });
    },
};


// ============================================================
// 启动
// ============================================================
document.addEventListener('DOMContentLoaded', async () => {
    // 先初始化面板（建立 DOM 引用）
    MemoryPanel.init();
    ToolMonitor.init();
    FilesPanel.init();

    // 等待异步初始化完成后刷新记忆面板
    await init();
    updateMemoryPanel();
});
