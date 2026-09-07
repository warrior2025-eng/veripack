"""
VeriPack backend entrypoint.

Run with:  python main.py
Serves the JSON API under /api/* and the server-rendered frontend (see
frontend/) under /. See README.md for full setup instructions.
"""

import logging
import os
import sys

from flask import Flask, jsonify, send_from_directory

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db.database import init_db, DB_PATH
from veripack.api import auth_routes, checks_routes, reviews_routes, rules_routes, dashboard_routes, audit_routes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("veripack")

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")


def create_app():
    app = Flask(
        __name__,
        static_folder=os.path.join(FRONTEND_DIR, "static"),
        static_url_path="/static",
    )
    app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024  # slightly above per-file limit, defense in depth

    # --- CORS -----------------------------------------------------------
    # Minimal same-origin-friendly CORS handling without an extra
    # dependency (flask-cors isn't installed and can't be fetched offline).
    allowed_origin = os.environ.get("VERIPACK_ALLOWED_ORIGIN", "*")

    @app.after_request
    def add_cors_headers(response):
        response.headers["Access-Control-Allow-Origin"] = allowed_origin
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        return response

    # --- Blueprints -------------------------------------------------------
    app.register_blueprint(auth_routes.bp)
    app.register_blueprint(checks_routes.bp)
    app.register_blueprint(reviews_routes.bp)
    app.register_blueprint(rules_routes.bp)
    app.register_blueprint(dashboard_routes.bp)
    app.register_blueprint(audit_routes.bp)

    # --- Error handling (never leak stack traces, PRD Part 35) -----------
    @app.errorhandler(404)
    def not_found(e):
        if _wants_json():
            return jsonify({"error": "NOT_FOUND"}), 404
        return send_from_directory(FRONTEND_DIR, "templates/index.html")

    @app.errorhandler(500)
    def server_error(e):
        logger.exception("Unhandled server error")
        return jsonify({"error": "INTERNAL_ERROR", "message": "An unexpected error occurred."}), 500

    def _wants_json():
        from flask import request
        return request.path.startswith("/api/")

    # --- Frontend (server-rendered, see docs/ARCHITECTURE.md for the
    # React-frontend swap-in note) -----------------------------------------
    @app.get("/")
    def index():
        return send_from_directory(FRONTEND_DIR, "templates/index.html")

    @app.get("/<path:page>")
    def spa_pages(page):
        # Any non-/api, non-/static path serves the single-page app shell;
        # client-side JS (frontend/static/js/app.js) handles routing.
        if page.startswith("api/") or page.startswith("static/"):
            return jsonify({"error": "NOT_FOUND"}), 404
        return send_from_directory(FRONTEND_DIR, "templates/index.html")

    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok", "db_path": DB_PATH})

    return app


if __name__ == "__main__":
    if not os.path.exists(DB_PATH):
        logger.info("No database found at %s -- initializing schema.", DB_PATH)
        init_db()
    app = create_app()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG", "0") == "1")
