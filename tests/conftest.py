"""pytest config: expose the project root on sys.path.

The project is a flat-layout collection of top-level modules (monitor.py,
database.py, etc.), not a package, so pytest needs help finding them. This
avoids having to install the project as editable just to run tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
