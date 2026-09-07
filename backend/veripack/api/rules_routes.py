"""
Admin Regulatory Rule Engine API (PRD Part 14).

Lifecycle: DRAFT -> REVIEW -> ACTIVE -> RETIRED.

A rule_version is locked (immutable) the first moment any compliance_check
references it, so historical checks always keep citing the exact rule text
that was active when they ran (PRD Part 47). `_is_locked` below always
computes this live from compliance_check, rather than trusting the cached
rule_version.locked column, so the check is correct even if a
compliance_check was written by a path that didn't explicitly update that
column -- the cached column is a read optimization for the list view
(`_sync_locks`), never the source of truth for a mutation decision.
"""

from flask import Blueprint, request, jsonify, g

from db.database import get_db, row_to_dict, rows_to_list, to_json
from veripack.auth import require_auth, require_role
from veripack import audit

bp = Blueprint("rules_api", __name__, url_prefix="/api/rules")


def _is_locked(cur, rule_version_id: int) -> bool:
    """Live, authoritative check: a rule_version is locked the moment any
    compliance_check references it. Queried directly with the caller's
    cursor (never trusting the cached `locked` column alone, and never
    opening a second nested connection context), and self-heals that
    cached column in the same statement so later cheap reads (the list
    view) stay accurate too."""
    cur.execute("SELECT COUNT(*) as c FROM compliance_check WHERE rule_version_id=?", (rule_version_id,))
    in_use = cur.fetchone()["c"] > 0
    if in_use:
        cur.execute("UPDATE rule_version SET locked=1 WHERE id=? AND locked=0", (rule_version_id,))
    return in_use


@bp.get("")
@require_auth
def list_rule_versions():
    category = request.args.get("category")
    with get_db() as cur:
        _sync_locks(cur)
        if category:
            cur.execute(
                """SELECT rv.*, (SELECT COUNT(*) FROM rule_requirement req WHERE req.rule_version_id = rv.id) as requirement_count
                   FROM rule_version rv WHERE category=? ORDER BY rv.id DESC""", (category,))
        else:
            cur.execute(
                """SELECT rv.*, (SELECT COUNT(*) FROM rule_requirement req WHERE req.rule_version_id = rv.id) as requirement_count
                   FROM rule_version rv ORDER BY rv.id DESC""")
        versions = rows_to_list(cur.fetchall())
    return jsonify({"rule_versions": versions})


def _sync_locks(cur):
    cur.execute(
        """UPDATE rule_version SET locked = 1
           WHERE id IN (SELECT DISTINCT rule_version_id FROM compliance_check WHERE rule_version_id IS NOT NULL)
             AND locked = 0""")


@bp.get("/<int:rule_version_id>")
@require_auth
def get_rule_version(rule_version_id):
    with get_db() as cur:
        cur.execute("SELECT * FROM rule_version WHERE id=?", (rule_version_id,))
        version = row_to_dict(cur.fetchone())
        if version is None:
            return jsonify({"error": "NOT_FOUND"}), 404
        cur.execute("SELECT * FROM rule_requirement WHERE rule_version_id=? ORDER BY id", (rule_version_id,))
        requirements = rows_to_list(cur.fetchall())
    return jsonify({"rule_version": version, "requirements": requirements})


@bp.post("")
@require_auth
@require_role("ADMIN")
def create_rule_version():
    body = request.get_json(silent=True) or {}
    required = ["name", "version_label", "category", "source_document"]
    missing = [f for f in required if not body.get(f)]
    if missing:
        return jsonify({"error": "VALIDATION_ERROR", "message": f"Missing fields: {missing}"}), 400

    with get_db() as cur:
        cur.execute(
            """INSERT INTO rule_version (name, version_label, category, status, source_document,
                                          source_reference, created_by)
               VALUES (?,?,?, 'DRAFT', ?, ?, ?)""",
            (body["name"], body["version_label"], body["category"], body["source_document"],
             body.get("source_reference"), g.user["id"]),
        )
        rule_version_id = cur.lastrowid

    audit.log(g.user["id"], "RULE_VERSION_CREATED", "rule_version", rule_version_id, new_value=body)
    return jsonify({"id": rule_version_id, "status": "DRAFT"}), 201


@bp.post("/<int:rule_version_id>/duplicate")
@require_auth
@require_role("ADMIN")
def duplicate_rule_version(rule_version_id):
    """The realistic way an admin updates the law: duplicate the active
    version, edit the draft copy, then activate it. The old version is
    untouched and stays cited by every historical check."""
    with get_db() as cur:
        cur.execute("SELECT * FROM rule_version WHERE id=?", (rule_version_id,))
        source = row_to_dict(cur.fetchone())
        if source is None:
            return jsonify({"error": "NOT_FOUND"}), 404

        body = request.get_json(silent=True) or {}
        new_label = body.get("version_label") or f"{source['version_label']}-copy"

        cur.execute(
            """INSERT INTO rule_version (name, version_label, category, status, source_document,
                                          source_reference, created_by)
               VALUES (?,?,?, 'DRAFT', ?, ?, ?)""",
            (source["name"], new_label, source["category"], source["source_document"],
             source["source_reference"], g.user["id"]),
        )
        new_id = cur.lastrowid

        cur.execute("SELECT * FROM rule_requirement WHERE rule_version_id=?", (rule_version_id,))
        for req in rows_to_list(cur.fetchall()):
            cur.execute(
                """INSERT INTO rule_requirement
                   (rule_version_id, requirement_code, requirement_name, description, field_type,
                    applicability_logic, validation_logic, severity, source_citation, enabled)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (new_id, req["requirement_code"], req["requirement_name"], req["description"],
                 req["field_type"], req["applicability_logic"], req["validation_logic"],
                 req["severity"], req["source_citation"], req["enabled"]),
            )

    audit.log(g.user["id"], "RULE_VERSION_DUPLICATED", "rule_version", new_id,
              metadata={"source_rule_version_id": rule_version_id})
    return jsonify({"id": new_id, "status": "DRAFT"}), 201


@bp.put("/<int:rule_version_id>")
@require_auth
@require_role("ADMIN")
def update_rule_version(rule_version_id):
    body = request.get_json(silent=True) or {}
    with get_db() as cur:
        if _is_locked(cur, rule_version_id):
            return jsonify({
                "error": "RULE_VERSION_LOCKED",
                "message": "This rule version has already been used by at least one compliance check "
                           "and cannot be edited. Duplicate it into a new draft instead."
            }), 409

        cur.execute("SELECT * FROM rule_version WHERE id=?", (rule_version_id,))
        existing = row_to_dict(cur.fetchone())
        if existing is None:
            return jsonify({"error": "NOT_FOUND"}), 404
        if existing["status"] not in ("DRAFT", "REVIEW"):
            return jsonify({"error": "INVALID_STATE",
                             "message": "Only DRAFT or REVIEW rule versions can be edited."}), 409

        fields = ["name", "version_label", "effective_from", "effective_to",
                  "source_document", "source_reference", "status"]
        updates = {f: body[f] for f in fields if f in body}
        if updates.get("status") not in (None, "DRAFT", "REVIEW"):
            return jsonify({"error": "VALIDATION_ERROR",
                             "message": "Use POST /activate to move a version to ACTIVE."}), 400

        if updates:
            set_clause = ", ".join(f"{k}=?" for k in updates)
            cur.execute(f"UPDATE rule_version SET {set_clause} WHERE id=?",
                        (*updates.values(), rule_version_id))

    audit.log(g.user["id"], "RULE_VERSION_UPDATED", "rule_version", rule_version_id,
              old_value=existing, new_value=updates)
    return jsonify({"status": "UPDATED"})


@bp.post("/<int:rule_version_id>/requirements")
@require_auth
@require_role("ADMIN")
def add_requirement(rule_version_id):
    body = request.get_json(silent=True) or {}
    required = ["requirement_code", "requirement_name", "field_type", "validation_logic", "source_citation"]
    missing = [f for f in required if not body.get(f)]
    if missing:
        return jsonify({"error": "VALIDATION_ERROR", "message": f"Missing fields: {missing}"}), 400

    with get_db() as cur:
        if _is_locked(cur, rule_version_id):
            return jsonify({"error": "RULE_VERSION_LOCKED",
                             "message": "Duplicate this rule version to add requirements."}), 409
        validation_logic = body["validation_logic"]
        if not isinstance(validation_logic, str):
            validation_logic = to_json(validation_logic)
        cur.execute(
            """INSERT INTO rule_requirement
               (rule_version_id, requirement_code, requirement_name, description, field_type,
                applicability_logic, validation_logic, severity, source_citation, enabled)
               VALUES (?,?,?,?,?,?,?,?,?,1)""",
            (rule_version_id, body["requirement_code"], body["requirement_name"],
             body.get("description"), body["field_type"], body.get("applicability_logic", "ALL"),
             validation_logic, body.get("severity", "MEDIUM"), body["source_citation"]),
        )
        requirement_id = cur.lastrowid

    audit.log(g.user["id"], "RULE_REQUIREMENT_ADDED", "rule_requirement", requirement_id,
              metadata={"rule_version_id": rule_version_id})
    return jsonify({"id": requirement_id}), 201


@bp.post("/<int:rule_version_id>/activate")
@require_auth
@require_role("ADMIN")
def activate_rule_version(rule_version_id):
    body = request.get_json(silent=True) or {}
    effective_from = body.get("effective_from")
    if not effective_from:
        return jsonify({"error": "VALIDATION_ERROR", "message": "effective_from (ISO date) is required."}), 400

    with get_db() as cur:
        cur.execute("SELECT * FROM rule_version WHERE id=?", (rule_version_id,))
        version = row_to_dict(cur.fetchone())
        if version is None:
            return jsonify({"error": "NOT_FOUND"}), 404
        cur.execute("SELECT COUNT(*) as c FROM rule_requirement WHERE rule_version_id=? AND enabled=1",
                    (rule_version_id,))
        if cur.fetchone()["c"] == 0:
            return jsonify({"error": "VALIDATION_ERROR",
                             "message": "Cannot activate a rule version with zero requirements."}), 400

        # Retire the currently-active version for this category, effective
        # exactly when the new one starts -- this is what makes "the law
        # changed without redeploying code" demonstrable and reproducible.
        cur.execute(
            "SELECT * FROM rule_version WHERE category=? AND status='ACTIVE'", (version["category"],))
        currently_active = row_to_dict(cur.fetchone())
        if currently_active:
            cur.execute(
                "UPDATE rule_version SET status='RETIRED', effective_to=? WHERE id=?",
                (effective_from, currently_active["id"]),
            )

        cur.execute(
            "UPDATE rule_version SET status='ACTIVE', effective_from=? WHERE id=?",
            (effective_from, rule_version_id),
        )

    audit.log(g.user["id"], "RULE_VERSION_ACTIVATED", "rule_version", rule_version_id,
              old_value={"previously_active_id": currently_active["id"] if currently_active else None},
              new_value={"effective_from": effective_from})
    return jsonify({"status": "ACTIVE", "effective_from": effective_from})
