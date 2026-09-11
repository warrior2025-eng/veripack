/**
 * VeriPack frontend application.
 *
 * A vanilla-JS hash router instead of React/Vite/Tailwind (the PRD's stated
 * preference) -- this sandbox has no network access to npm's registry
 * (`npm install react` fails: registry request returns host_not_allowed),
 * so nothing that needs to be fetched from npm can be used here. This file
 * talks to exactly the same JSON API a React app would; see
 * docs/ARCHITECTURE.md for what porting to React/Vite/Tailwind involves
 * (it is a frontend-only change -- zero backend changes required, because
 * the API in api.js is already the full contract).
 */

const VERDICT_LABELS = {
    COMPLIANT: "Compliant with checked requirements",
    POTENTIAL_NON_COMPLIANCE: "Potential non-compliance detected",
    REQUIRES_OFFICER_VERIFICATION: "Requires officer verification",
    INSUFFICIENT_EVIDENCE: "Insufficient evidence",
};

const NAV_ITEMS = [
    { path: "#/dashboard", label: "Dashboard", icon: "\u25A4", roles: null },
    { path: "#/scan", label: "Scan Product", icon: "\u2795", roles: null },
    { path: "#/checks", label: "Inspection History", icon: "\u2637", roles: null },
    { path: "#/reviews", label: "Review Queue", icon: "\u26A0", roles: null },
    { path: "#/admin/rules", label: "Regulatory Rules", icon: "\u2696", roles: ["ADMIN"] },
    { path: "#/audit", label: "Audit Log", icon: "\u2261", roles: ["ADMIN", "SENIOR_OFFICER"] },
];

function el(html) {
    const t = document.createElement("template");
    t.innerHTML = html.trim();
    return t.content.firstElementChild;
}

function escapeHtml(str) {
    if (str === null || str === undefined) return "";
    return String(str).replace(/[&<>"']/g, (c) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
}

function fmtDate(iso) {
    if (!iso) return "-";
    try {
        return new Date(iso.replace(" ", "T") + "Z").toLocaleString();
    } catch { return iso; }
}

function verdictBadge(verdict) {
    return `<span class="badge ${verdict}">${VERDICT_LABELS[verdict] || verdict}</span>`;
}

// ---------------------------------------------------------------------------
// Shell: sidebar + routed content
// ---------------------------------------------------------------------------

function renderShell(activePath, contentHtml) {
    const user = Api.currentUser();
    const app = document.getElementById("app");
    const nav = NAV_ITEMS
        .filter((item) => !item.roles || item.roles.includes(user.role))
        .map((item) => `<a href="${item.path}" class="${activePath.startsWith(item.path) ? "active" : ""}">
            <span>${item.icon}</span> ${item.label}</a>`)
        .join("");

    app.innerHTML = `
    <div class="app-shell">
        <div class="sidebar">
            <div class="brand">
                <h1>VeriPack</h1>
                <p>Scan the label. See the rule.<br/>Trust the evidence.</p>
            </div>
            <nav>${nav}</nav>
            <div class="user-box">
                <div>${escapeHtml(user.name)}</div>
                <div class="role-badge">${user.role}</div>
                <div style="margin-top:10px;"><a href="#" id="logout-link" style="color:rgba(255,255,255,0.7);font-size:12px;">Log out</a></div>
            </div>
        </div>
        <div class="main" id="main-content">${contentHtml}</div>
    </div>`;

    document.getElementById("logout-link").addEventListener("click", (e) => {
        e.preventDefault();
        Api.setToken(null);
        Api.setCurrentUser(null);
        window.location.hash = "#/login";
    });
}

function mainContent() {
    return document.getElementById("main-content");
}

// ---------------------------------------------------------------------------
// View: Login
// ---------------------------------------------------------------------------

function renderLogin() {
    document.getElementById("app").innerHTML = `
    <div class="login-screen">
        <div class="login-card">
            <p class="brand-title">VeriPack</p>
            <p class="brand-tagline">"Scan the label. See the rule. Trust the evidence."</p>
            <p style="font-size:13px;color:#5b6b7c;">AI-assisted Legal Metrology compliance screening for packaged commodities.</p>
            <form id="login-form">
                <label>Email</label>
                <input type="email" id="login-email" required value="officer@veripack.demo" />
                <label>Password</label>
                <input type="password" id="login-password" required value="ChangeMe123!" />
                <div id="login-error"></div>
                <button type="submit" class="primary" style="width:100%;margin-top:20px;">Log in</button>
            </form>
            <div class="hint-box">
                Demo credentials: <strong>officer@veripack.demo</strong> / <strong>admin@veripack.demo</strong>,
                password <strong>ChangeMe123!</strong> for both (development seed data only).
            </div>
        </div>
    </div>`;

    document.getElementById("login-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const email = document.getElementById("login-email").value;
        const password = document.getElementById("login-password").value;
        const errorBox = document.getElementById("login-error");
        errorBox.innerHTML = "";
        try {
            const res = await Api.login(email, password);
            Api.setToken(res.token);
            Api.setCurrentUser(res.user);
            window.location.hash = "#/dashboard";
        } catch (err) {
            errorBox.innerHTML = `<div class="error-banner">${escapeHtml(err.message)}</div>`;
        }
    });
}

// ---------------------------------------------------------------------------
// View: Dashboard
// ---------------------------------------------------------------------------

async function renderDashboard() {
    renderShell("#/dashboard", `<div class="empty-state">Loading dashboard...<br/><span class="spinner"></span></div>`);
    let summary;
    try {
        summary = await Api.dashboardSummary();
    } catch (err) {
        mainContent().innerHTML = `<div class="error-banner">${escapeHtml(err.message)}</div>`;
        return;
    }
    const v = summary.verdict_counts;

    const recentRows = summary.recent_checks.length
        ? summary.recent_checks.map((c) => `
            <tr onclick="window.location.hash='#/checks/${c.id}'">
                <td>#${c.id}</td><td>${escapeHtml(c.product_name || "-")}</td>
                <td>${escapeHtml(c.category || "-")}</td>
                <td><span class="status-pill">${c.status}</span></td>
                <td>${fmtDate(c.created_at)}</td>
            </tr>`).join("")
        : `<tr><td colspan="5" style="text-align:center;color:#5b6b7c;padding:24px;">No compliance checks yet. Try "Scan Product".</td></tr>`;

    const ruleRows = summary.rule_version_usage.length
        ? summary.rule_version_usage.map((r) => `
            <tr><td>${escapeHtml(r.name)} (v${escapeHtml(r.version_label)})</td>
                <td><span class="status-pill">${r.status}</span></td>
                <td>${r.usage_count}</td></tr>`).join("")
        : `<tr><td colspan="3" style="text-align:center;color:#5b6b7c;padding:16px;">No rule versions yet.</td></tr>`;

    mainContent().innerHTML = `
        <div class="page-header">
            <div><h2>Enforcement Dashboard</h2><p class="subtitle">Live data from the compliance database -- no fabricated figures.</p></div>
        </div>
        <div class="stat-grid">
            <div class="stat-box"><div class="value">${summary.total_checks}</div><div class="label">Total Checks</div></div>
            <div class="stat-box compliant"><div class="value">${v.COMPLIANT}</div><div class="label">Compliant Requirements</div></div>
            <div class="stat-box non-compliance"><div class="value">${v.POTENTIAL_NON_COMPLIANCE}</div><div class="label">Potential Non-Compliance</div></div>
            <div class="stat-box review"><div class="value">${v.REQUIRES_OFFICER_VERIFICATION}</div><div class="label">Requires Verification</div></div>
            <div class="stat-box insufficient"><div class="value">${v.INSUFFICIENT_EVIDENCE}</div><div class="label">Insufficient Evidence</div></div>
            <div class="stat-box"><div class="value">${summary.pending_reviews}</div><div class="label">Pending Reviews</div></div>
        </div>
        <div class="card">
            <h3>Recent Inspections</h3>
            <table class="data-table">
                <thead><tr><th>ID</th><th>Product</th><th>Category</th><th>Status</th><th>Submitted</th></tr></thead>
                <tbody>${recentRows}</tbody>
            </table>
        </div>
        <div class="card">
            <h3>Rule Version Usage</h3>
            <table class="data-table">
                <thead><tr><th>Rule Version</th><th>Status</th><th># Checks Using It</th></tr></thead>
                <tbody>${ruleRows}</tbody>
            </table>
        </div>`;
}

// ---------------------------------------------------------------------------
// View: Scan Product
// ---------------------------------------------------------------------------

const STAGE_LABELS = [
    "Image Quality", "Panel Detection", "OCR", "Field Extraction",
    "Category Detection", "Rule Matching", "Evidence Generation",
];

function renderScan() {
    renderShell("#/scan", `
        <div class="page-header">
            <div><h2>Scan Product</h2><p class="subtitle">Upload a label photo for real-time compliance screening.</p></div>
        </div>
        <div class="card">
            <div class="toolbar" style="margin-bottom:14px;">
                <button class="secondary" id="take-photo-btn">\u{1F4F8} Take Photo (Camera)</button>
            </div>
            <div class="dropzone" id="dropzone">
                <div class="icon">\u{1F4F7}</div>
                <p><strong>Click to upload</strong> or drag a label photo here</p>
                <p>JPEG or PNG, up to 10MB</p>
                <input type="file" id="file-input" accept="image/jpeg,image/png" style="display:none;" />
            </div>
            <div id="camera-panel" style="display:none;margin-top:16px;"></div>
            <div id="preview-area" style="margin-top:16px;"></div>
            <div style="margin-top:16px;">
                <label style="font-size:12.5px;font-weight:600;color:#3c4a5a;">Product name (optional)</label>
                <input type="text" id="product-name" placeholder="e.g. XYZ Foods Crunchy Wheat Biscuits" />
            </div>
            <div id="scan-actions" style="margin-top:18px;"></div>
            <div id="pipeline-progress"></div>
        </div>
        <div class="card">
            <h3>Bulk Upload</h3>
            <p class="subtitle" style="margin-top:0;">Scan up to 20 products in one batch -- useful for e-commerce/marketplace-style reviews.</p>
            <input type="file" id="bulk-file-input" accept="image/jpeg,image/png" multiple />
            <div id="bulk-selected-list" style="margin-top:10px;font-size:13px;color:#5b6b7c;"></div>
            <div id="bulk-actions" style="margin-top:14px;"></div>
            <div id="bulk-results" style="margin-top:16px;"></div>
        </div>
                <div class="card">
            <h3>Bulk Upload</h3>
            <p class="subtitle" style="margin-top:0;">Scan up to 20 products in one batch -- useful for e-commerce/marketplace-style reviews.</p>
            <input type="file" id="bulk-file-input" accept="image/jpeg,image/png" multiple />
            <div id="bulk-selected-list" style="margin-top:10px;font-size:13px;color:#5b6b7c;"></div>
            <div id="bulk-actions" style="margin-top:14px;"></div>
            <div id="bulk-results" style="margin-top:16px;"></div>
        </div>
                <div class="card">
            <h3>Bulk Upload</h3>
            <p class="subtitle" style="margin-top:0;">Scan up to 20 products in one batch -- useful for e-commerce/marketplace-style reviews.</p>
            <input type="file" id="bulk-file-input" accept="image/jpeg,image/png" multiple />
            <div id="bulk-selected-list" style="margin-top:10px;font-size:13px;color:#5b6b7c;"></div>
            <div id="bulk-actions" style="margin-top:14px;"></div>
            <div id="bulk-results" style="margin-top:16px;"></div>
        </div>
        <div class="card">
            <h3>Or try a seeded demo scenario</h3>
            <p class="subtitle" style="margin-top:0;">Uses the same pipeline and database -- not a separate fake UI (PRD Part 31).</p>
            <div class="toolbar">
                <button class="secondary" onclick="window.location.hash='#/checks'">View seeded demo checks in Inspection History</button>
            </div>
        </div>`);

    let selectedFile = null;
    const dropzone = document.getElementById("dropzone");
    const fileInput = document.getElementById("file-input");

    dropzone.addEventListener("click", () => fileInput.click());
    dropzone.addEventListener("dragover", (e) => { e.preventDefault(); dropzone.classList.add("dragover"); });
    dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
    dropzone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropzone.classList.remove("dragover");
        if (e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]);
    });
    fileInput.addEventListener("change", () => {
        if (fileInput.files.length) handleFile(fileInput.files[0]);
    });

    function handleFile(file) {
        selectedFile = file;
        const url = URL.createObjectURL(file);
        document.getElementById("preview-area").innerHTML =
            `<img src="${url}" class="preview-image" />`;
        document.getElementById("scan-actions").innerHTML =
            `<button class="primary" id="submit-scan-btn">Run Compliance Scan</button>`;
        document.getElementById("submit-scan-btn").addEventListener("click", submitScan);
    }

    // ---- Direct camera capture ----
    const takePhotoBtn = document.getElementById("take-photo-btn");
    const cameraPanel = document.getElementById("camera-panel");

    takePhotoBtn.addEventListener("click", openCamera);

    async function openCamera() {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            cameraPanel.style.display = "block";
            cameraPanel.innerHTML = `<div class="error-banner">Camera access is not supported in this browser. Please use "Click to upload" instead.</div>`;
            return;
        }

        stopActiveCameraStream();

        cameraPanel.style.display = "block";
        cameraPanel.innerHTML = `
            <div style="text-align:center;">
                <video id="camera-video" autoplay playsinline muted
                    style="width:100%;max-width:420px;border-radius:8px;border:1px solid var(--border);background:#000;"></video>
                <div class="toolbar" style="justify-content:center;margin-top:12px;">
                    <button class="primary" id="capture-photo-btn" disabled>Capture Photo</button>
                    <button class="secondary" id="cancel-camera-btn">Cancel</button>
                </div>
                <p class="subtitle" id="camera-status">Requesting camera access...</p>
            </div>`;
        document.getElementById("dropzone").style.display = "none";
        document.getElementById("cancel-camera-btn").addEventListener("click", closeCamera);

        try {
            _activeCameraStream = await navigator.mediaDevices.getUserMedia({
                video: { facingMode: "environment" },
                audio: false,
            });
            const video = document.getElementById("camera-video");
            if (!video) { stopActiveCameraStream(); return; }
            video.srcObject = _activeCameraStream;
            document.getElementById("camera-status").textContent = "Position the label in frame, then capture.";
            const captureBtn = document.getElementById("capture-photo-btn");
            captureBtn.disabled = false;
            captureBtn.addEventListener("click", capturePhoto);
        } catch (err) {
            const statusEl = document.getElementById("camera-status");
            if (statusEl) {
                statusEl.style.color = "#b3261e";
                statusEl.textContent = `Could not access camera (${err.message}). You can still use "Click to upload" instead.`;
            }
        }
    }

    function capturePhoto() {
        const video = document.getElementById("camera-video");
        if (!video || !video.videoWidth) return;
        const canvas = document.createElement("canvas");
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
        canvas.toBlob((blob) => {
            if (!blob) return;
            const file = new File([blob], `camera_capture_${Date.now()}.jpg`, { type: "image/jpeg" });
            closeCamera();
            handleFile(file);
        }, "image/jpeg", 0.92);
    }

    function closeCamera() {
        stopActiveCameraStream();
        cameraPanel.style.display = "none";
        cameraPanel.innerHTML = "";
        document.getElementById("dropzone").style.display = "";
    }

    async function submitScan() {
        if (!selectedFile) return;
        const actionsBox = document.getElementById("scan-actions");
        actionsBox.innerHTML = `<button class="primary" disabled><span class="spinner"></span> Submitting...</button>`;

        const formData = new FormData();
        formData.append("image", selectedFile);
        const productName = document.getElementById("product-name").value;
        if (productName) formData.append("product_name", productName);

        let checkId;
        try {
            const res = await Api.createCheck(formData);
            checkId = res.check_id;
        } catch (err) {
            actionsBox.innerHTML = `<div class="error-banner">${escapeHtml(err.message)}</div>`;
            return;
        }

        renderPipelineProgress(0);

        // The backend runs the pipeline synchronously; we animate through
        // the known stage list while awaiting the single /process call so
        // the officer sees the real workflow structure (PRD Part 27) --
        // we do not fabricate a longer delay than the backend actually takes.
        let stageIdx = 0;
        const stageTimer = setInterval(() => {
            stageIdx = Math.min(stageIdx + 1, STAGE_LABELS.length - 1);
            renderPipelineProgress(stageIdx);
        }, 350);

        try {
            const result = await Api.processCheck(checkId);
            clearInterval(stageTimer);
            renderPipelineProgress(STAGE_LABELS.length);
            setTimeout(() => { window.location.hash = `#/checks/${checkId}`; }, 500);
        } catch (err) {
            clearInterval(stageTimer);
            document.getElementById("pipeline-progress").innerHTML =
                `<div class="error-banner">${escapeHtml(err.message)}</div>`;
        }
    }

    function renderPipelineProgress(activeIdx) {
        const html = STAGE_LABELS.map((label, i) => {
            const cls = i < activeIdx ? "done" : (i === activeIdx ? "active" : "");
            return `<div class="pipeline-stage ${cls}"><span class="dot"></span> ${label}</div>`;
        }).join("");
        document.getElementById("pipeline-progress").innerHTML =
            `<div class="pipeline-stages">${html}</div>`;
    }

    let selectedBulkFiles = [];
    const bulkFileInput = document.getElementById("bulk-file-input");

    bulkFileInput.addEventListener("change", () => {
        selectedBulkFiles = Array.from(bulkFileInput.files);
        if (selectedBulkFiles.length > 20) {
            document.getElementById("bulk-selected-list").innerHTML =
                `<span style="color:#b3261e;">Please select 20 images or fewer.</span>`;
            document.getElementById("bulk-actions").innerHTML = "";
            return;
        }
        document.getElementById("bulk-selected-list").innerHTML =
            selectedBulkFiles.length
                ? `${selectedBulkFiles.length} file(s) selected: ${selectedBulkFiles.map((f) => escapeHtml(f.name)).join(", ")}`
                : "";
        document.getElementById("bulk-actions").innerHTML = selectedBulkFiles.length
            ? `<button class="primary" id="submit-bulk-btn">Run Bulk Scan (${selectedBulkFiles.length} images)</button>`
            : "";
        const submitBulkBtn = document.getElementById("submit-bulk-btn");
        if (submitBulkBtn) submitBulkBtn.addEventListener("click", submitBulkScan);
    });

    async function submitBulkScan() {
        const actionsBox = document.getElementById("bulk-actions");
        const resultsBox = document.getElementById("bulk-results");
        actionsBox.innerHTML = `<button class="primary" disabled><span class="spinner"></span> Processing ${selectedBulkFiles.length} images...</button>`;
        resultsBox.innerHTML = `<p class="subtitle">This can take a little while -- each image runs the full pipeline one at a time.</p>`;

        const formData = new FormData();
        selectedBulkFiles.forEach((file) => formData.append("images", file));

        try {
            const res = await Api.createBulkChecks(formData);
            const rows = res.results.map((r) => {
                const statusClass = r.status === "COMPLETED" ? "COMPLIANT"
                    : (r.status === "REJECTED" || r.status === "PROCESSING_FAILED") ? "POTENTIAL_NON_COMPLIANCE"
                    : "REQUIRES_OFFICER_VERIFICATION";
                const link = r.check_id ? `<a href="#/checks/${r.check_id}">View result &rarr;</a>` : "-";
                return `<tr>
                    <td>${escapeHtml(r.filename)}</td>
                    <td><span class="badge ${statusClass}">${escapeHtml(r.status)}</span></td>
                    <td>${link}</td>
                </tr>`;
            }).join("");
            resultsBox.innerHTML = `
                <table class="data-table">
                    <thead><tr><th>File</th><th>Status</th><th>Result</th></tr></thead>
                    <tbody>${rows}</tbody>
                </table>
                <div class="toolbar" style="margin-top:14px;">
                    <button class="secondary" onclick="window.location.hash='#/checks'">View All in Inspection History</button>
                </div>`;
            actionsBox.innerHTML = "";
        } catch (err) {
            resultsBox.innerHTML = `<div class="error-banner">${escapeHtml(err.message)}</div>`;
            actionsBox.innerHTML = `<button class="primary" id="submit-bulk-btn">Retry Bulk Scan</button>`;
            document.getElementById("submit-bulk-btn").addEventListener("click", submitBulkScan);
        }
    }
}

// ---------------------------------------------------------------------------
// View: Inspection History (list, with search/filter)
// ---------------------------------------------------------------------------

const CHECK_CATEGORIES = ["PACKAGED_FOOD_FMCG", "COSMETICS", "ELECTRONICS"];
const CHECK_STATUSES = ["COMPLETED", "PROCESSING", "QUEUED", "INVALID_IMAGE", "UNSUPPORTED_CATEGORY", "PROCESSING_FAILED"];

let _checksListFilters = { q: "", category: "", status: "", date_from: "", date_to: "" };

let _activeCameraStream = null;
function stopActiveCameraStream() {
    if (_activeCameraStream) {
        _activeCameraStream.getTracks().forEach((track) => track.stop());
        _activeCameraStream = null;
    }
}

async function renderChecksList() {
    renderShell("#/checks", `<div class="empty-state"><span class="spinner"></span> Loading...</div>`);
    await loadAndRenderChecksList();
}

async function loadAndRenderChecksList() {
    let data;
    try {
        data = await Api.listChecks(_checksListFilters);
    } catch (err) {
        mainContent().innerHTML = `<div class="error-banner">${escapeHtml(err.message)}</div>`;
        return;
    }

    const rows = data.checks.length
        ? data.checks.map((c) => `
            <tr onclick="window.location.hash='#/checks/${c.id}'">
                <td>#${c.id}</td>
                <td>${escapeHtml(c.product_name || "-")}</td>
                <td>${escapeHtml(c.category || "-")}</td>
                <td><span class="status-pill">${c.status}</span></td>
                <td>${c.image_quality_score !== null ? c.image_quality_score : "-"}</td>
                <td>${fmtDate(c.created_at)}</td>
            </tr>`).join("")
        : "";

    const categoryOptions = CHECK_CATEGORIES.map((cat) =>
        `<option value="${cat}" ${_checksListFilters.category === cat ? "selected" : ""}>${cat}</option>`).join("");
    const statusOptions = CHECK_STATUSES.map((st) =>
        `<option value="${st}" ${_checksListFilters.status === st ? "selected" : ""}>${st}</option>`).join("");

    const hasActiveFilters = Object.values(_checksListFilters).some((v) => v);

    mainContent().innerHTML = `
        <div class="page-header"><div><h2>Inspection History</h2><p class="subtitle">Every compliance check, most recent first.</p></div></div>
        <div class="card">
            <div class="toolbar" style="flex-wrap:wrap;">
                <input type="text" id="filter-q" placeholder="Search product name..." style="max-width:220px;" value="${escapeHtml(_checksListFilters.q)}" />
                <select id="filter-category" style="max-width:200px;">
                    <option value="">All categories</option>${categoryOptions}
                </select>
                <select id="filter-status" style="max-width:180px;">
                    <option value="">All statuses</option>${statusOptions}
                </select>
                <label style="font-size:12.5px;color:#5b6b7c;">From</label>
                <input type="date" id="filter-date-from" style="max-width:160px;" value="${_checksListFilters.date_from}" />
                <label style="font-size:12.5px;color:#5b6b7c;">To</label>
                <input type="date" id="filter-date-to" style="max-width:160px;" value="${_checksListFilters.date_to}" />
                <button class="secondary" id="filter-clear-btn" ${hasActiveFilters ? "" : "disabled"}>Clear Filters</button>
            </div>
            ${data.checks.length ? `
            <table class="data-table">
                <thead><tr><th>ID</th><th>Product</th><th>Category</th><th>Status</th><th>Image Quality</th><th>Submitted</th></tr></thead>
                <tbody>${rows}</tbody>
            </table>` : `
            <div class="empty-state">
                <div class="icon">\u{1F4CB}</div>
                <p>${hasActiveFilters ? "No checks match these filters." : "No compliance checks yet."}</p>
                ${hasActiveFilters ? "" : '<button class="primary" onclick="window.location.hash=\'#/scan\'">Scan a Product</button>'}
            </div>`}
        </div>`;

    let searchDebounceTimer = null;
    document.getElementById("filter-q").addEventListener("input", (e) => {
        clearTimeout(searchDebounceTimer);
        searchDebounceTimer = setTimeout(() => {
            _checksListFilters.q = e.target.value.trim();
            loadAndRenderChecksList();
        }, 350);
    });
    document.getElementById("filter-category").addEventListener("change", (e) => {
        _checksListFilters.category = e.target.value;
        loadAndRenderChecksList();
    });
    document.getElementById("filter-status").addEventListener("change", (e) => {
        _checksListFilters.status = e.target.value;
        loadAndRenderChecksList();
    });
    document.getElementById("filter-date-from").addEventListener("change", (e) => {
        _checksListFilters.date_from = e.target.value;
        loadAndRenderChecksList();
    });
    document.getElementById("filter-date-to").addEventListener("change", (e) => {
        _checksListFilters.date_to = e.target.value;
        loadAndRenderChecksList();
    });
    document.getElementById("filter-clear-btn").addEventListener("click", () => {
        _checksListFilters = { q: "", category: "", status: "", date_from: "", date_to: "" };
        loadAndRenderChecksList();
    });
}

// ---------------------------------------------------------------------------
// View: Check detail (results + evidence + report)
// ---------------------------------------------------------------------------

const STATUS_EXPLANATIONS = {
    INVALID_IMAGE: "Image quality is insufficient for reliable analysis. Please capture the label again.",
    UNSUPPORTED_CATEGORY: "Unsupported category -- compliance evaluation not available for this category.",
    PROCESSING_FAILED: "Processing failed due to an unexpected error. Please retry or contact an administrator.",
    QUEUED: "This check is queued and has not been processed yet.",
    PROCESSING: "This check is currently being processed.",
};

async function renderCheckDetail(checkId) {
    renderShell(`#/checks/${checkId}`, `<div class="empty-state"><span class="spinner"></span> Loading...</div>`);
    let bundle;
    try {
        bundle = await Api.getResults(checkId);
    } catch (err) {
        mainContent().innerHTML = `<div class="error-banner">${escapeHtml(err.message)}</div>`;
        return;
    }
    const check = bundle.check;

    if (check.status !== "COMPLETED") {
        mainContent().innerHTML = `
            <div class="page-header"><div><h2>Check #${checkId}</h2></div></div>
            <div class="card">
                <p><span class="status-pill">${check.status}</span></p>
                <p style="margin-top:12px;">${STATUS_EXPLANATIONS[check.status] || ""}</p>
                ${check.image_quality_notes ? `<p class="tag">Issues: ${escapeHtml(check.image_quality_notes)}</p>` : ""}
            </div>`;
        return;
    }

    const fieldByType = {};
    bundle.fields.forEach((f) => { fieldByType[f.field_type] = f; });

    const reqRows = bundle.results.map((r) => {
        const pct = Math.round(r.confidence * 100);
        return `
        <div class="requirement-row">
            <div class="req-top">
                <div>
                    <div class="req-name">${escapeHtml(r.requirement_name)}</div>
                    <div class="req-meta">Confidence ${pct}%${r.requires_review ? " &middot; Flagged for officer review" : ""}</div>
                </div>
                ${verdictBadge(r.verdict)}
            </div>
            <div class="confidence-bar-track"><div class="confidence-bar-fill" style="width:${pct}%"></div></div>
            <div class="req-reason">${escapeHtml(r.reason)}</div>
        </div>`;
    }).join("");

    mainContent().innerHTML = `
        <div class="page-header">
            <div>
                <h2>Check #${checkId} — ${escapeHtml(check.product_name || "Unnamed product")}</h2>
                <p class="subtitle">Category: ${escapeHtml(check.category || "-")} &middot; Rule Version ID: ${check.rule_version_id || "-"}
                    &middot; Image quality score: ${check.image_quality_score}</p>
            </div>
            <div class="toolbar">
                <button class="secondary" id="download-report-btn">Download PDF Report</button>
            </div>
        </div>

        <div class="card">
            <h3>Annotated Evidence</h3>
            <div class="evidence-image-wrap">
                <img src="${Api.evidenceImageUrl(checkId, "ANNOTATED_IMAGE")}" alt="Annotated evidence" />
            </div>
            <p class="subtitle" style="text-align:center;">Bounding boxes colour-coded by verdict: green = compliant, red = potential non-compliance, amber = requires verification, grey = insufficient evidence.</p>
        </div>

        <div class="card">
            <h3>Requirement-by-Requirement Results</h3>
            ${reqRows}
        </div>

        <div class="limitation-note">
            <strong>Important:</strong> VeriPack is an assistive screening tool, not a final legal determination.
            Declared net quantity format is checked; physical net quantity requires metrological weighing under the
            Sixth Schedule. Numeral-height estimates are relative and uncalibrated, not certified millimetre
            measurements. Final enforcement decisions remain with the authorized Legal Metrology Officer.
        </div>`;

        document.getElementById("download-report-btn").addEventListener("click", async () => {
        const btn = document.getElementById("download-report-btn");
        const originalText = btn.textContent;
        btn.disabled = true;
        btn.textContent = "Generating...";
        try {
            await Api.generateReport(checkId);
            // Fetch the PDF with the auth token attached (a plain
            // window.open/navigation cannot carry an Authorization header,
            // which is why this previously returned 401 UNAUTHORIZED).
            const blob = await Api.downloadReportBlob(checkId);
            const blobUrl = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = blobUrl;
            a.download = `veripack_report_check_${checkId}.pdf`;
            document.body.appendChild(a);
            a.click();
            a.remove();
            setTimeout(() => URL.revokeObjectURL(blobUrl), 10000);
        } catch (err) {
            alert(err.message);
        } finally {
            btn.disabled = false;
            btn.textContent = originalText;
        }
    });
}

// ---------------------------------------------------------------------------
// View: Review Queue
// ---------------------------------------------------------------------------

async function renderReviewQueue() {
    renderShell("#/reviews", `<div class="empty-state"><span class="spinner"></span> Loading...</div>`);
    let data;
    try {
        data = await Api.listReviews("PENDING");
    } catch (err) {
        mainContent().innerHTML = `<div class="error-banner">${escapeHtml(err.message)}</div>`;
        return;
    }

    if (!data.reviews.length) {
        mainContent().innerHTML = `
            <div class="page-header"><div><h2>Review Queue</h2></div></div>
            <div class="card"><div class="empty-state"><div class="icon">\u2705</div><p>No pending reviews. Everything above the confidence threshold has been auto-resolved.</p></div></div>`;
        return;
    }

    const rows = data.reviews.map((r) => `
        <div class="requirement-row">
            <div class="req-top">
                <div>
                    <div class="req-name">${escapeHtml(r.requirement_name)} — Check #${r.check_id}</div>
                    <div class="req-meta">Confidence ${Math.round(r.confidence * 100)}% &middot; ${escapeHtml(r.rule_reference)}</div>
                </div>
                ${verdictBadge(r.verdict)}
            </div>
            <div class="req-reason">${escapeHtml(r.reason)}</div>
            <div class="toolbar" style="margin-top:12px;margin-bottom:0;">
                <button class="secondary" data-action="confirm" data-task="${r.id}">Confirm AI Verdict</button>
                <button class="secondary" data-action="correct" data-task="${r.id}">Correct Verdict</button>
                <button class="secondary" data-action="insufficient" data-task="${r.id}">Mark Insufficient</button>
                <a href="#/checks/${r.check_id}" style="font-size:13px;">View full check &rarr;</a>
            </div>
        </div>`).join("");

    mainContent().innerHTML = `
        <div class="page-header"><div><h2>Review Queue</h2><p class="subtitle">${data.reviews.length} item(s) below the confidence threshold, awaiting officer verification.</p></div></div>
        ${rows}`;

    mainContent().querySelectorAll("button[data-action]").forEach((btn) => {
        btn.addEventListener("click", () => openReviewModal(btn.dataset.task, btn.dataset.action));
    });
}

function openReviewModal(taskId, action) {
    const overlay = el(`<div class="modal-overlay"></div>`);
    let bodyHtml = "";
    if (action === "confirm") {
        bodyHtml = `<p>Confirm the AI-generated verdict as correct. This will be logged with your officer ID.</p>
            <label>Reason / note</label><textarea id="review-reason" rows="3"></textarea>`;
    } else if (action === "correct") {
        bodyHtml = `<p>Provide the corrected verdict. The original AI result is preserved in history, not overwritten.</p>
            <label>Corrected verdict</label>
            <select id="corrected-verdict">
                <option value="COMPLIANT">Compliant with checked requirements</option>
                <option value="POTENTIAL_NON_COMPLIANCE">Potential non-compliance detected</option>
                <option value="REQUIRES_OFFICER_VERIFICATION">Requires officer verification</option>
                <option value="INSUFFICIENT_EVIDENCE">Insufficient evidence</option>
            </select>
            <label>Reason (required)</label><textarea id="review-reason" rows="3"></textarea>`;
    } else {
        bodyHtml = `<p>Mark this requirement as insufficient evidence.</p>
            <label>Reason (required)</label><textarea id="review-reason" rows="3"></textarea>`;
    }

    overlay.innerHTML = `
        <div class="modal-box">
            <h3>Officer Review</h3>
            ${bodyHtml}
            <div id="modal-error"></div>
            <div class="toolbar" style="margin-top:16px;">
                <button class="primary" id="modal-submit">Submit Decision</button>
                <button class="secondary" id="modal-cancel">Cancel</button>
            </div>
        </div>`;
    document.body.appendChild(overlay);

    overlay.querySelector("#modal-cancel").addEventListener("click", () => overlay.remove());
    overlay.querySelector("#modal-submit").addEventListener("click", async () => {
        const reason = overlay.querySelector("#review-reason").value.trim();
        if (!reason) {
            overlay.querySelector("#modal-error").innerHTML = `<div class="error-banner">A reason is required.</div>`;
            return;
        }
        const decisionMap = { confirm: "CONFIRM", correct: "CORRECT", insufficient: "MARK_INSUFFICIENT" };
        const payload = { decision: decisionMap[action], reason };
        if (action === "correct") payload.corrected_verdict = overlay.querySelector("#corrected-verdict").value;

        try {
            await Api.submitReviewDecision(taskId, payload);
            overlay.remove();
            renderReviewQueue();
        } catch (err) {
            overlay.querySelector("#modal-error").innerHTML = `<div class="error-banner">${escapeHtml(err.message)}</div>`;
        }
    });
}

// ---------------------------------------------------------------------------
// View: Admin -- Regulatory Rule Versions
// ---------------------------------------------------------------------------

async function renderRuleVersions() {
    renderShell("#/admin/rules", `<div class="empty-state"><span class="spinner"></span> Loading...</div>`);
    let data;
    try {
        data = await Api.listRuleVersions();
    } catch (err) {
        mainContent().innerHTML = `<div class="error-banner">${escapeHtml(err.message)}</div>`;
        return;
    }

    const rows = data.rule_versions.map((rv) => `
        <tr onclick="window.location.hash='#/admin/rules/${rv.id}'">
            <td>${escapeHtml(rv.name)}</td>
            <td>v${escapeHtml(rv.version_label)}</td>
            <td>${escapeHtml(rv.category)}</td>
            <td><span class="status-pill">${rv.status}</span></td>
            <td>${rv.effective_from || "-"}</td>
            <td>${rv.effective_to || "open"}</td>
            <td>${rv.requirement_count}</td>
        </tr>`).join("");

    mainContent().innerHTML = `
        <div class="page-header">
            <div><h2>Regulatory Rule Engine</h2><p class="subtitle">Rules are versioned data. Updating the law here does not require a code deployment.</p></div>
            <button class="primary" id="new-rule-btn">+ New Rule Version</button>
        </div>
        <div class="card">
            <table class="data-table">
                <thead><tr><th>Name</th><th>Version</th><th>Category</th><th>Status</th><th>Effective From</th><th>Effective To</th><th># Requirements</th></tr></thead>
                <tbody>${rows}</tbody>
            </table>
        </div>`;

    document.getElementById("new-rule-btn").addEventListener("click", openNewRuleVersionModal);
}

function openNewRuleVersionModal() {
    const overlay = el(`<div class="modal-overlay"></div>`);
    overlay.innerHTML = `
        <div class="modal-box">
            <h3>Create Rule Version</h3>
            <label>Name</label><input id="rv-name" placeholder="e.g. PC Rules 2011 (as amended 2026) - Food/FMCG" />
            <label>Version label</label><input id="rv-version" placeholder="e.g. 1.2" />
            <label>Category</label>
            <select id="rv-category"><option value="PACKAGED_FOOD_FMCG">Packaged Food / FMCG</option><option value="COSMETICS">Cosmetics</option><option value="ELECTRONICS">Electronics</option></select>
            <label>Source document</label><input id="rv-source-doc" placeholder="Legal Metrology (Packaged Commodities) Rules, 2011 as amended" />
            <label>Source reference (optional)</label><input id="rv-source-ref" placeholder="e.g. G.S.R. XXX(E), dated ..." />
            <div id="modal-error"></div>
            <div class="toolbar" style="margin-top:16px;">
                <button class="primary" id="modal-submit">Create Draft</button>
                <button class="secondary" id="modal-cancel">Cancel</button>
            </div>
        </div>`;
    document.body.appendChild(overlay);
    overlay.querySelector("#modal-cancel").addEventListener("click", () => overlay.remove());
    overlay.querySelector("#modal-submit").addEventListener("click", async () => {
        const payload = {
            name: overlay.querySelector("#rv-name").value.trim(),
            version_label: overlay.querySelector("#rv-version").value.trim(),
            category: overlay.querySelector("#rv-category").value,
            source_document: overlay.querySelector("#rv-source-doc").value.trim(),
            source_reference: overlay.querySelector("#rv-source-ref").value.trim(),
        };
        if (!payload.name || !payload.version_label || !payload.source_document) {
            overlay.querySelector("#modal-error").innerHTML = `<div class="error-banner">Name, version label, and source document are required.</div>`;
            return;
        }
        try {
            const res = await Api.createRuleVersion(payload);
            overlay.remove();
            window.location.hash = `#/admin/rules/${res.id}`;
        } catch (err) {
            overlay.querySelector("#modal-error").innerHTML = `<div class="error-banner">${escapeHtml(err.message)}</div>`;
        }
    });
}

async function renderRuleVersionDetail(ruleVersionId) {
    renderShell("#/admin/rules", `<div class="empty-state"><span class="spinner"></span> Loading...</div>`);
    let data;
    try {
        data = await Api.getRuleVersion(ruleVersionId);
    } catch (err) {
        mainContent().innerHTML = `<div class="error-banner">${escapeHtml(err.message)}</div>`;
        return;
    }
    const rv = data.rule_version;

    const reqRows = data.requirements.map((r) => `
        <tr>
            <td>${escapeHtml(r.requirement_name)}</td>
            <td>${escapeHtml(r.field_type)}</td>
            <td>${escapeHtml(r.applicability_logic)}</td>
            <td>${escapeHtml(r.severity)}</td>
            <td style="font-size:12px;">${escapeHtml(r.source_citation)}</td>
        </tr>`).join("") || `<tr><td colspan="5" style="text-align:center;color:#5b6b7c;">No requirements yet.</td></tr>`;

    const canEdit = !rv.locked && (rv.status === "DRAFT" || rv.status === "REVIEW");

    mainContent().innerHTML = `
        <div class="page-header">
            <div>
                <h2>${escapeHtml(rv.name)} <span class="status-pill">${rv.status}</span></h2>
                <p class="subtitle">Version ${escapeHtml(rv.version_label)} &middot; ${escapeHtml(rv.category)} &middot;
                    ${rv.locked ? "Locked (already used by at least one check -- immutable)" : "Editable draft"}</p>
            </div>
            <div class="toolbar">
                ${canEdit ? `<button class="secondary" id="add-req-btn">+ Add Requirement</button>` : ""}
                ${rv.status !== "ACTIVE" ? `<button class="primary" id="activate-btn">Activate</button>` : ""}
                <button class="secondary" id="duplicate-btn">Duplicate into New Draft</button>
            </div>
        </div>
        <div class="card">
            <h3>Source</h3>
            <p>${escapeHtml(rv.source_document)}</p>
            <p class="subtitle">${escapeHtml(rv.source_reference || "")}</p>
            <p class="subtitle">Effective from: ${rv.effective_from || "not yet activated"} &middot; Effective to: ${rv.effective_to || "open-ended"}</p>
        </div>
        <div class="card">
            <h3>Requirements (${data.requirements.length})</h3>
            <table class="data-table">
                <thead><tr><th>Requirement</th><th>Field</th><th>Applicability</th><th>Severity</th><th>Source Citation</th></tr></thead>
                <tbody>${reqRows}</tbody>
            </table>
        </div>`;

    const addBtn = document.getElementById("add-req-btn");
    if (addBtn) addBtn.addEventListener("click", () => openAddRequirementModal(ruleVersionId));

    document.getElementById("duplicate-btn").addEventListener("click", async () => {
        const label = prompt("New version label for the duplicate (e.g. 1.3):");
        if (!label) return;
        try {
            const res = await Api.duplicateRuleVersion(ruleVersionId, { version_label: label });
            window.location.hash = `#/admin/rules/${res.id}`;
        } catch (err) { alert(err.message); }
    });

    const activateBtn = document.getElementById("activate-btn");
    if (activateBtn) {
        activateBtn.addEventListener("click", async () => {
            const effectiveFrom = prompt("Effective from date (YYYY-MM-DD):", new Date().toISOString().slice(0, 10));
            if (!effectiveFrom) return;
            try {
                await Api.activateRuleVersion(ruleVersionId, { effective_from: effectiveFrom });
                renderRuleVersionDetail(ruleVersionId);
            } catch (err) { alert(err.message); }
        });
    }
}

function openAddRequirementModal(ruleVersionId) {
    const overlay = el(`<div class="modal-overlay"></div>`);
    overlay.innerHTML = `
        <div class="modal-box">
            <h3>Add Requirement</h3>
            <label>Requirement code</label><input id="req-code" placeholder="e.g. MRP" />
            <label>Requirement name</label><input id="req-name" placeholder="e.g. Maximum Retail Price" />
            <label>Field type</label>
            <select id="req-field-type">
                <option>MANUFACTURER</option><option>GENERIC_NAME</option><option>NET_QUANTITY</option>
                <option>MRP</option><option>MFG_DATE</option><option>BEST_BEFORE</option>
                <option>CONSUMER_CARE</option><option>COUNTRY_OF_ORIGIN</option>
            </select>
            <label>Validation type</label>
            <select id="req-validation-type">
                <option value="presence">Presence</option>
                <option value="qualified_presence">Qualified presence (manufacturer-style)</option>
                <option value="format">Format (MRP/Net Qty-style)</option>
                <option value="visual_geometric">Visual/geometric (font-size heuristic)</option>
            </select>
            <label>Applicability</label>
            <select id="req-applicability"><option value="ALL">All products in category</option><option value="IMPORTED_ONLY">Imported products only</option></select>
            <label>Severity</label>
            <select id="req-severity"><option value="HIGH">High</option><option value="MEDIUM" selected>Medium</option><option value="LOW">Low</option></select>
            <label>Source citation</label><input id="req-citation" placeholder="e.g. Rule 6(1)(e), PC Rules 2011" />
            <div id="modal-error"></div>
            <div class="toolbar" style="margin-top:16px;">
                <button class="primary" id="modal-submit">Add Requirement</button>
                <button class="secondary" id="modal-cancel">Cancel</button>
            </div>
        </div>`;
    document.body.appendChild(overlay);
    overlay.querySelector("#modal-cancel").addEventListener("click", () => overlay.remove());
    overlay.querySelector("#modal-submit").addEventListener("click", async () => {
        const vtype = overlay.querySelector("#req-validation-type").value;
        const validationLogic = vtype === "format"
            ? { type: "format", requires: ["value", "unit"] }
            : { type: vtype };
        const payload = {
            requirement_code: overlay.querySelector("#req-code").value.trim(),
            requirement_name: overlay.querySelector("#req-name").value.trim(),
            field_type: overlay.querySelector("#req-field-type").value,
            applicability_logic: overlay.querySelector("#req-applicability").value,
            severity: overlay.querySelector("#req-severity").value,
            source_citation: overlay.querySelector("#req-citation").value.trim(),
            validation_logic: validationLogic,
        };
        if (!payload.requirement_code || !payload.requirement_name || !payload.source_citation) {
            overlay.querySelector("#modal-error").innerHTML = `<div class="error-banner">Code, name, and source citation are required.</div>`;
            return;
        }
        try {
            await Api.addRequirement(ruleVersionId, payload);
            overlay.remove();
            renderRuleVersionDetail(ruleVersionId);
        } catch (err) {
            overlay.querySelector("#modal-error").innerHTML = `<div class="error-banner">${escapeHtml(err.message)}</div>`;
        }
    });
}

// ---------------------------------------------------------------------------
// View: Audit Log
// ---------------------------------------------------------------------------

async function renderAuditLog() {
    renderShell("#/audit", `<div class="empty-state"><span class="spinner"></span> Loading...</div>`);
    let data;
    try {
        data = await Api.auditLogs();
    } catch (err) {
        mainContent().innerHTML = `<div class="error-banner">${escapeHtml(err.message)}</div>`;
        return;
    }
    const rows = data.audit_logs.map((l) => `
        <tr>
            <td>${fmtDate(l.timestamp)}</td>
            <td>${escapeHtml(l.actor_name || "system")}</td>
            <td><span class="tag">${escapeHtml(l.action)}</span></td>
            <td>${escapeHtml(l.entity_type)} #${l.entity_id ?? "-"}</td>
        </tr>`).join("") || `<tr><td colspan="4" style="text-align:center;color:#5b6b7c;padding:20px;">No audit events yet.</td></tr>`;

    mainContent().innerHTML = `
        <div class="page-header"><div><h2>Audit Log</h2><p class="subtitle">Append-only. Every significant state change is recorded here.</p></div></div>
        <div class="card">
            <table class="data-table">
                <thead><tr><th>Timestamp</th><th>Actor</th><th>Action</th><th>Entity</th></tr></thead>
                <tbody>${rows}</tbody>
            </table>
        </div>`;
}

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------

async function router() {
    stopActiveCameraStream();
    const hash = window.location.hash || "#/dashboard";
    const isAuthed = !!Api.token() && !!Api.currentUser();

    if (!isAuthed) {
        if (hash !== "#/login") { window.location.hash = "#/login"; return; }
        renderLogin();
        return;
    }
    if (hash === "#/login") { window.location.hash = "#/dashboard"; return; }

    if (hash === "#/dashboard" || hash === "#/") return renderDashboard();
    if (hash === "#/scan") return renderScan();
    if (hash === "#/checks") return renderChecksList();

    let m = hash.match(/^#\/checks\/(\d+)$/);
    if (m) return renderCheckDetail(m[1]);

    if (hash === "#/reviews") return renderReviewQueue();
    if (hash === "#/admin/rules") return renderRuleVersions();

    m = hash.match(/^#\/admin\/rules\/(\d+)$/);
    if (m) return renderRuleVersionDetail(m[1]);

    if (hash === "#/audit") return renderAuditLog();

    return renderDashboard();
}

window.addEventListener("hashchange", router);
window.addEventListener("DOMContentLoaded", router);
