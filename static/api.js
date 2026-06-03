const API = {
    userId: null,
    currentTeamId: null,
    // Подписанные параметры запуска от VK — используются для безопасной авторизации
    vkLaunchParams: null,

    /**
     * Сохраняет launch params из URL. Вызывается один раз при загрузке.
     */
    initLaunchParams: function() {
        // Берём всю строку запроса как есть, в том виде в котором её прислал VK
        var search = window.location.search;
        if (search && search.length > 1) {
            this.vkLaunchParams = search.substring(1); // убираем ведущий '?'
            console.log('[API] Launch params saved');
        } else {
            console.warn('[API] No launch params in URL');
        }
    },

    /**
     * Базовый метод POST-запроса с автоматическим добавлением vk_launch_params.
     */
    post: async function(url, body) {
        body = body || {};
        if (this.vkLaunchParams) {
            body.vk_launch_params = this.vkLaunchParams;
        }
        // uid оставляем для обратной совместимости, но сервер должен доверять только vk_launch_params
        if (this.userId) body.uid = this.userId;
        if (this.currentTeamId && body.team_id === undefined) body.team_id = this.currentTeamId;

        const res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        return await res.json();
    },

    vkAuth: async function(vkData) {
        const data = await this.post('/api/vk-auth', vkData);
        if (data.id) { this.userId = data.id; console.log('[API] userId:', this.userId); }
        return data;
    },

    selectTeam: async function(teamId) {
        const data = await this.post('/api/select-team', { team_id: teamId });
        if (data.success) this.currentTeamId = teamId;
        return data;
    },

    createTeam: async function(data) {
        const result = await this.post('/api/create-team', data);
        if (result.success) this.currentTeamId = result.team_id;
        return result;
    },

    setStatsLevel: async function(level) {
        return await this.post('/api/set-stats-level', { stats_level: level });
    },

    createPayment: async function() {
        return await this.post('/api/create-payment', {});
    },

    startTrial: async function() {
        return await this.post('/api/start-trial', {});
    },

    setPosition: async function(playerId, position) {
        return await this.post('/api/set-position', { player_id: playerId, position: position });
    },

    joinTeam: async function(data) {
        const result = await this.post('/api/join-team', data);
        if (result.success) this.currentTeamId = result.team_id;
        return result;
    },

    addEvent: async function(data) {
        return await this.post('/api/add-event', data);
    },

    saveStats: async function(data) {
        return await this.post('/api/save-stats', data);
    },

    toggleAttendance: async function(data) {
    return await this.post('/api/toggle-attendance', data);
},

    leaveTeam: async function() {
        await this.post('/api/leave-team', {});
        this.currentTeamId = null;
    },

    quitTeam: async function() {
        const result = await this.post('/api/quit-team', {});
        if (result.success) this.currentTeamId = null;
        return result;
    },

    logout: async function() {
        await fetch('/api/logout');
        this.userId = null;
        this.currentTeamId = null;
    }
};

// Инициализируем launch params сразу при загрузке скрипта
API.initLaunchParams();