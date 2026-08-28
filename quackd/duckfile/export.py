"""`python -m quackd.duckfile.export` regenerates `schema.json` from the pydantic model.

The JSON file is committed so editors and other languages can validate `.duck` files
without importing quackd; a test asserts it never drifts from the model.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from quackd.duckfile.schema import json_schema

SCHEMA_PATH = Path(__file__).with_name("schema.json")


def write_schema(path: Path = SCHEMA_PATH) -> Path:
    path.write_text(json.dumps(json_schema(), indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


if __name__ == "__main__":
    out = write_schema(Path(sys.argv[1]) if len(sys.argv) > 1 else SCHEMA_PATH)
    sys.stdout.write(f"wrote {out}\n")
