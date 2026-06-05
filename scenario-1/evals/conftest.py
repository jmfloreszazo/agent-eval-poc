import sys
from pathlib import Path

# Allow importing trajectory_loader without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Load .env at the repo root (LLM judge credentials, etc.) if present.
# evals/ -> scenario-1/ -> repo root
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except ImportError:
    pass
