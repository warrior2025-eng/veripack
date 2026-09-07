# VeriPack

**Legal Metrology Compliance, Verified.**
*Scan the label. See the rule. Trust the evidence.*

An AI-assisted compliance screening and evidence platform for packaged
commodities under the Legal Metrology (Packaged Commodities) Rules, 2011 —
built for SIH26034 by Team StackVolt.

> **Read this first:** this codebase was built inside a sandboxed
> development container with **no internet access** and **no Docker
> daemon**. Several stack choices below (SQLite instead of PostgreSQL,
> Tesseract instead of EasyOCR, vanilla JS instead of React, Flask instead
> of FastAPI) are direct, documented consequences of that constraint —
> not shortcuts taken quietly. Every one of them is explained, with an
> exact upgrade path, in `docs/ARCHITECTURE.md` §7. Everything else — the
> rule engine, the four-state verdict system, the evidence packets, RBAC,
> the audit log, PDF reports — is real and fully functional, not mocked.

## 1. Project overview

VeriPack screens packaged-commodity labels (photographed or uploaded)
against a **versioned, admin-updatable** set of Legal Metrology
declaration requirements, and returns a **per-requirement, confidence-scored,
four-state verdict** — never a bare "illegal" claim. See the team's Master
Research Document & PRD for the full product rationale; this README covers
running and understanding *this* codebase.

Primary user: Legal Metrology enforcement officers. Secondary users:
manufacturers/packers/importers (self-check) and marketplace auditors.

## 2. Architecture at a glance

```
frontend/   vanilla HTML/CSS/JS single-page app (talks only to /api/*)
backend/
  main.py                Flask app entrypoint
  veripack/
    auth.py              JWT + RBAC
    audit.py              append-only audit logging
    reports.py            PDF generation (ReportLab)
    api/                  route handlers (auth, checks, reviews, rules, dashboard, audit)
    pipeline/              the domain layer -- see docs/AI_PIPELINE.md
      quality.py            image quality gate (blur/glare/curvature)
      ocr.py                 OCR abstraction (Tesseract)
      extraction.py          field extraction (regex + layout heuristics)
      normalization.py       deterministic unit/currency/date parsing
      category.py            keyword-based category classifier
      rules_engine.py         versioned rule engine -- see docs/RULE_ENGINE.md
      confidence.py           transparent confidence formula
      font_size.py            honest, uncalibrated font-size heuristic
      evidence.py              panel detection + annotated image rendering
      pipeline.py              orchestrates every stage above, in order
  db/
    schema.sql             full relational schema
    database.py            SQLite access layer
  seed/
    seed_data.py            realistic demo data (runs the REAL pipeline)
    generate_demo_images.py synthetic label images for the 3 demo scenarios
  tests/                    64 tests -- see §6
docs/
  ARCHITECTURE.md           full system design + production stack upgrade path
  RULE_ENGINE.md             the versioned rule engine explained
  AI_PIPELINE.md             CV/OCR pipeline, task separation, honest limitations
  SECURITY.md                 what's implemented, what a real deployment still needs
  DEMO.md                    SIH demo script
```

Full detail: `docs/ARCHITECTURE.md`.

## 3. Prerequisites

- Python 3.10+
- **Tesseract OCR** (a system package, not a pip package):
  - Debian/Ubuntu: `sudo apt-get install tesseract-ocr`
  - macOS: `brew install tesseract`
  - Windows: install from the [Tesseract project releases](https://github.com/UB-Mannheim/tesseract/wiki) and ensure `tesseract` is on `PATH`
- (Optional, for Docker) Docker + Docker Compose — **note**: the
  `Dockerfile`/`docker-compose.yml` in this repo were written correctly but
  never actually run in this project's development sandbox (no Docker
  daemon there). Test them yourself before relying on them.

## 4. Setup — local (no Docker)

```bash
cd backend
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp ../.env.example ../.env        # edit VERIPACK_JWT_SECRET at minimum

# Initialize the schema and load realistic demo data (3 compliance checks,
# 2 rule versions per category, seed users) -- this runs the REAL pipeline
# against synthetically generated demo label images, not fabricated rows.
python3 -m seed.seed_data

python3 main.py
```

Open `http://localhost:5000`. Demo credentials (development only):

| Role | Email | Password |
|---|---|---|
| Admin | `admin@veripack.demo` | `ChangeMe123!` |
| Officer | `officer@veripack.demo` | `ChangeMe123!` |

**Change or remove these before any deployment reachable by anyone else.**

## 5. Setup — Docker (untested in this sandbox, see the warning in §3)

```bash
cp .env.example .env              # edit VERIPACK_JWT_SECRET
docker compose up --build
```

The container's entrypoint (`backend/docker-entrypoint.sh`) initializes and
seeds the database automatically on first boot if none exists.

## 6. Running the tests

```bash
cd backend
python3 -m unittest discover -s tests -v
```

64 tests, all passing as of this build: password hashing, JWT issuance,
RBAC enforcement (including a direct-API test proving an Officer cannot
create a rule version even without a UI button for it), the four mandatory
rule-engine fixtures from the build brief (fully compliant / missing field
/ font-size under curvature / cropped image), rule-version applicability
edge cases, rule-version historical reproducibility (the core differentiator
— see §8), audit-log append-only behavior, PDF report generation, and a
full integration test that runs actual images through OCR → extraction →
rule engine → evidence → report via the real Flask API.

Two genuine bugs were caught and fixed by writing these tests (not just
cosmetic issues): an MRP-parsing regex that broke on Indian comma-grouped
numbers like "₹1,299.00", and a rule-version locking check that trusted a
cacheable column instead of computing live truth, which could have allowed
editing an already-in-use (and therefore supposedly immutable) rule
version. Both are covered by regression tests now.

## 7. Manual walkthrough (mirrors the project's acceptance criteria)

1. Run seed data (§4), start the server, open the app.
2. Log in as Officer → **Scan Product** → upload any label photo.
3. Watch the real pipeline-stage progress, then view the result screen:
   per-requirement verdicts, confidence, reasons, rule citations.
4. Open the annotated evidence image (bounding boxes colour-coded by
   verdict). Download the PDF report.
5. Go to **Review Queue**, resolve a low-confidence item — confirm the
   original AI verdict is preserved (a new `review_decision` row is
   created, the original `requirement_result` row is never overwritten).
6. Log in as Admin → **Regulatory Rules** → open a rule version →
   **Duplicate into New Draft** → add a requirement → **Activate**.
7. Re-scan the same product — the new rule version is now applied.
8. Open the *original* check in Inspection History — it still cites the
   *old* (now retired) rule version. Nothing about it silently changed.
9. Check **Audit Log** (Admin) — every action above is there.

## 8. The core differentiator, concretely

Research for this problem statement found no verified competitor offering
a regulator-updatable rule engine (see the team's Master Research
Document, Part 3–6). This codebase's answer to that gap is not aspirational
— it's the thing tested in `tests/test_rule_version_history.py` and
demoed in step 6–8 above: an admin can change what the law requires
through the API/UI, with the previous version automatically retired
(`effective_to` set) and locked, while every check that already ran keeps
citing the exact rule text that was active when it ran.

## 9. Known limitations (stated plainly, not hidden)

- **OCR is English-only** in this build (Tesseract, no Hindi language pack
  available offline). See `docs/AI_PIPELINE.md`.
- **Category classification is a keyword heuristic**, not a trained model
  — two categories supported (Packaged Food/FMCG, Cosmetics).
- **Font-size/placement is deliberately uncalibrated** — it will rarely if
  ever return `COMPLIANT` on its own; that's intentional, not a bug. See
  `docs/AI_PIPELINE.md`'s "the hard part" section.
- **Net quantity**: only the *declaration's presence and format* is
  checked. Physical quantity accuracy requires metrological weighing under
  the Sixth Schedule and is out of scope for any image-based system — the
  UI and PDF report say this explicitly.
- **Bulk upload / e-commerce listing scanning** are architecturally
  anticipated (see the `job` table and `ECOMMERCE_LISTING` as a valid
  `product_image.source` value in `db/schema.sql`) but not implemented in
  this MVP — single-scan was prioritized per the brief's "do not let
  optional features destabilize the core MVP" instruction.
- **Offline capture queue / PWA** is not implemented.
- **SQLite, not PostgreSQL; synchronous processing, not Celery** — see
  `docs/ARCHITECTURE.md` §6–7 for why and for the exact migration path.

## 10. License / attribution

Built by Team StackVolt for Smart India Hackathon 2026, Problem Statement
SIH26034, sponsored by the Department of Consumer Affairs, Ministry of
Consumer Affairs, Food & Public Distribution.
