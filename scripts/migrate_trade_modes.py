from __future__ import annotations

import os

import boto3

from src.core.mode import MODE_LIVE, MODE_SIMULATION, normalize_mode


def main() -> None:
    table_name = os.getenv("TRADES_TABLE_NAME", "crypto-trading-bot-trades")
    table = boto3.resource("dynamodb").Table(table_name)
    updated = 0
    scanned = 0
    kwargs: dict = {}
    while True:
        resp = table.scan(**kwargs)
        items = resp.get("Items") or []
        for item in items:
            scanned += 1
            trade_id = str(item.get("trade_id", ""))
            mode = normalize_mode(str(item.get("mode", "")))
            if mode not in (MODE_SIMULATION, MODE_LIVE, "live_test"):
                mode = MODE_SIMULATION
            if str(item.get("mode", "")) == mode:
                continue
            table.update_item(
                Key={"trade_id": trade_id},
                UpdateExpression="SET #m=:m",
                ExpressionAttributeNames={"#m": "mode"},
                ExpressionAttributeValues={":m": mode},
            )
            updated += 1
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
        kwargs = {"ExclusiveStartKey": lek}
    print(f"table={table_name} scanned={scanned} updated={updated}")


if __name__ == "__main__":
    main()
