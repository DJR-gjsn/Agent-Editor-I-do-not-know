/**
 * 管理后台脚本 — 从 admin.html 提取
 */
(function () {
    // 恢复主题
    const saved = safeStorage.get('wybzd-theme') || 'industrial';
    document.documentElement.setAttribute('data-theme', saved);

    // 加载统计数据
    async function loadStats() {
        try {
            const resp = await fetch('/api/projects');
            const projects = await resp.json();
            let components = 0, connections = 0;
            if (Array.isArray(projects)) {
                projects.forEach(p => {
                    components += p.componentCount || 0;
                    connections += p.connectionCount || 0;
                });
            }
            document.getElementById('stat-projects').textContent = Array.isArray(projects) ? projects.length : '--';
            document.getElementById('stat-components').textContent = components;
            document.getElementById('stat-connections').textContent = connections;
        } catch (e) { /* ignore */ }
    }

    // 加载系统信息
    async function loadInfo() {
        try {
            const resp = await fetch('/api/config');
            const cfg = await resp.json();
            document.getElementById('info-model').textContent = cfg.model || '--';
            document.getElementById('info-api-base').textContent = cfg.api_base || '--';
        } catch (e) { /* ignore */ }
    }

    // 设置按钮
    document.getElementById('btn-settings').addEventListener('click', () => {
        window.location.href = '/projects';
    });

    document.addEventListener('DOMContentLoaded', () => { loadStats(); loadInfo(); });
})();
