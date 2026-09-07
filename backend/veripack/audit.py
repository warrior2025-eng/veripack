"""
Append-only audit logging.

There is deliberately no update_audit_log() or delete_audit_log() function
in this module -- PRD Part 25 requires audit records to be immutable. Every
significant state change in the system calls record() at the point the
change happens, not as an afterthought.
"""

from db.database import get_db, to_json


def record(actor_id, action: str, entity_type: str, entity_id=None,
           old_value=None, new_value=None, metadata=None):
    with get_db() as cur:
        cur.execute(
            """INSERT INTO audit_log (actor_id, action, entity_type, entity_id, old_value, new_value, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                actor_id,
                action,
                entity_type,
                entity_id,
                to_json(old_value) if old_value is not None else None,
                to_json(new_value) if new_value is not None else None,
                to_json(metadata) if metadata is not None else None,
            ),
        )


# Alias so calling code can read naturally as `audit.log(...)` at call sites
# that treat this module as a generic logging facility.
log = record
