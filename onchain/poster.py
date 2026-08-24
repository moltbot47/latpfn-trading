"""
ForecastPoster — Automatically posts signal hashes on-chain to Base L2.

Every time the trading system generates a signal, this module:
1. Creates a keccak256 hash of (instrument, direction, confidence, timestamp)
2. Sends a transaction calling postForecast(instrument, hash) on the SignalAccess contract
3. The hash is permanently on-chain BEFORE the signal is delivered to subscribers

This makes results fully verifiable — anyone can check Basescan to confirm
predictions were committed before delivery (no hindsight bias possible).
"""

import json
import logging
import os
import time

from web3 import Web3
from eth_account import Account

logger = logging.getLogger(__name__)

# Minimal ABI — only the functions we need
POST_FORECAST_ABI = json.loads("""[
    {
        "inputs": [
            {"name": "instrument", "type": "string"},
            {"name": "hash", "type": "bytes32"}
        ],
        "name": "postForecast",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "forecastCount",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    }
]""")


class ForecastPoster:
    """Posts forecast hashes to the SignalAccess contract on Base L2."""

    def __init__(self):
        self.rpc_url = os.getenv("BASE_RPC_URL", "https://mainnet.base.org")
        self.contract_address = os.getenv(
            "SIGNAL_CONTRACT_ADDRESS",
            "0x901c169aa21a9eC593c52bc6F0eaA814eDf41091",
        )
        self.private_key = os.getenv("DEPLOYER_PRIVATE_KEY", "")

        if not self.private_key:
            logger.warning("DEPLOYER_PRIVATE_KEY not set — forecast posting disabled")
            self.enabled = False
            return

        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))
        self.account = Account.from_key(self.private_key)
        self.contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(self.contract_address),
            abi=POST_FORECAST_ABI,
        )
        self.enabled = True
        self.chain_id = 8453  # Base mainnet

        logger.info(
            "ForecastPoster initialized: contract=%s, signer=%s",
            self.contract_address[:10] + "...",
            self.account.address[:10] + "...",
        )

    @staticmethod
    def create_hash(instrument: str, direction: str, confidence: float, timestamp: int) -> bytes:
        """Create a deterministic keccak256 hash for a forecast."""
        payload = f"{instrument}-{direction}-{confidence:.4f}-{timestamp}"
        return Web3.keccak(text=payload)

    def post(self, instrument: str, direction: str, confidence: float, timestamp: int = 0) -> dict | None:
        """
        Post a forecast hash on-chain.

        Returns dict with tx_hash and hash on success, None on failure.
        Does not raise — failures are logged as warnings.
        """
        if not self.enabled:
            logger.debug("Forecast posting disabled (no private key)")
            return None

        if not timestamp:
            timestamp = int(time.time())

        forecast_hash = self.create_hash(instrument, direction, confidence, timestamp)

        try:
            nonce = self.w3.eth.get_transaction_count(self.account.address)

            tx = self.contract.functions.postForecast(
                instrument, forecast_hash
            ).build_transaction({
                "from": self.account.address,
                "nonce": nonce,
                "chainId": self.chain_id,
                "maxFeePerGas": self.w3.to_wei("0.1", "gwei"),
                "maxPriorityFeePerGas": self.w3.to_wei("0.05", "gwei"),
            })

            # Estimate gas
            tx["gas"] = self.w3.eth.estimate_gas(tx)

            # Sign and send
            signed = self.account.sign_transaction(tx)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)

            logger.info(
                "Forecast posted: %s %s (conf=%.2f) tx=%s",
                instrument, direction, confidence, tx_hash.hex()[:16] + "...",
            )

            return {
                "tx_hash": tx_hash.hex(),
                "forecast_hash": forecast_hash.hex(),
                "instrument": instrument,
                "direction": direction,
                "confidence": confidence,
                "timestamp": timestamp,
            }

        except Exception as e:
            logger.warning("Failed to post forecast on-chain: %s", e)
            return None

    def post_signal(self, signal) -> dict | None:
        """Post a TradingSignal object on-chain. Accepts any object with instrument/direction/confidence."""
        instrument = getattr(signal, "instrument", None) or signal.get("instrument", "")
        direction = getattr(signal, "direction", None) or signal.get("direction", "")
        confidence = getattr(signal, "confidence", 0) or signal.get("confidence", 0)
        timestamp = getattr(signal, "timestamp", 0) or signal.get("timestamp", 0)

        if not instrument or not direction:
            logger.debug("Skipping on-chain post: missing instrument/direction")
            return None

        return self.post(instrument, direction, confidence, int(timestamp) if timestamp else 0)

    def get_forecast_count(self) -> int:
        """Get the current number of forecasts posted on-chain."""
        if not self.enabled:
            return 0
        try:
            return self.contract.functions.forecastCount().call()
        except Exception:
            return 0

    def post_test(self):
        """Post a test forecast hash to verify the setup works."""
        result = self.post("TEST", "long", 0.9999, int(time.time()))
        if result:
            print(f"Test forecast posted successfully!")
            print(f"  TX: https://basescan.org/tx/{result['tx_hash']}")
            print(f"  Hash: {result['forecast_hash']}")
        else:
            print("Failed to post test forecast. Check logs.")
        return result
