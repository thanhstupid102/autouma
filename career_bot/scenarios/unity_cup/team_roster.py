"""Client-side Unity Cup team_data_array (the server sends it back null;
the real client computes the roster from the trainee + scouted members)."""

from typing import Any

import uma_data


class TeamRosterBuilder:
    DEFAULT_APTITUDE = {
        "proper_distance_short": 4,
        "proper_distance_mile": 4,
        "proper_distance_middle": 4,
        "proper_distance_long": 4,
        "proper_running_style_nige": 4,
        "proper_running_style_senko": 4,
        "proper_running_style_sashi": 4,
        "proper_running_style_oikomi": 4,
        "proper_ground_turf": 4,
        "proper_ground_dirt": 4,
    }
    DISTANCE_APTITUDE_KEY = {
        1: "proper_distance_short",
        2: "proper_distance_mile",
        3: "proper_distance_middle",
        4: "proper_distance_long",
        5: "proper_ground_dirt",
    }
    # 3 slots per distance race in the team-race edit screen (all opponent
    # teams in the 2026-07-08 capture also max out at 3 per distance).
    MAX_MEMBERS_PER_DISTANCE = 3
    # The team-edit screen has exactly 5 distance_type slots x
    # MAX_MEMBERS_PER_DISTANCE=3 members = 15 total. Once enough members have
    # been scouted (member_state==1) the roster can exceed this -- extras sit
    # on the bench (see _bench_overflow).
    MAX_ROSTER_SIZE = 5 * MAX_MEMBERS_PER_DISTANCE

    def __init__(self, base_dir=None):
        self.base_dir = base_dir
        self._scout_aptitude_cache = None
        self._card_chara_map_cache = None

    def _scout_aptitude_map(self):
        if self._scout_aptitude_cache is None:
            try:
                result = uma_data.load_scout_aptitudes(self.base_dir)
            except Exception:
                result = {}
            self._scout_aptitude_cache = (result or {}).get("aptitudes") or {}
        return self._scout_aptitude_cache

    def _card_chara_map(self):
        if self._card_chara_map_cache is None:
            try:
                result = uma_data.load_card_chara_map(self.base_dir)
            except Exception:
                result = {}
            self._card_chara_map_cache = (result or {}).get("card_chara_map") or {}
        return self._card_chara_map_cache

    def _trainee_chara_id(self, chara_info):
        card_id = int((chara_info or {}).get("card_id") or 0)
        if not card_id:
            return 0
        chara_id = self._card_chara_map().get(card_id)
        return int(chara_id) if chara_id else card_id // 100

    def _team_roster(self, chara_info, team_data_set):
        roster = []
        trainee_chara_id = self._trainee_chara_id(chara_info)
        if trainee_chara_id:
            roster.append((trainee_chara_id, chara_info or {}))
        for row in (team_data_set or {}).get("evaluation_info_array") or []:
            if int((row or {}).get("member_state") or 0) != 1:
                continue
            chara_id = int((row or {}).get("chara_id") or 0)
            if chara_id:
                roster.append((chara_id, None))
        return roster

    def _running_style(self, aptitude):
        # Argmax over the four running-style aptitudes; ties broken
        # senko > sashi > nige > oikomi (verified against a real client
        # capture: trainee senko7/sashi7 -> 2, chara 1009 nige7/senko7 -> 2).
        priorities = [
            (2, int((aptitude or {}).get("proper_running_style_senko") or 0)),
            (3, int((aptitude or {}).get("proper_running_style_sashi") or 0)),
            (1, int((aptitude or {}).get("proper_running_style_nige") or 0)),
            (4, int((aptitude or {}).get("proper_running_style_oikomi") or 0)),
        ]
        best_style, best_value = priorities[0]
        for style, value in priorities[1:]:
            if value > best_value:
                best_style, best_value = style, value
        return best_style

    def _distance_score(self, aptitude, distance_type):
        key = self.DISTANCE_APTITUDE_KEY[distance_type]
        return int((aptitude or {}).get(key) or 0)

    def _bench_overflow(self, members):
        """Drop the weakest scouted members down to MAX_ROSTER_SIZE (15) --
        the team-edit screen has no slot for anything beyond that. The
        trainee (members[0]) is never benched; among scouts, the ones with
        the lowest best-distance aptitude (max(scores)) go first, and ties
        are broken by benching the later roster entry (a later scout row)."""
        overflow = len(members) - self.MAX_ROSTER_SIZE
        if overflow <= 0:
            return members
        trainee, scouts = members[0], members[1:]
        bench_indexes = sorted(
            range(len(scouts)),
            key=lambda i: (max(scouts[i]["scores"]), -i),
        )[:overflow]
        benched = set(bench_indexes)
        kept_scouts = [scout for i, scout in enumerate(scouts) if i not in benched]
        return [trainee] + kept_scouts

    def _assign_distances(self, members):
        assignment: dict[int, list[Any]] = {distance_type: [] for distance_type in range(1, 6)}
        for member in members:
            # _bench_overflow (called from build()) caps len(members) at
            # MAX_ROSTER_SIZE (5 * MAX_MEMBERS_PER_DISTANCE), so by pigeonhole
            # at least one distance always has room here -- no "assign to any
            # distance" fallback needed. That fallback used to let a 4th
            # member land on one distance, which the server rejects
            # (single_mode_team/team_edit result_code 205).
            candidates = [d for d in range(1, 6) if len(assignment[d]) < self.MAX_MEMBERS_PER_DISTANCE]
            best = max(candidates, key=lambda d: (member["scores"][d - 1], -len(assignment[d]), -d))
            assignment[best].append(member)

        # Every distance must field at least one member -- pull the best fit
        # for an empty distance out of the currently largest group.
        for distance_type in range(1, 6):
            if assignment[distance_type]:
                continue
            largest = max(assignment, key=lambda d: len(assignment[d]))
            if len(assignment[largest]) <= 1:
                continue
            candidate = max(assignment[largest], key=lambda m: m["scores"][distance_type - 1])
            assignment[largest].remove(candidate)
            assignment[distance_type].append(candidate)

        return assignment

    def build(self, state):
        # The server sends team_data_set.team_data_array back as null before
        # single_mode_team/team_edit -- the real client computes the roster
        # client-side from the trainee + scouted team members. Verified
        # against a real client capture (2026-07-08): roster membership,
        # running-style argmax and the distance split are all reproduced
        # exactly (aptitude ties aside, any valid distance split is accepted
        # by the server).
        data = (state or {}).get("data") or {}
        chara_info = data.get("chara_info") or {}
        team_data_set = data.get("team_data_set") or {}

        roster = self._team_roster(chara_info, team_data_set)
        if not roster:
            return []

        scout_aptitudes = self._scout_aptitude_map()
        members = []
        for chara_id, trainee_aptitude in roster:
            aptitude = trainee_aptitude if trainee_aptitude is not None else (
                scout_aptitudes.get(chara_id) or self.DEFAULT_APTITUDE
            )
            members.append({
                "chara_id": chara_id,
                "running_style": self._running_style(aptitude),
                "scores": [self._distance_score(aptitude, d) for d in range(1, 6)],
            })

        members = self._bench_overflow(members)
        assignment = self._assign_distances(members)

        result = []
        for distance_type in range(1, 6):
            # No truncation here: every remaining (post-bench) roster member
            # must appear exactly once in the payload -- the 3-per-distance
            # cap is enforced during assignment, which is always satisfiable
            # since _bench_overflow already capped the roster at 15.
            entries = sorted(assignment[distance_type], key=lambda m: -m["scores"][distance_type - 1])
            for member_id, member in enumerate(entries, start=1):
                result.append({
                    "distance_type": distance_type,
                    "member_id": member_id,
                    "chara_id": member["chara_id"],
                    "running_style": member["running_style"],
                })
        return result
