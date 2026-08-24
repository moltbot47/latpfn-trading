#!/usr/bin/env python3
"""
TradingView Voice Alert Server

Receives TradingView webhook alerts and sends spoken notifications
to your iPhone via multiple delivery methods:

  1. Pushcut  (free) - triggers iOS Shortcut that speaks text
  2. Ntfy.sh  (free) - push notification + iOS Shortcut speaks it
  3. Twilio   (paid) - literally calls your phone and speaks the alert
  4. Pushover (paid) - rich push notification with custom sounds

Setup:
  1. In TradingView alert → Webhook URL: http://YOUR_SERVER:5060/alert
  2. Alert message format (use TradingView placeholders):

     {"symbol":"{{ticker}}","action":"{{strategy.order.action}}","price":"{{close}}","msg":"{{ticker}} breaking {{strategy.order.action}} at {{close}}"}

  Or for simple price alerts:

     {"symbol":"AUDCHF","action":"above","level":"0.5600","msg":"AUDCHF breaking above 0.5600"}

  3. Configure delivery method in .env or below
  4. Set up iOS Shortcut (instructions in README)

Usage:
    python scripts/voice_alerts.py
    python scripts/voice_alerts.py --port 5060
"""

import argparse
import hashlib
import hmac
import json
import logging
import os
import time
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request

# ── Configuration ────────────────────────────────────────────────────

# Delivery methods (set in .env or environment)
PUSHCUT_API_KEY = os.getenv("PUSHCUT_API_KEY", "")
PUSHCUT_NOTIFICATION_NAME = os.getenv("PUSHCUT_NOTIFICATION_NAME", "Trading Alert")

NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")  # your unique topic name
NTFY_SERVER = os.getenv("NTFY_SERVER", "https://ntfy.sh")

TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM = os.getenv("TWILIO_FROM_NUMBER", "")
TWILIO_TO = os.getenv("TWILIO_TO_NUMBER", "")

PUSHOVER_TOKEN = os.getenv("PUSHOVER_APP_TOKEN", "")
PUSHOVER_USER = os.getenv("PUSHOVER_USER_KEY", "")

# Alert log
LOG_DIR = Path(__file__).parent.parent / "data"
ALERT_LOG = LOG_DIR / "voice_alerts.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("voice_alerts")

app = Flask(__name__)


# ── Alert Processing ─────────────────────────────────────────────────


def parse_alert(data: dict) -> dict:
    """Parse incoming TradingView alert into a spoken message."""
    symbol = data.get("symbol", data.get("ticker", "unknown")).upper()
    action = data.get("action", "").lower()
    level = data.get("level", data.get("price", ""))
    custom_msg = data.get("msg", "")

    # Build the spoken text
    if custom_msg:
        spoken = custom_msg
    else:
        direction = "breaking above" if action in ("buy", "long", "above") else \
                    "breaking below" if action in ("sell", "short", "below") else \
                    action
        spoken = f"{symbol} {direction} {level}"

    # Make it more natural for TTS
    # Spell out symbol letter by letter for clarity
    symbol_spelled = " ".join(list(symbol))

    spoken_verbose = (
        f"Alert. {symbol_spelled}. "
        f"{spoken}. "
        f"Price is {level}."
    )

    return {
        "symbol": symbol,
        "action": action,
        "level": str(level),
        "spoken": spoken,
        "spoken_verbose": spoken_verbose,
        "raw": data,
        "timestamp": datetime.now().isoformat(),
    }


def log_alert(alert: dict):
    """Append alert to JSON log file."""
    try:
        if ALERT_LOG.exists():
            with open(ALERT_LOG) as f:
                logs = json.load(f)
        else:
            logs = []
        logs.append(alert)
        # Keep last 500 alerts
        logs = logs[-500:]
        with open(ALERT_LOG, "w") as f:
            json.dump(logs, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to log alert: {e}")


# ── Delivery Methods ─────────────────────────────────────────────────


def send_pushcut(alert: dict) -> bool:
    """
    Send via Pushcut (free tier: 1000 notifications/month).
    Pushcut can trigger an iOS Shortcut that speaks the text.

    Setup:
      1. Install Pushcut app on iPhone
      2. Create a notification named "Trading Alert"
      3. Add a Shortcut action that runs your "Speak Alert" shortcut
      4. Get your API key from Pushcut app settings
    """
    if not PUSHCUT_API_KEY:
        return False

    url = f"https://api.pushcut.io/{PUSHCUT_API_KEY}/notifications/{urllib.parse.quote(PUSHCUT_NOTIFICATION_NAME)}"
    payload = json.dumps({
        "text": alert["spoken"],
        "title": f"{alert['symbol']} Alert",
        "input": alert["spoken_verbose"],  # passed to Shortcut as input
        "sound": "alien",
    }).encode()

    try:
        req = urllib.request.Request(url, data=payload, method="POST",
                                      headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            logger.info(f"Pushcut sent: {resp.status}")
            return resp.status == 200
    except Exception as e:
        logger.error(f"Pushcut failed: {e}")
        return False


def send_ntfy(alert: dict) -> bool:
    """
    Send via ntfy.sh (completely free, self-hostable).

    Setup:
      1. Install ntfy app on iPhone
      2. Subscribe to your topic (e.g. "mytrading-alerts-xyz")
      3. In iOS Settings > Shortcuts > Automation > create:
         "When I get a notification from ntfy" → Run Shortcut → Speak Text
    """
    if not NTFY_TOPIC:
        return False

    url = f"{NTFY_SERVER}/{NTFY_TOPIC}"
    payload = alert["spoken_verbose"].encode()

    try:
        req = urllib.request.Request(url, data=payload, method="POST", headers={
            "Title": f"{alert['symbol']} Alert",
            "Priority": "high",
            "Tags": "chart_with_upwards_trend" if alert["action"] in ("buy", "long", "above") else "chart_with_downwards_trend",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            logger.info(f"Ntfy sent: {resp.status}")
            return resp.status == 200
    except Exception as e:
        logger.error(f"Ntfy failed: {e}")
        return False


def send_twilio_call(alert: dict) -> bool:
    """
    Call your phone and speak the alert via Twilio.
    Most reliable for critical alerts — your phone literally rings.

    Setup:
      1. Create Twilio account (free trial gives $15 credit)
      2. Get a phone number
      3. Set env vars: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN,
         TWILIO_FROM_NUMBER, TWILIO_TO_NUMBER
    """
    if not all([TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM, TWILIO_TO]):
        return False

    twiml = (
        f'<Response>'
        f'<Say voice="alice" language="en-US">{alert["spoken_verbose"]}</Say>'
        f'<Pause length="1"/>'
        f'<Say voice="alice" language="en-US">Repeating. {alert["spoken_verbose"]}</Say>'
        f'</Response>'
    )

    url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Calls.json"
    data = urllib.parse.urlencode({
        "To": TWILIO_TO,
        "From": TWILIO_FROM,
        "Twiml": twiml,
    }).encode()

    # Basic auth
    import base64
    auth = base64.b64encode(f"{TWILIO_SID}:{TWILIO_TOKEN}".encode()).decode()

    try:
        req = urllib.request.Request(url, data=data, method="POST",
                                      headers={"Authorization": f"Basic {auth}"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            logger.info(f"Twilio call initiated: {resp.status}")
            return resp.status in (200, 201)
    except Exception as e:
        logger.error(f"Twilio failed: {e}")
        return False


def send_pushover(alert: dict) -> bool:
    """
    Send via Pushover ($5 one-time purchase per platform).
    Supports custom sounds and high-priority alerts.

    Setup:
      1. Buy Pushover app on iPhone ($5)
      2. Create an application at pushover.net
      3. Set env vars: PUSHOVER_APP_TOKEN, PUSHOVER_USER_KEY
    """
    if not all([PUSHOVER_TOKEN, PUSHOVER_USER]):
        return False

    url = "https://api.pushover.net/1/messages.json"
    data = urllib.parse.urlencode({
        "token": PUSHOVER_TOKEN,
        "user": PUSHOVER_USER,
        "title": f"{alert['symbol']} Alert",
        "message": alert["spoken_verbose"],
        "priority": 1,  # high priority
        "sound": "cashregister",
        "device": "",  # all devices
    }).encode()

    try:
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            logger.info(f"Pushover sent: {resp.status}")
            return resp.status == 200
    except Exception as e:
        logger.error(f"Pushover failed: {e}")
        return False


def deliver_alert(alert: dict) -> dict:
    """Try all configured delivery methods."""
    results = {}

    if PUSHCUT_API_KEY:
        results["pushcut"] = send_pushcut(alert)
    if NTFY_TOPIC:
        results["ntfy"] = send_ntfy(alert)
    if TWILIO_SID:
        results["twilio"] = send_twilio_call(alert)
    if PUSHOVER_TOKEN:
        results["pushover"] = send_pushover(alert)

    if not results:
        logger.warning("No delivery methods configured! Set env vars in .env")
        results["none"] = False

    return results


# ── Flask Routes ─────────────────────────────────────────────────────


@app.route("/alert", methods=["POST"])
def receive_alert():
    """
    TradingView webhook endpoint.

    Accepts JSON or plain text alerts.
    """
    # Parse body
    if request.is_json:
        data = request.get_json()
    else:
        # TradingView sometimes sends plain text
        body = request.get_data(as_text=True).strip()
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            # Treat as simple text message
            data = {"msg": body, "symbol": "ALERT", "action": "info"}

    logger.info(f"Alert received: {data}")

    alert = parse_alert(data)
    log_alert(alert)
    results = deliver_alert(alert)

    return jsonify({
        "status": "ok",
        "alert": alert["spoken"],
        "delivery": results,
        "timestamp": alert["timestamp"],
    })


@app.route("/test", methods=["GET"])
def test_alert():
    """Send a test alert to verify delivery works."""
    alert = parse_alert({
        "symbol": "AUDCHF",
        "action": "above",
        "level": "0.5600",
        "msg": "Test alert. AUDCHF breaking above 0.5600",
    })
    log_alert(alert)
    results = deliver_alert(alert)

    return jsonify({
        "status": "test sent",
        "alert": alert["spoken_verbose"],
        "delivery": results,
    })


@app.route("/alerts", methods=["GET"])
def list_alerts():
    """View recent alerts."""
    try:
        if ALERT_LOG.exists():
            with open(ALERT_LOG) as f:
                alerts = json.load(f)
            return jsonify(alerts[-50:])
    except Exception:
        pass
    return jsonify([])


@app.route("/health", methods=["GET"])
def health():
    """Health check."""
    configured = []
    if PUSHCUT_API_KEY:
        configured.append("pushcut")
    if NTFY_TOPIC:
        configured.append("ntfy")
    if TWILIO_SID:
        configured.append("twilio")
    if PUSHOVER_TOKEN:
        configured.append("pushover")

    return jsonify({
        "status": "ok",
        "configured_methods": configured,
        "alert_count": len(json.load(open(ALERT_LOG))) if ALERT_LOG.exists() else 0,
    })


# ── Entry Point ──────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="TradingView Voice Alert Server")
    parser.add_argument("--port", type=int, default=5060)
    parser.add_argument("--host", type=str, default="0.0.0.0")
    args = parser.parse_args()

    print(f"""
    ╔═══════════════════════════════════════════════════════╗
    ║  TradingView Voice Alert Server                       ║
    ║  http://{args.host}:{args.port}                            ║
    ║                                                       ║
    ║  Webhook URL: http://YOUR_IP:{args.port}/alert             ║
    ║  Test:        http://localhost:{args.port}/test             ║
    ║  Health:      http://localhost:{args.port}/health            ║
    ║                                                       ║
    ║  Configured delivery methods:                         ║""")

    if PUSHCUT_API_KEY:
        print("    ║    [x] Pushcut  (iOS Shortcut trigger)               ║")
    else:
        print("    ║    [ ] Pushcut  (set PUSHCUT_API_KEY)                ║")
    if NTFY_TOPIC:
        print("    ║    [x] Ntfy     (free push notifications)            ║")
    else:
        print("    ║    [ ] Ntfy     (set NTFY_TOPIC)                     ║")
    if TWILIO_SID:
        print("    ║    [x] Twilio   (voice call)                         ║")
    else:
        print("    ║    [ ] Twilio   (set TWILIO_ACCOUNT_SID)             ║")
    if PUSHOVER_TOKEN:
        print("    ║    [x] Pushover (rich push)                          ║")
    else:
        print("    ║    [ ] Pushover (set PUSHOVER_APP_TOKEN)             ║")

    print("    ╚═══════════════════════════════════════════════════════╝\n")

    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
