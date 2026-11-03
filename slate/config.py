import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

ROOT = Path(__file__).resolve().parent.parent


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


INFERENCE_BASE_URL = env("VULTR_INFERENCE_BASE_URL", "https://api.vultrinference.com/v1")
INFERENCE_API_KEY = env("VULTR_INFERENCE_API_KEY")
PLANNER_MODEL = env("SLATE_PLANNER_MODEL", "glm-5.3")
VERIFIER_MODEL = env("SLATE_VERIFIER_MODEL", "qwen3.8-flash-next")
SAFETY_MODEL = env("SLATE_SAFETY_MODEL", "nemotron-3.5-content-safety")
LLM_MODE = env("SLATE_LLM", "vultr" if INFERENCE_API_KEY else "mock")
SANDBOX = env("SLATE_SANDBOX", "local")
PROXY_PORT = int(env("SLATE_PROXY_PORT", "8899"))
DATA_DIR = Path(env("SLATE_DATA_DIR", str(ROOT / "data")))
ALLOWLIST = [h.strip().lower() for h in env(
    "SLATE_ALLOWLIST", "127.0.0.1,localhost").split(",") if h.strip()]
TASK_TIMEOUT_S = int(env("SLATE_TASK_TIMEOUT_S", "240"))
VENDOR_BASE = env("SLATE_VENDOR_BASE", "")  # e.g. http://127.0.0.1:8000/vendors for local dev

DATA_DIR.mkdir(parents=True, exist_ok=True)
(DATA_DIR / "screens").mkdir(exist_ok=True)
