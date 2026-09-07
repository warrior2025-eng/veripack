# VeriPack — Rule Engine

## Why this exists

Research for SIH26034 (see the team's master research document) found no
verified competitor with a regulator-updatable rule engine. Every existing
tool either hardcodes category-specific logic in application code, or
routes every case through a human expert. The Legal Metrology (Packaged
Commodities) Rules, 2011 have been amended at least seven times between
2021 and 2025 — a hardcoded checklist is provably stale on a predictable
schedule. This module is the concrete answer to that gap.

## The core principle: rules are data, not code

`veripack/pipeline/rules_engine.py` contains **zero** hardcoded knowledge
of what any specific category requires. Every requirement — its
applicability, its validation logic, its severity, its legal citation — is
a row in the `rule_requirement` table, scoped to a `rule_version` (see
`db/schema.sql`). Changing what the law requires means an admin creating
new rows through `POST /api/rules` and `POST /api/rules/{id}/requirements`
(exercised by the frontend's Admin → Regulatory Rules screen) — never
editing this Python file.

## Rule version lifecycle

```
DRAFT ──(add requirements)──> DRAFT ──(activate)──> ACTIVE ──(a newer
  │                                                    │      version is
  │                                                    │      activated
  ▼                                                    ▼      for the same
(can be freely edited)                             RETIRED    category)
```

- **DRAFT**: editable. Requirements can be added, source fields updated.
- **ACTIVE**: exactly one `rule_version` per `category` can be ACTIVE at a
  time. Activating a new version automatically retires whichever version
  was previously ACTIVE for that category, setting its `effective_to` to
  the new version's `effective_from` — this is what makes "the law changed
  without a code deployment" both true and reproducible.
- **RETIRED**: no longer selected for new checks, but never deleted —
  historical checks still reference it by ID.
- **Locked**: the moment *any* `compliance_check` references a
  `rule_version` (by ID, in `compliance_check.rule_version_id`), that
  version becomes immutable. `rules_routes.py`'s `_is_locked()` computes
  this **live** from the `compliance_check` table on every mutating
  request — it does not trust a cached flag, specifically because an
  earlier version of this code had a real bug where the cached column
  could go stale and a locked version could still be edited (caught by
  `tests/test_rule_version_history.py::test_rule_version_locks_once_used_by_a_check`,
  now fixed and covered by a regression test).
- To change an already-used version's requirements, the correct workflow
  is **duplicate → edit the draft copy → activate the copy** (`POST
  /api/rules/{id}/duplicate`), never edit-in-place.

## Rule selection at evaluation time

`select_rule_version(category, audit_date)` returns the `ACTIVE`
`rule_version` for that category whose `[effective_from, effective_to)`
window contains `audit_date`. `audit_date` defaults to "today" but is
stored per-check (`compliance_check.audit_date`), so a retrospective audit
run against a past date would (if the feature were exposed in the UI, which
it currently isn't in the MVP frontend) correctly select the rule version
that was actually in force then — the schema and query already support
this even though there's no UI control for it yet.

If no `ACTIVE` version exists for a category at all, the check is marked
`UNSUPPORTED_CATEGORY` — the system never falls back to an arbitrary or
default rule set (see `pipeline.py`'s handling of this case).

## Validation types

Every `rule_requirement.validation_logic` is a small JSON object with a
`type` key, interpreted by `rules_engine.py`'s `_EVALUATORS` dispatch:

| `type` | Used for | Logic |
|---|---|---|
| `presence` | Generic name, mfg date, consumer care | Field detected at all? |
| `qualified_presence` | Manufacturer/packer/importer | Field detected AND the "manufactured by / packed by / marketed by" qualifier recognized (legal liability differs by qualifier — PC Rules Explanations I & II) |
| `format` | Net quantity, MRP | Field detected AND parses into the expected structured keys (e.g. `value` + `unit`) via `normalization.py` |
| `visual_geometric` | Font-size/placement | Routed to `font_size.py`'s heuristic — see docs/AI_PIPELINE.md for why this can essentially never return `COMPLIANT` from an uncalibrated photo |

## Applicability logic

`rule_requirement.applicability_logic` decides whether a requirement even
applies to a given product:

- `ALL` — always applicable.
- `IMPORTED_ONLY` — applicable only if the extracted `COUNTRY_OF_ORIGIN`
  field indicates a non-Indian origin. If no origin signal was extracted at
  all, the requirement returns `INSUFFICIENT_EVIDENCE` (import status
  itself is unknown) rather than being silently skipped — see
  `tests/test_rules_engine.py::TestRuleEngineApplicability` for both the
  "genuinely domestic → no result row at all" and "unknown →
  INSUFFICIENT_EVIDENCE" behaviors, which are deliberately different
  outcomes.
- The schema also anticipates `PERISHABLE_ONLY` / `GARMENT_ONLY` for future
  category expansion (combination/group/multi-piece packages, garment
  metric sizing — PRD Part 15) but the MVP's two categories don't yet
  populate requirements using them.

## What's deliberately NOT in the MVP rule set

Per the research document's Part 5 (Legal & Regulatory Analysis) and the
build brief's explicit exclusions:

- **Medical device numeral-height rules** — the 2025 amendment carves
  medical devices out to a *separate* rule text (Medical Devices Rules,
  2017) that was not independently verified in the research phase. Adding
  a medical-device category without first reading that separate rule text
  directly would risk inventing a legal requirement — explicitly against
  the project's instructions.
- **Certified physical net-quantity validation** — requires metrological
  weighing under the Sixth Schedule; no image-based system can do this
  (see docs/AI_PIPELINE.md).
- **Combination/group/multi-piece package-specific declarations** — the
  schema and `applicability_logic` design support adding these, but no
  MVP-category requirement uses them yet (flagged as a real engineering-risk
  area in the research document, not something to rush).
