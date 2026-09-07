# VeriPack — Demo Guide

## Setup before the room

1. `cd backend && python3 -m seed.seed_data` — resets and seeds the
   database with 3 demo compliance checks, 2 rule versions per category,
   and the two demo login accounts.
2. Start the server (`python3 main.py`, or the Docker Compose service).
3. Open `http://localhost:5000` and confirm the login screen loads with
   the demo credentials pre-filled.
4. Log in once as officer and once as admin beforehand to warm up
   Tesseract's first-load overhead, so the live demo scan feels instant.

## The live flow (mirrors PRD Part 32 / the build brief's judge-demo flow)

1. **Login as Officer** (`officer@veripack.demo` / `ChangeMe123!`).
2. **Dashboard** — point out the stat grid is live data, not placeholders
   (if this is a fresh seed, the numbers will match exactly what the seed
   script printed to the console).
3. **Scan Product** — upload a real product photo (a judge's own snack
   wrapper works well) or a phone photo taken in the room.
   - The pipeline-stage list animates through the real stages while the
     backend actually processes the image — this is not a fake delay; the
     `/process` call runs the full OCR→extraction→rules pipeline
     synchronously and the stage list simply steps forward while awaiting
     that one call (see `frontend/static/js/app.js`'s `submitScan`).
4. **Results screen** — walk through the per-requirement verdicts. Point
   out:
   - The four-state vocabulary (never "illegal").
   - Confidence percentages and the confidence bar per requirement.
   - The limitation note at the bottom (net quantity / font-size honesty).
5. **Annotated evidence image** — bounding boxes colour-coded by verdict,
   directly on the result page.
6. **Download PDF Report** — a real, generated PDF opens in a new tab.
7. **Review Queue** (if any items are pending) — show an officer resolving
   a low-confidence item, and note that the original AI verdict is
   preserved (not overwritten) — visible in the underlying
   `requirement_result` row if you want to show the database directly.
8. **The memorable moment — Admin → Regulatory Rules**:
   - Log in as Admin (`admin@veripack.demo` / `ChangeMe123!`) in a second
     tab or after logging out.
   - Open an existing ACTIVE rule version, click **Duplicate into New
     Draft**, add or edit a requirement, then **Activate** it with an
     effective date.
   - Point out that the previously ACTIVE version automatically became
     RETIRED with its `effective_to` set — no code was touched, no
     deployment happened.
   - Go back to the Officer tab and re-scan the **same** product image.
     The new rule version is now the one applied. Then open the original
     (already-completed) check from Inspection History and show that it
     still cites the *old* rule version — historical results didn't
     silently change.

## Suggested three scenarios (PRD Part 16)

The seed script already creates these three; use them if you don't have
time to demo a live judge-submitted image, or to fall back on if a live
photo doesn't OCR cleanly under room lighting:

1. **Clearly compliant** (`demo_compliant.jpg`) — all core Rule 6
   declarations present and well-formed. Expect mostly `COMPLIANT`.
2. **Obvious missing declaration** (`demo_missing_declaration.jpg`) — the
   consumer-care block was omitted at image-generation time. Expect
   `CONSUMER_CARE` to come back `POTENTIAL_NON_COMPLIANCE` while other
   requirements stay `COMPLIANT` — demonstrating the **per-requirement**,
   not blanket, verdict model.
3. **Difficult / edge case** (`demo_difficult.jpg`) — synthetically warped
   (curved-surface simulation) with a glare artifact overlaid. Expect the
   font-size/placement requirement to come back
   `REQUIRES_OFFICER_VERIFICATION` with a reason citing the detected
   curvature/glare — this is the single most important technical moment
   to narrate: the system is *refusing* to guess, on purpose.

## Honest answers ready for the Q&A

See the master research document's Part 18 ("Judge Q&A — Top 15") for the
full list. The three most likely to come up live, given what's actually
built:

- **"Is this using EasyOCR/multilingual OCR like the PRD says?"** — No,
  this build uses Tesseract (English only) because of sandbox network
  constraints during development; the architecture is built so swapping in
  EasyOCR is a one-class change (see docs/AI_PIPELINE.md). Say this
  plainly if asked — it's a environment constraint, not a design
  weakness, and the interface boundary that makes the swap easy is itself
  worth pointing to as evidence of good architecture.
- **"Is this running on PostgreSQL like a real deployment would?"** — No,
  SQLite for the same reason; see docs/ARCHITECTURE.md §7 for the exact,
  documented migration path.
- **"How do you know the confidence numbers are meaningful?"** — They're a
  transparent, documented multiplicative formula (docs/AI_PIPELINE.md),
  not a black-box model score — every factor is inspectable, and the
  threshold is a single named constant that would be tuned against a
  labelled validation set in a real deployment, which doesn't exist yet.
