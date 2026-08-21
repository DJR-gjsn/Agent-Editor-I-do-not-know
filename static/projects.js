/**
 * wybzd · 项目管理 — 前端逻辑
 */
const projGrid = document.getElementById('proj-grid');
const projEmpty = document.getElementById('proj-empty');
const btnNew = document.getElementById('btn-new-project');

// ============================================================
// 主题
// ============================================================
(function restoreTheme() {
    const saved = safeStorage.get('wybzd-theme') || 'industrial';
    document.documentElement.setAttribute('data-theme', saved);
})();

// ============================================================
// 初始化
// ============================================================
async function init() {
    btnNew.addEventListener('click', () => {
        window.location.href = '/editor?project=new';
    });
    setupSettingsIfPresent();
    await loadProjects();
}

function setupSettingsIfPresent() {
    const btnSettings = document.getElementById('btn-settings');
    const overlay = document.getElementById('settings-overlay');
    const btnClose = document.getElementById('settings-close');
    const themeOptions = document.getElementById('theme-options');

    if (!btnSettings || !overlay) return;

    // 恢复当前主题选中状态
    const current = document.documentElement.getAttribute('data-theme') || 'industrial';
    themeOptions.querySelectorAll('.theme-option').forEach(opt => {
        opt.classList.toggle('active', opt.dataset.theme === current);
    });

    // 打开设置
    btnSettings.addEventListener('click', () => {
        overlay.style.display = 'flex';
        const cur = document.documentElement.getAttribute('data-theme') || 'industrial';
        themeOptions.querySelectorAll('.theme-option').forEach(opt => {
            opt.classList.toggle('active', opt.dataset.theme === cur);
        });
    });

    // 退出登录：登出后清本地 LLM 配置并回登录页
    const btnLogout = document.getElementById('btn-logout');
    if (btnLogout) btnLogout.addEventListener('click', async () => {
        try { await fetch('/api/auth/logout', { method: 'POST' }); } catch (e) {}
        try { localStorage.removeItem('active-llm-config'); } catch (e) {}
        location.href = '/login';
    });

    // 关闭设置
    if (btnClose) {
        btnClose.addEventListener('click', () => { overlay.style.display = 'none'; });
    }
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) overlay.style.display = 'none';
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && overlay.style.display === 'flex') overlay.style.display = 'none';
    });

    // 切换主题
    themeOptions.querySelectorAll('.theme-option').forEach(btn => {
        btn.addEventListener('click', () => {
            const theme = btn.dataset.theme;
            document.documentElement.setAttribute('data-theme', theme);
            safeStorage.set('wybzd-theme', theme);
            themeOptions.querySelectorAll('.theme-option').forEach(opt => {
                opt.classList.toggle('active', opt.dataset.theme === theme);
            });
            const names = { industrial: 'Industrial', blue: 'Professional', glass: 'Glassmorphism' };
            showToast('Theme: ' + names[theme], 'info');
        });
    });
}

async function loadProjects() {
    try {
        const resp = await fetch('/api/projects');
        const projects = await resp.json();

        projGrid.innerHTML = '';

        if (!projects || projects.length === 0) {
            projEmpty.style.display = '';
            projGrid.style.display = 'none';
            return;
        }

        projEmpty.style.display = 'none';
        projGrid.style.display = '';

        projects.forEach(p => {
            const card = document.createElement('div');
            card.className = 'proj-card';
            card.innerHTML = `
                <div class="proj-card-body">
                    <div class="proj-card-icon">🤖</div>
                    <div class="proj-card-name">${escapeHtml(p.name)}</div>
                    <div class="proj-card-meta">
                        <span>📦 ${p.componentCount} 组件</span>
                        <span>🔗 ${p.connectionCount} 连线</span>
                    </div>
                    <div class="proj-card-time">${escapeHtml(p.updatedAt || '')}</div>
                </div>
                <div class="proj-card-actions">
                    <button class="proj-card-btn open" title="打开项目">打开</button>
                    <button class="proj-card-btn rename" title="重命名">改名</button>
                    <button class="proj-card-btn delete" title="删除项目">删除</button>
                </div>
            `;

            card.querySelector('.proj-card-body').addEventListener('click', () => {
                window.location.href = `/editor?project=${encodeURIComponent(p.id)}`;
            });
            card.querySelector('.proj-card-btn.open').addEventListener('click', (e) => {
                e.stopPropagation();
                window.location.href = `/editor?project=${encodeURIComponent(p.id)}`;
            });
            card.querySelector('.proj-card-btn.rename').addEventListener('click', (e) => {
                e.stopPropagation();
                renameProject(p.id, p.name);
            });
            card.querySelector('.proj-card-btn.delete').addEventListener('click', (e) => {
                e.stopPropagation();
                deleteProject(p.id, p.name);
            });

            projGrid.appendChild(card);
        });
    } catch (e) {
        console.error('加载项目列表失败:', e);
        projGrid.innerHTML = '<div class="proj-error">加载失败，请检查服务器连接</div>';
    }
}

async function renameProject(id, currentName) {
    const newName = prompt('请输入新名称:', currentName);
    if (!newName || !newName.trim() || newName.trim() === currentName) return;

    try {
        const resp = await fetch('/api/projects', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: id, name: newName.trim() }),
        });
        if (!resp.ok) throw new Error((await resp.json()).error || '请求失败');
        showToast(`已改名: ${newName.trim()}`, 'success');
        await loadProjects();
    } catch (e) {
        showToast('改名失败: ' + e.message, 'error');
    }
}

async function deleteProject(id, name) {
    if (!confirm(`确定要删除「${name}」吗？\n此操作不可撤销。`)) return;

    try {
        await fetch(`/api/projects/${encodeURIComponent(id)}`, { method: 'DELETE' });
        showToast(`已删除「${name}」`, 'info');
        await loadProjects();
    } catch (e) {
        showToast('删除失败: ' + e.message, 'error');
    }
}

document.addEventListener('DOMContentLoaded', init);
