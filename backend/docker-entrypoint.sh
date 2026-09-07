#!/bin/sh
# Initializes the SQLite schema (and, only on a genuinely empty database,
# seeds demo data) before handing off to whatever CMD was given -- so a
# fresh `docker run` of this image is immediately demoable, matching the
# "clone, configure, run" acceptance criteria in the project brief.
set -e

DB_PATH="${VERIPACK_DB_PATH:-storage/veripack.db}"

if [ ! -f "$DB_PATH" ]; then
    echo "No database found at $DB_PATH -- initializing and seeding demo data..."
    python -c "from db.database import init_db; init_db()"
    python -m seed.seed_data || echo "Seed step failed or already applied -- continuing."
fi

exec "$@"
