"""Discord webhook notifications for finished careers.

The webhook URL is stored in <state_root>/discord.json so it never
reaches the repo. Sending uses only the standard library (urllib), so no extra
dependency is needed.
"""

import gzip
import json
import logging
import re
import tempfile
import threading
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import core.operational_time as operational_time
from career_bot.outcomes import career_failed, career_retry_block_reason
from core.settings import Settings
from uma_api.diagnostics import safe_payload
from uma_api.trace import iter_trace_records
from core.runtime_paths import (
    atomic_write_private_text,
    resolve_master_json_path,
    resolve_state_root,
)

# `_log` (not `log`): _build_embed() binds a local `log` for the snapshot's
# recent-log rows, so the module-level name would be shadowed there.
_log = logging.getLogger(__name__)

_USER_AGENT = "career-webhook/1.0"
_TRACE_CHUNK_BYTES = 1024 * 1024
_TRACE_TAIL_CHUNK_RECORDS = 32
_ATTACHMENT_FALLBACK_STATUSES = {400, 413, 415, 422}
_DISCORD_SNOWFLAKE_RE = re.compile(r"^[0-9]{17,20}$")
_DISCORD_MENTION_RE = re.compile(r"^<@(?P<marker>[!&]?)(?P<id>[0-9]{17,20})>$")
_TRACE_PRIVATE_PATH_SUFFIXES = (
    ("device_name",),
    ("graphics_device_name",),
    ("ip_address",),
    ("platform_os_version",),
    ("user_info", "name"),
    ("circle_info", "name"),
    ("race_start_info", "race_horse_data", "trainer_name"),
    ("race_start_info", "race_horse_data", "owner_trainer_name"),
    ("team_data_set", "race_result_array", "race_horse_data_array", "trainer_name"),
    ("team_data_set", "race_result_array", "race_horse_data_array", "owner_trainer_name"),
)
_TRACE_PRIVATE_ENDPOINT_PATH_SUFFIXES = {
    "account/get_by_transition_code": (
        ("data", "name"),
        ("data", "request_user_name"),
    ),
    "account/chain_by_transition_code": (
        ("data", "chained_user_name"),
    ),
}


def _traceback_frames(stack_trace, limit=3):
    lines = str(stack_trace or "").splitlines()
    frames = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.lstrip().startswith('File "'):
            frame = [line.strip()]
            if index + 1 < len(lines):
                source = lines[index + 1]
                if source.startswith("    ") and not source.lstrip().startswith('File "'):
                    frame.append(source.strip())
                    index += 1
            frames.append("\n".join(frame))
        index += 1
    return "\n".join(frames[-max(1, int(limit)):])


def _trace_private_path(path, endpoint):
    suffixes = _TRACE_PRIVATE_PATH_SUFFIXES + (
        _TRACE_PRIVATE_ENDPOINT_PATH_SUFFIXES.get(endpoint) or ()
    )
    return any(len(path) >= len(suffix) and path[-len(suffix):] == suffix
               for suffix in suffixes)


def _redact_trace_upload(value, endpoint="", path=()):
    """Remove private identity fields from the webhook-only trace copy."""
    if isinstance(value, dict):
        redacted = {}
        for key, child in value.items():
            child_path = path + (str(key),)
            if _trace_private_path(child_path, endpoint):
                redacted[key] = "<redacted>"
            else:
                redacted[key] = _redact_trace_upload(
                    child, endpoint=endpoint, path=child_path,
                )
        return redacted
    if isinstance(value, list):
        return [
            _redact_trace_upload(item, endpoint=endpoint, path=path)
            for item in value
        ]
    return value


def _gzip_redacted_candidate(
    raw_file,
    start_offset,
    marker,
    spool_limit,
    end_offset=None,
):
    output = tempfile.SpooledTemporaryFile(max_size=max(1024, int(spool_limit)))
    try:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            compresslevel=6,
            fileobj=output,
            mtime=0,
        ) as compressed:
            if marker is not None:
                compressed.write(
                    json.dumps(
                        marker,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8") + b"\n",
                )
            raw_file.seek(start_offset)
            remaining = (
                None
                if end_offset is None
                else max(0, int(end_offset) - int(start_offset))
            )
            while True:
                read_size = _TRACE_CHUNK_BYTES
                if remaining is not None:
                    if remaining <= 0:
                        break
                    read_size = min(read_size, remaining)
                chunk = raw_file.read(read_size)
                if not chunk:
                    break
                compressed.write(chunk)
                if remaining is not None:
                    remaining -= len(chunk)
        size = output.tell()
        return output, size
    except Exception:
        output.close()
        raise


def _tail_marker(start, record_count):
    return {
        "type": "discord_trace_tail",
        "message": "Earlier records were dropped to fit the Discord attachment limit.",
        "dropped_records": start,
        "retained_records": record_count - start,
    }


def _gzip_redacted_tail(raw_file, offsets, max_bytes):
    """Return the earliest fitting suffix without monotonic-size assumptions.

    Large inputs are split into independent gzip members of at most 32 records.
    Each record is recompressed at most 32 times while its chunk is searched, so
    the work is linear in input bytes for that fixed chunk size, not quadratic.
    """
    record_count = len(offsets) - 1
    chunk_file = tempfile.TemporaryFile()
    chunks = []
    try:
        for chunk_start in range(0, record_count, _TRACE_TAIL_CHUNK_RECORDS):
            chunk_end = min(
                record_count,
                chunk_start + _TRACE_TAIL_CHUNK_RECORDS,
            )
            member, member_size = _gzip_redacted_candidate(
                raw_file,
                offsets[chunk_start],
                None,
                max_bytes + 1,
                end_offset=offsets[chunk_end],
            )
            try:
                member.seek(0)
                store_offset = chunk_file.tell()
                while True:
                    data = member.read(_TRACE_CHUNK_BYTES)
                    if not data:
                        break
                    chunk_file.write(data)
            finally:
                member.close()
            chunks.append({
                "start": chunk_start,
                "end": chunk_end,
                "size": member_size,
                "store_offset": store_offset,
            })

        suffix_sizes = [0] * (len(chunks) + 1)
        for index in range(len(chunks) - 1, -1, -1):
            suffix_sizes[index] = suffix_sizes[index + 1] + chunks[index]["size"]

        for start in range(1, record_count + 1):
            marker = _tail_marker(start, record_count)
            if start == record_count:
                chunk_index = len(chunks)
                prefix, prefix_size = _gzip_redacted_candidate(
                    raw_file,
                    offsets[start],
                    marker,
                    max_bytes + 1,
                    end_offset=offsets[start],
                )
                later_size = 0
            else:
                chunk_index = start // _TRACE_TAIL_CHUNK_RECORDS
                chunk_end = chunks[chunk_index]["end"]
                prefix, prefix_size = _gzip_redacted_candidate(
                    raw_file,
                    offsets[start],
                    marker,
                    max_bytes + 1,
                    end_offset=offsets[chunk_end],
                )
                later_size = suffix_sizes[chunk_index + 1]
            total_size = prefix_size + later_size
            if total_size > max_bytes:
                prefix.close()
                continue
            try:
                prefix.seek(0)
                data = prefix.read()
            finally:
                prefix.close()
            if chunk_index < len(chunks) - 1:
                chunk_file.seek(chunks[chunk_index + 1]["store_offset"])
                data += chunk_file.read()
            return data, start
        return None
    finally:
        chunk_file.close()


def _redacted_trace_attachment(path, max_bytes):
    """Create a redacted gzip copy, retaining the newest records if oversized."""
    source = Path(path)
    if not source.is_file():
        _log.warning("Discord trace attachment missing: %s", source)
        return None
    max_bytes = int(max_bytes)
    if max_bytes <= 0:
        return None

    raw_file = tempfile.TemporaryFile()
    offsets = [0]
    try:
        for record in iter_trace_records(source):
            endpoint = str(record.get("endpoint") or "")
            line = json.dumps(
                _redact_trace_upload(
                    safe_payload(record), endpoint=endpoint,
                ),
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8") + b"\n"
            raw_file.write(line)
            offsets.append(raw_file.tell())
        record_count = len(offsets) - 1
        if record_count == 0:
            _log.warning("Discord trace attachment has no readable records: %s", source)
            return None

        full, full_size = _gzip_redacted_candidate(
            raw_file,
            0,
            None,
            max_bytes + 1,
        )
        if full_size <= max_bytes:
            try:
                full.seek(0)
                data = full.read()
            finally:
                full.close()
            filename = "career_api_trace_redacted.jsonl.gz"
            return filename, data, 0
        full.close()

        tail_result = _gzip_redacted_tail(raw_file, offsets, max_bytes)
        if tail_result is None:
            _log.warning(
                "Discord trace attachment limit %d is too small for a tail marker",
                max_bytes,
            )
            return None
        data, best_start = tail_result
        filename = "career_api_trace_redacted_tail.jsonl.gz"
        return filename, data, best_start
    except Exception as exc:
        _log.warning("Discord trace redaction failed: %s", exc)
        return None
    finally:
        raw_file.close()


def _multipart_body(payload, filename, file_data):
    boundary = f"----discord-webhook-{uuid.uuid4().hex}"
    safe_name = str(filename).replace('"', "_").replace("\r", "_").replace("\n", "_")
    payload_json = json.dumps(payload).encode("utf-8")
    body = b"".join([
        f"--{boundary}\r\n".encode("ascii"),
        b'Content-Disposition: form-data; name="payload_json"\r\n',
        b"Content-Type: application/json\r\n\r\n",
        payload_json,
        b"\r\n",
        f"--{boundary}\r\n".encode("ascii"),
        (
            'Content-Disposition: form-data; name="files[0]"; '
            f'filename="{safe_name}"\r\n'
        ).encode("utf-8"),
        b"Content-Type: application/gzip\r\n\r\n",
        file_data,
        b"\r\n",
        f"--{boundary}--\r\n".encode("ascii"),
    ])
    return body, f"multipart/form-data; boundary={boundary}"


def _post_webhook(url, data, content_type):
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": content_type, "User-Agent": _USER_AGENT},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            code = int(getattr(resp, "status", None) or resp.getcode())
            return 200 <= code < 300, code
    except urllib.error.HTTPError as exc:
        _log.warning("Discord webhook failed: HTTP %s", exc.code)
        return False, int(exc.code)
    except Exception as exc:
        _log.warning(f"Discord webhook failed: {exc}")
        return False, None


def _discord_path(state_root):
    return Path(state_root) / "discord.json"


def _read_config(state_root):
    path = _discord_path(state_root)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    # read_text -> OSError / UnicodeDecodeError(ValueError); json.loads -> ValueError.
    except (OSError, ValueError):
        return {}


def _write_config(state_root, cfg):
    path = _discord_path(state_root)
    atomic_write_private_text(path, json.dumps(cfg, indent=2))


def get_webhook_url(state_root):
    return str(_read_config(state_root).get("webhook_url") or "").strip()


def set_webhook_url(state_root, url):
    cfg = _read_config(state_root)
    cfg["webhook_url"] = str(url or "").strip()
    _write_config(state_root, cfg)
    return True


def normalize_error_mention(value):
    """Return the canonical stored form for a Discord user or role target."""
    candidate = str(value or "").strip()
    match = _DISCORD_MENTION_RE.fullmatch(candidate)
    if match:
        marker = match.group("marker")
        return {
            "kind": "role" if marker == "&" else "user",
            "id": match.group("id"),
        }
    if _DISCORD_SNOWFLAKE_RE.fullmatch(candidate):
        return {"kind": "user", "id": candidate}
    raise ValueError(
        "Enter a 17-20 digit Discord user ID, user mention, or role mention."
    )


def get_error_mention(state_root):
    target = _read_config(state_root).get("error_mention")
    if not isinstance(target, dict):
        return None
    kind = target.get("kind")
    target_id = target.get("id")
    if kind not in {"user", "role"}:
        return None
    if not isinstance(target_id, str) or not _DISCORD_SNOWFLAKE_RE.fullmatch(target_id):
        return None
    return {"kind": kind, "id": target_id}


def set_error_mention(state_root, target):
    cfg = _read_config(state_root)
    cfg["error_mention"] = {
        "kind": target["kind"],
        "id": target["id"],
    }
    _write_config(state_root, cfg)


def clear_error_mention(state_root):
    cfg = _read_config(state_root)
    cfg.pop("error_mention", None)
    _write_config(state_root, cfg)


def format_error_mention(target):
    target_id = target["id"]
    return f"<@&{target_id}>" if target["kind"] == "role" else f"<@{target_id}>"


def get_account_name(state_root):
    return str(_read_config(state_root).get("account_name") or "").strip()


def uma_name(base_dir, card_id, state_root=None):
    if not card_id:
        return None
    try:
        path = resolve_master_json_path(
            base_dir, "chara_list.json", state_root,
        )
        names = json.loads(path.read_text(encoding="utf-8"))
        return names.get(str(card_id))
    # Path()/read_text -> TypeError / OSError / UnicodeDecodeError(ValueError);
    # json.loads -> ValueError; .get() on a non-mapping payload -> AttributeError.
    except (OSError, TypeError, ValueError, AttributeError) as exc:
        _log.warning(f"Uma name lookup failed: {exc}")
        return None


_SPARK_CAT_ORDER = ["stat", "aptitude", "unique", "skill", "race", "scenario", "other"]
_SPARK_CAT_LABEL = {
    "stat": "📊 Stat", "aptitude": "🎯 Aptitude", "unique": "🌟 Unique",
    "skill": "💡 Skill", "race": "🏆 Race", "scenario": "📖 Scenario", "other": "🔹 Other",
}
# Ids 19-98 are the U-ranks: each letter has 10 steps (UG, UG1..UG9, then
# UF, UF1..UF9, ...). 18 base ranks + 8 letters x 10 steps = 98, exactly the
# id count of master.mdb single_mode_rank. The old map treated 20/21/22 as
# UF/UE/UD, mislabelling what are really UG1/UG2/UG3.
_RANK_MAP = {
    1: "G", 2: "G+", 3: "F", 4: "F+", 5: "E", 6: "E+", 7: "D", 8: "D+",
    9: "C", 10: "C+", 11: "B", 12: "B+", 13: "A", 14: "A+", 15: "S",
    16: "S+", 17: "SS", 18: "SS+",
}
for _i, _letter in enumerate("GFEDCBAS"):
    _base = 19 + _i * 10
    _RANK_MAP[_base] = f"U{_letter}"
    for _step in range(1, 10):
        _RANK_MAP[_base + _step] = f"U{_letter}{_step}"


def resolve_sparks(base_dir, factor_ids, state_root=None):
    """Turn factor ids (inheritance sparks) into {name, stars, category} via
    data/factor_map.json. Unknown ids are skipped."""
    if not factor_ids:
        return []
    try:
        path = resolve_master_json_path(
            base_dir, "factor_map.json", state_root,
        )
        fm = json.loads(path.read_text(encoding="utf-8"))
    # Path()/read_text -> TypeError / OSError / UnicodeDecodeError(ValueError);
    # json.loads -> ValueError.
    except (OSError, TypeError, ValueError) as exc:
        _log.warning(f"Spark lookup failed: {exc}")
        return []
    out = []
    for fid in factor_ids:
        e = fm.get(str(fid))
        if e and e.get("name"):
            out.append({
                "name": e["name"],
                "stars": int(e.get("stars") or 0),
                "category": e.get("category") or "other",
            })
    return out


def _format_sparks(sparks):
    by_cat: dict[str, list[str]] = {}
    for s in sparks:
        stars = max(1, min(3, int(s.get("stars") or 1)))
        by_cat.setdefault(s.get("category") or "other", []).append(f"{s['name']} {'★' * stars}")
    lines = []
    for cat in _SPARK_CAT_ORDER:
        if by_cat.get(cat):
            lines.append(f"**{_SPARK_CAT_LABEL.get(cat, cat)}:** " + " · ".join(by_cat[cat]))
    return "\n".join(lines)


def _format_reroll_sparks(spark_lists, choice):
    original, rerolled = (list(spark_lists or []) + [[], []])[:2]
    picked = {1: "Original", 2: "Rerolled"}.get(int(choice or 0), "?")
    choice_line = f"🤖 Bot chose: **{picked}**"
    text = "\n\n".join([
        f"**Original**\n{_format_sparks(original) or '—'}",
        f"**Rerolled:**\n{_format_sparks(rerolled) or '—'}",
        choice_line,
    ])
    if len(text) <= 1024:
        return text
    # ponytail: one Discord field only; upgrade to multiple fields if clipped lists matter.
    return "\n".join([text[:1024 - len(choice_line) - 2] + "…", choice_line])


def _retry_attempt_text(summary):
    attempt = int(summary.get("resume_attempt") or 0)
    limit = int(summary.get("resume_attempt_limit") or 0)
    block_reason = career_retry_block_reason(summary)
    failed = career_failed(summary)
    if attempt > 0 and limit > 0:
        text = f"{attempt}/{limit}"
        if failed and (block_reason or attempt >= limit):
            text += " - FINAL; no automatic retries remain"
            if block_reason:
                text += f" ({block_reason})"
        return text
    if failed and block_reason:
        return f"FINAL; automatic retry disabled ({block_reason})"
    return ""


def _build_embed(summary):
    status = str(summary.get("status") or "?")
    failed = career_failed(summary)
    color = {"finished": 0x2ECC71, "stopped": 0xF1C40F, "error": 0xE74C3C}.get(status, 0x95A5A6)
    title = {
        "finished": "🏁 Career Finished",
        "stopped": "⏹️ Career Stopped",
        "error": "⚠️ Career Error",
    }.get(status, "Career")
    if failed and status == "stopped":
        color = 0xE74C3C
        title = "⚠️ Career Automatically Aborted"
    stats = summary.get("stats") or {}
    fans = int(summary.get("fans") or stats.get("fans") or 0)

    description = ""
    if summary.get("account"):
        description += f"👤 Account **{summary['account']}** · "
    description += f"**{summary.get('uma_name') or 'Unknown'}**"
    if summary.get("preset"):
        description += f" · `{summary['preset']}`"
    loop_target = int(summary.get("loop_target") or 0)
    if loop_target != 1:
        description += f" · 🔁 Run {int(summary.get('loop_index') or 1)}/{'∞' if loop_target == 0 else loop_target}"

    status_dot = {"finished": "🟢", "stopped": "🟡", "error": "🔴"}.get(status, "⚪")
    status_text = status.capitalize()
    if failed and status == "stopped":
        status_dot = "🔴"
        status_text = "Automatic abort"
    fields = [
        {"name": "📋 Status", "value": f"{status_dot} {status_text}", "inline": True},
        {"name": "🔄 Turn", "value": str(summary.get("final_turn") or 0), "inline": True},
        {"name": "⏱️ Duration", "value": str(summary.get("duration") or "?"), "inline": True},
        {"name": "📣 Total Fans", "value": f"{fans:,}", "inline": True},
        {"name": "💎 Skill Point", "value": str(stats.get("skill_point", 0)), "inline": True},
        {"name": "🎓 Skills Bought", "value": str(summary.get("skills_bought", 0)), "inline": True},
        {
            "name": "📊 Stats",
            "value": "⚡ SPD **{}** · 🫀 STA **{}** · 💪 PWR **{}** · 🔥 GUT **{}** · 🧠 WIT **{}**".format(
                stats.get("speed", 0), stats.get("stamina", 0), stats.get("power", 0),
                stats.get("guts", 0), stats.get("wit", 0),
            ),
            "inline": False,
        },
        {"name": "🏇 Races", "value": str(summary.get("races", 0)), "inline": True},
    ]
    retry_text = _retry_attempt_text(summary)
    if retry_text:
        fields.insert(1, {
            "name": "Resume Attempt",
            "value": retry_text[:1024],
            "inline": True,
        })
    if failed and status == "stopped":
        # `abort_reason` is supplied only for the runner's local auto-backoff
        # message, not from a server response.
        abort_reason = str(summary.get("abort_reason") or "")
        if abort_reason:
            fields.append({
                "name": "Abort Reason",
                "value": abort_reason[:1024],
                "inline": False,
            })
    rank_int = int(summary.get("rank") or 0)
    rank_score = int(summary.get("rank_score") or 0)
    if rank_int or rank_score:
        grade = _RANK_MAP.get(rank_int, "?")
        fields.append({"name": "🏅 Rating", "value": f"**{grade}** · {rank_score:,} pts", "inline": True})
    reroll_sparks = summary.get("spark_reroll_sparks") or []
    if len(reroll_sparks) >= 2 and (reroll_sparks[0] or reroll_sparks[1]):
        spark_text = _format_reroll_sparks(reroll_sparks, summary.get("spark_reroll_choice"))
        fields.append({"name": "✨ Sparks (original | rerolled)", "value": spark_text, "inline": False})
    else:
        sparks = summary.get("sparks") or []
        if sparks:
            spark_text = _format_sparks(sparks)
            if spark_text:
                fields.append({"name": "✨ Sparks (inheritance factors)", "value": spark_text[:1024], "inline": False})
    if status == "error":
        failure = summary.get("api_failure") or {}
        endpoint = str(failure.get("endpoint") or "unknown")
        result_code = failure.get("result_code")
        turn = failure.get("turn")
        failure_bits = [f"Endpoint `{endpoint}`"]
        if result_code is not None:
            failure_bits.append(f"result_code `{result_code}`")
        if turn is not None:
            failure_bits.append(f"turn `{turn}`")
        failure_text = " · ".join(failure_bits)
        fields.append({
            "name": "Failed API Call",
            "value": failure_text[:1024],
            "inline": False,
        })

        error = summary.get("error") or {}
        fields.append({
            "name": "Exception",
            "value": f"`{str(error.get('type') or 'Unknown')[:200]}`",
            "inline": False,
        })
        frame_text = _traceback_frames(error.get("stack_trace"))
        if frame_text:
            fields.append({
                "name": "Last Traceback Frames",
                "value": ("```text\n" + frame_text[:980] + "\n```")[:1024],
                "inline": False,
            })
    embed = {
        "title": title,
        "description": description,
        "color": color,
        "fields": fields,
    }
    try:
        ts = operational_time.utc_iso_seconds()
        if ts:
            embed["timestamp"] = ts
    except ValueError:
        pass
    return embed


_LIVE_STATUS_META = {
    "running":  (0x2ECC71, "🟢", "Running"),
    "paused":   (0xF1C40F, "⏸️", "Paused"),
    "finished": (0x3498DB, "🏁", "Finished"),
    "stopped":  (0xF1C40F, "⏹️", "Stopped"),
    "error":    (0xE74C3C, "⚠️", "Error"),
}

_MOOD_LABELS = {5: "Perfect ✨", 4: "Great", 3: "Normal", 2: "Bad", 1: "Awful"}

_ACTION_EMOJI = {
    "train": "💪", "race": "🐎", "rest": "🛌", "recreation": "🎉",
    "medic": "🏥", "finish": "🏁", "skills": "🎓", "started": "▶️",
    "pause": "⏸️", "resume": "▶️",
}


def _bar(value, total, width=12):
    total = max(1, int(total or 0))
    filled = max(0, min(width, round(width * (int(value or 0) / total))))
    return "█" * filled + "░" * (width - filled)


def _mood_stars(motivation):
    n = max(0, min(5, int(motivation or 0)))
    return "⭐" * n + "·" * (5 - n)


def _latest_stats(snapshot):
    hist = snapshot.get("action_history") or []
    for row in reversed(hist):
        if row.get("stats"):
            return row["stats"]
    return {}


def _live_action_label(snapshot):
    """Human-friendly last action. Prefer action_history (has action + facility,
    e.g. 'train Wit', 'race Yasuda Kinen') over the raw status['last_action']
    (which can be a bare 'command')."""
    hist = snapshot.get("action_history") or []
    if hist:
        row = hist[-1]
        action = str(row.get("action") or "").strip()
        facility = str(row.get("facility") or "").strip()
        label = (f"{action} {facility}").strip()
        if label:
            return action, label
    raw = str(snapshot.get("last_action") or "").strip()
    return raw, (raw or "—")


def _build_live_embed(snapshot, base_dir=None, state_root=None):
    status = str(snapshot.get("status") or "").strip()
    if not status:
        status = "paused" if snapshot.get("paused") else ("running" if snapshot.get("running") else "?")
    failed = career_failed({**snapshot, "status": status})
    color, dot, status_label = _LIVE_STATUS_META.get(status, (0x95A5A6, "⚪", status or "—"))
    if failed and status == "stopped":
        color, dot, status_label = 0xE74C3C, "🔴", "Automatically Aborted"

    stats = _latest_stats(snapshot)
    turn = int(snapshot.get("turn") or 0)
    total = int(snapshot.get("total_turns") or 78)
    pct = round(100 * turn / max(1, total), 1)

    trainee = ""
    if base_dir and snapshot.get("card_id"):
        trainee = uma_name(
            base_dir, snapshot.get("card_id"), state_root,
        ) or ""

    desc_bits = []
    if snapshot.get("account"):
        desc_bits.append(f"👤 **{snapshot['account']}**")
    if trainee:
        desc_bits.append(f"🐎 **{trainee}**")
    if snapshot.get("preset"):
        desc_bits.append(f"`{snapshot['preset']}`")
    loop_target = int(snapshot.get("loop_target") or 0)
    loop_index = int(snapshot.get("loop_index") or 1)
    desc_bits.append(f"🔁 Run {loop_index}/{'∞' if loop_target == 0 else loop_target}")
    description = " · ".join(desc_bits) or "—"

    energy = int(stats.get("hp") or 0)
    max_energy = int(stats.get("max_hp") or 0)
    if max_energy:
        energy_line = f"{_bar(energy, max_energy)} {energy}/{max_energy} ({round(100 * energy / max_energy)}%)"
    else:
        energy_line = "—"

    motivation = int(stats.get("motivation") or 0)
    mood = f"{_mood_stars(motivation)} {_MOOD_LABELS.get(motivation, '')}".strip()

    action_key, action_label = _live_action_label(snapshot)
    action_emoji = _ACTION_EMOJI.get(action_key, "•")

    stats_line = "💨 SPD **{}** · 🫀 STA **{}** · 💪 PWR **{}** · 🔥 GUT **{}** · 🧠 WIT **{}**".format(
        stats.get("speed", 0), stats.get("stamina", 0), stats.get("power", 0),
        stats.get("guts", 0), stats.get("wit", 0),
    )
    purchases_line = "🎓 Skills **{}** · 🎒 Items **{}** (used {}) · ⏰ Clocks **{}**".format(
        snapshot.get("skills_bought", 0), snapshot.get("items_bought", 0),
        snapshot.get("items_used", 0), snapshot.get("clocks_used", 0),
    )

    fields = [
        {"name": "Status", "value": f"{dot} {status_label}", "inline": True},
        {"name": "Turn / Steps", "value": f"{turn} / {total}  ·  {snapshot.get('steps', 0)} steps", "inline": True},
        {"name": "✨ Skill Pt", "value": str(stats.get("skill_point") or 0), "inline": True},
        {"name": "Last Action", "value": f"{action_emoji} {action_label}", "inline": False},
        {"name": "⚡ Energy", "value": energy_line, "inline": True},
        {"name": "😊 Mood", "value": mood or "—", "inline": True},
        {"name": "📊 Stats", "value": stats_line, "inline": False},
        {"name": "🛒 Purchases", "value": purchases_line, "inline": False},
        {"name": f"📈 Progress · {turn}/{total} turns · {pct}%", "value": _bar(turn, total, width=20), "inline": False},
    ]
    if failed and status == "stopped":
        # The live snapshot gets this value from the local circuit-breaker path.
        abort_reason = str(snapshot.get("last_error") or "")
        if abort_reason:
            fields.append({"name": "Abort Reason", "value": abort_reason[:1024], "inline": False})

    log = snapshot.get("log") or []
    if log:
        recent = log[-7:]
        lines = [f"`{e.get('time', '')}` T{e.get('turn', 0)} **{e.get('action', '')}** {e.get('detail', '')}".rstrip()
                 for e in recent]
        text = "\n".join(lines)[:1024]
        fields.append({"name": "📋 Recent Log", "value": text or "—", "inline": False})

    return {
        "title": "🐎 Uma Musume Career Bot",
        "description": description,
        "color": color,
        "fields": fields,
        "footer": {"text": "Polling every 10s"},
    }


class LiveMonitor:
    """Self-updating Discord message for a running career (webhook transport).

    POSTs the first frame with ?wait=true to learn the message id, then PATCHes
    that message on a fixed interval. All network errors are swallowed so the
    monitor can never crash a career. message id lives in RAM only.
    """

    def __init__(
        self,
        source_root,
        state_root,
        snapshot_fn=None,
        interval=10.0,
    ):
        if snapshot_fn is None and callable(state_root):
            snapshot_fn = state_root
            state_root = resolve_state_root(source_root).root
        self.source_root = source_root
        self.state_root = state_root
        self.snapshot_fn = snapshot_fn
        self.interval = float(interval)
        self.url = get_webhook_url(state_root)
        self.message_id = None
        self._stop = threading.Event()
        self._thread = None
        self._dead = False  # set on 404 (message deleted) -> stop patching

    def _post_first(self, snapshot):
        payload = {
            "embeds": [
                _build_live_embed(snapshot, self.source_root, self.state_root)
            ]
        }
        data = json.dumps(payload).encode("utf-8")
        sep = "&" if "?" in self.url else "?"
        req = urllib.request.Request(
            self.url + sep + "wait=true", data=data,
            headers={"Content-Type": "application/json", "User-Agent": _USER_AGENT},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8") or "{}"
        self.message_id = str((json.loads(body) or {}).get("id") or "") or None

    def _patch(self, snapshot):
        if not self.message_id or self._dead:
            return
        payload = {
            "embeds": [
                _build_live_embed(snapshot, self.source_root, self.state_root)
            ]
        }
        data = json.dumps(payload).encode("utf-8")
        url = f"{self.url}/messages/{self.message_id}"
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json", "User-Agent": _USER_AGENT},
            method="PATCH",
        )
        try:
            with urllib.request.urlopen(req, timeout=10):
                pass
        except urllib.error.HTTPError as exc:
            if getattr(exc, "code", None) == 404:
                self._dead = True
        except Exception:
            pass  # transient; retry next tick

    def start(self):
        if not self.url:
            return self  # no webhook -> no-op
        try:
            self._post_first(self.snapshot_fn() or {})
        except Exception as exc:
            _log.warning(f"Live monitor POST failed: {type(exc).__name__}")
            self.message_id = None
            return self
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def _loop(self):
        while not self._stop.wait(self.interval):
            try:
                self._patch(self.snapshot_fn() or {})
            except Exception:
                pass

    def stop(self, final_snapshot=None):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=12.0)
        if self.url and self.message_id and not self._dead:
            try:
                self._patch(final_snapshot or (self.snapshot_fn() or {}))
            except Exception:
                pass


def start_live_monitor(
    source_root,
    state_root,
    snapshot_fn=None,
    interval=10.0,
):
    """Create + start a LiveMonitor. Always returns a handle (no-op if no webhook)."""
    if snapshot_fn is None and callable(state_root):
        snapshot_fn = state_root
        state_root = resolve_state_root(source_root).root
    return LiveMonitor(
        source_root,
        state_root,
        snapshot_fn,
        interval=interval,
    ).start()


def stop_live_monitor(monitor, final_snapshot=None):
    if monitor is None:
        return
    try:
        monitor.stop(final_snapshot)
    except Exception as exc:
        _log.warning(f"Live monitor stop failed: {type(exc).__name__}")


def send_alert(state_root, title, message):
    """Best-effort POST of a simple one-embed operational alert."""
    url = get_webhook_url(state_root)
    if not url:
        return False
    payload = {
        "embeds": [{
            "title": str(title or "Umamusume bot alert")[:256],
            "description": str(message or "")[:4096],
            "color": 0xE6A23C,
        }]
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": _USER_AGENT},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
            return 200 <= int(code) < 300
    except Exception as exc:
        _log.warning(f"Discord alert failed: {exc}")
        return False


def send_career_summary(
    source_root,
    state_root,
    summary=None,
    attachment_path=None,
):
    """POST a career-summary embed to the configured Discord webhook.

    Returns True on success, False if no webhook is configured or the request
    fails (failures are swallowed so they never crash a finished career)."""
    if summary is None:
        summary = state_root
        state_root = resolve_state_root(source_root).root
    url = get_webhook_url(state_root)
    if not url:
        return False
    summary = dict(summary or {})
    # An explicit operator-authored display name overrides the local account identity
    # without changing the identity used for report and trace filenames.
    label = get_account_name(state_root)
    if label:
        summary["account"] = label
    if not summary.get("uma_name") and summary.get("card_id"):
        summary["uma_name"] = uma_name(
            source_root, summary.get("card_id"), state_root,
        )
    if "sparks" not in summary:
        summary["sparks"] = resolve_sparks(
            source_root,
            summary.get("factor_ids") or [],
            state_root,
        )
    if "spark_reroll_sparks" not in summary and summary.get("spark_reroll_factor_ids"):
        summary["spark_reroll_sparks"] = [
            resolve_sparks(source_root, ids, state_root)
            for ids in summary.get("spark_reroll_factor_ids") or []
        ]
    payload: dict[str, object] = {"embeds": [_build_embed(summary)]}
    attachment = None
    if career_failed(summary):
        mention_target = get_error_mention(state_root)
        if mention_target is not None:
            target_id = mention_target["id"]
            target_field = "roles" if mention_target["kind"] == "role" else "users"
            account = str(summary.get("account") or "Unknown account")[:100]
            message = "career stopped with an error."
            if str(summary.get("status") or "") == "stopped":
                message = "career automatically aborted."
            retry_text = _retry_attempt_text(summary)
            if retry_text:
                message += f" Resume attempt {retry_text}."
            payload["content"] = (
                f"{format_error_mention(mention_target)} Account {account}: {message}"
            )
            payload["allowed_mentions"] = {
                "parse": [],
                target_field: [target_id],
            }
        if attachment_path is not None:
            attachment = _redacted_trace_attachment(
                attachment_path,
                Settings.UMA_DISCORD_CAREER_TRACE_MAX_BYTES,
            )
    json_data = json.dumps(payload).encode("utf-8")
    if attachment is not None:
        filename, file_data, _dropped_records = attachment
        data, content_type = _multipart_body(payload, filename, file_data)
        sent, status = _post_webhook(url, data, content_type)
        if sent:
            return True
        if status not in _ATTACHMENT_FALLBACK_STATUSES:
            return False
        _log.warning(
            "Discord rejected trace attachment with HTTP %d; retrying embed only",
            status,
        )
    sent, _status = _post_webhook(url, json_data, "application/json")
    return sent
