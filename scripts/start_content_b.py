"""Local launcher: credentials remain outside source and are never printed."""
import argparse
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from content_b.config import load_config

parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, default=7861)
parser.add_argument("--config", default=str(ROOT / ".env.content.local"))
args = parser.parse_args()
config = Path(args.config)
if config.is_file():
    try:
        load_config(config)
    except (OSError, ValueError):
        raise SystemExit("本地配置无法加载，请检查配置字段与文件权限；详情已隐藏。") from None
    print("B local configuration loaded; credential values withheld.")
sys.argv = [str(ROOT / "app.py"), "--port", str(args.port)]
runpy.run_path(str(ROOT / "app.py"), run_name="__main__")
