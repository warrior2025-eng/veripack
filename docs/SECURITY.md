# VeriPack — Security

## What's implemented

- **Password hashing**: `werkzeug.security.generate_password_hash` /
  `check_password_hash` (PBKDF2-SHA256). Not bcrypt (the PRD's stated
  preference) because `pip install bcrypt` requires a C-extension wheel
  this sandbox couldn't download — see `veripack/auth.py`'s module
  docstring for the one-line swap once you have network access.
- **JWT auth**: HS256-signed tokens (`veripack/auth.py`), 8-hour expiry,
  verified server-side on every protected route via the `@require_auth`
  decorator. The secret is read from `VERIPACK_JWT_SECRET` — the
  in-code default is explicitly a dev-only placeholder and must be
  overridden via `.env` before any real deployment (see `.env.example`).
- **RBAC enforced server-side, not just hidden in the UI**: `@require_role`
  checks `g.user["role"]` on the backend for every admin-only endpoint
  (rule version CRUD, audit log). The frontend also hides those nav items
  for non-admins, but that's a UX convenience, not the security boundary —
  see `tests/test_auth_rbac.py::test_officer_cannot_create_rule_version`
  for a test that hits the API directly, bypassing the UI entirely, and
  confirms the backend still rejects it.
- **Organization-level data isolation**: `veripack/auth.py`'s
  `organization_scoped_filter()` restricts MANUFACTURER and
  MARKETPLACE_AUDITOR roles to their own organization's data — Officers
  and Admins see everything (state-wide enforcement view), matching the
  PRD's stated access model (Part 11.20/11.22).
- **Upload validation** (`checks_routes.py`): MIME-type allowlist
  (JPEG/PNG only), file-size limit, and secure filename handling via a
  UUID-based generated filename (never the client-supplied filename) —
  see that file's `create_check` handler.
- **SQL injection protection**: every query in `db/database.py` and every
  route/pipeline module uses parameterized queries (`cur.execute(sql,
  params)`) — string-formatted SQL never appears anywhere in this codebase.
- **No secrets committed to the repo**: `.env.example` documents required
  variables without real values; `.gitignore` (see repo root) excludes
  `.env`, `storage/*.db`, and uploaded/generated files.
- **Structured error responses**: API errors return a JSON `{"error":
  CODE, "message": "..."}` shape (see `docs/API` conventions in
  `checks_routes.py`) rather than leaking Python stack traces to the
  client. Flask's debug mode is off by default (`FLASK_DEBUG=0` in
  `.env.example`).
- **Audit log**: every significant state change is recorded append-only
  (see `veripack/audit.py` — there is no update/delete function on that
  module by construction) with actor, timestamp, before/after values where
  relevant.

## What's NOT implemented (and should be, before any real deployment)

Being direct about this, per the brief's "act like a real developer, don't
silently fake things" instruction:

- **CORS configuration** is currently permissive (`VERIPACK_ALLOWED_ORIGIN`
  defaults to `*` in `.env.example`) for local development convenience.
  Set this to your actual frontend origin before deploying anywhere
  reachable from the open internet.
- **Rate limiting** on `/api/auth/login` (or any endpoint) is not
  implemented — a production deployment should add this (e.g. via
  Flask-Limiter, once network access allows installing it) to blunt
  credential-stuffing attempts.
- **Refresh tokens** aren't implemented — sessions simply expire after 8
  hours and require a fresh login. Fine for an officer's shift-length use
  pattern, but worth revisiting for the manufacturer/marketplace-auditor
  self-check personas if they need longer sessions.
- **HTTPS termination** is not handled by this application (correctly —
  that's a reverse-proxy/load-balancer concern, not application code), but
  is worth stating explicitly: do not expose this Flask app directly to
  the internet without TLS in front of it.
- **File content sniffing beyond MIME/extension** (e.g., verifying the
  uploaded bytes are actually a valid JPEG/PNG, not just named like one) is
  partially covered by the pipeline's own `cv2.imread` failing gracefully
  on non-image data (surfaced as `INVALID_IMAGE`/`PROCESSING_FAILED`), but
  a dedicated magic-byte check before that point would be a cheap
  hardening addition.
- **Secrets rotation / vault integration** — `.env`-based configuration is
  adequate for a hackathon deployment; a real institutional deployment
  handling enforcement evidence should use a proper secrets manager.

## Data privacy notes

Product/label images are commercial packaging, not personal data, in the
overwhelming majority of cases. The privacy-sensitive surface here is
narrower than a typical consumer app:

- A manufacturer's self-check submissions should not be visible to another
  manufacturer — enforced by `organization_scoped_filter()` (see above).
- Officer activity (who scanned what, when) is itself sensitive
  operational data — protected by the same RBAC and audit-log mechanisms,
  not by any special additional handling, since this document is not the
  place to invent a data-protection compliance claim beyond what's
  actually implemented.
