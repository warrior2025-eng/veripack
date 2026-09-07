# VeriPack — AI / CV / OCR Pipeline

## Task separation (what's AI, what's deterministic code)

| Stage | Module | Category | Why |
|---|---|---|---|
| Image quality gate (blur/glare/resolution/curvature) | `pipeline/quality.py` | Classical CV (OpenCV heuristics) | Cheap, explainable, no training data needed |
| Preprocessing (grayscale, CLAHE, denoise, sharpen) | `pipeline/quality.py` | Classical CV | Deterministic, improves OCR accuracy measurably on real photos |
| Panel localization | `pipeline/evidence.py::detect_panel` | Classical CV heuristic | A trained detector needs labelled data this project couldn't obtain offline (see below) |
| Text detection + recognition | `pipeline/ocr.py` | OCR (Tesseract) | See "Why Tesseract, not EasyOCR" below |
| Field extraction (which text is MRP vs address) | `pipeline/extraction.py` | Regex + layout heuristics | Deterministic and traceable — every field is provably derived from OCR text, never invented |
| Quantity/currency/date normalization | `pipeline/normalization.py` | Deterministic parsing | Explicitly required by the brief: "do not use LLMs for basic parsing" |
| Category classification | `pipeline/category.py` | Keyword heuristic (not a trained model) | See "Why not a trained classifier" below |
| Rule selection + evaluation | `pipeline/rules_engine.py` | Deterministic rule engine | The compliance decision must be reproducible and auditable — see docs/RULE_ENGINE.md |
| Confidence scoring | `pipeline/confidence.py` | Transparent multiplicative formula | Not a trained model; every factor is independently inspectable |
| Font-size/placement | `pipeline/font_size.py` | CV heuristic, explicitly uncalibrated | See "The hard part" below |
| Evidence annotation | `pipeline/evidence.py::draw_annotations` | Deterministic rendering (OpenCV drawing calls) | — |
| PDF report | `reports.py` | Deterministic templating (ReportLab) | — |

**LLM usage**: none is wired into this build. No LLM API was reachable
from the development sandbox. The brief's LLM-assistance boundary
(synonym matching / generic-name interpretation / explanation wording,
**never** the compliance decision) is documented here as the integration
point for when one is available — it would slot in as an optional
enhancement to `extraction.py`'s generic-name matching and to
`rules_engine.py`'s `reason` text generation, called *after* the
deterministic verdict is already decided, never before.

## Why Tesseract, not EasyOCR

The PRD specifies EasyOCR for better multilingual/Devanagari support.
EasyOCR downloads pretrained model weights from the internet on first use
(`pip install easyocr` itself also failed in this sandbox — `ERROR: Could
not find a version that satisfies the requirement`, since there's no route
to PyPI). Tesseract is a system binary that was already installed with no
further downloads required, so it's the only OCR engine that could
actually run here. `pipeline/ocr.py`'s `TesseractOCRService` implements a
narrow interface (`extract_regions`, `reconstruct_lines`) specifically so
an `EasyOCRService` implementing the same interface is a drop-in swap —
see docs/ARCHITECTURE.md §7.

## Why English only (not Hindi/Devanagari)

`tesseract --list-langs` in the development container reports only `eng`
and `osd` — the Hindi trained-data file (`hin.traineddata`, a small
download from the Tesseract project's GitHub releases) could not be
fetched. `OCRRegion.script` and `_detect_script()` in `ocr.py` already
detect *whether* a piece of text is in the Devanagari Unicode range, so the
system honestly reports "Devanagari text detected, not recognized" rather
than silently mis-OCRing it as Latin garbage — but it cannot extract
structured fields from Devanagari text in this build. Dropping a
`hin.traineddata` file into the tessdata directory (or switching to
EasyOCR) enables Hindi with no changes to any calling code.

## Why category classification is a keyword heuristic, not a trained model

Training a real image/text category classifier needs a labelled dataset of
real product photos across categories — this sandbox has neither the data
nor network access to assemble or download one. The PRD explicitly says
not to train a custom CV model unless absolutely necessary, and a keyword
heuristic (`pipeline/category.py`) is the honest, practical substitute:
it counts category-indicative keywords in the OCR'd text (e.g. "SPF",
"lotion" → cosmetics; "net wt", "FSSAI" → food) and defaults to
`PACKAGED_FOOD_FMCG` at low confidence if nothing matches, rather than
guessing an unsupported category.

## The hard part: font-size and placement, done honestly

Pixel height in a photograph is **not** a physical measurement — the same
1mm numeral can occupy 8px or 40px purely depending on camera distance.
`pipeline/font_size.py` therefore:

- Never converts a pixel measurement to millimetres.
- Reports only a *relative* ratio (numeral height ÷ detected panel height),
  used solely as a coarse "looks obviously undersized" flag.
- Downgrades to `REQUIRES_OFFICER_VERIFICATION` whenever curvature or
  glare is detected (via `quality.py`'s heuristics) — because curved or
  reflective packaging distorts text geometry non-uniformly, making even
  the relative ratio unreliable.
- Can, in principle, essentially never return `COMPLIANT` on its own in
  this MVP — there is no calibration-marker or known-package-dimension
  input wired into the capture flow yet (both are described as post-MVP
  in the PRD). This is a deliberate, documented limitation, not an
  oversight: claiming certified millimetre accuracy from an ordinary
  uncalibrated photo would be false precision.

## Confidence model

```
confidence = field_confidence × image_quality_score × validation_confidence × visual_quality_factor
```

All four factors are in `[0, 1]` and independently visible in the evidence
packet. `visual_quality_factor` is `1.0` for ordinary presence/format
checks and only drops below 1.0 for `visual_geometric` checks under
detected curvature/glare (`confidence.py::visual_quality_factor_from_issues`)
— curved packaging should not silently fail an OCR-based presence check,
only a geometry-based one (PRD Part 18). The threshold
(`CONFIDENCE_THRESHOLD = 0.75`) is a single named constant, not scattered
magic numbers, so it's easy to find and tune against a labelled validation
set later.

## Image quality gate

`quality.py::assess_image_quality` runs three classical heuristics —
Laplacian-variance blur detection, near-white pixel ratio for glare, and a
contour-irregularity proxy for curvature — before anything else runs. If
the composite score is below a usability threshold, the check is marked
`INVALID_IMAGE` and the pipeline stops there: no compliance logic ever
runs on an image too poor to say anything reliable about (PRD Part 9 /
Part 34).
