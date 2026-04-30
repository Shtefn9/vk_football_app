/**
 * API клиент — все запросы к Flask бэкенду
 */
const API = {
    userId: null,  // сохраняем после авторизации, передаём в каждый запрос

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

    getUser: async function() {
        const res = await fetch('/api/user', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ uid: this.userId })
        });
        return await res.json();
    },

    createTeam: async function(data) {
        const res = await fetch('/api/create-team', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ...data, uid: this.userId })
        });
        return await res.json();
    },

    joinTeam: async function(data) {
        const res = await fetch('/api/join-team', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ...data, uid: this.userId })
        });
        return await res.json();
    },

    addEvent: async function(data) {
        const res = await fetch('/api/add-event', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ...data, uid: this.userId })
        });
        return await res.json();
    },

    logout: async function() {
        await fetch('/api/logout');
        this.userId = null;
    }
};