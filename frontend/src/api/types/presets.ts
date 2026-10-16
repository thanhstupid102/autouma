// ---------------------------------------------------------------------------
// Race preset
// ---------------------------------------------------------------------------

export interface RacePreset {
  name: string
  extra_race_list: number[]
}

export interface GetRacePresetsResponse {
  success: boolean
  presets: RacePreset[]
}

export interface SaveRacePresetBody {
  preset: RacePreset
}

export interface DeleteRacePresetBody {
  name: string
}

export interface SaveRacesToRacePresetBody {
  preset_name: string
  races: number[]
}

// ---------------------------------------------------------------------------
// Skill preset
// ---------------------------------------------------------------------------

export interface Preset {
  name: string
  /** 1=Front Runner 2=Pace Chaser 3=Late Surger 4=End Closer */
  running_style?: number
  /** Tiers — each tier is an array of skill NAME strings */
  learn_skill_list?: string[][]
  /** Flat array of skill NAME strings to blacklist */
  learn_skill_blacklist?: string[]
  /** Race IDs (numeric strings or numbers) — stored as strings by legacy */
  extra_race_list?: (number | string)[]
  learn_skill_threshold?: number
  /**
   * Scenario the preset runs under (4 = MANT / Trackblazer, 2 = Unity Cup, …).
   * Absent on legacy presets written before the id was persisted — the backend
   * (`career_bot.planning.presets.hydrate_preset`) then falls back to MANT, so
   * treat `undefined` as MANT here too.
   */
  scenario_id?: number
  /** Legacy alias the backend regenerates on hydrate; mirrors `scenario_id`. */
  scenario?: number
  [k: string]: unknown
}

export interface SavePresetBody {
  preset: Preset
}

export interface DeletePresetBody {
  name: string
}
