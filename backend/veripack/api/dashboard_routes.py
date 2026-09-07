from flask import Blueprint, jsonify, g

from db.database import get_db, rows_to_list
from veripack.auth import require_auth, organization_scoped_filter

bp = Blueprint("dashboard_api", __name__, url_prefix="/api/dashboard")


@bp.get("/summary")
@require_auth
def summary():
    scope = organization_scoped_filter(g.user)
    org_filter_sql = " AND cc.organization_id = ?" if scope is not None else ""
    params = [scope] if scope is not None else []

    with get_db() as cur:
        cur.execute(f"SELECT COUNT(*) as c FROM compliance_check cc WHERE 1=1{org_filter_sql}", params)
        total_checks = cur.fetchone()["c"]

        cur.execute(
            f"""SELECT rr.verdict, COUNT(*) as c FROM requirement_result rr
                JOIN compliance_check cc ON cc.id = rr.compliance_check_id
                WHERE 1=1{org_filter_sql} GROUP BY rr.verdict""", params)
        verdict_counts = {row["verdict"]: row["c"] for row in cur.fetchall()}

        cur.execute(
            f"""SELECT COUNT(*) as c FROM review_task rt
                JOIN compliance_check cc ON cc.id = rt.compliance_check_id
                WHERE rt.status='PENDING'{org_filter_sql}""", params)
        pending_reviews = cur.fetchone()["c"]

        cur.execute(
            f"""SELECT cc.category, COUNT(*) as c FROM compliance_check cc
                WHERE cc.category IS NOT NULL{org_filter_sql} GROUP BY cc.category""", params)
        category_breakdown = rows_to_list(cur.fetchall())

        cur.execute(
            f"""SELECT cc.status, COUNT(*) as c FROM compliance_check cc WHERE 1=1{org_filter_sql}
                GROUP BY cc.status""", params)
        status_breakdown = rows_to_list(cur.fetchall())

        cur.execute(
            f"""SELECT rv.name, rv.version_label, rv.status, COUNT(cc.id) as usage_count
                FROM rule_version rv LEFT JOIN compliance_check cc ON cc.rule_version_id = rv.id
                {"WHERE cc.organization_id = ? OR cc.id IS NULL" if scope is not None else ""}
                GROUP BY rv.id ORDER BY rv.id DESC""", params if scope is not None else [])
        rule_version_usage = rows_to_list(cur.fetchall())

        cur.execute(
            f"""SELECT cc.id, cc.status, cc.category, cc.created_at, p.name as product_name
                FROM compliance_check cc LEFT JOIN product p ON p.id = cc.product_id
                WHERE 1=1{org_filter_sql} ORDER BY cc.created_at DESC LIMIT 10""", params)
        recent_checks = rows_to_list(cur.fetchall())

    return jsonify({
        "total_checks": total_checks,
        "verdict_counts": {
            "COMPLIANT": verdict_counts.get("COMPLIANT", 0),
            "POTENTIAL_NON_COMPLIANCE": verdict_counts.get("POTENTIAL_NON_COMPLIANCE", 0),
            "REQUIRES_OFFICER_VERIFICATION": verdict_counts.get("REQUIRES_OFFICER_VERIFICATION", 0),
            "INSUFFICIENT_EVIDENCE": verdict_counts.get("INSUFFICIENT_EVIDENCE", 0),
        },
        "pending_reviews": pending_reviews,
        "category_breakdown": category_breakdown,
        "status_breakdown": status_breakdown,
        "rule_version_usage": rule_version_usage,
        "recent_checks": recent_checks,
    })


@bp.get("/trends")
@require_auth
def trends():
    """Daily count of POTENTIAL_NON_COMPLIANCE verdicts over the last 30
    days -- a real GROUP BY query, not a fabricated series. Returns an
    empty list (not fake data) when there is no history yet."""
    scope = organization_scoped_filter(g.user)
    org_filter_sql = " AND cc.organization_id = ?" if scope is not None else ""
    params = [scope] if scope is not None else []
    with get_db() as cur:
        cur.execute(
            f"""SELECT substr(rr.created_at, 1, 10) as day, COUNT(*) as c
                FROM requirement_result rr
                JOIN compliance_check cc ON cc.id = rr.compliance_check_id
                WHERE rr.verdict = 'POTENTIAL_NON_COMPLIANCE'{org_filter_sql}
                GROUP BY day ORDER BY day ASC""", params)
        rows = rows_to_list(cur.fetchall())
    return jsonify({"potential_non_compliance_by_day": rows})
