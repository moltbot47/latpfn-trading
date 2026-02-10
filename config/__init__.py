import os
import yaml
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

_CONFIG_PATH = Path(__file__).parent / "settings.yaml"


def load_config(path: str = None) -> dict:
    """Load configuration from YAML and overlay environment variables."""
    config_path = Path(path) if path else _CONFIG_PATH
    with open(config_path) as f:
        config = yaml.safe_load(f)

    # Overlay Tradovate credentials from environment
    config.setdefault("tradovate", {})
    config["tradovate"]["credentials"] = {
        "username": os.getenv("TRADOVATE_USERNAME", ""),
        "password": os.getenv("TRADOVATE_PASSWORD", ""),
        "secret": os.getenv("TRADOVATE_SECRET", ""),
        "cid": int(os.getenv("TRADOVATE_CID", "1")),
    }

    # Resolve environment overrides
    env = os.getenv("ENVIRONMENT")
    if env:
        config["system"]["environment"] = env
    log_level = os.getenv("LOG_LEVEL")
    if log_level:
        config["system"]["log_level"] = log_level

    return config
