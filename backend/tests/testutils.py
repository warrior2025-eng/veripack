"""Shared helpers for the VeriPack test suite."""

import os

from db import database as db_module
from db.database import init_db, get_db, to_json


def reset_db():
    """Drops the thread-local cached connection (if any) and recreates the
    schema from scratch. Needed because sqlite3 connections in this
    process would otherwise keep pointing at a deleted/recreated file
    handle across tests -- see db/database.py's threading.local() cache."""
    if hasattr(db_module._local, "conn"):
        try:
            db_module._local.conn.close()
        except Exception:
            pass
        del db_module._local.conn
    init_db(reset=True)


def make_user(email="test@veripack.demo", role="OFFICER", name="Test User", organization_id=1, password_hash="x"):
    with get_db() as cur:
        cur.execute("INSERT INTO organization (id, name, org_type) VALUES (1, 'Test Org', 'GOVERNMENT') "
                    "ON CONFLICT(id) DO NOTHING")
        cur.execute(
            "INSERT INTO user (name, email, password_hash, role, organization_id, active) VALUES (?,?,?,?,?,1)",
            (name, email, password_hash, role, organization_id),
        )
        return cur.lastrowid


def make_rule_version(category="PACKAGED_FOOD_FMCG", status="ACTIVE", effective_from="2020-01-01",
                       effective_to=None, version_label="1.0", locked=0):
    with get_db() as cur:
        cur.execute(
            """INSERT INTO rule_version
               (name, version_label, category, status, effective_from, effective_to,
                source_document, source_reference, locked)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (f"Test Rules {category}", version_label, category, status, effective_from, effective_to,
             "Test Source Document", "Test Reference", locked),
        )
        return cur.lastrowid


def make_requirement(rule_version_id, code="MANUFACTURER_NAME_ADDRESS", name="Manufacturer / Packer / Importer",
                      field_type="MANUFACTURER", applicability="ALL", validation_logic=None,
                      severity="HIGH", citation="Rule 6(1)(a), PC Rules 2011"):
    validation_logic = validation_logic or {"type": "presence"}
    with get_db() as cur:
        cur.execute(
            """INSERT INTO rule_requirement
               (rule_version_id, requirement_code, requirement_name, field_type,
                applicability_logic, validation_logic, severity, source_citation, enabled)
               VALUES (?,?,?,?,?,?,?,?,1)""",
            (rule_version_id, code, name, field_type, applicability, to_json(validation_logic), severity, citation),
        )
        return cur.lastrowid


def make_field(field_type, raw_text, normalized_value, confidence, bbox=None, script="LATIN"):
    """Builds an in-memory extracted-field dict shaped like extraction.py's
    output, for feeding directly into rules_engine.evaluate_check() without
    needing a full OCR pass in a unit test."""
    return {
        "field_type": field_type,
        "raw_text": raw_text,
        "normalized_value": normalized_value,
        "confidence": confidence,
        "bounding_box": bbox or [10, 10, 200, 20],
        "source": "OCR",
        "script": script,
    }


GOOD_QUALITY = {"score": 1.0, "issues": [], "usable": True,
                "raw": {"blur_variance": 500, "glare_ratio": 0.0, "curvature_estimate": 0.0, "width": 800, "height": 600}}
POOR_QUALITY = {"score": 0.15, "issues": ["BLURRY", "LOW_RESOLUTION"], "usable": False,
                "raw": {"blur_variance": 10, "glare_ratio": 0.0, "curvature_estimate": 0.0, "width": 200, "height": 150}}
CURVED_QUALITY = {"score": 0.5, "issues": ["CURVED_SURFACE"], "usable": True,
                   "raw": {"blur_variance": 200, "glare_ratio": 0.01, "curvature_estimate": 0.5, "width": 800, "height": 600}}
