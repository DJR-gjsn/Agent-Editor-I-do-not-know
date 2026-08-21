// 共享设置面板（admin 首页 / projects 项目管理页）
// 生成设置面板（主题 + 账号区：当前用户/改密码/退出登录），自包含无外部依赖
// 使用：页面引入 common.js 后引入本文件；按钮调用 window.openSettingsPanel()
(function () {
    let initialized = false;

    function openSettings() {
        if (!initialized) build();
        const overlay = document.getElementById('settings-overlay');
        if (overlay) overlay.style.display = 'flex';
        loadAccountInfo();
        syncThemeOptions();
    }

    function build() {
        initialized = true;
        const overlay = document.createElement('div');
        overlay.id = 'settings-overlay';
        overlay.className = 'settings-overlay';
        overlay.style.display = 'none';
        overlay.innerHTML = `
            <div class="settings-panel">
                <div class="settings-header">
                    <span>Settings</span>
                    <button class="settings-close" id="settings-close">&times;</button>
                </div>
                <div class="settings-body">
                    <div class="settings-group">
                        <label class="settings-label">Theme / 主题</label>
                        <div class="theme-options" id="theme-options">
                            <button class="theme-option" data-theme="industrial">
                                <span class="theme-swatch industrial"></span>
                                <span class="theme-info"><strong>Industrial</strong><small>机能风 · 亮黄+黑灰</small></span>
                            </button>
                            <button class="theme-option" data-theme="blue">
                                <span class="theme-swatch blue"></span>
                                <span class="theme-info"><strong>Professional</strong><small>专业风 · 蓝+白</small></span>
                            </button>
                            <button class="theme-option" data-theme="glass">
                                <span class="theme-swatch glass"></span>
                                <span class="theme-info"><strong>Glassmorphism</strong><small>玻璃态 · 紫蓝渐变+毛玻璃</small></span>
                            </button>
                        </div>
                    </div>
                    <div class="settings-group">
                        <label class="settings-label">账号</label>
                        <div style="margin-top:8px;font-size:13px;">
                            <div id="acct-info" style="margin-bottom:10px;color:var(--text-secondary);">加载中…</div>
                            <div style="display:flex;gap:6px;">
                                <input id="acct-old-pass" type="password" placeholder="旧密码" style="flex:1;padding:6px;border:1px solid #d9d9d9;border-radius:4px;">
                                <input id="acct-new-pass" type="password" placeholder="新密码（≥6 位）" style="flex:1;padding:6px;border:1px solid #d9d9d9;border-radius:4px;">
                                <button class="module-btn secondary" id="btn-change-pass" style="flex-shrink:0;">改密码</button>
                            </div>
                            <div id="acct-msg" style="margin-top:6px;min-height:16px;font-size:12px;"></div>
                            <button class="module-btn secondary" id="btn-acct-logout" style="margin-top:6px;width:100%;color:#f5222d;">⏻ 退出登录</button>
                        </div>
                    </div>
                </div>
            </div>
        `;
        document.body.appendChild(overlay);

        // 关闭
        document.getElementById('settings-close').addEventListener('click', () => { overlay.style.display = 'none'; });
        overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.style.display = 'none'; });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && overlay.style.display === 'flex') overlay.style.display = 'none';
        });

        // 主题切换
        const themeOptions = overlay.querySelector('#theme-options');
        themeOptions.querySelectorAll('.theme-option').forEach(btn => {
            btn.addEventListener('click', () => {
                const theme = btn.dataset.theme;
                document.documentElement.setAttribute('data-theme', theme);
                try { localStorage.setItem('wybzd-theme', theme); } catch (e) {}
                syncThemeOptions();
                const names = { industrial: 'Industrial', blue: 'Professional', glass: 'Glassmorphism' };
                if (typeof showToast === 'function') showToast('Theme: ' + names[theme], 'info');
            });
        });

        // 改密码
        document.getElementById('btn-change-pass').addEventListener('click', async () => {
            const oldPass = document.getElementById('acct-old-pass').value;
            const newPass = document.getElementById('acct-new-pass').value;
            const msg = document.getElementById('acct-msg');
            if (!newPass || newPass.length < 6) { msg.textContent = '新密码至少 6 位'; return; }
            msg.textContent = '修改中…';
            try {
                const resp = await fetch('/api/auth/change-password', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ old_password: oldPass, new_password: newPass }),
                });
                const data = await resp.json();
                if (data.success) {
                    msg.textContent = '✅ 密码已修改';
                    document.getElementById('acct-old-pass').value = '';
                    document.getElementById('acct-new-pass').value = '';
                } else {
                    msg.textContent = (resp.status === 401 ? '❌ ' : '⚠️ ') + (data.error || '修改失败');
                }
            } catch (ex) {
                msg.textContent = '网络错误: ' + ex.message;
            }
        });

        // 退出登录
        document.getElementById('btn-acct-logout').addEventListener('click', async () => {
            try { await fetch('/api/auth/logout', { method: 'POST' }); } catch (e) {}
            try { localStorage.removeItem('active-llm-config'); } catch (e) {}
            location.href = '/login';
        });
    }

    function syncThemeOptions() {
        const opts = document.querySelectorAll('#theme-options .theme-option');
        const cur = document.documentElement.getAttribute('data-theme') || 'industrial';
        opts.forEach(o => o.classList.toggle('active', o.dataset.theme === cur));
    }

    async function loadAccountInfo() {
        const box = document.getElementById('acct-info');
        if (!box) return;
        try {
            const resp = await fetch('/api/auth/me');
            const data = await resp.json();
            if (resp.ok && data.success) {
                box.textContent = '当前用户：' + data.user.username;
            } else {
                box.textContent = '未登录';
            }
        } catch (ex) {
            box.textContent = '获取账号信息失败';
        }
    }

    window.openSettingsPanel = openSettings;
})();
