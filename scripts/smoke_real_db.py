"""Manual smoke test against the real DB-IP Lite databases.

Not part of the test suite: it downloads ~62 MB and depends on DB-IP being
reachable, so it is a deliberate, on-demand check rather than something CI
runs. Verifies the download/decompress/install path and that real data maps
onto the ip2location field names callers expect.

    python scripts/smoke_real_db.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import GeoDatabases  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

data_dir = Path(os.environ.get("EVO_LOCATE_DATA_DIR", "data"))
db = GeoDatabases(data_dir)
db.refresh_all()
db.open_all()

print("ready:", db.ready, "present:", db.present())
for ip in ("8.8.8.8", "1.1.1.1", "2001:4860:4860::8888"):
    print(f"{ip} -> {json.dumps(db.lookup(ip))}")
