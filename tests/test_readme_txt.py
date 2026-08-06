# Evomedia.net evo.locate — https://github.com/kellymichels/evo.locate
# Created by Kelly Michels · dev@evomedia.net
# Licensed under the MIT License. See LICENSE.

"""README.txt is generated from README.md; committing one without
regenerating the other ships a stale mirror. The script's --check mode is
the single source of truth for "in sync", so the test just runs it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_readme_txt_is_in_sync_with_readme_md():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "readme_txt.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
