"""Report whether expected environment variables are present, without values."""

import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import ENV_VARIABLES


def main() -> None:
    for name in ENV_VARIABLES:
        status = "OK" if os.environ.get(name) is not None else "MISSING"
        print(f"{name}: {status}")


if __name__ == "__main__":
    main()
