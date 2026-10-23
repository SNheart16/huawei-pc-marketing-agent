"""Start the integrated local demo; startup never calls a model or loads .env files."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import runpy
import sys


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=7868)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    os.environ["KNOWLEDGE_SOURCE_MODE"] = "local"
    os.environ["USE_MOCK"] = "false"
    os.environ.setdefault("SYSTEM_PROMPT_PATH", str(ROOT / "prompts" / "system.md"))
    names = ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "LOCAL_KB_PATH",
             "SYSTEM_PROMPT_PATH", "KNOWLEDGE_SOURCE_MODE", "USE_MOCK")
    print(json.dumps({name: "OK" if os.environ.get(name) else "MISSING" for name in names}), flush=True)
    print(f"Real integration page: http://127.0.0.1:{args.port}/demo.html", flush=True)
    print("Configuration presence does not verify model connectivity. No automatic model calls.", flush=True)
    sys.path.insert(0, str(ROOT))
    sys.argv = [str(ROOT / "app.py"), "--port", str(args.port)]
    runpy.run_path(str(ROOT / "app.py"), run_name="__main__")


if __name__ == "__main__":
    main()
