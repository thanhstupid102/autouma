from pydantic import BaseModel


class StartCareerRequest(BaseModel):
    card_id: int
    support_card_ids: list[int]
    friend_viewer_id: int
    friend_card_id: int
    parent_id_1: int
    parent_id_2: int
    scenario_id: int = 4
    deck_id: int = 1
    use_tp: int = 30
    difficulty_id: int = 0
    difficulty: int = 0
    is_boost: int = 0
    boost_story_event_id: int = 0
    burn_clocks: bool = False
    spark_reroll: bool = False
    rental_friend_viewer_id: int = 0


class RunCareerRequest(BaseModel):
    card_id: int = 0
    support_card_ids: list[int] = []
    friend_viewer_id: int = 0
    friend_card_id: int = 0
    parent_id_1: int = 0
    parent_id_2: int = 0
    scenario_id: int = 0
    deck_id: int = 1
    use_tp: int = 30
    difficulty_id: int = 0
    difficulty: int = 0
    is_boost: int = 0
    boost_story_event_id: int = 0
    preset_name: str = ""
    race_preset_name: str = ""
    max_steps: int = 2500
    burn_clocks: bool = False
    two_pal_deck: bool = False
    spark_reroll: bool = False
    dev_mode: bool = False
    run_count: int = 1
    rental_friend_viewer_id: int = 0


class CareerActionRequest(BaseModel):
    command_type: int
    command_id: int
    current_turn: int
    current_vital: int
    command_group_id: int = 0
    select_id: int = 0


class FriendListRequest(BaseModel):
    exclude_viewer_ids: list[int] = []


class DeleteCareerRequest(BaseModel):
    current_turn: int = 0


class BurnClocksRequest(BaseModel):
    burn_clocks: bool
