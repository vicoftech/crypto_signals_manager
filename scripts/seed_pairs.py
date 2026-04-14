from __future__ import annotations

INITIAL_PAIRS = [
    {
        "pair": "BTCUSDT",
        "tier": "1",
        "active": True,
        "strategies": ["EMAPullback", "RangeBreakout", "SupportBounce", "MACDCross", "ORB", "Momentum"],
    },
    {
        "pair": "ETHUSDT",
        "tier": "1",
        "active": True,
        "strategies": ["EMAPullback", "RangeBreakout", "SupportBounce", "MACDCross", "ORB", "Momentum"],
    },
]


def main():
    print("Seed prepared for", len(INITIAL_PAIRS), "pairs.")
    for p in INITIAL_PAIRS:
        print(p)


if __name__ == "__main__":
    main()
