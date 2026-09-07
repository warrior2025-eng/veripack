from flask import Blueprint, request, jsonify, g

from db.database import get_db, rows_to_list, from_json
from veripack.auth import require_auth, require_role

bp = Blueprint("audit_api", __name__, url_prefix="/api/audit-logs")


@bp.get("")
@require_auth
@require_role("ADMIN", "SENIOR_OFFICER")
def list_audit_logs():
    entity_type = request.args.get("entity_type")
    entity_id = request.args.get("entity_id")
    query = """SELECT al.*, u.name as actor_name FROM audit_log al
               LEFT JOIN user u ON u.id = al.actor_id WHERE 1=1"""
    params = []
    if entity_type:
        query += " AND al.entity_type = ?"
        params.append(entity_type)
    if entity_id:
        query += " AND al.entity_id = ?"
        params.append(entity_id)
    query += " ORDER BY al.timestamp DESC LIMIT 300"

    with get_db() as cur:
        cur.execute(query, params)
        logs = rows_to_list(cur.fetchall())

    for log in logs:
        log["old_value"] = from_json(log["old_value"])
        log["new_value"] = from_json(log["new_value"])
        log["metadata"] = from_json(log["metadata"])

    return jsonify({"audit_logs": logs})
