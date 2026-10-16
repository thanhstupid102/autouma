"""Capture the REAL game client's ground-truth `current_succession_rank_point`
value for single_mode_*/start, straight off the wire.

WHY THIS APPROACH (not an il2cpp method hook):
    GameAssembly.dll on disk is packed/virtualized (see
    uma_runtime/re_rankpoint/FINDINGS.md) -- Il2CppDumper's automatic
    CodeRegistration/MetadataRegistration search returns 0/0 against the real
    file, and Codex's Unicorn-based unpacking trace shows classic VM-trampoline
    obfuscation (call / add rsp,8 / xchg[rsp],rax chains) even at the module
    entry point. Statically finding and disassembling "the rank-point method"
    is not a reasonable-effort task on this binary.

    BUT we don't need the method's internals at all: the real client computes
    `current_succession_rank_point` and puts it straight into the
    single_mode_free/start (or single_mode_team/start, for Unity Cup)
    request body, in plaintext (well, AES-encrypted-but-we-have-the-key wire
    format the bot already speaks). The hook named by
    Settings.JS_UMA_NETWORK_HOOKS already hooks the
    game's UnityTls read/write functions (resolved via the exported, NOT
    obfuscated, `il2cpp_unity_install_unitytls_interface`) and hands us every
    outgoing request body. So: let the human play the REAL client, start a
    career with a chosen parent pair, and read the value the client itself
    sent. That's ground truth, no VM-unpacking required.

USAGE:
    1. Close the bot dashboard/server (main.py) if it's running -- only one
       process should be attached to the game via Frida at a time.
    2. Launch Umamusume (UmamusumePrettyDerby.exe) for real, log in, reach Home.
    3. Run:  python scripts/hook_rankpoint.py
    4. In the game, navigate to a career-start flow (Character menu -> Start
       Training, or however your scenario reaches the parent-select screen),
       pick TWO specific parents (note which cards/units you picked -- the
       script only sees opaque trained_chara_id numbers, not card names), and
       press the button that actually commits the start.
    5. The moment the client's start request goes out, this script prints:
           card_id (trainee) / parent_1 trained_chara_id / parent_2
           trained_chara_id (or rental viewer_id:trained_chara_id) /
           current_succession_rank_point (the ground-truth value!)
       and appends a JSON line to
           uma_runtime/re_rankpoint/hook_rankpoint_captures.jsonl
    6. Repeat step 4 for as many parent pairs as you want data points for.
       Ctrl+C to stop -- this script does NOT auto-exit after one capture.

CAVEAT -- this has real in-game side effects: pressing "start" on the parent
select screen actually begins a real career (consumes a career slot / uses up
whatever trainee card you picked). There is no known "preview" endpoint that
reveals current_succession_rank_point without committing. Decide for yourself
whether to use disposable/test trainees, or abandon the career afterward.

CROSS-REFERENCING: this script only gives you opaque succession_trained_chara_id
values. To turn a captured value into a formula data point you still need each
parent's card_id and G1-win count -- read those off the in-game parent-select
screen (it shows the card + evaluation info directly), or cross-reference the
trained_chara_id against the bot's own succession/list data.

Reuses the exact TLS hook (Settings.JS_UMA_NETWORK_HOOKS)
and wire decode (uma_api.client.unpack_request) that scripts/capture_boot.py and
scripts/capture_rental.py already use in this repo -- same proven mechanism,
just filtered/labeled for the rank-point RE task.
"""
import sys
import json
import time
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import frida  # noqa: E402
from core.settings import Settings  # noqa: E402
from uma_api.client import unpack_request  # noqa: E402 (safe import, no side effects)

PROCESS_NAME = Settings.APP_PROCESS_NAME
JS_CODE = Settings.JS_UMA_NETWORK_HOOKS.read_text(encoding="utf-8")

# Both scenario namespaces (MANT / free careers, and Unity Cup team careers) --
# see memory note "Scenario endpoint namespaces": endpoints are namespaced per
# scenario_id, so match by substring rather than an exact endpoint string.
START_MARKERS = ("single_mode_free/start", "single_mode_team/start")
NOISE = {"tool/start_session"}  # heartbeat-ish; skip from the general log

OUT_DIR = ROOT / "uma_runtime" / "re_rankpoint"
ALL_LOG = OUT_DIR / f"hook_rankpoint_all_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
RANKPOINT_LOG = OUT_DIR / "hook_rankpoint_captures.jsonl"

ATTACH_TIMEOUT_SEC = 120


def _extract_start_fields(wire):
    sc = wire.get("start_chara") or {}
    rental = sc.get("rental_succession_trained_chara") or {}
    return {
        "card_id": sc.get("card_id"),
        "scenario_id": sc.get("scenario_id"),
        "parent_1_trained_chara_id": sc.get("succession_trained_chara_id_1"),
        "parent_2_trained_chara_id": sc.get("succession_trained_chara_id_2"),
        "rental_viewer_id": rental.get("viewer_id"),
        "rental_trained_chara_id": rental.get("trained_chara_id"),
        "current_succession_rank_point": wire.get("current_succession_rank_point"),
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Attaching to {PROCESS_NAME} ...", flush=True)
    session = None
    deadline = time.monotonic() + ATTACH_TIMEOUT_SEC
    while time.monotonic() < deadline:
        try:
            session = frida.attach(PROCESS_NAME)
            break
        except Exception:
            time.sleep(1.0)
    if not session:
        print(f"Error: {PROCESS_NAME} not found within {ATTACH_TIMEOUT_SEC}s. "
              f"Launch the game first.", flush=True)
        return 1

    print(f"Attached. All requests -> {ALL_LOG}", flush=True)
    print(f"Rank-point captures  -> {RANKPOINT_LOG}", flush=True)
    print(">>> In game: navigate to career start, pick two parents, press start.", flush=True)

    counts = {"all": 0, "rankpoint": 0}

    def on_message(message, data):
        if message.get("type") == "error":
            print(f"Frida error: {message.get('description')}", flush=True)
            return
        payload = message.get("payload") or {}
        if payload.get("type") != "creds":
            return
        ep = payload.get("endpoint", "")
        if ep in NOISE:
            return
        udid = payload.get("udid") or ""
        body = payload.get("body") or ""
        try:
            wire = unpack_request(body, udid)
        except Exception as exc:
            print(f"[{ep}] decode failed: {exc}", flush=True)
            return

        counts["all"] += 1
        with open(ALL_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(
                {"ts": time.time(), "endpoint": ep, "payload": wire},
                ensure_ascii=False, default=str,
            ) + "\n")

        is_start = any(marker in ep for marker in START_MARKERS)
        if not is_start:
            print(f"[{counts['all']:3}] {ep}", flush=True)
            return

        fields = _extract_start_fields(wire)
        counts["rankpoint"] += 1
        record = {
            "n": counts["rankpoint"],
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "endpoint": ep,
            **fields,
        }
        with open(RANKPOINT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

        print("\n" + "=" * 60, flush=True)
        print(f"*** GROUND-TRUTH CAPTURE #{counts['rankpoint']}  ({ep}) ***", flush=True)
        print(f"    trainee card_id            = {fields['card_id']}", flush=True)
        print(f"    parent_1 trained_chara_id  = {fields['parent_1_trained_chara_id']}", flush=True)
        if fields["rental_trained_chara_id"]:
            print(f"    parent_2 = RENTAL viewer_id={fields['rental_viewer_id']} "
                  f"trained_chara_id={fields['rental_trained_chara_id']}", flush=True)
        else:
            print(f"    parent_2 trained_chara_id  = {fields['parent_2_trained_chara_id']}", flush=True)
        print(f"    current_succession_rank_point = {fields['current_succession_rank_point']}   <-- GROUND TRUTH", flush=True)
        print("=" * 60 + "\n", flush=True)

    try:
        script = session.create_script(JS_CODE)
        script.on("message", on_message)
        script.load()
        print("Hook loaded. Waiting for career-start requests. Ctrl+C to stop.\n", flush=True)
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print(f"\nStopped. {counts['rankpoint']} rank-point capture(s), "
              f"{counts['all']} request(s) total.", flush=True)
        print(f"Rank-point data -> {RANKPOINT_LOG}", flush=True)
    finally:
        try:
            session.detach()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
