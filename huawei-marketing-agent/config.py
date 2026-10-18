"""Environment-variable configuration scaffold; no secrets are hard-coded."""

import os
from typing import Dict, Optional


ENV_VARIABLES = (
    "IMA_OPENAPI_CLIENTID",
    "IMA_OPENAPI_APIKEY",
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "LLM_MODEL",
    "USE_MOCK",
    "LOCAL_KB_PATH",
    "KNOWLEDGE_SOURCE_MODE",
    "SYSTEM_PROMPT_PATH",
    "LLM_API_TYPE",
)


def load_config() -> Dict[str, Optional[str]]:
    """Return configured environment values, leaving unset values as None."""
    return {name: os.environ.get(name) for name in ENV_VARIABLES}
