(function () {
    const MODE_LOGIN = 'login', MODE_REGISTER = 'register';
    let mode = MODE_LOGIN;

    // 已登录则直接进编辑器
    fetch('/api/auth/me').then(r => {
        if (r.ok) location.href = '/editor';
    }).catch(() => {});

    function render() {
        const isLogin = mode === MODE_LOGIN;
        document.getElementById('auth-form').innerHTML = `
            <form id="auth-f">
                <label>用户名</label>
                <input id="f-user" autocomplete="username" placeholder="3-32 位字母/数字/下划线">
                <label>密码</label>
                <input id="f-pass" type="password" autocomplete="${isLogin ? 'current-password' : 'new-password'}" placeholder="${isLogin ? '密码' : '至少 6 位'}">
                <button type="submit">${isLogin ? '登 录' : '注 册'}</button>
            </form>
            <div class="switch" id="f-switch">${isLogin ? '没有账号？注册' : '已有账号？登录'}</div>
        `;
        document.getElementById('f-switch').onclick = () => { mode = isLogin ? MODE_REGISTER : MODE_LOGIN; render(); };
        document.getElementById('auth-f').onsubmit = submit;
    }

    async function submit(e) {
        e.preventDefault();
        const user = document.getElementById('f-user').value.trim();
        const pass = document.getElementById('f-pass').value;
        const err = document.getElementById('auth-error');
        err.textContent = '';
        const url = mode === MODE_LOGIN ? '/api/auth/login' : '/api/auth/register';
        try {
            const resp = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username: user, password: pass }),
            });
            const data = await resp.json();
            if (data.success) {
                if (mode === MODE_REGISTER) { mode = MODE_LOGIN; render(); err.textContent = '注册成功，请登录'; return; }
                location.href = '/editor';
            } else {
                err.textContent = data.error || '操作失败';
            }
        } catch (ex) {
            err.textContent = '网络错误: ' + ex.message;
        }
    }

    render();
})();
