"""
Seed script (PRD Part 48).

Run with:  python -m seed.seed_data

Creates:
  - 2 organizations (a government enforcement org, a manufacturer org)
  - 2 users: admin@veripack.demo / officer@veripack.demo (dev-only creds,
    documented in README.md, NOT meant for any real deployment)
  - 2 RuleVersions for PACKAGED_FOOD_FMCG (one RETIRED historical, one
    ACTIVE current) + 1 RuleVersion for COSMETICS (ACTIVE), each with real
    requirement rows carrying source citations
  - 3 compliance checks, run through the REAL pipeline (OCR -> extraction
    -> rule engine -> evidence) against synthetic demo label images -- not
    fabricated result rows. See seed/generate_demo_images.py for why the
    images are synthetic.
"""

import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import init_db, get_db, to_json
from veripack.auth import hash_password
from veripack.pipeline.pipeline import run_pipeline
from seed.generate_demo_images import generate_all

TODAY = date.today().isoformat()
HISTORICAL_FROM = (date.today() - timedelta(days=730)).isoformat()
HISTORICAL_TO = (date.today() - timedelta(days=365)).isoformat()
CURRENT_FROM = (date.today() - timedelta(days=365)).isoformat()


def _insert_org(cur, name, org_type):
    cur.execute("INSERT INTO organization (name, org_type) VALUES (?,?)", (name, org_type))
    return cur.lastrowid


def _insert_user(cur, name, email, password, role, org_id):
    cur.execute(
        "INSERT INTO user (name, email, password_hash, role, organization_id) VALUES (?,?,?,?,?)",
        (name, email, hash_password(password), role, org_id),
    )
    return cur.lastrowid


def _insert_rule_version(cur, name, version_label, category, status, effective_from, effective_to,
                          source_document, source_reference, created_by):
    cur.execute(
        """INSERT INTO rule_version
           (name, version_label, category, status, effective_from, effective_to,
            source_document, source_reference, created_by, locked)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (name, version_label, category, status, effective_from, effective_to,
         source_document, source_reference, created_by, 1 if status == "RETIRED" else 0),
    )
    return cur.lastrowid


def _insert_requirement(cur, rule_version_id, code, name, field_type, applicability,
                         validation_logic: dict, severity, citation):
    cur.execute(
        """INSERT INTO rule_requirement
           (rule_version_id, requirement_code, requirement_name, description, field_type,
            applicability_logic, validation_logic, severity, source_citation, enabled)
           VALUES (?,?,?,?,?,?,?,?,?,1)""",
        (rule_version_id, code, name, None, field_type, applicability,
         to_json(validation_logic), severity, citation),
    )


FOOD_SOURCE_DOC = "Legal Metrology (Packaged Commodities) Rules, 2011 (as amended through 2025)"
COSMETICS_SOURCE_DOC = "Legal Metrology (Packaged Commodities) Rules, 2011 (as amended through 2025)"


def seed_rule_requirements(cur, rule_version_id, category, include_best_before, qualified_manufacturer):
    _insert_requirement(cur, rule_version_id, "MANUFACTURER_NAME_ADDRESS",
                         "Manufacturer / Packer / Importer name & address", "MANUFACTURER", "ALL",
                         {"type": "qualified_presence" if qualified_manufacturer else "presence"},
                         "HIGH", "Rule 6(1)(a), PC Rules 2011")
    _insert_requirement(cur, rule_version_id, "GENERIC_NAME",
                         "Generic / common name of commodity", "GENERIC_NAME", "ALL",
                         {"type": "presence"}, "MEDIUM", "Rule 6(1)(b), PC Rules 2011")
    _insert_requirement(cur, rule_version_id, "NET_QUANTITY",
                         "Net quantity declaration (value + unit)", "NET_QUANTITY", "ALL",
                         {"type": "format", "requires": ["value", "unit"]},
                         "HIGH", "Rule 6(1)(c), PC Rules 2011 & Sixth Schedule (format only; "
                                  "physical accuracy requires metrological weighing)")
    _insert_requirement(cur, rule_version_id, "MRP",
                         "Maximum Retail Price (inclusive of all taxes)", "MRP", "ALL",
                         {"type": "format", "requires": ["value", "currency"]},
                         "HIGH", "Rule 6(1)(e) & Rule 18, PC Rules 2011")
    _insert_requirement(cur, rule_version_id, "MFG_DATE",
                         "Manufacturing / packing date", "MFG_DATE", "ALL",
                         {"type": "presence"}, "MEDIUM", "Rule 6(1)(f) area, PC Rules 2011")
    if include_best_before:
        _insert_requirement(cur, rule_version_id, "BEST_BEFORE",
                             "Best-before / use-by date", "BEST_BEFORE", "ALL",
                             {"type": "presence"}, "MEDIUM",
                             "PC Rules provision for shelf-life-limited commodities "
                             "(category-dependent; applied for Packaged Food/FMCG in MVP)")
    _insert_requirement(cur, rule_version_id, "CONSUMER_CARE",
                         "Consumer care / grievance contact details", "CONSUMER_CARE", "ALL",
                         {"type": "presence"}, "MEDIUM", "Rule 6 area, PC Rules 2011")
    _insert_requirement(cur, rule_version_id, "COUNTRY_OF_ORIGIN",
                         "Country of origin (imported products only)", "COUNTRY_OF_ORIGIN",
                         "IMPORTED_ONLY", {"type": "presence"}, "MEDIUM",
                         "Rule 6 (imported packages), PC Rules 2011")
    _insert_requirement(cur, rule_version_id, "NUMERAL_HEIGHT",
                         "Numeral/letter height of declarations", "MRP", "ALL",
                         {"type": "visual_geometric"}, "LOW",
                         "Rule 7, PC Rules 2011 (heuristic relative estimate only -- "
                         "not a certified millimetre measurement, see docs/AI_PIPELINE.md)")


def run():
    init_db(reset=True)

    with get_db() as cur:
        gov_org = _insert_org(cur, "Directorate of Legal Metrology (Demo State)", "GOVERNMENT")
        mfr_org = _insert_org(cur, "Demo Manufacturer Org", "MANUFACTURER")

        admin_id = _insert_user(cur, "VeriPack Admin", "admin@veripack.demo", "ChangeMe123!", "ADMIN", gov_org)
        officer_id = _insert_user(cur, "Inspector Rina", "officer@veripack.demo", "ChangeMe123!", "OFFICER", gov_org)

        # --- Historical (RETIRED) rule version: simpler manufacturer check ---
        old_food_rv = _insert_rule_version(
            cur, "PC Rules 2011 - Food/FMCG", "1.0", "PACKAGED_FOOD_FMCG", "RETIRED",
            HISTORICAL_FROM, HISTORICAL_TO, FOOD_SOURCE_DOC,
            "Baseline PC Rules 2011 declarations", admin_id)
        seed_rule_requirements(cur, old_food_rv, "PACKAGED_FOOD_FMCG",
                                include_best_before=True, qualified_manufacturer=False)

        # --- Current (ACTIVE) rule version: manufacturer qualifier now checked ---
        current_food_rv = _insert_rule_version(
            cur, "PC Rules 2011 (as amended 2023/2025) - Food/FMCG", "1.1", "PACKAGED_FOOD_FMCG", "ACTIVE",
            CURRENT_FROM, None, FOOD_SOURCE_DOC,
            "Incorporates Rule 6/26 clarifications from the 2023 & 2025 amendments", admin_id)
        seed_rule_requirements(cur, current_food_rv, "PACKAGED_FOOD_FMCG",
                                include_best_before=True, qualified_manufacturer=True)

        current_cosmetics_rv = _insert_rule_version(
            cur, "PC Rules 2011 (as amended) - Cosmetics", "1.0", "COSMETICS", "ACTIVE",
            CURRENT_FROM, None, COSMETICS_SOURCE_DOC,
            "Cosmetics category does not carry a general best-before mandate in MVP rule table",
            admin_id)
        seed_rule_requirements(cur, current_cosmetics_rv, "COSMETICS",
                                include_best_before=False, qualified_manufacturer=True)

    # --- Demo images + real pipeline runs ---------------------------------
    images = generate_all("storage/uploads/demo")
    demo_checks = []

    for scenario_key, image_path, product_name in [
        ("compliant", images["compliant"], "XYZ Foods Crunchy Wheat Biscuits (Demo)"),
        ("missing_declaration", images["missing_declaration"], "Rivera Snacks Spicy Corn Puffs (Demo)"),
        ("difficult", images["difficult"], "Mountain Fresh Herbal Face Cream (Demo)"),
    ]:
        with get_db() as cur:
            cur.execute("INSERT INTO product (name, organization_id) VALUES (?,?)", (product_name, gov_org))
            product_id = cur.lastrowid
            cur.execute(
                "INSERT INTO product_image (product_id, file_path, source, uploaded_by) VALUES (?,?,'DEMO',?)",
                (product_id, image_path, officer_id))
            product_image_id = cur.lastrowid
            cur.execute(
                """INSERT INTO compliance_check
                   (product_id, product_image_id, submitted_by, organization_id, status, audit_date)
                   VALUES (?,?,?,?,'QUEUED',?)""",
                (product_id, product_image_id, officer_id, gov_org, TODAY))
            check_id = cur.lastrowid

        result = run_pipeline(check_id)
        demo_checks.append((scenario_key, check_id, result))
        print(f"  seeded demo check [{scenario_key}] -> check_id={check_id} -> {result.get('status')}")

    print("\nSeed complete.")
    print("Login credentials (development only -- change before any real deployment):")
    print("  Admin:   admin@veripack.demo   / ChangeMe123!")
    print("  Officer: officer@veripack.demo / ChangeMe123!")
    print(f"\nDemo compliance_check IDs: {[c[1] for c in demo_checks]}")


if __name__ == "__main__":
    run()
