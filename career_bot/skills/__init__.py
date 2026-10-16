from pathlib import Path

from career_bot.skills.data import *  # noqa: F401 -- preserve the legacy skills facade
from career_bot.skills.catalog import SkillCatalogMixin
from career_bot.skills.purchase import SkillPurchaseMixin
from core.runtime_paths import resolve_state_root


class SkillBuyer(SkillCatalogMixin, SkillPurchaseMixin):

    def __init__(self, base_dir, state_root=None):
        self.base_dir = Path(base_dir)
        self.state_root = (
            Path(state_root).resolve()
            if state_root is not None
            else resolve_state_root(self.base_dir).root
        )
        self.skill_names = {}
        self.skill_rarities = {}
        self.skill_costs = {}
        self.skill_grade_values = {}
        self.skill_id_exists = set()
        self.group_to_skill_ids = {}
        self.skill_to_group_id = {}
        self.failed_this_turn = {}
        self.current_turn = None
        self.last_candidates = []
        self.last_selected = []
        self.last_attempt = []
        self.last_result = {}
        self.recover_after_error = False
        self.fast_learner = False
        self.unobtainable = set()
        # Skills successfully bought THIS career. The server accepts a re-buy of an
        # already-owned skill (result_code 1) but grants nothing while still draining
        # SP, and its success response does not always refresh chara.skill_array -- so
        # without this set the finish SP-drain could keep "buying" the same skill and
        # burn SP for nothing. Treated as owned everywhere. Career-scoped (a new career
        # builds a fresh SkillBuyer); reset_scoped_failures must NOT clear it.
        self.bought = set()
        self.attempt_events = []
        self._load()
