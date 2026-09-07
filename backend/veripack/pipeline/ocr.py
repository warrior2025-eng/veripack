"""
OCR abstraction (PRD Part 9).

    OCRService.extract_regions(image) -> list[OCRRegion]

The rest of the pipeline (extraction.py, rules_engine.py) depends only on
this interface, not on Tesseract specifically. Swapping the engine for
EasyOCR (the PRD's stated preference, for better multilingual/Devanagari
support) means writing a second implementation of this interface and
changing one constructor call in pipeline.py -- nothing downstream changes.

WHY TESSERACT AND NOT EASYOCR HERE:
EasyOCR ships as a pip package that downloads pretrained model weights from
the internet on first use. This sandbox has no network access (confirmed:
`pip install easyocr` fails, and even if it were pre-installed, the model
weights are fetched at runtime from GitHub/AWS on first call). Tesseract is
a system binary already installed in this container with no additional
downloads required, so it is the only OCR engine that can actually run here.

WHY ENGLISH ONLY:
`tesseract --list-langs` in this container reports only `eng` and `osd`.
The Hindi (`hin`) trained-data file is a ~5MB download from the Tesseract
project's GitHub releases, which this sandbox cannot reach. The
`language_hint` parameter and `script` field on every OCRRegion exist so
that dropping a `hin.traineddata` file into the tessdata directory (or
swapping in EasyOCR) enables Hindi with no changes to any calling code --
see docs/AI_PIPELINE.md for exact upgrade steps.
"""

from dataclasses import dataclass, field
from typing import List

import cv2
import numpy as np
import pytesseract
from pytesseract import Output

OCR_ENGINE_VERSION = f"tesseract-{pytesseract.get_tesseract_version()}"


@dataclass
class OCRRegion:
    text: str
    confidence: float          # 0..1 (tesseract reports 0..100, we normalize)
    bbox: List[int]            # [x, y, w, h] in source image pixel space
    block_num: int
    par_num: int
    line_num: int
    script: str = "LATIN"      # 'LATIN' | 'DEVANAGARI' | 'UNKNOWN'


def _detect_script(text: str) -> str:
    """Cheap Unicode-range check -- flags Devanagari text if present so the
    UI/report can surface 'detected but not recognized' honestly, rather
    than silently mis-decoding it as Latin garbage."""
    for ch in text:
        if "\u0900" <= ch <= "\u097F":
            return "DEVANAGARI"
    return "LATIN"


class TesseractOCRService:
    """Concrete OCRService implementation. See module docstring for the
    interface contract and the reasons for this specific engine choice."""

    def __init__(self, language_hint: str = "eng"):
        self.language_hint = language_hint

    def extract_regions(self, preprocessed_gray: np.ndarray) -> List[OCRRegion]:
        data = pytesseract.image_to_data(
            preprocessed_gray, lang=self.language_hint, output_type=Output.DICT,
            config="--psm 6",  # assume a single uniform block of text (a label panel)
        )
        regions = []
        n = len(data["text"])
        for i in range(n):
            text = data["text"][i].strip()
            conf_raw = data["conf"][i]
            try:
                conf = float(conf_raw)
            except (ValueError, TypeError):
                conf = -1.0
            if not text or conf < 0:
                continue
            regions.append(OCRRegion(
                text=text,
                confidence=round(conf / 100.0, 3),
                bbox=[data["left"][i], data["top"][i], data["width"][i], data["height"][i]],
                block_num=data["block_num"][i],
                par_num=data["par_num"][i],
                line_num=data["line_num"][i],
                script=_detect_script(text),
            ))
        return regions

    def reconstruct_lines(self, regions: List[OCRRegion]) -> List[dict]:
        """Group word-level regions into lines by tesseract's
        (block_num, par_num, line_num) triple -- line_num alone resets to 1
        within every new block/paragraph, so grouping on line_num only would
        silently merge unrelated visual lines that happen to share a number.
        This was caught by inspecting real pipeline output on seed data
        (see git history / PR notes), not assumed correct from the API docs."""
        lines = {}
        for r in regions:
            key = (r.block_num, r.par_num, r.line_num)
            lines.setdefault(key, []).append(r)
        result = []
        # Sort groups by their top-most word's y-coordinate so lines come out
        # in reading order regardless of block/par numbering order.
        ordered_keys = sorted(lines.keys(), key=lambda k: min(w.bbox[1] for w in lines[k]))
        for key in ordered_keys:
            words = lines[key]
            words_sorted = sorted(words, key=lambda w: w.bbox[0])
            text = " ".join(w.text for w in words_sorted)
            xs = [w.bbox[0] for w in words_sorted]
            ys = [w.bbox[1] for w in words_sorted]
            x2s = [w.bbox[0] + w.bbox[2] for w in words_sorted]
            y2s = [w.bbox[1] + w.bbox[3] for w in words_sorted]
            avg_conf = sum(w.confidence for w in words_sorted) / len(words_sorted)
            result.append({
                "text": text,
                "bbox": [min(xs), min(ys), max(x2s) - min(xs), max(y2s) - min(ys)],
                "confidence": round(avg_conf, 3),
                "words": words_sorted,
            })
        return result


def load_image(path: str) -> np.ndarray:
    image = cv2.imread(path)
    if image is None:
        raise ValueError(f"Could not decode image at {path}")
    return image
