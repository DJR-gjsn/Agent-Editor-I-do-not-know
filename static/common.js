/**
 * wybzd · 共享工具函数
 * 两个页面共用：safeStorage、escapeHtml、SSE 解析、Toast
 */

// ============================================================
// 安全的 localStorage 操作
// ============================================================
const safeStorage = {
    get(key) {
        try {
            const raw = localStorage.getItem(key);
            return raw ? JSON.parse(raw) : null;
        } catch (e) {
            console.warn(`localStorage.get("${key}") 失败:`, e);
            return null;
        }
    },
    set(key, value) {
        try {
            localStorage.setItem(key, JSON.stringify(value));
            return true;
        } catch (e) {
            console.warn(`localStorage.set("${key}") 失败 (可能已满):`, e);
            return false;
        }
    },
    remove(key) {
        try {
            localStorage.removeItem(key);
        } catch (e) {
            console.warn(`localStorage.remove("${key}") 失败:`, e);
        }
    },
    getRaw(key) {
        try {
            return localStorage.getItem(key);
        } catch (e) {
            return null;
        }
    },
};

// ============================================================
// HTML 转义（纯字符串方式，不创建 DOM 元素）
// ============================================================
const HTML_ESCAPE_MAP = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
};
const HTML_ESCAPE_RE = /[&<>"']/g;
function escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(HTML_ESCAPE_RE, ch => HTML_ESCAPE_MAP[ch]);
}

// ============================================================
// SSE 流解析（ReadableStream → 逐 chunk 回调）
// 支持: onData(delta) 文本增量, onToolCall({name, arguments}) 工具调用,
//       onToolResult({name, result}) 工具结果, onError(msg) 错误
// ============================================================
async function readSSEStream(response, callbacks) {
    const { onData, onReasoning, onToolCall, onToolResult, onError } = callbacks || {};
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let fullContent = '';

    try {
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                const dataStr = line.slice(6);
                if (dataStr === '[DONE]') {
                    return { done: true, content: fullContent };
                }
                try {
                    const data = JSON.parse(dataStr);
                    if (data.error) {
                        if (onError) onError(data.error);
                        return { done: true, error: data.error };
                    }
                    // 处理 tool calls
                    if (data.tool_calls) {
                        for (const tc of data.tool_calls) {
                            if (onToolCall) onToolCall({ name: tc.name, arguments: tc.arguments });
                        }
                        continue;
                    }
                    // 处理 tool results
                    if (data.tool_result) {
                        if (onToolResult) onToolResult(data.tool_result);
                        continue;
                    }
                    // 处理思考过程（推理模型）
                    const reasoning = data.choices?.[0]?.delta?.reasoning_content;
                    if (reasoning) {
                        if (onReasoning) onReasoning(reasoning);
                        continue;
                    }
                    // 处理文本增量
                    const delta = data.choices?.[0]?.delta?.content;
                    if (delta) {
                        fullContent += delta;
                        if (onData) onData(delta);
                    }
                } catch (e) {
                    // 跳过无法解析的行
                }
            }
        }
    } catch (e) {
        if (onError) onError(e.message);
        return { done: true, error: e.message };
    }
    return { done: true };
}

// ============================================================
// Toast 通知
// ============================================================
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(60px)';
        toast.style.transition = 'all 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 2500);
}

// ============================================================
// 防抖函数
// ============================================================
function debounce(fn, delay = 200) {
    let timer;
    return function (...args) {
        clearTimeout(timer);
        timer = setTimeout(() => fn.apply(this, args), delay);
    };
}

// ============================================================
// 工具调用监控面板（共享：index.html 和 chat.html 共用）
// ============================================================
const ToolMonitor = {
    _body: null,
    _clearBtn: null,

    init() {
        this._body = document.getElementById('tm-body');
        this._clearBtn = document.getElementById('tm-clear');
        if (this._clearBtn) {
            this._clearBtn.addEventListener('click', () => this.clear());
        }
    },

    log(method, name, argsOrResult, isError) {
        if (!this._body) return;
        // 隐藏空状态
        const empty = this._body.querySelector('.tm-empty');
        if (empty) empty.remove();

        const now = new Date();
        const time = now.toLocaleTimeString('zh-CN', { hour12: false });

        const entry = document.createElement('div');
        if (method === 'call') {
            entry.className = 'tm-entry tool-call';
            const argsStr = typeof argsOrResult === 'string' ? argsOrResult : JSON.stringify(argsOrResult, null, 2);
            entry.innerHTML = `
                <div class="tm-entry-header">
                    <span class="tm-entry-icon">📤</span>
                    <span class="tm-entry-name">${escapeHtml(name)}</span>
                </div>
                <div class="tm-entry-args">${escapeHtml(argsStr.slice(0, 300))}</div>
                <div class="tm-entry-time">${time}</div>
            `;
        } else {
            entry.className = `tm-entry ${isError ? 'tool-error' : 'tool-result'}`;
            const resultStr = typeof argsOrResult === 'string' ? argsOrResult : JSON.stringify(argsOrResult, null, 2);
            entry.innerHTML = `
                <div class="tm-entry-header">
                    <span class="tm-entry-icon">${isError ? '❌' : '📥'}</span>
                    <span class="tm-entry-name">${escapeHtml(name)}</span>
                </div>
                <div class="tm-entry-content">${escapeHtml(resultStr.slice(0, 500))}</div>
                <div class="tm-entry-time">${time}</div>
            `;
        }

        this._body.appendChild(entry);
        this._body.scrollTop = this._body.scrollHeight;

        // 限制最多 100 条
        while (this._body.children.length > 100) {
            this._body.firstChild.remove();
        }
    },

    logCall(name, args) { this.log('call', name, args, false); },
    logResult(name, result, isError) { this.log('result', name, result, isError); },

    clear() {
        if (!this._body) return;
        this._body.innerHTML = `
            <div class="tm-empty">
                <div class="tm-empty-icon">🔧</div>
                <div class="tm-empty-text">发送消息后<br>在此查看工具调用</div>
            </div>
        `;
    },
};

// ============================================================
// 对话记忆面板（工具调用下方，显示 Token 用量/上限）
// ============================================================
const MemoryPanel = {
    _countEl: null,
    _barEl: null,
    _markerEl: null,
    _thresholdLabel: null,
    _thresholdTokens: null,      // 自动总结阈值（外部设置）
    MAX_CHARS: 100000,           // 服务端字符上限（对应 server.py 100000）
    CHARS_PER_TOKEN: 3.5,        // 中英文混合估算 ~3.5 字符/token

    init() {
        this._countEl = document.getElementById('mem-token-count');
        this._barEl = document.getElementById('mem-bar-fill');
        // 创建阈值标记线
        const barContainer = document.querySelector('.mem-bar');
        if (barContainer) {
            let marker = barContainer.querySelector('.mem-bar-threshold');
            if (!marker) {
                marker = document.createElement('div');
                marker.className = 'mem-bar-threshold';
                marker.title = '自动总结阈值';
                barContainer.appendChild(marker);
            }
            this._markerEl = marker;
        }
        this.update(this._lastTokens || 0);
    },

    /** 设置自动总结阈值（tokens），在进度条上显示标记线 */
    setThreshold(tokens) {
        this._thresholdTokens = tokens;
        if (this._countEl) this.update(0); // 刷新阈值线位置
    },

    /**
     * 从消息数组计算估算 token 数
     * @param {Array} messages
     * @returns {{chars: number, tokens: number}}
     */
    calcTokens(messages) {
        let chars = 0;
        (messages || []).forEach(m => {
            const c = m.content || '';
            chars += (typeof c === 'string' ? c.length : String(c).length);
        });
        return {
            chars,
            tokens: Math.round(chars / this.CHARS_PER_TOKEN),
        };
    },

    /**
     * 更新记忆面板
     * @param {number} tokens 当前 token 数
     */
    update(tokens) {
        this._lastTokens = tokens;
        const maxTokens = Math.round(this.MAX_CHARS / this.CHARS_PER_TOKEN);
        if (!this._countEl || !this._barEl) {
            // DOM 元素还未就绪，静默跳过（下次 update 会重试）
            return;
        }

        const pct = Math.min(100, Math.round((tokens / maxTokens) * 100));
        let cls = '';
        if (pct >= 90) cls = 'danger';
        else if (pct >= 70) cls = 'warning';

        this._countEl.textContent = `${tokens} / ~${Math.round(maxTokens / 1000)}K`;
        this._countEl.className = 'mem-stat-value' + (cls ? ' ' + cls : '');

        this._barEl.style.width = pct + '%';
        this._barEl.className = 'mem-bar-fill' + (cls ? ' ' + cls : '');

        // 渲染阈值标记线
        if (this._markerEl && this._thresholdTokens != null && this._thresholdTokens > 0) {
            const thresholdPct = Math.min(100, Math.round((this._thresholdTokens / maxTokens) * 100));
            this._markerEl.style.left = thresholdPct + '%';
            this._markerEl.style.display = 'block';
            this._markerEl.title = `自动总结阈值: ${this._thresholdTokens} tokens`;
        } else if (this._markerEl) {
            this._markerEl.style.display = 'none';
        }
    },
};
