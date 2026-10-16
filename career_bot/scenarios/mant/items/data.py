
# Underscore-aliased so the `from ...items.data import *` facades don't
# re-export typing names into the item mixins.
from typing import TYPE_CHECKING as _TYPE_CHECKING, Any as _Any

from career_bot.scenarios.mant import (  # noqa: F401 -- compatibility re-exports
    BAD_EFFECT_NAMES,
    SIRIUS_THRONE_GROUP_IDS,
    SUMMER_CAMP_TURNS,
    TEAM_SIRIUS_SUPPORT_ID,
    THRONE_SUPPORT_ID,
)

ITEM_NAMES = {
    1001: "Speed Notepad",
    1002: "Stamina Notepad",
    1003: "Power Notepad",
    1004: "Guts Notepad",
    1005: "Wit Notepad",
    1101: "Speed Manual",
    1102: "Stamina Manual",
    1103: "Power Manual",
    1104: "Guts Manual",
    1105: "Wit Manual",
    1201: "Speed Scroll",
    1202: "Stamina Scroll",
    1203: "Power Scroll",
    1204: "Guts Scroll",
    1205: "Wit Scroll",
    2001: "Vita 20",
    2002: "Vita 40",
    2003: "Vita 65",
    2101: "Royal Kale Juice",
    2201: "Energy Drink MAX",
    2202: "Energy Drink MAX EX",
    2301: "Plain Cupcake",
    2302: "Berry Sweet Cupcake",
    3001: "Yummy Cat Food",
    3101: "Grilled Carrots",
    4001: "Pretty Mirror",
    4002: "Reporter's Binoculars",
    4003: "Master Practice Guide",
    4004: "Scholar's Hat",
    4101: "Fluffy Pillow",
    4102: "Pocket Planner",
    4103: "Rich Hand Cream",
    4104: "Smart Scale",
    4105: "Aroma Diffuser",
    4106: "Practice Drills DVD",
    4201: "Miracle Cure",
    5001: "Speed Training Application",
    5002: "Stamina Training Application",
    5003: "Power Training Application",
    5004: "Guts Training Application",
    5005: "Wit Training Application",
    7001: "Reset Whistle",
    8001: "Coaching Megaphone",
    8002: "Motivating Megaphone",
    8003: "Empowering Megaphone",
    9001: "Speed Ankle Weights",
    9002: "Stamina Ankle Weights",
    9003: "Power Ankle Weights",
    9004: "Guts Ankle Weights",
    10001: "Good-Luck Charm",
    11001: "Artisan Cleat Hammer",
    11002: "Master Cleat Hammer",
    11003: "Glow Sticks",
}

DISPLAY_TO_ID = {v: k for k, v in ITEM_NAMES.items()}

ITEM_LOG_ALIASES = {
    "Vita 20": "vit_20",
    "Vita 40": "vit_40",
    "Vita 65": "vit_65",
    "Royal Kale Juice": "RKJ",
    "Plain Cupcake": "PCup",
    "Berry Sweet Cupcake": "BCup",
    "Grilled Carrots": "GC",
    "Rich Hand Cream": "RHC",
    "Miracle Cure": "Cleanser",
    "Reset Whistle": "Whistle",
    "Coaching Megaphone": "CM",
    "Motivating Megaphone": "MM",
    "Empowering Megaphone": "EM",
    "Speed Ankle Weights": "Spd AW",
    "Stamina Ankle Weights": "Sta AW",
    "Power Ankle Weights": "Pow AW",
    "Guts Ankle Weights": "Guts AW",
    "Good-Luck Charm": "GLC",
    "Artisan Cleat Hammer": "ACHam",
    "Master Cleat Hammer": "MCHam",
}


def item_log_name(name_or_id):
    # An int id missing from ITEM_NAMES deliberately falls through as the raw id
    # (both lookups return their own default), so `name` is str-or-int here.
    name: _Any = ITEM_NAMES.get(name_or_id, name_or_id) if isinstance(name_or_id, int) else str(name_or_id or "")
    return ITEM_LOG_ALIASES.get(name, name)


def format_item_counts(owned, prefix="Inventory"):
    parts = [f"{item_log_name(name)} {int(count)}" for name, count in sorted((owned or {}).items()) if int(count or 0) > 0]
    return f"{prefix}: " + (", ".join(parts) if parts else "empty")


def format_item_uses(rows, prefix="Items used"):
    parts = []
    for row in rows or []:
        item_id = int((row or {}).get("item_id") or 0)
        name = (row or {}).get("name") or ITEM_NAMES.get(item_id, str(item_id or ""))
        count = int((row or {}).get("use_num") or 1)
        parts.append(f"{item_log_name(name)} x{count}")
    return f"{prefix}: " + (", ".join(parts) if parts else "none")

SHOP_ITEM_COSTS = {
    "Speed Notepad": 10, "Stamina Notepad": 10, "Power Notepad": 10, "Guts Notepad": 10, "Wit Notepad": 10,
    "Speed Manual": 15, "Stamina Manual": 15, "Power Manual": 15, "Guts Manual": 15, "Wit Manual": 15,
    "Speed Scroll": 30, "Stamina Scroll": 30, "Power Scroll": 30, "Guts Scroll": 30, "Wit Scroll": 30,
    "Vita 20": 35, "Vita 40": 55, "Vita 65": 75, "Royal Kale Juice": 70,
    "Energy Drink MAX": 30, "Energy Drink MAX EX": 50,
    "Plain Cupcake": 30, "Berry Sweet Cupcake": 55,
    "Yummy Cat Food": 10, "Grilled Carrots": 40,
    "Pretty Mirror": 150, "Reporter's Binoculars": 150, "Master Practice Guide": 150, "Scholar's Hat": 280,
    "Fluffy Pillow": 15, "Pocket Planner": 15, "Rich Hand Cream": 15, "Smart Scale": 15,
    "Aroma Diffuser": 15, "Practice Drills DVD": 15, "Miracle Cure": 40,
    "Speed Training Application": 150, "Stamina Training Application": 150,
    "Power Training Application": 150, "Guts Training Application": 150, "Wit Training Application": 150,
    "Reset Whistle": 20,
    "Coaching Megaphone": 40, "Motivating Megaphone": 55, "Empowering Megaphone": 70,
    "Speed Ankle Weights": 50, "Stamina Ankle Weights": 50, "Power Ankle Weights": 50, "Guts Ankle Weights": 50,
    "Good-Luck Charm": 40,
    "Artisan Cleat Hammer": 25, "Master Cleat Hammer": 40,
    "Glow Sticks": 15,
}

AILMENT_CURE_MAP = {
    "Night Owl": "Fluffy Pillow",
    "Slacker": "Pocket Planner",
    "Skin Outbreak": "Rich Hand Cream",
    "Slow Metabolism": "Smart Scale",
    "Migraine": "Aroma Diffuser",
    "Practice Poor": "Practice Drills DVD",
}

AILMENT_CURE_ALL = "Miracle Cure"

CURE_ITEMS = set(AILMENT_CURE_MAP.values()) | {AILMENT_CURE_ALL}

INSTANT_USE_ITEMS = [
    "Pretty Mirror",
    "Scholar's Hat",
    "Speed Notepad", "Stamina Notepad", "Power Notepad", "Guts Notepad", "Wit Notepad",
    "Speed Manual", "Stamina Manual", "Power Manual", "Guts Manual", "Wit Manual",
    "Speed Scroll", "Stamina Scroll", "Power Scroll", "Guts Scroll", "Wit Scroll",
    "Speed Training Application", "Stamina Training Application",
    "Power Training Application", "Guts Training Application", "Wit Training Application",
]

ONE_TIME_BUFF_ITEMS = {
    "Pretty Mirror",
    "Scholar's Hat",
    "Reporter's Binoculars",
    "Master Practice Guide",
}

ENERGY_ITEMS = {
    "Vita 20": 20,
    "Vita 40": 40,
    "Vita 65": 65,
    "Royal Kale Juice": 100,
}

# Stock ramps 6 turns before the 8-turn pre-camp hold, then locks full stock
# 8 turns before each Summer Camp. Reserve lifts at camp start (37/61).
# SUMMER_CAMP_TURNS is imported from career_bot.scenarios.mant (shared with strategy.py).
EARLY_PRE_SUMMER_TURNS = set(range(23, 29)) | set(range(47, 53))
PRE_SUMMER_TURNS = set(range(29, 37)) | set(range(53, 61))
SUMMER_HOLD_TURNS = EARLY_PRE_SUMMER_TURNS | PRE_SUMMER_TURNS
SUMMER_ITEM_RELEASE_TURN = 65
SUMMER_RAW_STAT_TARGET = 50
SUMMER_ENERGY_CHARM_TARGET = 200
SUMMER_EARLY_ENERGY_CHARM_TARGET = SUMMER_ENERGY_CHARM_TARGET // 2
SUMMER_RKJ_STOCK_VALUE = 90
SUMMER_MEGA_STOCK = 2
SUMMER_CUPCAKE_STOCK = {"Plain Cupcake": 2, "Berry Sweet Cupcake": 1}
TRAIN_LOW_VITAL_RKJ_THRESHOLD = 27
MEGAPHONE_PRIORITY = ["Empowering Megaphone", "Motivating Megaphone", "Coaching Megaphone"]

# Reserve cleat hammers for the T74/76/78 climax finale races, borrowed from
# the Icarus Trackblazer tuning.
# TEAM_SIRIUS_SUPPORT_ID / THRONE_SUPPORT_ID / GROUP_SUPPORT_IDS are imported
# from career_bot.scenarios.mant (aliased below to keep the existing set-typed name).
GROUP_SUPPORT_IDS = set(SIRIUS_THRONE_GROUP_IDS)
MASTER_HAMMER_CLIMAX_RESERVE = 2
MASTER_HAMMER_EARLY_RESERVE = 1
MASTER_HAMMER_EARLY_HOLD_TURN = 56
MASTER_HAMMER_FULL_HOLD_TURN = 66
CLIMAX_RACE_TURNS = (74, 76, 78)
CLIMAX_FIRST_RACE_TURN = CLIMAX_RACE_TURNS[0]
TAKARAZUKA_YEAR2_TURN = 36
SENIOR_INHERITANCE_DONE_TURN = 49
CHARMING_ITEM_ID = 4001
FORBIDDEN_BUY_ITEMS = {"Yummy Cat Food", "Glow Sticks", "Reporter's Binoculars", "Master Practice Guide"}
ALLOWED_TRAINING_APPLICATIONS = {"Speed Training Application", "Wit Training Application"}
TRAINING_APPLICATION_ITEMS = {name for name in ITEM_NAMES.values() if name.endswith("Training Application")}

MEGAPHONE_TIERS = {
    "Coaching Megaphone": (1, 4),
    "Motivating Megaphone": (2, 3),
    "Empowering Megaphone": (3, 2),
}

TRAINING_TYPE_ANKLET = {
    101: "Speed Ankle Weights",
    601: "Speed Ankle Weights",
    105: "Stamina Ankle Weights",
    602: "Stamina Ankle Weights",
    102: "Power Ankle Weights",
    603: "Power Ankle Weights",
    103: "Guts Ankle Weights",
    604: "Guts Ankle Weights",
}

TRAINING_ITEM_DECK_TYPE_INDEX = {
    "Speed Ankle Weights": 0,
    "Stamina Ankle Weights": 1,
    "Power Ankle Weights": 2,
    "Guts Ankle Weights": 3,
    "Speed Training Application": 0,
    "Stamina Training Application": 1,
    "Power Training Application": 2,
    "Guts Training Application": 3,
    "Wit Training Application": 4,
}

DEFAULT_ITEM_TIERS = {
    "speed_notepad": 1,
    "speed_manual": 1,
    "speed_scroll": 1,
    "stamina_notepad": 1,
    "stamina_manual": 1,
    "stamina_scroll": 1,
    "power_notepad": 1,
    "power_manual": 1,
    "power_scroll": 1,
    "guts_notepad": 1,
    "guts_manual": 1,
    "guts_scroll": 1,
    "wit_notepad": 1,
    "wit_manual": 1,
    "wit_scroll": 1,
    "vita_20": 3,
    "vita_40": 2,
    "vita_65": 2,
    "royal_kale_juice": 3,
    "energy_drink_max": 6,
    "energy_drink_max_ex": 7,
    "plain_cupcake": 3,
    "berry_sweet_cupcake": 4,
    "yummy_cat_food": 7,
    "grilled_carrots": 4,
    "pretty_mirror": 7,
    "reporters_binoculars": 8,
    "master_practice_guide": 7,
    "scholars_hat": 8,
    "fluffy_pillow": 7,
    "pocket_planner": 7,
    "rich_hand_cream": 5,
    "smart_scale": 7,
    "aroma_diffuser": 7,
    "practice_drills_dvd": 8,
    "miracle_cure": 5,
    "speed_training_application": 7,
    "stamina_training_application": 7,
    "power_training_application": 7,
    "guts_training_application": 7,
    "wit_training_application": 7,
    "reset_whistle": 1,
    "coaching_megaphone": 999,
    "motivating_megaphone": 3,
    "empowering_megaphone": 3,
    "speed_ankle_weights": 7,
    "stamina_ankle_weights": 7,
    "power_ankle_weights": 7,
    "guts_ankle_weights": 7,
    "good-luck_charm": 3,
    "artisan_cleat_hammer": 1,
    "master_cleat_hammer": 1,
    "glow_sticks": 8,
}


def display_to_slug(name):
    return str(name or "").lower().replace("'", "").replace(" ", "_")


# Shared turn-bucket ladder used by both _coin_reserve and _coin_cap: each entry is
# (turn_max, default_reserve, cap_cfg_key, default_cap). The two methods previously
# hardcoded these same breakpoints independently -- this is the single source of truth.
_COIN_TURN_BUCKETS = (
    (20, 100, "mant_coin_cap_t20", 999999),
    (35, 160, "mant_coin_cap_t35", 300),
    (45, 140, "mant_coin_cap_t45", 260),
    (55, 80, "mant_coin_cap_t55", 200),
    (64, 40, "mant_coin_cap_t64", 140),
    (72, 40, "mant_coin_cap_t72", 80),
)
_COIN_TURN_BUCKET_FINAL = (0, "mant_coin_cap_final", 0)


def _coin_turn_bucket(turn):
    """Return (default_reserve, cap_cfg_key, default_cap) for the bucket `turn` falls in."""
    for turn_max, reserve_default, cap_key, cap_default in _COIN_TURN_BUCKETS:
        if turn <= turn_max:
            return reserve_default, cap_key, cap_default
    return _COIN_TURN_BUCKET_FINAL


class MantItemManagerState:
    """Type-only contract of the state MantItemManager owns and its mixins share.

    MantItemManager.__init__ creates every attribute below, and the three mixins
    (shop / summer / use) freely read each other's helpers -- so from any single
    mixin's point of view those names come "from the host". This class declares
    them once so mypy can check the mixin bodies.

    It is TYPE-ONLY: the body is bare annotations plus a TYPE_CHECKING-guarded
    block, so it defines no runtime attribute or method, and the mixins inherit
    it only under TYPE_CHECKING (see the `_HostState` alias in each mixin
    module). At runtime every mixin's MRO is unchanged: (Mixin, object).
    """

    # --- state created in MantItemManager.__init__ ---
    used_buffs: _Any
    failed_exchange_this_snapshot: _Any
    failed_use_this_turn: _Any
    current_turn: int | None
    shop_snapshot_key: tuple[_Any, ...] | None
    recover_after_exchange_error: bool
    recover_after_use_error: bool
    last_buy_options: list[dict[str, _Any]]
    last_buy_selected: list[dict[str, _Any]]
    last_buy_attempt: list[dict[str, _Any]]
    last_buy_result: dict[str, _Any]
    last_use_options: list[dict[str, _Any]]
    last_use_selected: list[dict[str, _Any]]
    last_use_attempt: list[dict[str, _Any]]
    last_use_result: dict[str, _Any]
    last_pre_race_use_selected: list[dict[str, _Any]]
    last_pre_race_use_attempt: list[dict[str, _Any]]
    last_pre_race_use_result: dict[str, _Any]
    buy_attempt_events: list[dict[str, _Any]]
    use_attempt_events: list[dict[str, _Any]]
    first_shop_megaphone_done: bool
    first_shop_megaphone_to_use: str | None

    if _TYPE_CHECKING:  # noqa: C901 - mccabe scores each type-only stub below as a branch
        # --- helpers a mixin borrows from a sibling mixin or the manager ---
        # The bodies below are unreachable at runtime (TYPE_CHECKING is False);
        # the real implementations live in the module named above each group.
        # manager.py
        def _set_turn(self, turn: _Any) -> None:
            raise NotImplementedError

        def _set_shop_snapshot(self, rows: _Any) -> None:
            raise NotImplementedError

        def _merge_state(self, state: _Any, res: _Any) -> _Any:
            raise NotImplementedError

        # use.py
        def _mant_cfg(self, preset: _Any) -> dict[_Any, _Any]:
            raise NotImplementedError

        def _owned_map(self, free: _Any) -> dict[str, int]:
            raise NotImplementedError

        def _active_bad_statuses(self, data: _Any) -> list[str]:
            raise NotImplementedError

        def _is_instant_stat_item(self, name: _Any) -> bool:
            raise NotImplementedError

        def _can_use_cure_now(self, name: _Any, data: _Any, turn: _Any) -> bool:
            raise NotImplementedError

        def _training_application_allowed(self, name: _Any) -> bool:
            raise NotImplementedError

        def _megaphone_buy_surplus(self, data: _Any, owned: _Any, turn: _Any, race_planner: _Any, preset: _Any) -> bool:
            raise NotImplementedError

        def _pre_summer_boost_tier(self, name: _Any, owned: _Any, cfg: _Any, preset: _Any = None, turn: _Any = None) -> int | None:
            raise NotImplementedError

        def _merge_targets(self, targets: _Any, owned: _Any) -> list[_Any]:
            raise NotImplementedError

        # summer.py
        def _summer_turn(self, turn: _Any) -> bool:
            raise NotImplementedError

        def _summer_hold_active(self, turn: _Any) -> bool:
            raise NotImplementedError

        def _early_pre_summer_hold_active(self, turn: _Any) -> bool:
            raise NotImplementedError

        def _summer_stock_item(self, name: _Any) -> bool:
            raise NotImplementedError

        def _summer_stock_needed(self, name: _Any, owned: _Any, preset: _Any, turn: _Any = None) -> bool:
            raise NotImplementedError

        def _summer_reserved_items(self, owned: _Any, preset: _Any, turn: _Any) -> dict[str, int]:
            raise NotImplementedError

        def _summer_ankle_target(self, name: _Any, preset: _Any) -> int:
            raise NotImplementedError

        def _summer_energy_charm_target(self, turn: _Any = None) -> int:
            raise NotImplementedError

        def _summer_energy_charm_value(self, owned: _Any, turn: _Any = None) -> int:
            raise NotImplementedError
