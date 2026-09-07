"""
Test package bootstrap.

Sets environment variables that point every storage path (SQLite DB,
evidence images, PDF reports) at an isolated tests/_test_data/ directory
BEFORE any application module is imported -- db/database.py reads
VERIPACK_DB_PATH at import time, so this must run first. Python guarantees
this package's __init__.py runs before any tests.test_* submodule when the
suite is run with `python -m unittest discover`.
"""

import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_THIS_DIR)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

_TEST_DATA_DIR = os.path.join(_THIS_DIR, "_test_data")
os.environ.setdefault("VERIPACK_DB_PATH", os.path.join(_TEST_DATA_DIR, "test_veripack.db"))
os.environ.setdefault("VERIPACK_EVIDENCE_DIR", os.path.join(_TEST_DATA_DIR, "evidence"))
os.environ.setdefault("VERIPACK_REPORT_DIR", os.path.join(_TEST_DATA_DIR, "reports"))
os.environ.setdefault("VERIPACK_JWT_SECRET", "test-secret-not-for-production")

os.makedirs(_TEST_DATA_DIR, exist_ok=True)
os.makedirs(os.environ["VERIPACK_EVIDENCE_DIR"], exist_ok=True)
os.makedirs(os.environ["VERIPACK_REPORT_DIR"], exist_ok=True)
