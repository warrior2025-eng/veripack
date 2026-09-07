from flask import Blueprint, request, jsonify, g

from db.database import get_db, row_to_dict
from veripack.auth import verify_password, issue_token, require_auth
from veripack import audit

bp = Blueprint("auth_api", __name__, url_prefix="/api/auth")


@bp.post("/login")
def login():
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    if not email or not password:
        return jsonify({"error": "VALIDATION_ERROR", "message": "email and password are required."}), 400

    with get_db() as cur:
        cur.execute("SELECT * FROM user WHERE email = ? AND active = 1", (email,))
        user = row_to_dict(cur.fetchone())

    if user is None or not verify_password(password, user["password_hash"]):
        return jsonify({"error": "INVALID_CREDENTIALS", "message": "Incorrect email or password."}), 401

    token = issue_token(user)
    audit.log(user["id"], "LOGIN", "user", user["id"])
    return jsonify({
        "token": token,
        "user": {"id": user["id"], "name": user["name"], "email": user["email"],
                  "role": user["role"], "organization_id": user["organization_id"]},
    })


@bp.get("/me")
@require_auth
def me():
    u = g.user
    return jsonify({"id": u["id"], "name": u["name"], "email": u["email"],
                     "role": u["role"], "organization_id": u["organization_id"]})
