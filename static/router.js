/**
 * SPA Router — навигация без перезагрузки страницы
 */
const Router = {
    container: null,
    currentData: {},

    init: function() {
        this.container = document.getElementById('app-container');
        console.log('[Router] Initialized');

        // Обработка кнопки "Назад" от VK
        if (typeof vkBridge !== 'undefined') {
            vkBridge.subscribe(function(event) {
                if (event.detail && event.detail.type === 'VKWebAppBack') {
                    history.back();
                }
            });
        }

        // Стартовый маршрут — всегда авторизация
        this.navigate('/');
    },

    navigate: async function(route) {
        console.log('[Router] Navigate to:', route);

        // Показываем индикатор загрузки
        this.container.innerHTML =
            '<div style="text-align:center;padding:60px 20px;color:#667eea;">' +
            '<h2>⚽</h2><p>Загрузка...</p></div>';

        try {
            const res = await fetch('/api/fragment', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ route: route })
            });

            const result = await res.json();

            // Сервер просит перейти на другой маршрут
            if (result.redirect) {
                console.log('[Router] Redirect to:', result.redirect);
                return this.navigate(result.redirect);
            }

            if (result.error && !result.html) {
                this.container.innerHTML =
                    '<div style="text-align:center;padding:40px;color:red;">❌ ' + result.error + '</div>';
                return;
            }

            // Сохраняем данные для фрагмента
            this.currentData = result.data || {};

            // Вставляем HTML фрагмента
            this.container.innerHTML = result.html;

            // Выполняем скрипты внутри фрагмента
            var scripts = this.container.querySelectorAll('script');
            scripts.forEach(function(oldScript) {
                var newScript = document.createElement('script');
                newScript.textContent = oldScript.textContent;
                oldScript.parentNode.replaceChild(newScript, oldScript);
            });

            // Обновляем URL без перезагрузки
            if (route !== '/') {
                history.pushState({ route: route }, '', '#' + route);
            } else {
                history.replaceState({ route: '/' }, '', window.location.pathname);
            }

        } catch (error) {
            console.error('[Router] Error:', error);
            this.container.innerHTML =
                '<div style="text-align:center;padding:40px;color:red;">❌ Ошибка соединения</div>';
        }
    }
};

// Запуск при загрузке страницы
document.addEventListener('DOMContentLoaded', function() {
    Router.init();
});

// Обработка кнопки назад в браузере
window.addEventListener('popstate', function(event) {
    var route = (event.state && event.state.route) || '/';
    Router.navigate(route);
});