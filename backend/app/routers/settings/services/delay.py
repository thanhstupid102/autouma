from uma_api.session import Session


class DelayConfigService:

    def normalize_turn_delay(
        self,
        min_value: float = 0.0,
        max_value: float = 0.0,
        disabled: bool = False
    ):
        left = max(0.0, min_value)
        right = max(0.0, max_value)
        if left > right:
            right = left
        if disabled:
            left = 0.0
            right = 0.0
        return left, right, bool(disabled)

    def set_turn_delay(
        self,
        session: Session,
        min_value: float,
        max_value: float,
        disabled: bool = False
    ):
        # Per-account: write THIS account's delay_config (never the delay-module globals,
        # which would clobber every other account) and push it onto the account's live
        # TimingDNA so a running career re-paces immediately.
        next_min, next_max, next_disabled = self.normalize_turn_delay(
            min_value, max_value, disabled
        )
        cfg = session.delay_config
        cfg["min"] = next_min
        cfg["max"] = next_max
        cfg["disabled"] = next_disabled
        if not next_disabled:
            cfg["restore_min"] = next_min
            cfg["restore_max"] = next_max
        session.apply_delay_to_dna()
        return self.get_turn_delay(session)

    def get_turn_delay(self, session: Session):
        cfg = session.delay_config
        return {
            "success": True,
            "min": cfg.get("min", 0.0),
            "max": cfg.get("max", 0.0),
            "restore_min": cfg.get("restore_min", 1.6),
            "restore_max": cfg.get("restore_max", 3.7),
            "disabled": cfg.get("disabled", True),
        }
