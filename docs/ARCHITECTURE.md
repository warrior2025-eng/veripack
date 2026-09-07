# VeriPack — Architecture

## 1. What this document covers

The overall system architecture, how the pieces fit together, the database
design, and — because this reference implementation was built in a sandbox
with no internet access — exactly what changes if you move it to the PRD's
originally specified stack (React/TypeScript/Vite/Tailwind, FastAPI,
PostgreSQL, Redis + Celery, EasyOCR, Docker) in an environment that can
reach the internet.

## 2. Development environment note (read this first)

This implementation was built inside a sandboxed container with **no
network access** (`pip install fastapi` and `npm install react` both fail
outright — the npm registry request returns `host_not_allowed`) and **no
Docker daemon**. Every architectural decision below that deviates from the
PRD's stated stack is a direct, documented consequence of that constraint,
not a design preference. The `Dockerfile` and `docker-compose.yml` in this
repo were written correctly against that constraint's absence (i.e., for a
normal machine with Docker installed) but were never actually built or run,
because nothing in the development sandbox could run them. Build and test
them yourself before depending on them in a real deployment.

## 3. High-level architecture (as built)

```
┌─────────────────────────────────────────────────────────────────────┐
│  Browser                                                             │
│  frontend/templates/index.html + frontend/static/js/{api,app}.js     │
│  Vanilla JS hash router. Talks to the backend ONLY via the JSON API   │
│  in api.js -- no server-rendered state leaks into the JS beyond that. │
└───────────────────────────────┬───────────────────────────────────────┘
                                 │  fetch() -> /api/*
┌───────────────────────────────▼───────────────────────────────────────┐
│  Flask app (backend/main.py)                                          │
│  ┌───────────────┐  ┌────────────────┐  ┌─────────────────────────┐  │
│  │ auth_routes    │  │ checks_routes  │  │ rules_routes             │ │
│  │ reviews_routes │  │ dashboard_...  │  │ audit_routes             │ │
│  └───────┬────────┘  └───────┬────────┘  └────────────┬─────────────┘  │
│          │  (route handlers contain NO domain logic --                │
│          │   they parse the request, call a pipeline/domain           │
│          │   function, and shape the JSON response)                   │
│  ┌───────▼─────────────────────────────────────────────────────────┐  │
│  │ veripack/pipeline/*  (the domain layer)                          │  │
│  │  quality -> ocr -> extraction -> normalization -> category ->    │  │
│  │  rules_engine -> confidence -> font_size -> evidence -> pipeline │  │
│  └───────┬─────────────────────────────────────────────────────────┘  │
│  ┌───────▼─────────────┐  ┌──────────────┐  ┌───────────────────────┐│
│  │ db/database.py       │  │ veripack/    │  │ veripack/reports.py  ││
│  │ (SQLite access layer)│  │ audit.py     │  │ (PDF generation)     ││
│  └───────┬───────────────┘  └──────────────┘  └───────────────────────┘│
└──────────┼───────────────────────────────────────────────────────────┘
           │
┌──────────▼───────────────────────────────────────────────────────────┐
│  storage/  (SQLite DB file, uploaded images, evidence images, PDFs)    │
└─────────────────────────────────────────────────────────────────────┘
```

## 4. Data flow for one scan

`POST /api/checks` (multipart image upload) → `checks_routes.create_check`
validates and stores the file, inserts `product`/`product_image`/
`compliance_check` rows with status `QUEUED`, returns `check_id`.

`POST /api/checks/{id}/process` → `checks_routes.process_check` calls
`pipeline.run_pipeline(check_id)` **synchronously** (see §6 on why), which
runs every stage in `veripack/pipeline/pipeline.py` in order and persists
`extracted_field`, `requirement_result`, `review_task` (where needed), and
`evidence_item` rows, then marks the check `COMPLETED` (or `INVALID_IMAGE`
/ `UNSUPPORTED_CATEGORY` / `PROCESSING_FAILED` — see docs/AI_PIPELINE.md
for how those are distinguished from each other and from a true error).

Every other endpoint (`/results`, `/evidence`, `/report`, dashboard,
history, review queue, audit log) reads from those same tables — there is
no separate "read model"; SQLite plus a handful of indexes (see
`db/schema.sql`) was fast enough for the scan volumes this MVP targets.

## 5. Database design

Full schema: `backend/db/schema.sql`. Entity relationships, summarized:

```
organization ─┬─< user
              └─< product ─< product_image ─< compliance_check
                                                    │
                    ┌───────────────────────────────┼──────────────────┐
                    │                                │                  │
              extracted_field                 requirement_result   evidence_item
                                                    │
                                              review_task ─< review_decision

rule_version ─< rule_requirement          (rule_version_id referenced by
                                            compliance_check AND by
                                            requirement_result indirectly
                                            via rule_requirement)

report (1:1-ish with compliance_check, but modeled as its own table since
        a check could in principle be re-reported)

audit_log (append-only; references user as actor, any entity_type/entity_id)

job (stands in for a Celery task table -- see §6)
```

Every table uses an integer surrogate primary key and explicit foreign
keys, and timestamps are stored as ISO-8601 TEXT. This was a deliberate
choice so the schema is a near-direct PostgreSQL port (see §7) — swapping
`TEXT` timestamp columns for `TIMESTAMPTZ` and running the same DDL through
`psql` is most of the migration.

## 6. Why synchronous processing, not Celery/Redis

The PRD requires bulk jobs to be architecturally asynchronous while
allowing single scans to run synchronously. This implementation:

- Runs a single scan's pipeline **synchronously inside the request** for
  `/api/checks/{id}/process` — acceptable because Tesseract + OpenCV on one
  image completes in low single-digit seconds on typical hardware.
- Includes a `job` table (`db/schema.sql`) that models exactly what a
  Celery task row would need (`job_type`, `status`, timestamps, `error`) —
  this is the concrete extension point for bulk uploads: a bulk-upload
  endpoint would insert N `job` rows with `status='PENDING'` and a
  background worker loop (or, with network access, an actual Celery worker
  consuming a Redis queue) would claim and process them, exactly mirroring
  how `run_pipeline()` already works per-check.
- Bulk upload itself is **not implemented** in this MVP (it was marked
  "should have if time/practical" and the core single-scan path was
  prioritized) — the `job` table exists so adding it later is additive,
  not a redesign.

## 7. Production stack upgrade path

If you're reading this in an environment with normal internet access, here
is exactly what changes to reach the PRD's originally specified stack.
Nothing in the **domain logic** (`veripack/pipeline/*`) needs to change for
any of this — the swaps are at the edges.

| Layer | This build | Target (PRD) | What changes |
|---|---|---|---|
| Frontend | Vanilla JS + hash router (`frontend/static/js/app.js`) | React + TS + Vite + Tailwind | Rewrite the views as React components calling the *same* `/api/*` endpoints in `api.js` — the backend contract doesn't change. `app.js`'s view functions map roughly 1:1 to what would become React pages/components. |
| Backend framework | Flask (`main.py`, `veripack/api/*`) | FastAPI + Pydantic | Route handlers are already thin and call into `veripack/pipeline/*` and `db/database.py` — porting means rewriting the Flask `@bp.route` decorators as FastAPI path operations and adding Pydantic request/response models; the underlying function bodies barely change. |
| Database | SQLite (`db/database.py`, raw `sqlite3`) | PostgreSQL + SQLAlchemy + Alembic | `db/schema.sql` is written to be a near-direct Postgres port (see §5). Replace `db/database.py`'s `get_db()`/`get_conn()` with a SQLAlchemy session factory; every other module only depends on the `get_db()` cursor-yielding contract, not on SQLite specifically, so the query code itself (mostly parameterized `cur.execute(...)`) needs only mechanical translation to the ORM or to `psycopg2` if you keep raw SQL. |
| OCR | Tesseract (`veripack/pipeline/ocr.py`, `TesseractOCRService`) | EasyOCR (better multilingual/Devanagari support) | Write a second class implementing the same interface (`extract_regions(image) -> list[OCRRegion]`, `reconstruct_lines(...)`) and swap the one constructor call in `pipeline.py` (`_ocr_service = TesseractOCRService(...)` → `EasyOCRService(...)`). Nothing downstream (`extraction.py`, `rules_engine.py`) needs to change — they only depend on the `OCRRegion`/line-dict shape. |
| Background jobs | Synchronous in-request (§6) | Redis + Celery | Add a Celery app, move `run_pipeline()`'s call site into a `@task`, and use the `job` table (already in the schema) as the durable record backing task status. |
| Storage | Local filesystem (`storage/uploads`, `storage/evidence`, `storage/reports`) | S3-compatible object storage | Replace the `open(path, "wb")` calls in `checks_routes.py`/`pipeline.py`/`reports.py` with an S3 client; `evidence_item.file_path` and similar columns would store an S3 key instead of a local path. |
| Password hashing | `werkzeug.security` (PBKDF2-SHA256) | bcrypt via passlib | One-line change in `veripack/auth.py`'s `hash_password`/`verify_password`. |
| Deployment | Plain Python / gunicorn in Docker (untested here, see §2) | Docker + docker-compose, PaaS-ready | The `Dockerfile`/`docker-compose.yml` in this repo are a starting point; add `postgres`, `redis`, and a `celery` service to `docker-compose.yml` per §6. |

## 8. Module boundaries (what depends on what)

```
veripack/api/*        -> veripack/pipeline/*, veripack/auth.py, veripack/audit.py, veripack/reports.py, db/database.py
veripack/pipeline/*   -> db/database.py only (never imports veripack/api/*)
veripack/reports.py   -> db/database.py only
veripack/auth.py      -> db/database.py only
db/database.py        -> stdlib sqlite3 only
```

This one-directional dependency graph is why, for example, the rule-locking
fix (see git history / test suite) lives as a self-contained check inside
`rules_routes.py` rather than requiring `veripack/pipeline/pipeline.py` to
import from the API layer — the pipeline layer must never depend on the API
layer, only the reverse.
