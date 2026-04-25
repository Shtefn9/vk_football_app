/**
 * Футбольная команда - Главный JavaScript файл
 */

document.addEventListener('DOMContentLoaded', function() {
    console.log('[App] DOM loaded');

    // Инициализация вкладок (если есть на странице)
    initTabs();

    // Инициализация форм
    initForms();
});

// Переключение вкладок
function showTab(tabName) {
    console.log('[Tabs] Switching to:', tabName);

    document.querySelectorAll('.tab').forEach(function(tab) {
        tab.classList.remove('active');
    });

    document.querySelectorAll('.nav button').forEach(function(btn) {
        btn.classList.remove('active');
    });

    const targetTab = document.getElementById(tabName);
    const targetBtn = document.getElementById('btn-' + tabName);

    if (targetTab) targetTab.classList.add('active');
    if (targetBtn) targetBtn.classList.add('active');
}

function initTabs() {
    const navButtons = document.querySelectorAll('.nav button');
    if (navButtons.length === 0) return;

    console.log('[Tabs] Initializing tabs');

    navButtons.forEach(function(button) {
        button.addEventListener('click', function() {
            const tabName = this.id.replace('btn-', '');
            showTab(tabName);
        });
    });
}

// Управление формами
function initForms() {
    // Авто-апкейс для кода команды
    const joinCodeInput = document.querySelector('input[name="join_code"]');
    if (joinCodeInput) {
        joinCodeInput.addEventListener('input', function() {
            this.value = this.value.toUpperCase();
        });
    }
}

// Показать/скрыть форму добавления события
function toggleAddEventForm() {
    const form = document.getElementById('addEventForm');
    if (!form) return;

    if (form.style.display === 'none' || form.style.display === '') {
        form.style.display = 'block';
    } else {
        form.style.display = 'none';
    }
}