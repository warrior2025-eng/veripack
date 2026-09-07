"""
Authentication and role-based access control.

Password hashing uses werkzeug.security (PBKDF2-SHA256), which ships with
Flask, instead of bcrypt/passlib -- those require a C extension wheel that
cannot be downloaded in this offline sandbox. PBKDF2-SHA256 with werkzeug's
default iteration count is an acceptable, real password hash (not a toy);
swapping to bcrypt later is a one-line change in `hash_password` /
`verify_password` if the target environment has network access to install it.

JWTs are signed with HS256 using a server-side secret from the environment.
"""

import os
import time
from functools import wraps

import jwt
from flask import request, jsonify, g
from werkzeug.security import generate_password_hash, check_password_hash

from db.database import get_db, row_to_dict

JWT_SECRET = os.environ.get("VERIPACK_JWT_SECRET", "dev-secret-change-me-in-production")
JWT_ALGO = "HS256"
JWT_EXPIRY_SECONDS = 60 * 60 * 8  # 8 hour shift-length session

ROLE_HIERARCHY_NOTE = """
MVP implements ADMIN and OFFICER fully. SENIOR_OFFICER, MANUFACTURER and
MARKETPLACE_AUDITOR roles exist in the schema/permission map so the
architecture does not need to change when those personas are built out
(PRD Part 11.20) -- they are not exercised by the seeded demo users.
"""


def hash_password(plain: str) -> str:
    return generate_password_hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return check_password_hash(hashed, plain)


def issue_token(user: dict) -> str:
    payload = {
        "sub": user["id"],
        "email": user["email"],
        "role": user["role"],
        "organization_id": user["organization_id"],
        "iat": int(time.time()),
        "exp": int(time.time()) + JWT_EXPIRY_SECONDS,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def decode_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])


def get_current_user_from_request():
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1]
    else:
        # Fallback for requests that cannot set a custom header -- e.g. an
        # <img src="..."> tag loading an evidence image directly in the
        # browser. The frontend passes the token as a `t` query parameter
        # in that one case (see api.js's evidenceImageUrl); this is the
        # backend half of that, which was previously missing entirely --
        # the query param was being sent but never actually checked here,
        # so every <img> evidence load silently failed with 401.
        token = request.args.get("t", "")
        if not token:
            return None
    try:
        payload = decode_token(token)
    except jwt.PyJWTError:
        return None
    with get_db() as cur:
        cur.execute("SELECT * FROM user WHERE id = ? AND active = 1", (payload["sub"],))
        user = row_to_dict(cur.fetchone())
    return user

def require_auth(fn):
    """Populate g.user or return 401. Every protected route uses this --
    permissions are enforced server-side, never only hidden in the UI."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = get_current_user_from_request()
        if user is None:
            return jsonify({"error": "UNAUTHORIZED", "message": "Valid Bearer token required."}), 401
        g.user = user
        return fn(*args, **kwargs)

    return wrapper


def require_role(*allowed_roles):
    """Stack after @require_auth. Admin implicitly passes every role check
    (Admin = superset of Officer functionality per PRD 11.20)."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if g.user["role"] != "ADMIN" and g.user["role"] not in allowed_roles:
                return jsonify({
                    "error": "FORBIDDEN",
                    "message": f"Role '{g.user['role']}' cannot perform this action."
                }), 403
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def organization_scoped_filter(user: dict):
    """Manufacturer / marketplace-auditor users may only see data belonging
    to their own organization (PRD 11.20, 11.22). Officers and Admins see
    everything (state-wide enforcement view). Returns an organization_id to
    filter by, or None meaning 'no restriction'."""
    if user["role"] in ("MANUFACTURER", "MARKETPLACE_AUDITOR"):
        return user["organization_id"]
    return None
