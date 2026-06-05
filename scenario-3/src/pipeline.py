"""
Experiment 3 - pipeline.py
===========================

Thin wrapper. ALL real orchestration lives in `corp.py`. Keep this
shim only so older docs/scripts pointing at `pipeline.py` keep working.

For new code, prefer:

    from corp import Corp
    Corp().analyze_case(case)

or from a terminal:

    .\\.venv\\Scripts\\python.exe scenario-3\\src\\corp.py --all
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from corp import (  # noqa: E402,F401  -- re-exports for backwards compat
    Corp,
    load_chatmode_prompt,
    main,
    _try_parse_json,
)


if __name__ == "__main__":
    raise SystemExit(main())
