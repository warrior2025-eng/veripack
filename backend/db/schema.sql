-- VeriPack relational schema
-- SQLite for this sandbox (no network access to install PostgreSQL client libs).
-- Design is written to be a near-direct port to PostgreSQL: every table has a
-- surrogate integer primary key, explicit foreign keys, and JSON columns are
-- only used where the PRD explicitly calls for flexibility (extracted-field
-- payloads, rule validation logic, audit metadata) -- see docs/ARCHITECTURE.md.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Identity & access
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS organization (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    org_type        TEXT NOT NULL CHECK (org_type IN ('GOVERNMENT', 'MANUFACTURER', 'MARKETPLACE')),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS user (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    email           TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('ADMIN', 'OFFICER', 'SENIOR_OFFICER', 'MANUFACTURER', 'MARKETPLACE_AUDITOR')),
    organization_id INTEGER REFERENCES organization(id),
    active          INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------------
-- Regulatory rule engine (the core differentiator -- see docs/RULE_ENGINE.md)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS rule_version (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL,               -- e.g. "PC Rules 2011 (as amended) - Food/FMCG"
    version_label     TEXT NOT NULL,                -- e.g. "1.0", "1.1"
    category          TEXT NOT NULL,                -- e.g. "PACKAGED_FOOD_FMCG", "COSMETICS"
    status            TEXT NOT NULL CHECK (status IN ('DRAFT', 'REVIEW', 'ACTIVE', 'RETIRED')) DEFAULT 'DRAFT',
    effective_from    TEXT,                         -- ISO date; NULL while DRAFT
    effective_to      TEXT,                         -- ISO date; NULL = open-ended
    source_document   TEXT NOT NULL,                -- e.g. "Legal Metrology (Packaged Commodities) Rules, 2011 as amended"
    source_reference  TEXT,                         -- e.g. "Rule 6, G.S.R. 722(E) 06-Oct-2023"
    created_by        INTEGER REFERENCES user(id),
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    -- Once a rule_version has been used by any compliance_check, it must not be
    -- edited in place. Enforced in application code (see rules.py) rather than
    -- SQL trigger, so a clear error message can be surfaced to the admin UI.
    locked            INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS rule_requirement (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_version_id     INTEGER NOT NULL REFERENCES rule_version(id),
    requirement_code    TEXT NOT NULL,              -- e.g. "MANUFACTURER_NAME_ADDRESS"
    requirement_name    TEXT NOT NULL,              -- e.g. "Manufacturer / Packer / Importer name & address"
    description         TEXT,
    field_type          TEXT NOT NULL,              -- links to extracted_field.field_type
    applicability_logic TEXT NOT NULL DEFAULT 'ALL', -- 'ALL' | 'IMPORTED_ONLY' | 'PERISHABLE_ONLY' | 'GARMENT_ONLY' | ...
    validation_logic    TEXT NOT NULL,               -- JSON: {"type": "presence"} | {"type":"format","pattern":"..."} etc.
    severity            TEXT NOT NULL CHECK (severity IN ('HIGH', 'MEDIUM', 'LOW')) DEFAULT 'MEDIUM',
    source_citation     TEXT NOT NULL,              -- e.g. "Rule 6(1)(a), PC Rules 2011"
    enabled             INTEGER NOT NULL DEFAULT 1,
    UNIQUE (rule_version_id, requirement_code)
);

-- ---------------------------------------------------------------------------
-- Product / scanning subjects
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS product (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT,                            -- may be filled after extraction, or supplied at capture time
    category        TEXT,                            -- 'PACKAGED_FOOD_FMCG' | 'COSMETICS' | 'UNSUPPORTED'
    organization_id INTEGER REFERENCES organization(id),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS product_image (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id      INTEGER REFERENCES product(id),
    file_path       TEXT NOT NULL,
    source          TEXT NOT NULL CHECK (source IN ('CAMERA', 'UPLOAD', 'ECOMMERCE_LISTING', 'DEMO')) DEFAULT 'UPLOAD',
    uploaded_by     INTEGER REFERENCES user(id),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------------
-- Compliance checks (the central workflow object)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS compliance_check (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id              INTEGER REFERENCES product(id),
    product_image_id        INTEGER REFERENCES product_image(id),
    submitted_by            INTEGER REFERENCES user(id),
    organization_id         INTEGER REFERENCES organization(id),
    status                  TEXT NOT NULL CHECK (status IN (
                                'QUEUED', 'PROCESSING', 'COMPLETED',
                                'PROCESSING_FAILED', 'INVALID_IMAGE', 'UNSUPPORTED_CATEGORY'
                            )) DEFAULT 'QUEUED',
    category                TEXT,                     -- resolved category (may differ from product.category if reclassified)
    rule_version_id         INTEGER REFERENCES rule_version(id),
    ocr_engine_version      TEXT,
    pipeline_version        TEXT,
    image_quality_score     REAL,                      -- 0..1
    image_quality_notes     TEXT,                       -- JSON list of detected issues (blur/glare/crop/curvature)
    audit_date              TEXT,                       -- date used to select rule_version (defaults to created_at date)
    created_at              TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at            TEXT
);

CREATE TABLE IF NOT EXISTS extracted_field (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    compliance_check_id   INTEGER NOT NULL REFERENCES compliance_check(id),
    field_type            TEXT NOT NULL,              -- e.g. "MRP", "NET_QUANTITY", "MANUFACTURER", ...
    raw_text              TEXT,
    normalized_value      TEXT,                       -- JSON: normalized structured value
    confidence            REAL NOT NULL,               -- 0..1, OCR/extraction confidence for this field
    bounding_box          TEXT,                        -- JSON: [x, y, w, h] in source image pixel space
    source                TEXT NOT NULL DEFAULT 'OCR', -- 'OCR' | 'LLM_ASSISTED' | 'MANUAL_OVERRIDE'
    script                TEXT DEFAULT 'LATIN',        -- 'LATIN' | 'DEVANAGARI' | 'UNKNOWN'
    created_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS requirement_result (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    compliance_check_id   INTEGER NOT NULL REFERENCES compliance_check(id),
    rule_requirement_id   INTEGER NOT NULL REFERENCES rule_requirement(id),
    verdict               TEXT NOT NULL CHECK (verdict IN (
                                'COMPLIANT', 'POTENTIAL_NON_COMPLIANCE',
                                'REQUIRES_OFFICER_VERIFICATION', 'INSUFFICIENT_EVIDENCE'
                            )),
    confidence            REAL NOT NULL,
    reason                TEXT NOT NULL,               -- human-readable, cites the rule
    extracted_field_ids   TEXT,                        -- JSON list of extracted_field.id
    rule_reference         TEXT NOT NULL,
    requires_review       INTEGER NOT NULL DEFAULT 0,
    created_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS evidence_item (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    compliance_check_id   INTEGER NOT NULL REFERENCES compliance_check(id),
    kind                  TEXT NOT NULL CHECK (kind IN ('ORIGINAL_IMAGE', 'PROCESSED_IMAGE', 'ANNOTATED_IMAGE', 'CROP')),
    file_path             TEXT NOT NULL,
    related_field_id      INTEGER REFERENCES extracted_field(id),
    created_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------------
-- Human review
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS review_task (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    compliance_check_id     INTEGER NOT NULL REFERENCES compliance_check(id),
    requirement_result_id   INTEGER NOT NULL REFERENCES requirement_result(id),
    assigned_to             INTEGER REFERENCES user(id),
    status                  TEXT NOT NULL CHECK (status IN ('PENDING', 'RESOLVED')) DEFAULT 'PENDING',
    created_at              TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS review_decision (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    review_task_id        INTEGER NOT NULL REFERENCES review_task(id),
    officer_id            INTEGER NOT NULL REFERENCES user(id),
    decision              TEXT NOT NULL CHECK (decision IN ('CONFIRM', 'CORRECT', 'MARK_INSUFFICIENT', 'OVERRIDE')),
    corrected_verdict     TEXT CHECK (corrected_verdict IN (
                                'COMPLIANT', 'POTENTIAL_NON_COMPLIANCE',
                                'REQUIRES_OFFICER_VERIFICATION', 'INSUFFICIENT_EVIDENCE'
                            )),
    reason                TEXT NOT NULL,
    created_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------------
-- Reporting
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS report (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    compliance_check_id   INTEGER NOT NULL REFERENCES compliance_check(id),
    file_path             TEXT NOT NULL,
    generated_by          INTEGER REFERENCES user(id),
    created_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------------
-- Audit log -- append-only, never updated/deleted by application code
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS audit_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id      INTEGER REFERENCES user(id),
    action        TEXT NOT NULL,               -- e.g. "CHECK_SUBMITTED", "RULE_VERSION_ACTIVATED"
    entity_type   TEXT NOT NULL,               -- e.g. "compliance_check", "rule_version"
    entity_id     INTEGER,
    old_value     TEXT,                        -- JSON
    new_value     TEXT,                        -- JSON
    metadata      TEXT,                        -- JSON
    timestamp     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------------
-- Background job table (stands in for a Celery/Redis queue -- see
-- docs/ARCHITECTURE.md for the production swap-in)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS job (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    job_type              TEXT NOT NULL,        -- 'PROCESS_CHECK'
    compliance_check_id   INTEGER REFERENCES compliance_check(id),
    status                TEXT NOT NULL CHECK (status IN ('PENDING', 'RUNNING', 'DONE', 'FAILED')) DEFAULT 'PENDING',
    error                 TEXT,
    created_at            TEXT NOT NULL DEFAULT (datetime('now')),
    started_at            TEXT,
    finished_at           TEXT
);

CREATE INDEX IF NOT EXISTS idx_check_status ON compliance_check(status);
CREATE INDEX IF NOT EXISTS idx_check_org ON compliance_check(organization_id);
CREATE INDEX IF NOT EXISTS idx_reqres_check ON requirement_result(compliance_check_id);
CREATE INDEX IF NOT EXISTS idx_extfield_check ON extracted_field(compliance_check_id);
CREATE INDEX IF NOT EXISTS idx_review_status ON review_task(status);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity_type, entity_id);
