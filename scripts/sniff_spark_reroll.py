"""Bot-side Spark Reroll response sniffer.

Default account is "A". Run at the finished-career screen before final submit.

Commands:
  python scripts/sniff_spark_reroll.py select
  python scripts/sniff_spark_reroll.py reroll
  python scripts/sniff_spark_reroll.py inspect
  python scripts/sniff_spark_reroll.py finish 2
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.domain.account_store import (  # noqa: E402
    load_account_config,
    load_steam_token,
)
from uma_api.account_io import safe_account_name  # noqa: E402
from uma_api.client import UmaClient, get_ticket  # noqa: E402


NEEDLES = ("factor", "lottery", "relottery", "resume")
ENDPOINT_FILES = (
    "single_mode_free__factor_select.json",
    "single_mode_free__factor_lottery.json",
    "single_mode_free__load.json",
)


class Tee(io.TextIOBase):
    def __init__(self, *streams):
        self.streams = streams

    def write(self, s):
        for stream in self.streams:
            stream.write(s)
            stream.flush()
        return len(s)

    def flush(self):
        for stream in self.streams:
            stream.flush()


def short(value, limit=1600):
    return json.dumps(value, ensure_ascii=False, default=str)[:limit]


def interesting_walk(value, path="$", depth=0):
    if depth > 12:
        return
    if isinstance(value, dict):
        keys = list(value.keys())
        hit = any(any(n in str(k).lower() for n in NEEDLES) for k in keys) or "factor_id" in value
        if hit:
            print(f"\n{path}")
            print("keys =", keys[:80])
            for key, child in value.items():
                low = str(key).lower()
                if any(n in low for n in NEEDLES) or key in {"factor_id", "factor_id_array", "factor_info_array"}:
                    print(f"{key} = {short(child)}")
        for key, child in value.items():
            interesting_walk(child, f"{path}.{key}", depth + 1)
    elif isinstance(value, list):
        if value and any(
            isinstance(item, dict)
            and any("factor" in str(k).lower() or "lottery" in str(k).lower() for k in item)
            for item in value[:5]
        ):
            print(f"\n{path} LIST len={len(value)}")
            print(short(value[:2]))
        for idx, child in enumerate(value[:60]):
            interesting_walk(child, f"{path}[{idx}]", depth + 1)


def print_response(label, response):
    headers = response.get("data_headers") or {}
    data = response.get("data") or {}
    print("\n" + "=" * 40)
    print(label)
    print("result_code:", headers.get("result_code"))
    print("data keys:", list(data.keys()) if isinstance(data, dict) else type(data).__name__)
    interesting_walk(data)


def account_cfg(account):
    safe = safe_account_name(account)
    path = ROOT / "uma_runtime" / "accounts" / f"{safe}.json"
    cfg = load_account_config(safe)
    if not isinstance(cfg, dict):
        raise SystemExit(f"Account file not found: {path}")
    if not cfg.get("steam_session_ticket"):
        steam_path = ROOT / "uma_runtime" / "accounts" / f"{safe}.steam.json"
        steam = load_steam_token(safe)
        if not isinstance(steam, dict):
            raise SystemExit(
                f"Missing Steam token file: {steam_path}\n"
                "Stop the other bot process and log in once through the web UI, or copy a fresh steam_session_ticket into the account config."
            )
        token = steam.get("refresh_token")
        if not token:
            raise SystemExit(f"No refresh_token in {steam_path}")
        print("Generating fresh Steam ticket from saved refresh token...")
        steam_id, ticket, _rotated = get_ticket(refresh_token=token)
        cfg.update({"steam_id": steam_id, "steam_session_ticket": ticket})
    return safe, cfg


def make_client(account):
    safe, cfg = account_cfg(account)
    client = UmaClient(cfg, trace_enabled=True).bind_api_warehouse(ROOT, account)
    client.login()
    return safe, client


def current_turn(client):
    response = client.load_career()
    data = response.get("data") or {}
    chara = data.get("chara_info") or data.get("single_mode_chara_light") or {}
    return int(chara.get("turn") or 24), response


def factor_select(client, turn):
    return client.call("single_mode_free/factor_select", {
        "current_turn": turn,
        "skill_id_array": None,
    })


def factor_select_if_needed(client, turn):
    try:
        return factor_select(client, turn)
    except Exception as exc:
        if "API error 102" in str(exc):
            print("factor_select returned 102; already on factor-select screen, continuing to reroll.")
            return None
        raise


def ensure_tp(client, cost=30):
    tp = int((client.tp_info or {}).get("current_tp") or 0)
    print("TP before reroll:", client.tp_info)
    if tp >= cost:
        return
    print("TP < 30 -> using one plain TP bottle item_id=32")
    client.use_recovery_item(32, 1)
    print("TP after bottle:", client.tp_info)
    if int((client.tp_info or {}).get("current_tp") or 0) < cost:
        raise SystemExit("Still below 30 TP after bottle; stop here and finish manually.")


def inspect_warehouse(safe):
    warehouse = ROOT / "uma_runtime" / "api_warehouse" / safe
    print("\nwarehouse:", warehouse)
    for name in ENDPOINT_FILES:
        path = warehouse / name
        print("\n====", path)
        if not path.exists():
            print("missing")
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        print("endpoint:", record.get("endpoint"))
        print("result_code:", record.get("result_code"))
        interesting_walk(record.get("data") or {})


def run(args):
    safe = safe_account_name(args.account)
    if args.command == "inspect":
        inspect_warehouse(safe)
        return

    safe, client = make_client(args.account)
    turn, load_response = current_turn(client)
    print("account:", args.account)
    print("safe account:", safe)
    print("turn:", turn)
    print("trace/warehouse responses are also saved under uma_runtime/")

    if args.command == "select":
        print_response("single_mode_free/load", load_response)
        print_response("single_mode_free/factor_select", factor_select(client, turn))
        inspect_warehouse(safe)
        return

    if args.command == "reroll":
        factor_select_if_needed(client, turn)
        ensure_tp(client)
        print_response("single_mode_free/factor_lottery", client.call("single_mode_free/factor_lottery", {
            "lottery_count": 1,
            "tp_info": client.tp_info,
            "use_tp": 30,
        }))
        print_response("single_mode_free/load after reroll", client.call("single_mode_free/load", {}))
        inspect_warehouse(safe)
        print("\nReroll done. Resolve with: python scripts/sniff_spark_reroll.py finish 1|2")
        return

    if args.command == "finish":
        choice = int(args.choice or 0)
        if choice not in (1, 2):
            raise SystemExit("finish requires choice 1(original) or 2(rerolled)")
        print_response("single_mode_free/finish", client.call("single_mode_free/finish", {
            "is_force_delete": False,
            "current_turn": turn,
            "factor_lottery_id": choice,
        }))
        return

    raise SystemExit(f"Unknown command: {args.command}")


def main():
    parser = argparse.ArgumentParser(description="Sniff decrypted Spark Reroll responses via bot UmaClient.call().")
    parser.add_argument("command", nargs="?", default="select", choices=("select", "reroll", "inspect", "finish"))
    parser.add_argument("choice", nargs="?", help="finish choice: 1 original, 2 rerolled")
    parser.add_argument("--account", default="A")
    args = parser.parse_args()

    out_dir = ROOT / "uma_runtime" / "captures"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"spark_reroll_{safe_account_name(args.account)}_{args.command}_{time.strftime('%Y%m%d_%H%M%S')}.txt"
    with out_path.open("w", encoding="utf-8") as f, redirect_stdout(Tee(sys.stdout, f)):
        run(args)
        print("\nSaved sanitized output:", out_path)


if __name__ == "__main__":
    main()
