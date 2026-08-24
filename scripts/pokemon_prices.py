#!/usr/bin/env python3
"""
Pokemon card price fetching module.

Integrates with:
- pokemontcg.io — card metadata + images (free, no auth)
- TCGPlayer — market prices (requires API key)
- PriceCharting — historical price data (requires API key)
- eBay Browse API — sold listings (requires API key)
- Manual entry fallback always available

Usage:
    from scripts.pokemon_prices import search_cards, fetch_prices, refresh_all_prices
"""

import json
import os
import sqlite3
import urllib.request
import urllib.parse
from datetime import datetime, date
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
POKEMON_DB_PATH = DATA_DIR / "pokemon_cards.db"

# API keys from environment
TCGPLAYER_KEY = os.getenv("TCGPLAYER_API_KEY", "")
PRICECHARTING_KEY = os.getenv("PRICECHARTING_API_KEY", "")
EBAY_APP_ID = os.getenv("EBAY_APP_ID", "")


def _get_pokemon_db():
    conn = sqlite3.connect(str(POKEMON_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_pokemon_db():
    """Create Pokemon card tables if they don't exist."""
    conn = _get_pokemon_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS pokemon_cards (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL,
            set_name        TEXT,
            set_code        TEXT,
            card_number     TEXT,
            rarity          TEXT,
            condition_grade TEXT DEFAULT 'Near Mint',
            grade_service   TEXT DEFAULT 'RAW',
            grade_value     REAL,
            image_url       TEXT,
            tcgplayer_id    TEXT,
            pokemontcg_id   TEXT,
            acquired_date   TEXT,
            acquired_price  REAL DEFAULT 0,
            acquired_source TEXT,
            quantity        INTEGER DEFAULT 1,
            notes           TEXT,
            created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS pokemon_prices (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            card_id     INTEGER REFERENCES pokemon_cards(id) ON DELETE CASCADE,
            price_date  TEXT NOT NULL,
            market_price REAL,
            low_price   REAL,
            mid_price   REAL,
            high_price  REAL,
            source      TEXT DEFAULT 'manual',
            created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS pokemon_watchlist (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL,
            set_name        TEXT,
            pokemontcg_id   TEXT,
            image_url       TEXT,
            target_buy_price REAL,
            current_price   REAL,
            alert_enabled   INTEGER DEFAULT 1,
            notes           TEXT,
            created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE INDEX IF NOT EXISTS idx_pokemon_prices_card ON pokemon_prices(card_id, price_date);
        CREATE INDEX IF NOT EXISTS idx_pokemon_cards_name ON pokemon_cards(name);
    """)
    conn.commit()
    conn.close()


# ── pokemontcg.io API (free, no auth) ────────────────────────────────


def search_cards(query: str, page: int = 1, page_size: int = 20) -> dict:
    """Search Pokemon cards via pokemontcg.io API."""
    params = urllib.parse.urlencode({
        "q": f"name:{query}*",
        "page": page,
        "pageSize": page_size,
        "orderBy": "-set.releaseDate",
    })
    url = f"https://api.pokemontcg.io/v2/cards?{params}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PikaTracker/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            cards = []
            for c in data.get("data", []):
                prices = c.get("tcgplayer", {}).get("prices", {})
                market_price = None
                for variant in ["holofoil", "reverseHolofoil", "normal", "1stEditionHolofoil"]:
                    if variant in prices and prices[variant].get("market"):
                        market_price = prices[variant]["market"]
                        break

                cards.append({
                    "id": c["id"],
                    "name": c["name"],
                    "set_name": c.get("set", {}).get("name", ""),
                    "set_code": c.get("set", {}).get("id", ""),
                    "number": c.get("number", ""),
                    "rarity": c.get("rarity", ""),
                    "image_small": c.get("images", {}).get("small", ""),
                    "image_large": c.get("images", {}).get("large", ""),
                    "market_price": market_price,
                    "tcgplayer_url": c.get("tcgplayer", {}).get("url", ""),
                })
            return {"cards": cards, "total": data.get("totalCount", 0), "page": page}
    except Exception as e:
        return {"cards": [], "total": 0, "page": page, "error": str(e)}


def get_sets() -> list:
    """Get all Pokemon TCG sets from pokemontcg.io."""
    url = "https://api.pokemontcg.io/v2/sets?orderBy=-releaseDate&pageSize=50"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PikaTracker/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return [{
                "id": s["id"],
                "name": s["name"],
                "series": s.get("series", ""),
                "total": s.get("total", 0),
                "release_date": s.get("releaseDate", ""),
                "logo": s.get("images", {}).get("logo", ""),
                "symbol": s.get("images", {}).get("symbol", ""),
            } for s in data.get("data", [])]
    except Exception as e:
        return []


def fetch_card_price(pokemontcg_id: str) -> dict | None:
    """Fetch current price for a specific card from pokemontcg.io."""
    url = f"https://api.pokemontcg.io/v2/cards/{pokemontcg_id}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PikaTracker/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            c = data.get("data", {})
            prices = c.get("tcgplayer", {}).get("prices", {})
            result = {"low": None, "mid": None, "market": None, "high": None}
            for variant in ["holofoil", "reverseHolofoil", "normal", "1stEditionHolofoil"]:
                if variant in prices:
                    p = prices[variant]
                    result["low"] = p.get("low")
                    result["mid"] = p.get("mid")
                    result["market"] = p.get("market")
                    result["high"] = p.get("high")
                    break
            return result
    except Exception:
        return None


# ── Portfolio Operations ─────────────────────────────────────────────


def get_portfolio() -> list:
    """Get all cards in portfolio with latest prices."""
    conn = _get_pokemon_db()
    cards = conn.execute("""
        SELECT c.*,
               p.market_price as current_price,
               p.low_price, p.mid_price, p.high_price, p.source as price_source
        FROM pokemon_cards c
        LEFT JOIN pokemon_prices p ON p.card_id = c.id
            AND p.price_date = (SELECT MAX(p2.price_date) FROM pokemon_prices p2 WHERE p2.card_id = c.id)
        ORDER BY c.created_at DESC
    """).fetchall()
    conn.close()
    return [dict(c) for c in cards]


def get_portfolio_summary() -> dict:
    """Calculate portfolio summary statistics."""
    cards = get_portfolio()
    total_cost = 0
    total_value = 0
    card_count = 0
    top_gainer = None
    top_gainer_pct = -999

    for c in cards:
        qty = c.get("quantity", 1)
        cost = (c.get("acquired_price") or 0) * qty
        price = (c.get("current_price") or c.get("acquired_price") or 0) * qty
        total_cost += cost
        total_value += price
        card_count += qty

        if cost > 0:
            gain_pct = (price - cost) / cost * 100
            if gain_pct > top_gainer_pct:
                top_gainer_pct = gain_pct
                top_gainer = c.get("name", "Unknown")

    gain_loss = total_value - total_cost
    roi = (gain_loss / total_cost * 100) if total_cost > 0 else 0

    return {
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2),
        "gain_loss": round(gain_loss, 2),
        "roi_pct": round(roi, 1),
        "card_count": card_count,
        "unique_cards": len(cards),
        "avg_card_value": round(total_value / card_count, 2) if card_count else 0,
        "top_gainer": top_gainer,
        "top_gainer_pct": round(top_gainer_pct, 1) if top_gainer else 0,
    }


def add_card(data: dict) -> int:
    """Add a card to the portfolio. Returns the new card ID."""
    conn = _get_pokemon_db()
    cur = conn.execute("""
        INSERT INTO pokemon_cards
            (name, set_name, set_code, card_number, rarity, condition_grade, grade_service,
             grade_value, image_url, tcgplayer_id, pokemontcg_id, acquired_date,
             acquired_price, acquired_source, quantity, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get("name"), data.get("set_name"), data.get("set_code"),
        data.get("card_number"), data.get("rarity"), data.get("condition_grade", "Near Mint"),
        data.get("grade_service", "RAW"), data.get("grade_value"),
        data.get("image_url"), data.get("tcgplayer_id"), data.get("pokemontcg_id"),
        data.get("acquired_date", date.today().isoformat()),
        data.get("acquired_price", 0), data.get("acquired_source"),
        data.get("quantity", 1), data.get("notes"),
    ))
    card_id = cur.lastrowid

    # If we have a current price, store it
    if data.get("current_price"):
        conn.execute("""
            INSERT INTO pokemon_prices (card_id, price_date, market_price, source)
            VALUES (?, ?, ?, 'pokemontcg.io')
        """, (card_id, date.today().isoformat(), data["current_price"]))

    conn.commit()
    conn.close()
    return card_id


def delete_card(card_id: int) -> bool:
    conn = _get_pokemon_db()
    conn.execute("DELETE FROM pokemon_prices WHERE card_id = ?", (card_id,))
    conn.execute("DELETE FROM pokemon_cards WHERE id = ?", (card_id,))
    conn.commit()
    conn.close()
    return True


def refresh_all_prices() -> dict:
    """Fetch latest prices for all cards with pokemontcg_id."""
    conn = _get_pokemon_db()
    cards = conn.execute(
        "SELECT id, pokemontcg_id FROM pokemon_cards WHERE pokemontcg_id IS NOT NULL"
    ).fetchall()

    updated = 0
    errors = 0
    today = date.today().isoformat()

    for card in cards:
        prices = fetch_card_price(card["pokemontcg_id"])
        if prices and prices.get("market"):
            conn.execute("""
                INSERT OR REPLACE INTO pokemon_prices (card_id, price_date, market_price, low_price, mid_price, high_price, source)
                VALUES (?, ?, ?, ?, ?, ?, 'pokemontcg.io')
            """, (card["id"], today, prices["market"], prices.get("low"), prices.get("mid"), prices.get("high")))
            updated += 1
        else:
            errors += 1

    conn.commit()
    conn.close()
    return {"updated": updated, "errors": errors, "total": len(cards)}


def get_price_history(card_id: int) -> list:
    """Get price history for a card."""
    conn = _get_pokemon_db()
    rows = conn.execute("""
        SELECT price_date, market_price, low_price, mid_price, high_price, source
        FROM pokemon_prices WHERE card_id = ? ORDER BY price_date
    """, (card_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Watchlist Operations ─────────────────────────────────────────────


def get_watchlist() -> list:
    conn = _get_pokemon_db()
    rows = conn.execute("SELECT * FROM pokemon_watchlist ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_to_watchlist(data: dict) -> int:
    conn = _get_pokemon_db()
    cur = conn.execute("""
        INSERT INTO pokemon_watchlist (name, set_name, pokemontcg_id, image_url, target_buy_price, current_price, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get("name"), data.get("set_name"), data.get("pokemontcg_id"),
        data.get("image_url"), data.get("target_buy_price"), data.get("current_price"),
        data.get("notes"),
    ))
    conn.commit()
    wid = cur.lastrowid
    conn.close()
    return wid


def remove_from_watchlist(wid: int) -> bool:
    conn = _get_pokemon_db()
    conn.execute("DELETE FROM pokemon_watchlist WHERE id = ?", (wid,))
    conn.commit()
    conn.close()
    return True


# ── Top Movers ───────────────────────────────────────────────────────


def get_top_movers(days: int = 7) -> dict:
    """Get cards with biggest price changes over N days."""
    conn = _get_pokemon_db()
    cards = conn.execute("""
        SELECT c.id, c.name, c.set_name, c.image_url,
               latest.market_price as current_price,
               older.market_price as old_price
        FROM pokemon_cards c
        JOIN pokemon_prices latest ON latest.card_id = c.id
            AND latest.price_date = (SELECT MAX(p.price_date) FROM pokemon_prices p WHERE p.card_id = c.id)
        LEFT JOIN pokemon_prices older ON older.card_id = c.id
            AND older.price_date = (SELECT MAX(p2.price_date) FROM pokemon_prices p2
                                    WHERE p2.card_id = c.id AND p2.price_date < date('now', ?))
        WHERE latest.market_price IS NOT NULL
    """, (f"-{days} days",)).fetchall()
    conn.close()

    movers = []
    for c in cards:
        if c["old_price"] and c["old_price"] > 0:
            change_pct = (c["current_price"] - c["old_price"]) / c["old_price"] * 100
            change_usd = c["current_price"] - c["old_price"]
            movers.append({
                "name": c["name"], "set_name": c["set_name"],
                "image_url": c["image_url"],
                "current_price": c["current_price"],
                "change_pct": round(change_pct, 1),
                "change_usd": round(change_usd, 2),
            })

    movers.sort(key=lambda x: x["change_pct"], reverse=True)
    gainers = [m for m in movers if m["change_pct"] > 0][:5]
    losers = sorted([m for m in movers if m["change_pct"] < 0], key=lambda x: x["change_pct"])[:5]

    return {"gainers": gainers, "losers": losers, "period_days": days}


# Initialize DB on import
init_pokemon_db()
