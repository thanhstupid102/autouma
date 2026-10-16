// ---------------------------------------------------------------------------
// Career / runner status
// ---------------------------------------------------------------------------

export interface ActionHistoryRow {
  turn: number | string
  action: string
  facility: string
  detail: string
  stats?: {
    hp?: number
    max_hp?: number
    motivation?: number
    speed?: number
    stamina?: number
    power?: number
    guts?: number
    wit?: number
    skill_point?: number
  }
}

export interface RunnerStatus {
  running: boolean
  paused?: boolean
  turn?: number
  steps?: number
  last_action?: string
  last_error?: string
  finished?: boolean
  loop_active?: boolean
  circuit_tripped?: boolean
  retry_waiting?: boolean
  retry_attempt?: number
  retry_limit?: number
  retry_wait_seconds?: number
  burn_clocks?: boolean
  clocks_used?: number
  action_history?: ActionHistoryRow[]
  log?: { action: string; turn?: number; detail?: string }[]
  [k: string]: unknown
}

export interface CareerStatus {
  active: boolean
  turn?: number
  card_id?: number
  parent_id_1?: number
  parent_id_2?: number
  friend_viewer_id?: number
  friend_card_id?: number
  deck_id?: number
  [k: string]: unknown
}

// ---------------------------------------------------------------------------
// Event info
// ---------------------------------------------------------------------------

export interface EventInfo {
  success: boolean
  available?: boolean
  difficulty_id?: number
  max_level?: number
  [k: string]: unknown
}

// ---------------------------------------------------------------------------
// Career run body (two variants)
// ---------------------------------------------------------------------------

/** Body sent when an active career already exists (resume). */
export interface RunCareerResumeBody {
  preset_name: string
  race_preset_name?: string
  max_steps?: number
  burn_clocks?: boolean
  two_pal_deck?: boolean
  spark_reroll?: boolean
  run_count?: number
}

/** Body sent when starting a brand-new career (full selection). */
export interface RunCareerNewBody {
  card_id: number
  support_card_ids: number[]
  friend_viewer_id: number
  friend_card_id: number
  parent_id_1: number
  parent_id_2: number
  deck_id: number
  scenario_id?: number
  use_tp?: number
  difficulty_id?: number
  difficulty?: number
  is_boost?: number
  boost_story_event_id?: number
  preset_name: string
  race_preset_name?: string
  max_steps?: number
  burn_clocks?: boolean
  two_pal_deck?: boolean
  spark_reroll?: boolean
  run_count?: number
  rental_friend_viewer_id?: number
}

export type RunCareerBody = RunCareerResumeBody | RunCareerNewBody

export interface DeleteCareerBody {
  current_turn: number
}

export interface BurnClocksBody {
  burn_clocks: boolean
}
