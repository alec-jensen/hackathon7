function urlJoin(...args) {
    // Ensure all parts are strings and trim whitespace
    const parts = args.map(part => String(part).trim());
    if (parts.length === 0) return '';

    // Handle the base URL separately
    let joined = parts[0];

    for (let i = 1; i < parts.length; i++) {
        let part = parts[i];
        if (!part) continue; // Skip empty/null parts

        // Avoid double slashes
        if (joined.endsWith('/')) {
            joined = joined.slice(0, -1);
        }
        if (part.startsWith('/')) {
            part = part.slice(1);
        }
        joined = `${joined}/${part}`;
    }

    // Ensure the final URL doesn't end with a slash if the last part didn't
    // (unless it's just the base URL like "http://example.com/")
    const lastPart = parts[parts.length - 1];
    if (joined !== parts[0] && !lastPart.endsWith('/') && joined.endsWith('/')) {
         joined = joined.slice(0, -1);
    }

    return joined;
}

export default class ChorusAPI {
    constructor(baseURL, apiKey = null) {
        this.baseURL = baseURL;
        this.apiKey = apiKey;
    }

    /**
     * Makes a request to the API.
     * @param {string} endpoint - The API endpoint path.
     * @param {string} [method='GET'] - The HTTP method.
     * @param {object|null} [body=null] - The request body for POST/PATCH/PUT/DELETE.
     * @param {object} [headers={}] - Additional request headers.
     * @param {object} [queryParams={}] - Query parameters for GET requests.
     * @returns {Promise<object|null>} The JSON response from the API or null for 204 responses.
     * @throws {Error} If the network request fails or the API returns an error status.
     */
    async request(endpoint, method = 'GET', body = null, headers = {}, queryParams = {}) {
        // Construct query string if queryParams are provided
        const queryString = Object.keys(queryParams)
            .map(key => `${encodeURIComponent(key)}=${encodeURIComponent(queryParams[key])}`)
            .join('&');
        const baseEndpointUrl = urlJoin(this.baseURL, endpoint);
        const url = `${baseEndpointUrl}${queryString ? `?${queryString}` : ''}`; // Append query string

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

        if (body && (method === 'POST' || method === 'PATCH' || method === 'PUT' || method === 'DELETE')) { // Only add body for relevant methods
            options.body = JSON.stringify(body);
        }

        const response = await fetch(url, options);
        if (!response.ok) {
            let errorBody;
            try {
                errorBody = await response.json(); // Try to parse error details
            } catch (e) {
                errorBody = await response.text(); // Fallback to text
            }
            console.error("API Error Response:", errorBody); // Log error details
            throw new Error(`HTTP error! status: ${response.status}, details: ${JSON.stringify(errorBody)}`);
        }
        // Handle cases where response might be empty (e.g., 204 No Content)
        if (response.status === 204) {
            return null;
        }
        return response.json();
    }

    // User Management
    /**
     * Creates a new user.
     * @param {string} username - The desired username.
     * @param {string} password - The desired password.
     * @param {string|null} [email=null] - The user's email address (optional).
     * @returns {Promise<{message: string, user_id: string}>} Confirmation message and the new user's ID.
     */
    async createUser(username, password, email = null) {
        return this.request('/users/', 'POST', { username, password, email });
    }

    /**
     * Gets the details of the currently authenticated user.
     * @param {string} token - The authentication token (JWT).
     * @returns {Promise<{user_id: string, username: string, email: string|null, disabled: boolean, api_keys: Array<string>}>} The user's details.
     */
    async getUserDetails(token) {
        return this.request('/users/me', 'GET', null, { Authorization: `Bearer ${token}` });
    }

    /**
     * Updates the details of the currently authenticated user.
     * @param {string} token - The authentication token (JWT).
     * @param {object} updates - An object containing the fields to update (e.g., { username: 'new_name', email: 'new@example.com' }).
     * @returns {Promise<{user_id: string, username: string, email: string|null, disabled: boolean, api_keys: Array<string>}>} The updated user's details.
     */
    async updateUserDetails(token, updates) {
        return this.request('/users/me', 'PATCH', updates, { Authorization: `Bearer ${token}` });
    }

    /**
     * Deletes the currently authenticated user.
     * @param {string} token - The authentication token (JWT).
     * @returns {Promise<{message: string}>} Confirmation message.
     */
    async deleteUser(token) {
        return this.request('/users/me', 'DELETE', null, { Authorization: `Bearer ${token}` });
    }

    /**
     * Creates a new API key for the currently authenticated user.
     * @param {string} token - The authentication token (JWT).
     * @returns {Promise<{api_key: string}>} The newly generated API key.
     */
    async createApiKey(token) {
        return this.request('/users/me/api-keys', 'POST', null, { Authorization: `Bearer ${token}` });
    }

    /**
     * Deletes an API key for the currently authenticated user.
     * @param {string} token - The authentication token (JWT).
     * @param {string} apiKey - The API key to delete.
     * @returns {Promise<{message: string}>} Confirmation message.
     */
    async deleteApiKey(token, apiKey) {
        return this.request(`/users/me/api-keys/${apiKey}`, 'DELETE', null, { Authorization: `Bearer ${token}` });
    }

    /**
     * Gets all API keys for the currently authenticated user.
     * @param {string} token - The authentication token (JWT).
     * @returns {Promise<{api_keys: Array<string>}>} A list of the user's API keys.
     */
    async getApiKeys(token) {
        return this.request('/users/me/api-keys', 'GET', null, { Authorization: `Bearer ${token}` });
    }

    /**
     * Gets all projects the currently authenticated user is a member of.
     * @param {string} token - The authentication token (JWT).
     * @returns {Promise<{projects: Array<{_id: string, project_id: string, name: string, owner_id: string, members: Array<string>, repos?: Array<string>}>}>} A list of projects.
     */
    async getUserProjects(token) {
        return this.request('/users/me/projects', 'GET', null, { Authorization: `Bearer ${token}` });
    }

    // Project Management
    /**
     * Creates a new project.
     * @param {string} name - The name of the project.
     * @param {string} token - The authentication token (JWT).
     * @returns {Promise<{message: string, project_id: string}>} Confirmation message and the new project's ID.
     */
    async createProject(name, token) {
        return this.request('/projects/', 'POST', { name }, { Authorization: `Bearer ${token}` });
    }

    /**
     * Adds a member to a project.
     * @param {string} projectId - The ID of the project.
     * @param {string} email - The email address of the user to add.
     * @param {string} token - The authentication token (JWT).
     * @returns {Promise<{message: string}>} Confirmation message.
     */
    async addMemberToProject(projectId, email, token) {
        return this.request(`/projects/${projectId}/add-member`, 'POST', { email }, { Authorization: `Bearer ${token}` });
    }

    /**
     * Adds a repository to a project.
     * @param {string} projectId - The ID of the project.
     * @param {string} repoUrl - The URL of the Git repository.
     * @param {string} token - The authentication token (JWT).
     * @returns {Promise<{message: string}>} Confirmation message.
     */
    async addRepoToProject(projectId, repoUrl, token) {
        return this.request(`/projects/${projectId}/add-repo`, 'POST', { repo_url: repoUrl }, { Authorization: `Bearer ${token}` });
    }

    /**
     * Gets the details of a specific project.
     * @param {string} projectId - The ID of the project.
     * @param {string} token - The authentication token (JWT).
     * @returns {Promise<{_id: string, project_id: string, name: string, owner_id: string, members: Array<string>, repos?: Array<string>}>} The project details.
     */
    async getProjectDetails(projectId, token) {
        return this.request(`/projects/${projectId}`, 'GET', null, { Authorization: `Bearer ${token}` });
    }

    /**
     * Updates a project's details (e.g., name).
     * @param {string} projectId - The ID of the project.
     * @param {object} updates - An object containing the fields to update (e.g., { name: 'New Project Name' }).
     * @param {string} token - The authentication token (JWT).
     * @returns {Promise<{_id: string, project_id: string, name: string, owner_id: string, members: Array<string>, repos?: Array<string>}>} The updated project details.
     */
    async updateProject(projectId, updates, token) {
        return this.request(`/projects/${projectId}`, 'PATCH', updates, { Authorization: `Bearer ${token}` });
    }

    /**
     * Deletes a project.
     * @param {string} projectId - The ID of the project.
     * @param {string} token - The authentication token (JWT).
     * @returns {Promise<{message: string}>} Confirmation message.
     */
    async deleteProject(projectId, token) {
        return this.request(`/projects/${projectId}`, 'DELETE', null, { Authorization: `Bearer ${token}` });
    }

    /**
     * Gets emotion data for a project within a specified time range.
     * @param {string} projectId - The ID of the project.
     * @param {number} [startTime=0] - The start time as a Unix timestamp (seconds). Defaults to 0.
     * @param {number} [endTime=0] - The end time as a Unix timestamp (seconds). Defaults to the current time if 0.
     * @param {string} token - The authentication token (JWT).
     * @returns {Promise<{emotions: Array<{_id: string, user_id: string, timestamp: string, emotions: object, received_at: string}>}>} A list of emotion data entries.
     */
    async getProjectEmotions(projectId, startTime, endTime, token) {
        const queryParams = {};
        if (startTime !== undefined && startTime !== null) queryParams.start_time = startTime;
        if (endTime !== undefined && endTime !== null) queryParams.end_time = endTime;
        return this.request(`/projects/${projectId}/emotions`, 'GET', null, {
            Authorization: `Bearer ${token}`
        }, queryParams); // Pass query params here
    }

    /**
     * Gets paginated individual mood reports for a specific user within a project.
     * @param {string} projectId - The ID of the project.
     * @param {string} userId - The ID of the user whose reports to fetch.
     * @param {string} token - The authentication token (JWT).
     * @param {number} [page=1] - The page number to retrieve.
     * @param {number} [pageSize=10] - The number of reports per page.
     * @returns {Promise<Array<{_id: string, user_id: string, project_id: string, report_timestamp: string, start_time: string, end_time: string, average_emotions: object, mood_summary: string, processed_entries: number, commit_count: number, report_type: string, is_alarm: boolean, alarm_message: string|null}>>} A list of individual mood reports.
     */
    async getIndividualReports(projectId, userId, token, page = 1, pageSize = 10) {
        const queryParams = {
            user_id: userId,
            page: page,
            page_size: pageSize,
        };
        return this.request(`/projects/${projectId}/reports/individual`, 'GET', null, {
            Authorization: `Bearer ${token}`
        }, queryParams);
    }

    /**
     * Gets paginated group mood reports for a project.
     * @param {string} projectId - The ID of the project.
     * @param {string} token - The authentication token (JWT).
     * @param {number} [page=1] - The page number to retrieve.
     * @param {number} [pageSize=10] - The number of reports per page.
     * @returns {Promise<Array<{_id: string, user_id: null, project_id: string, report_timestamp: string, start_time: string, end_time: string, average_emotions: object, mood_summary: string, processed_entries: number, commit_count: number, processed_user_count: number, report_type: string, is_alarm: boolean, alarm_message: null}>>} A list of group mood reports.
     */
    async getGroupReports(projectId, token, page = 1, pageSize = 10) {
        const queryParams = {
            page: page,
            page_size: pageSize,
        };
        return this.request(`/projects/${projectId}/reports/group`, 'GET', null, {
            Authorization: `Bearer ${token}`
        }, queryParams);
    }

    // Authentication
    /**
     * Logs in a user and retrieves an access token.
     * @param {string} username - The username.
     * @param {string} password - The password.
     * @returns {Promise<{access_token: string, token_type: string}>} The access token and token type ('bearer').
     */
    async login(username, password) {
        const body = new URLSearchParams({ username, password });
        const tokenUrl = urlJoin(this.baseURL, '/token');
        const response = await fetch(tokenUrl, {
            method: 'POST',
            body,
        });
        if (!response.ok) {
            // Try to get more details from the error response
            let errorBody;
            try {
                errorBody = await response.json();
            } catch (e) {
                errorBody = await response.text();
            }
            console.error("Login API Error Response:", errorBody);
            throw new Error(`HTTP error! status: ${response.status}, details: ${JSON.stringify(errorBody)}`);
        }
        return response.json();
    }
}

export const chorusAPI = new ChorusAPI('http://170.9.230.52:8000/');