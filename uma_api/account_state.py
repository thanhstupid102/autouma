"""Client-side helpers for account state echoed by the server.

Every response may carry a slice of the player's account (TP, coins, item
counts). This keeps the transport's cached copy current. The functions take the
cache *holder* rather than owning the dicts themselves, because
``cached_load_data`` / ``tp_info`` / ``coin_info`` / ``item_map`` are read
directly off ``UmaClient`` all over the bot and must stay plain attributes there.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any


ITEM_LIST_KEYS = ('user_item', 'user_item_array', 'item_list')
ITEM_COUNT_KEYS = ('number', 'num', 'current_num', 'item_num')


class AccountPlayVerdict(str, Enum):
    """One-way result for whether account history is proven by a payload."""

    PLAYED = "PLAYED"
    UNVERIFIED = "UNVERIFIED"


class AccountPlaySignal(str, Enum):
    """Payload facts that can contribute to a played-account verdict."""

    TUTORIAL_COMPLETE = "tutorial_complete"
    TRAINED_CAREER_RECORDS = "trained_career_records"
    FAN_COUNT = "fan_count"
    RANK_SCORE = "rank_score"
    OWNED_CHARACTERS = "owned_characters"
    OWNED_SUPPORT_CARDS = "owned_support_cards"
    UNLOCKED_EPISODES = "unlocked_episodes"


@dataclass(frozen=True)
class AccountPlayEvidence:
    """A single observed play-history signal and its payload value."""

    signal: AccountPlaySignal
    value: int


@dataclass(frozen=True)
class AccountPlayClassification:
    """A one-way play-history verdict plus the evidence behind it."""

    verdict: AccountPlayVerdict
    evidence: tuple[AccountPlayEvidence, ...]


# No fresh-account capture is available, so the weak thresholds remain
# deliberately conservative. Three independent signs are required because no
# one of them proves play history by itself.
LARGE_FAN_COUNT = 1_000_000
HIGH_RANK_SCORE = 100_000
MANY_OWNED_CHARACTERS = 15
MANY_OWNED_SUPPORT_CARDS = 100
MANY_UNLOCKED_EPISODES = 25
MIN_CORROBORATING_PROGRESS_SIGNALS = 3


def classify_account_played(load_index_payload: object) -> AccountPlayClassification:
    """Classify an account as played only when the payload proves its history.

    ``UNVERIFIED`` means the payload did not prove the account was played; it is
    never a claim that the account is fresh or empty. The function accepts either
    a decoded ``load/index`` envelope or its decoded ``data`` object.
    """
    data = _load_index_data(load_index_payload)
    if data is None:
        return AccountPlayClassification(AccountPlayVerdict.UNVERIFIED, ())

    evidence: list[AccountPlayEvidence] = []
    user_info = _as_mapping(data.get("user_info"))
    tutorial_step = _integer(user_info.get("tutorial_step")) if user_info else None
    if tutorial_step == 1000:
        evidence.append(AccountPlayEvidence(AccountPlaySignal.TUTORIAL_COMPLETE, tutorial_step))

    trained_career_count = _record_count(data, "trained_chara", "trained_chara_id")
    if trained_career_count:
        evidence.append(
            AccountPlayEvidence(AccountPlaySignal.TRAINED_CAREER_RECORDS, trained_career_count)
        )

    weak_evidence = _corroborating_progress_evidence(data, user_info)
    evidence.extend(weak_evidence)
    played = bool(
        tutorial_step == 1000
        or trained_career_count
        or len(weak_evidence) >= MIN_CORROBORATING_PROGRESS_SIGNALS
    )
    verdict = AccountPlayVerdict.PLAYED if played else AccountPlayVerdict.UNVERIFIED
    return AccountPlayClassification(verdict, tuple(evidence))


def _load_index_data(payload: object) -> Mapping[str, Any] | None:
    decoded_payload = _as_mapping(payload)
    if decoded_payload is None:
        return None
    decoded_data = _as_mapping(decoded_payload.get("data"))
    return decoded_data if decoded_data is not None else decoded_payload


def _as_mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _integer(value: object) -> int | None:
    return value if type(value) is int else None


def _record_count(data: Mapping[str, Any], key: str, identifier_key: str) -> int:
    rows = data.get(key)
    if not isinstance(rows, list):
        return 0
    return sum(
        1
        for row in rows
        if isinstance(row, Mapping) and (_integer(row.get(identifier_key)) or 0) > 0
    )


def _corroborating_progress_evidence(
    data: Mapping[str, Any],
    user_info: Mapping[str, Any] | None,
) -> tuple[AccountPlayEvidence, ...]:
    fan_count = _integer(user_info.get("fan")) if user_info else None
    rank_score = _integer(user_info.get("rank_score")) if user_info else None
    checks = (
        (AccountPlaySignal.FAN_COUNT, fan_count, LARGE_FAN_COUNT),
        (AccountPlaySignal.RANK_SCORE, rank_score, HIGH_RANK_SCORE),
        (
            AccountPlaySignal.OWNED_CHARACTERS,
            _record_count(data, "card_list", "card_id"),
            MANY_OWNED_CHARACTERS,
        ),
        (
            AccountPlaySignal.OWNED_SUPPORT_CARDS,
            _record_count(data, "support_card_list", "support_card_id"),
            MANY_OWNED_SUPPORT_CARDS,
        ),
        (
            AccountPlaySignal.UNLOCKED_EPISODES,
            _record_count(data, "released_episode_data_array", "id"),
            MANY_UNLOCKED_EPISODES,
        ),
    )
    return tuple(
        AccountPlayEvidence(signal, value)
        for signal, value, threshold in checks
        if value is not None and value >= threshold
    )


def find_item_rows(data, list_keys=ITEM_LIST_KEYS):
    """The item-count rows in a response, whichever key carries them."""
    if not data:
        return None
    for key in list_keys:
        rows = data.get(key)
        if isinstance(rows, list):
            return rows
        if isinstance(rows, dict):
            return [rows]
    return None


def item_count(item, count_keys=ITEM_COUNT_KEYS):
    """An item row's owned count, or None when the row states no count."""
    for count_key in count_keys:
        if count_key in item:
            return max(int(item.get(count_key) or 0), 0)
    return None


def rows_report_item(rows, item_id, count_keys=ITEM_COUNT_KEYS):
    """True when ``rows`` explicitly restates ``item_id``'s owned count."""
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        try:
            # Raw server field: when absent this is None and int() raises
            # TypeError, which the except below is the deliberate handler for.
            # Typed Any so that stays the control flow rather than becoming a
            # None check (which would change behaviour, not just types).
            raw_id: Any = item.get('item_id')
            if (
                int(raw_id) == item_id
                and any(count_key in item for count_key in count_keys)
            ):
                return True
        except (TypeError, ValueError):
            continue
    return False


def refresh_account_state(state, data, list_keys=ITEM_LIST_KEYS, count_keys=ITEM_COUNT_KEYS):
    """Merge a response's account-state block into ``state``'s caches."""
    if not data:
        return
    state.cached_load_data.update(data)
    if data.get('tp_info'):
        state.tp_info = data['tp_info']
    if data.get('coin_info'):
        state.coin_info = data['coin_info']

    item_list = find_item_rows(data, list_keys)
    if item_list is not None:
        # These arrays can be partial deltas (career start returns an empty
        # user_item_array), so only an explicit row may replace a count.
        for item in item_list:
            iid = item.get('item_id') if isinstance(item, dict) else None
            if iid is None:
                continue
            c = item_count(item, count_keys)
            if c is not None:
                state.item_map[int(iid)] = c
