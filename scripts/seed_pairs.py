from __future__ import annotations

from datetime import datetime, timezone


def _stats():
    return {
        "total_sim": 0,
        "ganadoras": 0,
        "perdedoras": 0,
        "pnl_total_usd": 0.0,
        "r_multiple_avg": 0.0,
        "last_updated": None,
    }


INITIAL_PAIRS = [
    {
        "pair": "BTCUSDT",
        "tier": "1",
        "active": True,
        "sim_mode": "auto",
        "auto_trade": True,
        "auto_trade_strategies": [
            "EMAPullback",
            "RangeBreakout",
            "SupportBounce",
            "MACDCross",
            "ORB",
            "Momentum",
        ],
        "sim_auto_enabled_at": datetime.now(timezone.utc).isoformat(),
        "sim_auto_reason": "Validacion inicial del sistema",
        "sim_stats": _stats(),
        "strategies": ["EMAPullback", "RangeBreakout", "SupportBounce", "MACDCross", "ORB", "Momentum"],
    },
    {
        "pair": "ETHUSDT",
        "tier": "1",
        "active": True,
        "sim_mode": "auto",
        "auto_trade": True,
        "auto_trade_strategies": [
            "EMAPullback",
            "RangeBreakout",
            "SupportBounce",
            "MACDCross",
            "ORB",
            "Momentum",
        ],
        "sim_auto_enabled_at": datetime.now(timezone.utc).isoformat(),
        "sim_auto_reason": "Validacion inicial del sistema",
        "sim_stats": _stats(),
        "strategies": ["EMAPullback", "RangeBreakout", "SupportBounce", "MACDCross", "ORB", "Momentum"],
    },
    {
        "pair": "SOLUSDT",
        "tier": "1",
        "active": True,
        "sim_mode": "manual",
        "auto_trade": True,
        "auto_trade_strategies": [
            "EMAPullback",
            "RangeBreakout",
            "SupportBounce",
            "Momentum",
        ],
        "sim_stats": _stats(),
        "strategies": ["EMAPullback", "RangeBreakout", "SupportBounce", "Momentum"],
    },
    {
        "pair": "XRPUSDT",
        "tier": "1",
        "active": True,
        "sim_mode": "manual",
        "auto_trade": True,
        "auto_trade_strategies": [
            "EMAPullback",
            "RangeBreakout",
            "SupportBounce",
            "MACDCross",
        ],
        "sim_stats": _stats(),
        "strategies": ["EMAPullback", "RangeBreakout", "SupportBounce", "MACDCross"],
    },
    {
        "pair": "BNBUSDT",
        "tier": "1",
        "active": True,
        "sim_mode": "manual",
        "auto_trade": True,
        "auto_trade_strategies": [
            "EMAPullback",
            "SupportBounce",
            "MACDCross",
            "Momentum",
        ],
        "sim_stats": _stats(),
        "strategies": ["EMAPullback", "SupportBounce", "MACDCross", "Momentum"],
    },
]


def main():
    print("Seed prepared for", len(INITIAL_PAIRS), "pairs.")
    for p in INITIAL_PAIRS:
        print(p["pair"], p.get("sim_mode"))


if __name__ == "__main__":
    main()
