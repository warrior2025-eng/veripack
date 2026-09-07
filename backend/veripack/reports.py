"""
PDF compliance report (PRD Part 24).

Uses ONLY the four-state verdict vocabulary. There is no code path in this
module that can print the word "illegal" -- VERDICT_LABELS below is the
single source of truth for how each verdict is rendered, so that vocabulary
discipline is enforced structurally, not just by convention.
"""

import os
from datetime import datetime, timezone

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER

from db.database import get_db, row_to_dict, rows_to_list, from_json

REPORT_DIR = os.environ.get("VERIPACK_REPORT_DIR", "storage/reports")

VERDICT_LABELS = {
    "COMPLIANT": "Compliant with checked requirements",
    "POTENTIAL_NON_COMPLIANCE": "Potential non-compliance detected",
    "REQUIRES_OFFICER_VERIFICATION": "Requires officer verification",
    "INSUFFICIENT_EVIDENCE": "Insufficient evidence",
}
VERDICT_COLORS = {
    "COMPLIANT": colors.HexColor("#1f7a3d"),
    "POTENTIAL_NON_COMPLIANCE": colors.HexColor("#b3261e"),
    "REQUIRES_OFFICER_VERIFICATION": colors.HexColor("#b06a00"),
    "INSUFFICIENT_EVIDENCE": colors.HexColor("#6b6b6b"),
}

LIMITATION_TEXT = (
    "VeriPack is an assistive screening and evidence tool. It does not issue a final legal "
    "determination of non-compliance -- that authority remains with the Legal Metrology Officer "
    "and the statutory process. Declared net quantity presence/format is checked; physical net "
    "quantity accuracy cannot be certified from a photograph and requires metrological weighing "
    "under the Sixth Schedule. Numeral height (font-size) estimates in this report are relative, "
    "uncalibrated approximations, not certified millimetre measurements, unless a calibration "
    "reference was used at capture time. All verdicts should be read alongside the confidence "
    "score and underlying evidence, not in isolation."
)


def _fetch_check_bundle(check_id: int) -> dict:
    with get_db() as cur:
        cur.execute("SELECT * FROM compliance_check WHERE id=?", (check_id,))
        check = row_to_dict(cur.fetchone())
        if check is None:
            raise ValueError(f"compliance_check {check_id} not found")

        cur.execute("SELECT * FROM product WHERE id=?", (check["product_id"],))
        product = row_to_dict(cur.fetchone())

        cur.execute("SELECT * FROM user WHERE id=?", (check["submitted_by"],))
        officer = row_to_dict(cur.fetchone())

        cur.execute("SELECT * FROM rule_version WHERE id=?", (check["rule_version_id"],))
        rule_version = row_to_dict(cur.fetchone())

        cur.execute(
            """SELECT rr.*, req.requirement_name, req.source_citation
               FROM requirement_result rr
               JOIN rule_requirement req ON req.id = rr.rule_requirement_id
               WHERE rr.compliance_check_id=? ORDER BY rr.id""",
            (check_id,),
        )
        results = rows_to_list(cur.fetchall())

        cur.execute(
            "SELECT * FROM evidence_item WHERE compliance_check_id=? AND kind='ANNOTATED_IMAGE'",
            (check_id,))
        annotated = row_to_dict(cur.fetchone())

    return {"check": check, "product": product, "officer": officer,
            "rule_version": rule_version, "results": results, "annotated": annotated}


def generate_report(check_id: int, generated_by: int) -> str:
    """Builds the PDF and returns the file path. Also inserts a `report`
    row so the report is discoverable from inspection history (PRD Part 23)."""
    bundle = _fetch_check_bundle(check_id)
    os.makedirs(REPORT_DIR, exist_ok=True)
    file_path = os.path.join(REPORT_DIR, f"veripack_report_check_{check_id}.pdf")

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("VPTitle", parent=styles["Title"], textColor=colors.HexColor("#0b3d66"))
    h2 = ParagraphStyle("VPH2", parent=styles["Heading2"], textColor=colors.HexColor("#0b3d66"), spaceBefore=14)
    normal = styles["Normal"]
    small = ParagraphStyle("VPSmall", parent=styles["Normal"], fontSize=8.5, textColor=colors.HexColor("#444444"))
    center = ParagraphStyle("VPCenter", parent=normal, alignment=TA_CENTER)

    doc = SimpleDocTemplate(file_path, pagesize=A4,
                             topMargin=18 * mm, bottomMargin=18 * mm,
                             leftMargin=16 * mm, rightMargin=16 * mm)
    story = []

    story.append(Paragraph("VeriPack", title_style))
    story.append(Paragraph("Legal Metrology Compliance Screening Report", styles["Heading3"]))
    story.append(HRFlowable(width="100%", color=colors.HexColor("#0b3d66"), thickness=1.2))
    story.append(Spacer(1, 8))

    meta_rows = [
        ["Check ID", str(bundle["check"]["id"]), "Status", bundle["check"]["status"]],
        ["Generated", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
         "Officer", (bundle["officer"] or {}).get("name", "-")],
        ["Category", bundle["check"]["category"] or "-",
         "Image Quality", f"{bundle['check']['image_quality_score']}"
         if bundle["check"]["image_quality_score"] is not None else "-"],
        ["Rule Version", Paragraph((bundle["rule_version"] or {}).get("name", "-"), small),
         "Rule Ref.", Paragraph((bundle["rule_version"] or {}).get("source_reference", "-") or "-", small)],
        ["OCR Engine", bundle["check"]["ocr_engine_version"] or "-",
         "Pipeline", bundle["check"]["pipeline_version"] or "-"],
    ]
    meta_table = Table(meta_rows, colWidths=[32 * mm, 62 * mm, 32 * mm, 52 * mm])
    meta_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#0b3d66")),
        ("TEXTCOLOR", (2, 0), (2, -1), colors.HexColor("#0b3d66")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dddddd")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f7f9fb")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 10))

    if bundle["annotated"] and os.path.exists(bundle["annotated"]["file_path"]):
        try:
            img = Image(bundle["annotated"]["file_path"], width=100 * mm, height=75 * mm, kind="proportional")
            story.append(img)
            story.append(Spacer(1, 4))
            story.append(Paragraph("Annotated evidence image (bounding boxes colour-coded by verdict).", small))
        except Exception:
            pass

    story.append(Paragraph("Requirement-by-Requirement Results", h2))
    header = ["Requirement", "Verdict", "Confidence", "Rule Reference"]
    table_data = [header]
    for r in bundle["results"]:
        table_data.append([
            Paragraph(r["requirement_name"], small),
            Paragraph(f'<font color="{VERDICT_COLORS.get(r["verdict"], colors.black).hexval()}">'
                      f'<b>{VERDICT_LABELS.get(r["verdict"], r["verdict"])}</b></font>', small),
            f'{r["confidence"]:.2f}',
            Paragraph(r["rule_reference"], small),
        ])
    results_table = Table(table_data, colWidths=[45 * mm, 55 * mm, 20 * mm, 58 * mm], repeatRows=1)
    results_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0b3d66")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dddddd")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f6fa")]),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(results_table)
    story.append(Spacer(1, 10))

    story.append(Paragraph("Detailed Reasoning", h2))
    for r in bundle["results"]:
        story.append(Paragraph(
            f'<b>{r["requirement_name"]}</b> — '
            f'<font color="{VERDICT_COLORS.get(r["verdict"], colors.black).hexval()}">'
            f'{VERDICT_LABELS.get(r["verdict"], r["verdict"])}</font> '
            f'(confidence {r["confidence"]:.2f})', normal))
        story.append(Paragraph(r["reason"], small))
        story.append(Spacer(1, 4))

    story.append(PageBreak())
    story.append(Paragraph("Important Limitations", h2))
    story.append(Paragraph(LIMITATION_TEXT, normal))
    story.append(Spacer(1, 10))
    story.append(Paragraph(
        "This report was generated automatically by VeriPack and reflects the rule version and "
        "AI/OCR pipeline versions recorded above. Historical reports remain reproducible even if "
        "the regulatory rule set is later updated.", small))

    doc.build(story)

    with get_db() as cur:
        cur.execute(
            "INSERT INTO report (compliance_check_id, file_path, generated_by) VALUES (?,?,?)",
            (check_id, file_path, generated_by),
        )

    return file_path
