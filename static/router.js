/**
 * SPA Router — навигация без перезагрузки страницы
 */
const Router = {
    container: null,
    currentData: {},

    init: function() {
        this.container = document.getElementById('app-container');
        console.log('[Router] Initialized');

        if (typeof vkBridge !== 'undefined') {
            vkBridge.subscribe(function(event) {
                if (event.detail && event.detail.type === 'VKWebAppBack') {
                    history.back();
                }
            });
        }

        this.navigate('/');
    },

    navigate: async function(route, extraParams) {
        console.log('[Router] Navigate to:', route, extraParams || '');

        if (!this.container.innerHTML.trim()) {
            this.container.innerHTML =
                '<div style="text-align:center;padding:60px 20px;color:#667eea;">' +
                '<h2>⚽</h2><p>Загрузка...</p></div>';
        } else {
            this.container.style.opacity = '0.6';
        }

        try {
            // Собираем параметры запроса
            var params = { route: route, uid: API.userId, team_id: API.currentTeamId };
            if (extraParams) {
                Object.assign(params, extraParams);
            }

            const res = await fetch('/api/fragment', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(params)
            });

            const result = await res.json();

            if (result.redirect) {
                console.log('[Router] Redirect to:', result.redirect);
                if (result.redirect === route) {
                    console.error('[Router] Цикличный редирект, останавливаем');
                    this.container.style.opacity = '1';
                    return;
                }
                this.container.style.opacity = '1';
                return this.navigate(result.redirect);
            }

            if (result.error && !result.html) {
                this.container.innerHTML =
                    '<div style="text-align:center;padding:40px;color:red;">❌ ' + result.error + '</div>';
                this.container.style.opacity = '1';
                return;
            }

            this.currentData = result.data || {};

            this.container.innerHTML = result.html;
            this.container.style.opacity = '1';

            var scripts = this.container.querySelectorAll('script');
            scripts.forEach(function(oldScript) {
                var newScript = document.createElement('script');
                newScript.textContent = oldScript.textContent;
                oldScript.parentNode.replaceChild(newScript, oldScript);
            });

            if (route !== '/') {
                history.pushState({ route: route }, '', '#' + route);
            } else {
                history.replaceState({ route: '/' }, '', window.location.pathname);
            }

        } catch (error) {
            console.error('[Router] Error:', error);
            this.container.innerHTML =
                '<div style="text-align:center;padding:40px;color:red;">❌ Ошибка соединения</div>';
            this.container.style.opacity = '1';
        }
    }
};

document.addEventListener('DOMContentLoaded', function() {
    Router.init();
});

window.addEventListener('popstate', function(event) {
    var route = (event.state && event.state.route) || '/';
    Router.navigate(route);
});