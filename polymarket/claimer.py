"""
Auto-claims resolved Polymarket positions.

Calls CTF.redeemPositions() via the Gnosis Safe proxy wallet to convert
winning conditional tokens back to USDC, making funds available for new trades.

Flow:
  1. Scan open positions for resolved conditions (on-chain check)
  2. Build redeemPositions calldata for the CTF contract
  3. Execute via Gnosis Safe's execTransaction (EOA signs as Safe owner)
  4. USDC returns to Safe → available for CLOB trading
"""

import logging
import os
import time
from typing import Dict, List, Optional

import requests
from eth_account import Account
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

logger = logging.getLogger(__name__)

# ── Polygon mainnet contract addresses ────────────────────────────────
CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
NEG_RISK_ADAPTER = "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296"
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

# ── Minimal ABIs (only the functions we need) ─────────────────────────
CTF_ABI = [
    {
        "name": "redeemPositions",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "collateralToken", "type": "address"},
            {"name": "parentCollectionId", "type": "bytes32"},
            {"name": "conditionId", "type": "bytes32"},
            {"name": "indexSets", "type": "uint256[]"},
        ],
        "outputs": [],
    },
    {
        "name": "payoutDenominator",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "", "type": "bytes32"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "payoutNumerators",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "", "type": "bytes32"},
            {"name": "", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "uint256"}],
    },
]

SAFE_ABI = [
    {
        "name": "execTransaction",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "value", "type": "uint256"},
            {"name": "data", "type": "bytes"},
            {"name": "operation", "type": "uint8"},
            {"name": "safeTxGas", "type": "uint256"},
            {"name": "baseGas", "type": "uint256"},
            {"name": "gasPrice", "type": "uint256"},
            {"name": "gasToken", "type": "address"},
            {"name": "refundReceiver", "type": "address"},
            {"name": "signatures", "type": "bytes"},
        ],
        "outputs": [{"name": "success", "type": "bool"}],
    },
    {
        "name": "nonce",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "getTransactionHash",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "value", "type": "uint256"},
            {"name": "data", "type": "bytes"},
            {"name": "operation", "type": "uint8"},
            {"name": "safeTxGas", "type": "uint256"},
            {"name": "baseGas", "type": "uint256"},
            {"name": "gasPrice", "type": "uint256"},
            {"name": "gasToken", "type": "address"},
            {"name": "refundReceiver", "type": "address"},
            {"name": "_nonce", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "bytes32"}],
    },
]

ERC20_ABI = [
    {
        "name": "balanceOf",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "account", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
]

ERC1155_ABI = [
    {
        "name": "balanceOf",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "account", "type": "address"},
            {"name": "id", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "uint256"}],
    },
]

MAX_CLAIMS_PER_CYCLE = 5  # Limit on-chain TXs per cycle


class PositionClaimer:
    """Auto-claims resolved Polymarket positions via CTF + Gnosis Safe."""

    def __init__(self, config: dict):
        pm_cfg = config.get("polymarket", {})
        self._rpc_url = pm_cfg.get("rpc_url", "https://polygon-bor.publicnode.com")
        self._claim_interval = pm_cfg.get("claim_interval_minutes", 30) * 60
        self._safe_address = os.getenv("POLYMARKET_FUNDER_ADDRESS", "")
        self._private_key = os.getenv("POLYMARKET_PRIVATE_KEY", "")
        self._eoa_address = os.getenv("POLYMARKET_WALLET_ADDRESS", "")
        self._w3: Optional[Web3] = None
        self._last_claim_time = 0.0
        self._claimed_conditions: set = set()

    # ── Public API ────────────────────────────────────────────────────

    async def claim_resolved_positions(self, position_mgr, override_interval: float = 0) -> List[Dict]:
        """
        Scan open positions for resolved markets and redeem winnings.

        Called at the start of each orchestrator cycle.  Rate-limited
        to avoid excessive RPC calls.

        Args:
            position_mgr:      PositionManager instance.
            override_interval: If > 0, use this interval instead of the default.

        Returns:
            List of claim results with tx_hash, usdc_received, etc.
        """
        interval = override_interval if override_interval > 0 else self._claim_interval
        now = time.time()
        if now - self._last_claim_time < interval:
            return []
        self._last_claim_time = now

        if not self._safe_address or not self._private_key:
            return []

        open_positions = position_mgr.get_open_positions()

        # Group by condition_id (skip already-claimed)
        by_condition: Dict[str, List] = {}
        for key, pos in open_positions.items():
            if pos.market_id not in self._claimed_conditions:
                by_condition.setdefault(pos.market_id, []).append((key, pos))

        if not by_condition:
            return []

        # Connect to Polygon
        try:
            w3 = self._connect()
        except Exception as e:
            logger.error("Claimer: cannot connect to Polygon RPC: %s", e)
            return []

        # Check EOA has MATIC for gas
        eoa_cksum = Web3.to_checksum_address(self._eoa_address)
        eoa_balance = w3.eth.get_balance(eoa_cksum)
        if eoa_balance < w3.to_wei(0.005, "ether"):
            logger.warning(
                "Claimer: EOA has low MATIC (%.6f). "
                "Send MATIC to %s on Polygon to enable auto-claim.",
                w3.from_wei(eoa_balance, "ether"),
                self._eoa_address,
            )
            return []

        ctf = w3.eth.contract(
            address=Web3.to_checksum_address(CTF_ADDRESS), abi=CTF_ABI
        )

        results = []
        claims_sent = 0
        safe_cksum = Web3.to_checksum_address(self._safe_address)

        for condition_id, positions in by_condition.items():
            if claims_sent >= MAX_CLAIMS_PER_CYCLE:
                break

            try:
                condition_bytes = _to_bytes32(condition_id)

                # Check on-chain if resolved
                denom = ctf.functions.payoutDenominator(condition_bytes).call()
                if denom == 0:
                    continue  # Not resolved yet

                # Check if Safe still holds tokens for any position
                has_tokens = False
                for _key, pos in positions:
                    try:
                        token_id = int(pos.token_id)
                        erc1155 = w3.eth.contract(
                            address=Web3.to_checksum_address(CTF_ADDRESS),
                            abi=ERC1155_ABI,
                        )
                        bal = erc1155.functions.balanceOf(safe_cksum, token_id).call()
                        if bal > 0:
                            has_tokens = True
                            break
                    except Exception:
                        pass

                if not has_tokens:
                    # Tokens already sold/redeemed — just mark positions resolved
                    for key, pos in positions:
                        payout = self._compute_payout(ctf, condition_bytes, pos)
                        position_mgr.resolve_position(key, payout)
                    self._claimed_conditions.add(condition_id)
                    logger.debug(
                        "Resolved %s: no tokens to redeem (already exited)",
                        condition_id[:12],
                    )
                    continue

                logger.info(
                    "Resolved market with tokens: %s (%s) — redeeming...",
                    condition_id[:16],
                    positions[0][1].question[:40],
                )

                # Check if neg_risk market
                neg_risk = self._check_neg_risk(condition_id)
                if neg_risk:
                    logger.info(
                        "Skipping neg_risk market %s (not yet supported)",
                        condition_id[:16],
                    )
                    continue

                # Snapshot USDC balance before
                usdc_before = self._get_safe_usdc(w3)

                # Execute redemption via Safe
                tx_hash = self._execute_redeem(w3, condition_id)
                claims_sent += 1

                # Snapshot USDC balance after
                usdc_after = self._get_safe_usdc(w3)
                usdc_received = usdc_after - usdc_before

                # Determine payouts and resolve tracked positions
                for key, pos in positions:
                    payout = self._compute_payout(ctf, condition_bytes, pos)
                    position_mgr.resolve_position(key, payout)

                self._claimed_conditions.add(condition_id)

                result = {
                    "condition_id": condition_id,
                    "question": positions[0][1].question,
                    "tx_hash": tx_hash,
                    "usdc_received": round(usdc_received, 4),
                    "positions_resolved": len(positions),
                }
                results.append(result)
                logger.info(
                    "Claimed: %s → +$%.4f USDC (%d positions) tx=%s",
                    condition_id[:12],
                    usdc_received,
                    len(positions),
                    tx_hash[:16],
                )

            except Exception as e:
                logger.error(
                    "Claim failed for %s: %s", condition_id[:12], e
                )

        if results:
            total = sum(r["usdc_received"] for r in results)
            logger.info(
                "Auto-claim complete: %d markets, +$%.2f USDC returned",
                len(results),
                total,
            )

        return results

    # ── Internal helpers ──────────────────────────────────────────────

    def _connect(self) -> Web3:
        """Lazy-connect to Polygon RPC."""
        if self._w3 is None or not self._w3.is_connected():
            self._w3 = Web3(
                Web3.HTTPProvider(self._rpc_url, request_kwargs={"timeout": 30})
            )
            # Polygon is a POA chain — inject middleware to handle extraData
            self._w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            if not self._w3.is_connected():
                raise ConnectionError(f"Cannot connect to {self._rpc_url}")
            logger.info(
                "Claimer connected to Polygon (block %d)",
                self._w3.eth.block_number,
            )
        return self._w3

    def _check_neg_risk(self, condition_id: str) -> bool:
        """Check CLOB API if market uses neg_risk (multi-outcome)."""
        try:
            resp = requests.get(
                f"https://clob.polymarket.com/markets/{condition_id}",
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json().get("neg_risk", False)
        except Exception:
            pass
        return False

    def _get_safe_usdc(self, w3: Web3) -> float:
        """Get USDC balance of the Safe (6-decimal conversion)."""
        usdc = w3.eth.contract(
            address=Web3.to_checksum_address(USDC_ADDRESS), abi=ERC20_ABI
        )
        raw = usdc.functions.balanceOf(
            Web3.to_checksum_address(self._safe_address)
        ).call()
        return raw / 1e6

    def _compute_payout(self, ctf, condition_bytes: bytes, pos) -> float:
        """Compute the payout multiplier for a position (0.0 or 1.0)."""
        try:
            denom = ctf.functions.payoutDenominator(condition_bytes).call()
            if denom == 0:
                return 0.0
            # Outcome index: YES=0, NO=1
            idx = 0 if pos.direction == "YES" else 1
            numerator = ctf.functions.payoutNumerators(
                condition_bytes, idx
            ).call()
            return numerator / denom
        except Exception:
            return 0.0

    def _execute_redeem(self, w3: Web3, condition_id: str) -> str:
        """
        Execute CTF.redeemPositions via Gnosis Safe execTransaction.

        The Safe holds the conditional tokens.  We sign as the Safe owner
        (EOA) and submit the transaction on Polygon (costs ~0.001 MATIC).
        """
        safe_addr = Web3.to_checksum_address(self._safe_address)
        eoa_addr = Web3.to_checksum_address(self._eoa_address)
        ctf_addr = Web3.to_checksum_address(CTF_ADDRESS)
        zero_addr = Web3.to_checksum_address(ZERO_ADDRESS)
        condition_bytes = _to_bytes32(condition_id)

        # Build CTF.redeemPositions calldata
        ctf = w3.eth.contract(address=ctf_addr, abi=CTF_ABI)
        calldata = ctf.encode_abi(
            abi_element_identifier="redeemPositions",
            args=[
                Web3.to_checksum_address(USDC_ADDRESS),
                b"\x00" * 32,       # parentCollectionId (always zero)
                condition_bytes,     # conditionId
                [1, 2],              # indexSets: YES=1, NO=2
            ],
        )
        calldata_bytes = Web3.to_bytes(hexstr=calldata)

        # Get Safe contract
        safe = w3.eth.contract(address=safe_addr, abi=SAFE_ABI)
        nonce = safe.functions.nonce().call()

        # Compute Safe transaction hash (EIP-712)
        safe_tx_hash = safe.functions.getTransactionHash(
            ctf_addr,       # to
            0,              # value
            calldata_bytes, # data
            0,              # operation (CALL)
            0,              # safeTxGas
            0,              # baseGas
            0,              # gasPrice (no refund)
            zero_addr,      # gasToken
            zero_addr,      # refundReceiver
            nonce,          # _nonce
        ).call()

        # Sign the hash with the Safe owner's key (standard ECDSA, v=27/28)
        signed = Account.unsafe_sign_hash(
            safe_tx_hash, private_key=self._private_key
        )
        signature = (
            signed.r.to_bytes(32, "big")
            + signed.s.to_bytes(32, "big")
            + bytes([signed.v])
        )

        # Build execTransaction with gas price included
        gas_price = max(w3.eth.gas_price, w3.to_wei(30, "gwei"))
        tx = safe.functions.execTransaction(
            ctf_addr,
            0,
            calldata_bytes,
            0,              # operation
            0,              # safeTxGas
            0,              # baseGas
            0,              # gasPrice
            zero_addr,      # gasToken
            zero_addr,      # refundReceiver
            signature,
        ).build_transaction(
            {
                "from": eoa_addr,
                "nonce": w3.eth.get_transaction_count(eoa_addr),
                "gas": 500_000,
                "gasPrice": gas_price,
                "chainId": 137,
            }
        )

        # Sign and send
        signed_tx = w3.eth.account.sign_transaction(tx, self._private_key)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

        if receipt["status"] != 1:
            raise RuntimeError(f"Redeem TX reverted: {tx_hash.hex()}")

        logger.info(
            "Redeem TX confirmed: %s (gas used: %d)",
            tx_hash.hex(),
            receipt["gasUsed"],
        )
        return tx_hash.hex()


# ── Module-level helpers ──────────────────────────────────────────────

def _to_bytes32(hex_str: str) -> bytes:
    """Convert a hex string (with or without 0x prefix) to 32 bytes."""
    clean = hex_str.replace("0x", "")
    if len(clean) < 64:
        clean = clean.zfill(64)
    return bytes.fromhex(clean[:64])
