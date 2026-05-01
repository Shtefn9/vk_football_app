/**
 * API клиент — все запросы к Flask бэкенду
 */
const API = {
    userId: null,
    currentTeamId: null,

    vkAuth: async function(vkData) {
        const res = await fetch('/api/vk-auth', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(vkData)
        });
        const data = await res.json();
        if (data.id) {
            this.userId = data.id;
            console.log('[API] userId сохранён:', this.userId);
        }
        return data;
    },

    selectTeam: async function(teamId) {
    const res = await fetch('/api/select-team', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ uid: this.userId, team_id: teamId })
    });
    const data = await res.json();
    if (data.success) {
        this.currentTeamId = teamId;  // сохраняем локально
        }
    return data;
    },

    createTeam: async function(data) {
        const res = await fetch('/api/create-team', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ...data, uid: this.userId })
        });
        const result = await res.json();
        if (result.success) {
            this.currentTeamId = result.team_id;
        }
        return result;
    },

    joinTeam: async function(data) {
        const res = await fetch('/api/join-team', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ...data, uid: this.userId })
        });
        const result = await res.json();
        if (result.success) {
            this.currentTeamId = result.team_id;
        }
        return result;
    },

    addEvent: async function(data) {
        const res = await fetch('/api/add-event', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ...data, uid: this.userId, team_id: this.currentTeamId })
        });
        return await res.json();
    },

    leaveTeam: async function() {
        await fetch('/api/leave-team', { method: 'POST' });
        this.currentTeamId = null;
    },

    logout: async function() {
        await fetch('/api/logout');
        this.userId = null;
        this.currentTeamId = null;
    }
};