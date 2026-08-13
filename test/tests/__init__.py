# Package marker for the tests directory.
#
# sys.path shim: the suite may be launched either from the repo root
# (`python -m unittest discover -s test/tests`) or from inside `test/`
# (`python -m unittest discover -s tests`). In the latter case the repo
# root is not on sys.path, so imports of the `scripts.*` packages would
# fail with ModuleNotFoundError. Inserting the repo root here makes both
# invocation styles work identically.
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
