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
    /**
     * Initializes the API client with the base URL and optional token/API key.
     * @param {string} baseURL - The base URL of the API.
     * @param {string|null} [token=null] - Optional authentication token (JWT).
     * @param {string|null} [apiKey=null] - Optional API key.
     */
    constructor(baseURL, token = null, apiKey = null) {
        this.baseURL = baseURL;
        this.token = token;
        this.apiKey = apiKey;

        // if token is null, get it from local storage
        if (!this.token) {
            const storedToken = localStorage.getItem('token');
            if (storedToken) {
                this.token = storedToken;
            }
        }
    }

    /**
     * Sets or clears the authentication token.
     * @param {string|null} token - The JWT token or null to clear it.
     */
    setToken(token) {
        this.token = token;
    }

    /**
     * Makes a request to the API. Automatically adds Authorization header if token is set.
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
                ...headers, // Allow overriding default headers or adding new ones
            },
        };

        // Add Authorization header if token exists
        if (this.token) {
            options.headers['Authorization'] = `Bearer ${this.token}`;
        }

        // Add API key header if it exists (can be used alongside token or independently)
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
            // Clear token on 401 Unauthorized or 403 Forbidden
            if (response.status === 401 || response.status === 403) {
                this.setToken(null);
                // Optionally redirect to login or notify the user
                console.warn(`Authentication error (${response.status}). Token cleared.`);
            }
            throw new Error(`HTTP error! status: ${response.status}, details: ${JSON.stringify(errorBody)}`);
        }
        // Handle cases where response might be empty (e.g., 204 No Content)
        if (response.status === 204) {
            return null;
        }
        return response.json();
    }

    async isLoggedIn() {
        if (!this.token) {
            return false; // No token, definitely not logged in
        }
        try {
            // Request user details using the stored token
            const response = await this.request('/users/me', 'GET');
            return response && response.user_id ? true : false;
        } catch (error) {
            // If the request fails (e.g., token expired, network error), assume not logged in
            console.error("isLoggedIn check failed:", error);
            return false;
        }
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
     * Gets the details of the currently authenticated user (using the stored token).
     * @returns {Promise<{user_id: string, username: string, email: string|null, disabled: boolean, api_keys: Array<string>}>} The user's details.
     */
    async getUserDetails() {
        return this.request('/users/me', 'GET'); // Token added automatically by request()
    }

    /**
     * Gets the details of a specific user by their ID.
     * @param {string} userId - The ID of the user.
     * @returns {Promise<{username: string}>} The user's details.
     */
    async getUserDetailsById(userId) {
        return this.request(`/users/users/${userId}`, 'GET'); // Token added automatically by request()
    }

    /**
     * Updates the details of the currently authenticated user (using the stored token).
     * @param {object} updates - An object containing the fields to update (e.g., { username: 'new_name', email: 'new@example.com' }).
     * @returns {Promise<{user_id: string, username: string, email: string|null, disabled: boolean, api_keys: Array<string>}>} The updated user's details.
     */
    async updateUserDetails(updates) {
        return this.request('/users/me', 'PATCH', updates); // Token added automatically
    }

    /**
     * Deletes the currently authenticated user (using the stored token).
     * @returns {Promise<{message: string}>} Confirmation message.
     */
    async deleteUser() {
        return this.request('/users/me', 'DELETE'); // Token added automatically
    }

    /**
     * Creates a new API key for the currently authenticated user (using the stored token).
     * @returns {Promise<{api_key: string}>} The newly generated API key.
     */
    async createApiKey() {
        return this.request('/users/me/api-keys', 'POST'); // Token added automatically
    }

    /**
     * Deletes an API key for the currently authenticated user (using the stored token).
     * @param {string} apiKey - The API key to delete.
     * @returns {Promise<{message: string}>} Confirmation message.
     */
    async deleteApiKey(apiKey) {
        return this.request(`/users/me/api-keys/${apiKey}`, 'DELETE'); // Token added automatically
    }

    /**
     * Gets all API keys for the currently authenticated user (using the stored token).
     * @returns {Promise<{api_keys: Array<string>}>} A list of the user's API keys.
     */
    async getApiKeys() {
        return this.request('/users/me/api-keys', 'GET'); // Token added automatically
    }

    /**
     * Gets all projects the currently authenticated user is a member of (using the stored token).
     * @returns {Promise<{projects: Array<{_id: string, project_id: string, name: string, owner_id: string, members: Array<string>, repos?: Array<string>}>}>} A list of projects.
     */
    async getUserProjects() {
        return this.request('/users/me/projects', 'GET'); // Token added automatically
    }

    // Project Management
    /**
     * Creates a new project (using the stored token).
     * @param {string} name - The name of the project.
     * @returns {Promise<{message: string, project_id: string}>} Confirmation message and the new project's ID.
     */
    async createProject(name) {
        return this.request('/projects/', 'POST', { name }); // Token added automatically
    }

    /**
     * Adds a member to a project (using the stored token).
     * @param {string} projectId - The ID of the project.
     * @param {string} email - The email address of the user to add.
     * @returns {Promise<{message: string}>} Confirmation message.
     */
    async addMemberToProject(projectId, email) {
        return this.request(`/projects/${projectId}/add-member`, 'POST', { email }); // Token added automatically
    }

    /**
     * Adds a repository to a project (using the stored token).
     * @param {string} projectId - The ID of the project.
     * @param {string} repoUrl - The URL of the Git repository.
     * @returns {Promise<{message: string}>} Confirmation message.
     */
    async addRepoToProject(projectId, repoUrl) {
        return this.request(`/projects/${projectId}/add-repo`, 'POST', { repo_url: repoUrl }); // Token added automatically
    }

    /**
     * Gets the details of a specific project (using the stored token).
     * @param {string} projectId - The ID of the project.
     * @returns {Promise<{_id: string, project_id: string, name: string, owner_id: string, members: Array<string>, repos?: Array<string>}>} The project details.
     */
    async getProjectDetails(projectId) {
        return this.request(`/projects/${projectId}`, 'GET'); // Token added automatically
    }

    /**
     * Updates a project's details (e.g., name) (using the stored token).
     * @param {string} projectId - The ID of the project.
     * @param {object} updates - An object containing the fields to update (e.g., { name: 'New Project Name' }).
     * @returns {Promise<{_id: string, project_id: string, name: string, owner_id: string, members: Array<string>, repos?: Array<string>}>} The updated project details.
     */
    async updateProject(projectId, updates) {
        return this.request(`/projects/${projectId}`, 'PATCH', updates); // Token added automatically
    }

    /**
     * Deletes a project (using the stored token).
     * @param {string} projectId - The ID of the project.
     * @returns {Promise<{message: string}>} Confirmation message.
     */
    async deleteProject(projectId) {
        return this.request(`/projects/${projectId}`, 'DELETE'); // Token added automatically
    }

    /**
     * Gets emotion data for a project within a specified time range (using the stored token).
     * @param {string} projectId - The ID of the project.
     * @param {number} [startTime=0] - The start time as a Unix timestamp (seconds). Defaults to 0.
     * @param {number} [endTime=0] - The end time as a Unix timestamp (seconds). Defaults to the current time if 0.
     * @returns {Promise<{emotions: Array<{_id: string, user_id: string, timestamp: string, emotions: object, received_at: string}>}>} A list of emotion data entries.
     */
    async getProjectEmotions(projectId, startTime, endTime) {
        const queryParams = {};
        if (startTime !== undefined && startTime !== null) queryParams.start_time = startTime;
        if (endTime !== undefined && endTime !== null) queryParams.end_time = endTime;
        // Token added automatically by request()
        return this.request(`/projects/${projectId}/emotions`, 'GET', null, {}, queryParams);
    }

    async getProjectAverageEmotions(projectId, startTime, endTime) {
        const queryParams = {};
        if (startTime !== undefined && startTime !== null) queryParams.start_time = startTime;
        if (endTime !== undefined && endTime !== null) queryParams.end_time = endTime;
        // Token added automatically by request()
        return this.request(`/projects/${projectId}/average-mood`, 'GET', null, {}, queryParams);
    }

    /**
     * Gets paginated individual mood reports for a specific user within a project (using the stored token).
     * @param {string} projectId - The ID of the project.
     * @param {string} userId - The ID of the user whose reports to fetch.
     * @param {number} [page=1] - The page number to retrieve.
     * @param {number} [pageSize=10] - The number of reports per page.
     * @returns {Promise<Array<{_id: string, user_id: string, project_id: string, report_timestamp: string, start_time: string, end_time: string, average_emotions: object, mood_summary: string, processed_entries: number, commit_count: number, report_type: string, is_alarm: boolean, alarm_message: string|null}>>} A list of individual mood reports.
     */
    async getIndividualReports(projectId, userId, page = 1, pageSize = 10) {
        const queryParams = {
            user_id: userId,
            page: page,
            page_size: pageSize,
        };
        // Token added automatically by request()
        return this.request(`/projects/${projectId}/reports/individual`, 'GET', null, {}, queryParams);
    }

    /**
     * Gets paginated group mood reports for a project (using the stored token).
     * @param {string} projectId - The ID of the project.
     * @param {number} [page=1] - The page number to retrieve.
     * @param {number} [pageSize=10] - The number of reports per page.
     * @returns {Promise<Array<{_id: string, user_id: null, project_id: string, report_timestamp: string, start_time: string, end_time: string, average_emotions: object, mood_summary: string, processed_entries: number, commit_count: number, processed_user_count: number, report_type: string, is_alarm: boolean, alarm_message: null}>>} A list of group mood reports.
     */
    async getGroupReports(projectId, page = 1, pageSize = 10) {
        const queryParams = {
            page: page,
            page_size: pageSize,
        };
        // Token added automatically by request()
        return this.request(`/projects/${projectId}/reports/group`, 'GET', null, {}, queryParams);
    }

    // Authentication
    /**
     * Logs in a user, retrieves an access token, and stores it in the instance.
     * @param {string} username - The username.
     * @param {string} password - The password.
     * @returns {Promise<{access_token: string, token_type: string}>} The access token and token type ('bearer').
     */
    async login(username, password) {
        const body = new URLSearchParams({ username, password });
        const tokenUrl = urlJoin(this.baseURL, '/token');
        const response = await fetch(tokenUrl, {
            method: 'POST',
            // 'Content-Type' header is automatically set to 'application/x-www-form-urlencoded'
            // by fetch when the body is URLSearchParams
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
            this.setToken(null); // Clear any existing token on login failure
            throw new Error(`HTTP error! status: ${response.status}, details: ${JSON.stringify(errorBody)}`);
        }
        const tokenData = await response.json();
        if (tokenData.access_token) {
            this.setToken(tokenData.access_token); // Store the token
        } else {
            this.setToken(null); // Ensure token is cleared if login response is malformed
            throw new Error("Login successful but no access_token received.");
        }
        return tokenData; // Return the full token data ({access_token, token_type})
    }
}

// Create a default instance (without token initially)
export const chorusAPI = new ChorusAPI('http://170.9.230.52:8000/');