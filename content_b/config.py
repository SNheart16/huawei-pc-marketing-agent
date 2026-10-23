"""Load one explicit local configuration file, without shell evaluation or disclosure."""
import os
from pathlib import Path

ALLOWED = {"LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL", "LLM_API_TYPE", "IMAGE_BASE_URL", "IMAGE_API_KEY", "IMAGE_MODEL", "IMAGE_TIMEOUT", "CONTENT_DATA_DIR", "FACT_CHECK_FINAL_URL", "FACT_CHECK_API_KEY"}


def load_config(path):
    pairs = {}
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or key not in ALLOWED:
            raise ValueError("配置包含不支持的字段；值已隐藏。")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key in pairs:
            raise ValueError("配置字段重复；值已隐藏。")
        pairs[key] = value
    for key, value in pairs.items():
        if value:
            os.environ.setdefault(key, value)
