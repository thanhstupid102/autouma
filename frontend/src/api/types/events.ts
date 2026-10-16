// ---------------------------------------------------------------------------
// Event catalog + prefs
// ---------------------------------------------------------------------------

export type EventSource = 'support' | 'scenario' | 'chara' | 'other'

/** One choice's gametora-scraped reward, attached server-side from
 *  data/event_effects_scraped.json. */
export interface ChoiceEffect {
  select_index: number
  label: string
  effect: string
}

export interface EventCatalogEntry {
  story_id: string
  chara_id: number
  support_card_id: number
  n_choices: number
  select_indexes: number[]
  source: EventSource
  label: string
  /** Event title from master.mdb (text_data cat 181); may be "" if unresolved. */
  name?: string
  seen_count: number
  /** Owning support card / trainee (EN), scraped from gametora; "" when none. */
  owner?: string
  /** Per-choice effects (gametora). Present only for events in the effect DB. */
  choice_effects?: ChoiceEffect[]
  /** 0-based POSITION (index into choice_effects) the bot would auto-pick, or null. */
  recommended_choice?: number | null
}

export interface EventCatalogResponse {
  success: boolean
  events: EventCatalogEntry[]
}

export interface EventPrefsResponse {
  success: boolean
  prefs: Record<string, number>
}

export interface SaveEventPrefsBody {
  prefs: Record<string, number>
}

export interface RebuildCatalogResponse {
  success: boolean
  count: number
}

export interface UpdateEventDatabaseResponse {
  success: boolean
  events?: number
  multi?: number
  count?: number
  detail?: string
}
