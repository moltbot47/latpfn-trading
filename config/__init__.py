import logging
import os
import yaml
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent / "settings.yaml"

# Required top-level config sections
_REQUIRED_SECTIONS = ("system", "schedule", "model", "instruments", "risk", "signal")


def load_config(path: str = None) -> dict:
    """Load configuration from YAML and overlay environment variables.

    Raises:
        FileNotFoundError: If config file doesn't exist.
        ValueError: If required config sections are missing.
    """
    config_path = Path(path) if path else _CONFIG_PATH
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path) as f:
        config = yaml.safe_load(f)

    if config is None:
        raise ValueError(f"Config file is empty: {config_path}")

    # Validate required sections
    missing = [s for s in _REQUIRED_SECTIONS if s not in config]
    if missing:
        raise ValueError(f"Config missing required sections: {missing}")

    # Overlay Tradovate credentials from environment
    config.setdefault("tradovate", {})
    try:
        cid = int(os.getenv("TRADOVATE_CID", "1"))
    except (ValueError, TypeError):
        logger.warning("TRADOVATE_CID is not a valid integer, defaulting to 1")
        cid = 1

    config["tradovate"]["credentials"] = {
        "username": os.getenv("TRADOVATE_USERNAME", ""),
        "password": os.getenv("TRADOVATE_PASSWORD", ""),
        "secret": os.getenv("TRADOVATE_SECRET", ""),
        "cid": cid,
    }

    # Overlay PickMyTrade credentials from environment
    config.setdefault("pickmytrade", {})
    config["pickmytrade"]["token"] = os.getenv("PICKMYTRADE_TOKEN", "")
    config["pickmytrade"]["account_id"] = os.getenv("PICKMYTRADE_ACCOUNT_ID", "")
    config["pickmytrade"].setdefault(
        "webhook_url", "https://api.pickmytrade.trade/v2/add-trade-data-latest"
    )

    # Overlay Discord bot credentials from environment
    config.setdefault("discord", {})
    config["discord"]["bot_token"] = os.getenv("DISCORD_BOT_TOKEN", "")
    config["discord"].setdefault(
        "channel_id", os.getenv("DISCORD_CHANNEL_ID", "")
    )

    # Resolve environment overrides
    env = os.getenv("ENVIRONMENT")
    if env:
        config["system"]["environment"] = env
    log_level = os.getenv("LOG_LEVEL")
    if log_level:
        config["system"]["log_level"] = log_level

    # Account equity override from environment (actual Tradovate balance)
    equity_env = os.getenv("ACCOUNT_EQUITY")
    if equity_env:
        try:
            config.setdefault("execution", {})["default_equity"] = float(equity_env)
        except ValueError:
            logger.warning("ACCOUNT_EQUITY is not a valid number: %s", equity_env)

    return config
