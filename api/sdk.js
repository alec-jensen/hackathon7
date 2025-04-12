export default class ChorusAPI {
    constructor(baseURL, apiKey = null) {
        this.baseURL = baseURL;
        this.apiKey = apiKey;
    }

    async request(endpoint, method = 'GET', body = null, headers = {}) {
        const url = `${this.baseURL}${endpoint}`;
        const options = {
            method,
            headers: {
                'Content-Type': 'application/json',
                ...headers,
            },
        };

        if (this.apiKey) {
            options.headers['x-api-key'] = this.apiKey;
        }

        if (body) {
            options.body = JSON.stringify(body);
        }

        const response = await fetch(url, options);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
    }

    // User Management
    async createUser(username, password, email = null) {
        return this.request('/users/', 'POST', { username, password, email });
    }

    async getUserDetails(token) {
        return this.request('/users/me', 'GET', null, { Authorization: `Bearer ${token}` });
    }

    async updateUserDetails(token, updates) {
        return this.request('/users/me', 'PATCH', updates, { Authorization: `Bearer ${token}` });
    }

    async deleteUser(token) {
        return this.request('/users/me', 'DELETE', null, { Authorization: `Bearer ${token}` });
    }

    async createApiKey(token) {
        return this.request('/users/me/api-keys', 'POST', null, { Authorization: `Bearer ${token}` });
    }

    async deleteApiKey(token, apiKey) {
        return this.request(`/users/me/api-keys/${apiKey}`, 'DELETE', null, { Authorization: `Bearer ${token}` });
    }

    async getApiKeys(token) {
        return this.request('/users/me/api-keys', 'GET', null, { Authorization: `Bearer ${token}` });
    }

    async getUserProjects(token) {
        return this.request('/users/me/projects', 'GET', null, { Authorization: `Bearer ${token}` });
    }

    // Project Management
    async createProject(name, token) {
        return this.request('/projects/', 'POST', { name }, { Authorization: `Bearer ${token}` });
    }

    async addMemberToProject(projectId, email, token) {
        return this.request(`/projects/${projectId}/add-member`, 'POST', { email }, { Authorization: `Bearer ${token}` });
    }

    async addRepoToProject(projectId, repoUrl, token) {
        return this.request(`/projects/${projectId}/add-repo`, 'POST', { repo_url: repoUrl }, { Authorization: `Bearer ${token}` });
    }

    async getProjectDetails(projectId, token) {
        return this.request(`/projects/${projectId}`, 'GET', null, { Authorization: `Bearer ${token}` });
    }

    async updateProject(projectId, updates, token) {
        return this.request(`/projects/${projectId}`, 'PATCH', updates, { Authorization: `Bearer ${token}` });
    }

    async deleteProject(projectId, token) {
        return this.request(`/projects/${projectId}`, 'DELETE', null, { Authorization: `Bearer ${token}` });
    }

    async getProjectEmotions(projectId, startTime, endTime, token) {
        return this.request(`/projects/${projectId}/emotions`, 'GET', null, {
            Authorization: `Bearer ${token}`,
            'start_time': startTime,
            'end_time': endTime,
        });
    }

    // Authentication
    async login(username, password) {
        const body = new URLSearchParams({ username, password });
        const response = await fetch(`${this.baseURL}/token`, {
            method: 'POST',
            body,
        });
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
    }
}