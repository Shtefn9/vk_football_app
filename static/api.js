/**
 * API клиент — все запросы к Flask бэкенду
 */
const API = {

    vkAuth: async function(vkData) {
        const res = await fetch('/api/vk-auth', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(vkData)
        });
        return await res.json();
    },

    getUser: async function() {
        const res = await fetch('/api/user');
        return await res.json();
    },

    createTeam: async function(data) {
        const res = await fetch('/api/create-team', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        return await res.json();
    },

    joinTeam: async function(data) {
        const res = await fetch('/api/join-team', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        return await res.json();
    },

    addEvent: async function(data) {
        const res = await fetch('/api/add-event', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        return await res.json();
    },

    logout: async function() {
        await fetch('/api/logout');
    }
};