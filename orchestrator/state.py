"""
Persist system state across restarts.
"""

import json
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

STATE_FILE = Path("./state.json")


def save_state(state: dict, path: Path = STATE_FILE):
    """Save state to disk."""
    # Convert non-serializable types
    serializable = {}
    for k, v in state.items():
        if isinstance(v, datetime):
            serializable[k] = v.isoformat()
        else:
            serializable[k] = v

    path.write_text(json.dumps(serializable, indent=2, default=str))
    logger.debug("State saved to %s", path)


def load_state(path: Path = STATE_FILE) -> dict:
    """Load state from disk, or return empty dict."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception as e:
        logger.warning("Failed to load state: %s", e)
        return {}
