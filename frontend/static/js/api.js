/**
 * VeriPack API client. Every fetch() call in the app goes through here so
 * auth headers, error handling, and the base URL are defined exactly once.
 */
const Api = (() => {
    function token() {
        return localStorage.getItem("veripack_token");
    }

    function setToken(t) {
        if (t) localStorage.setItem("veripack_token", t);
        else localStorage.removeItem("veripack_token");
    }

    function currentUser() {
        const raw = localStorage.getItem("veripack_user");
        return raw ? JSON.parse(raw) : null;
    }

    function setCurrentUser(u) {
        if (u) localStorage.setItem("veripack_user", JSON.stringify(u));
        else localStorage.removeItem("veripack_user");
    }

    async function fetchWithRetry(path, options, method) {
        const maxRetries = method === "GET" ? 2 : 0;
        for (let attempt = 0; attempt <= maxRetries; attempt++) {
            try {
                return await fetch(path, options);
            } catch (networkErr) {
                if (attempt < maxRetries) {
                    await new Promise((resolve) => setTimeout(resolve, 2500));
                } else {
                    throw new Error("Could not reach the server. It may still be waking up -- please try again in a few seconds.");
                }
            }
        }
    }

    async function request(path, { method = "GET", body = null, isFormData = false } = {}) {
        const headers = {};
        const t = token();
        if (t) headers["Authorization"] = `Bearer ${t}`;
        if (body && !isFormData) headers["Content-Type"] = "application/json";

        const resp = await fetchWithRetry(path, {
            method,
            headers,
            body: isFormData ? body : (body ? JSON.stringify(body) : undefined),
        }, method);

        if (resp.status === 401) {
            setToken(null);
            setCurrentUser(null);
            window.location.hash = "#/login";
            throw new Error("Session expired. Please log in again.");
        }

        const contentType = resp.headers.get("content-type") || "";
        if (contentType.includes("application/json")) {
            const data = await resp.json();
            if (!resp.ok) {
                throw new Error(data.message || data.error || "Request failed.");
            }
            return data;
        }
        if (!resp.ok) {
            throw new Error(`Request failed with status ${resp.status}`);
        }
        return resp;
    }

    return {
        login: (email, password) => request("/api/auth/login", { method: "POST", body: { email, password } }),
        me: () => request("/api/auth/me"),

        createCheck: (formData) => request("/api/checks", { method: "POST", body: formData, isFormData: true }),
                createCheck: (formData) => request("/api/checks", { method: "POST", body: formData, isFormData: true }),
        createBulkChecks: (formData) => request("/api/checks/bulk", { method: "POST", body: formData, isFormData: true }),
        processCheck: (id) => request(`/api/checks/${id}/process`, { method: "POST" }),
        listChecks: (filters = {}) => {
            const qs = new URLSearchParams();
            Object.entries(filters).forEach(([key, value]) => {
                if (value) qs.set(key, value);
            });
            const query = qs.toString();
            return request(`/api/checks${query ? `?${query}` : ""}`);
        },
        getCheck: (id) => request(`/api/checks/${id}`),
        getResults: (id) => request(`/api/checks/${id}/results`),
        getEvidence: (id) => request(`/api/checks/${id}/evidence`),
        evidenceImageUrl: (id, kind) => `/api/checks/${id}/evidence/${kind}?t=${token() || ""}`,
        generateReport: (id) => request(`/api/checks/${id}/report`, { method: "POST" }),
        reportDownloadUrl: (id) => `/api/checks/${id}/report`,
                reportDownloadUrl: (id) => `/api/checks/${id}/report`,
        downloadReportBlob: async (id) => {
            const resp = await fetch(`/api/checks/${id}/report`, {
                headers: { Authorization: `Bearer ${token()}` },
            });
            if (!resp.ok) throw new Error("Failed to download report.");
            return resp.blob();
        },

        listReviews: (status = "PENDING") => request(`/api/reviews?status=${status}`),
        submitReviewDecision: (taskId, payload) =>
            request(`/api/reviews/${taskId}/decision`, { method: "POST", body: payload }),

        listRuleVersions: (category = null) =>
            request(`/api/rules${category ? `?category=${category}` : ""}`),
        getRuleVersion: (id) => request(`/api/rules/${id}`),
        createRuleVersion: (payload) => request("/api/rules", { method: "POST", body: payload }),
        duplicateRuleVersion: (id, payload) => request(`/api/rules/${id}/duplicate`, { method: "POST", body: payload }),
        updateRuleVersion: (id, payload) => request(`/api/rules/${id}`, { method: "PUT", body: payload }),
        addRequirement: (id, payload) => request(`/api/rules/${id}/requirements`, { method: "POST", body: payload }),
        activateRuleVersion: (id, payload) => request(`/api/rules/${id}/activate`, { method: "POST", body: payload }),

        dashboardSummary: () => request("/api/dashboard/summary"),
        dashboardTrends: () => request("/api/dashboard/trends"),

        auditLogs: (params = {}) => {
            const qs = new URLSearchParams(params).toString();
            return request(`/api/audit-logs${qs ? `?${qs}` : ""}`);
        },

        token, setToken, currentUser, setCurrentUser,
    };
})();
