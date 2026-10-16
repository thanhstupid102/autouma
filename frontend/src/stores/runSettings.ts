/**
 * runSettings store — mirrors the legacy app.js run-options state.
 *
 * Legacy localStorage keys (preserved for cross-UI compat):
 *   uma_turn_delay_settings  JSON { min, max, restoreMin, restoreMax, disabled }
 *   uma_burn_clocks          JSON boolean
 *   uma_two_pal_deck         JSON boolean
 *   uma_spark_reroll         JSON boolean
 *   uma_dev_career           JSON "true"/"false" string (legacy stores raw string via localStorage.setItem)
 *   uma_run_count            raw Number string (-1 = stop after SP dump, 0 = infinite)
 *   uma_scenario_id          raw Number string (4 = MANT / Trackblazer, 2 = Unity Cup)
 *
 * Note: storage-event cross-tab sync (window 'storage') is intentionally skipped —
 * single-tab assumption matches the backend's single-runner model.
 *
 * Note: event (enabled/level/boost) live here for convenience; they are part of
 * the selection POST payload in the legacy UI but logically belong to run-settings.
 */

import { create } from 'zustand'
import { accountKey } from '@/lib/accountKey'
import { listScenarios } from '../api/scenarios'
import type { ScenarioOption } from '../api/types/scenario'

// -------------------------------------------------------------------------
// Run-settings keys — scoped PER ACCOUNT so each account keeps its own
// delays / run count / burn-clocks / dev / event settings.
// -------------------------------------------------------------------------
const delayKey = () => accountKey('uma_turn_delay_settings')
const burnKey = () => accountKey('uma_burn_clocks')
const twoPalDeckKey = () => accountKey('uma_two_pal_deck')
const sparkRerollKey = () => accountKey('uma_spark_reroll')
const devKey = () => accountKey('uma_dev_career')
const runCountKey = () => accountKey('uma_run_count')
const scenarioKey = () => accountKey('uma_scenario_id')

// -------------------------------------------------------------------------
// normalizeDelayBounds — exact port of app.js:416-423
// -------------------------------------------------------------------------
function normalizeDelayBounds(
  min: unknown,
  max: unknown,
  disabled = false,
  restoreMin: unknown = null,
  restoreMax: unknown = null,
): DelayNormalized {
  const fallbackMin = Number.isFinite(Number(restoreMin)) ? Number(restoreMin) : 1.6
  const fallbackMax = Number.isFinite(Number(restoreMax)) ? Number(restoreMax) : 3.7
  if (disabled) {
    return { min: 0, max: 0, restoreMin: fallbackMin, restoreMax: fallbackMax, disabled: true }
  }
  const left = Math.max(0, Number.isFinite(Number(min)) ? Number(min) : fallbackMin)
  let right = Math.max(0, Number.isFinite(Number(max)) ? Number(max) : fallbackMax)
  if (left > right) right = left
  return { min: left, max: right, restoreMin: left, restoreMax: right, disabled: false }
}

interface DelayNormalized {
  min: number
  max: number
  restoreMin: number
  restoreMax: number
  disabled: boolean
}

// -------------------------------------------------------------------------
// writeLocalSetting / readLocalSetting — exact port of app.js:391-402
// -------------------------------------------------------------------------
function writeLocalSetting(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch { /* ignore QuotaExceededError etc. */ }
}

function readLocalSetting<T>(raw: string | null, fallback: T): T {
  if (!raw) return fallback
  try {
    return JSON.parse(raw) as T
  } catch {
    return fallback
  }
}

export function normalizeScenarioId(value: unknown, validIds: number[] = [4, 2]): number {
  const n = Number(value)
  return validIds.includes(n) ? n : (validIds[0] ?? 4)
}

// -------------------------------------------------------------------------
// Store types
// -------------------------------------------------------------------------
export interface RunSettingsState {
  delayMin: number
  delayMax: number
  /** NoCd / "Tempt Fate" — zeroes delays while preserving restore values */
  noCd: boolean
  restoreMin: number
  restoreMax: number
  runCount: number
  eventEnabled: boolean
  eventLevel: number
  eventBoost: boolean
  burnClocks: boolean
  twoPalDeck: boolean
  sparkReroll: boolean
  devCareer: boolean
  scenarioId: number
  scenarios: ScenarioOption[]
}

export interface RunSettingsActions {
  setDelay: (min: number, max: number) => void
  setNoCd: (on: boolean) => void
  setRunCount: (n: number) => void
  setEvent: (ev: { enabled: boolean; level: number; boost: boolean }) => void
  setBurnClocks: (on: boolean) => void
  setTwoPalDeck: (on: boolean) => void
  setSparkReroll: (on: boolean) => void
  setDevCareer: (on: boolean) => void
  setScenarioId: (id: number) => void
  loadScenarios: () => Promise<void>
  loadLegacy: () => void
}

export type RunSettingsStore = RunSettingsState & RunSettingsActions & { getInitialState: () => RunSettingsState }

// -------------------------------------------------------------------------
// Default state
// -------------------------------------------------------------------------
// Used until /api/scenarios answers. It must list every runnable scenario:
// normalizeScenarioId validates against this, so a scenario missing here has a
// saved selection silently rewritten to MANT on load. Mirrors
// career_bot/scenarios/__init__.py runnable_scenarios().
const FALLBACK_SCENARIOS: ScenarioOption[] = [
  { id: 4, label: 'MANT / Trackblazer' },
  { id: 2, label: 'Unity Cup' },
  { id: 3, label: 'Grand Live' },
]

const INITIAL_STATE: RunSettingsState = {
  delayMin: 1.6,
  delayMax: 3.7,
  noCd: false,
  restoreMin: 1.6,
  restoreMax: 3.7,
  // runCount: -1 = stop after SP dump; 0 = infinite; 1+ = career count
  runCount: 1,
  eventEnabled: false,
  eventLevel: 1,
  eventBoost: false,
  burnClocks: false,
  twoPalDeck: false,
  sparkReroll: false,
  devCareer: false,
  scenarioId: 4,
  scenarios: FALLBACK_SCENARIOS,
}

// -------------------------------------------------------------------------
// Store
// -------------------------------------------------------------------------
export const useRunSettings = create<RunSettingsStore>()((set, get) => ({
  ...INITIAL_STATE,

  getInitialState: () => ({ ...INITIAL_STATE }),

  setDelay(min, max) {
    const normalized = normalizeDelayBounds(min, max, false)
    set({
      delayMin: normalized.min,
      delayMax: normalized.max,
      restoreMin: normalized.restoreMin,
      restoreMax: normalized.restoreMax,
      noCd: false,
    })
    writeLocalSetting(delayKey(), normalized)
  },

  setNoCd(on) {
    const { delayMin, delayMax, restoreMin, restoreMax } = get()
    if (on) {
      // Store current values as restore targets, then zero delays
      const normalized = normalizeDelayBounds(delayMin, delayMax, true, restoreMin, restoreMax)
      set({ noCd: true, delayMin: 0, delayMax: 0, restoreMin: normalized.restoreMin, restoreMax: normalized.restoreMax })
      writeLocalSetting(delayKey(), normalized)
    } else {
      // Restore previous delay values
      const normalized = normalizeDelayBounds(restoreMin, restoreMax, false)
      set({ noCd: false, delayMin: normalized.min, delayMax: normalized.max, restoreMin: normalized.min, restoreMax: normalized.max })
      writeLocalSetting(delayKey(), normalized)
    }
  },

  setRunCount(n) {
    const safe = (Number.isInteger(n) && n >= -1) ? n : 1
    set({ runCount: safe })
    // Legacy stores raw number string, not JSON
    localStorage.setItem(runCountKey(), String(safe))
  },

  setEvent({ enabled, level, boost }) {
    set({ eventEnabled: enabled, eventLevel: level, eventBoost: boost })
    // Event settings are not persisted to localStorage in the legacy UI;
    // they are read from DOM state on each run start and synced via /api/selection.
  },

  setBurnClocks(on) {
    set({ burnClocks: on })
    writeLocalSetting(burnKey(), on)
  },

  setTwoPalDeck(on) {
    set({ twoPalDeck: on })
    writeLocalSetting(twoPalDeckKey(), on)
  },

  setSparkReroll(on) {
    set({ sparkReroll: on })
    writeLocalSetting(sparkRerollKey(), on)
  },

  setDevCareer(on) {
    set({ devCareer: on })
    // Legacy stores raw string "true"/"false" via localStorage.setItem (not writeLocalSetting)
    localStorage.setItem(devKey(), String(on))
  },

  setScenarioId(id) {
    const scenarioId = normalizeScenarioId(id, get().scenarios.map((scenario) => scenario.id))
    set({ scenarioId })
    localStorage.setItem(scenarioKey(), String(scenarioId))
  },

  async loadScenarios() {
    try {
      const res = await listScenarios()
      if (res.success && res.scenarios.length > 0) {
        set({ scenarios: res.scenarios })
      }
    } catch {
      // Keep the fallback options when the registry endpoint is unavailable.
    }
  },

  loadLegacy() {
    // Reset to defaults first so switching to an account with no saved settings
    // doesn't inherit the previously-selected account's values.
    set({ ...INITIAL_STATE, scenarios: get().scenarios })

    // uma_turn_delay_settings — JSON { min, max, restoreMin, restoreMax, disabled }
    const rawDelay = localStorage.getItem(delayKey())
    const storedDelay = readLocalSetting<DelayNormalized | null>(rawDelay, null)
    if (storedDelay) {
      const normalized = normalizeDelayBounds(
        storedDelay.min,
        storedDelay.max,
        storedDelay.disabled,
        storedDelay.restoreMin,
        storedDelay.restoreMax,
      )
      set({
        delayMin: normalized.min,
        delayMax: normalized.max,
        noCd: normalized.disabled,
        restoreMin: normalized.restoreMin,
        restoreMax: normalized.restoreMax,
      })
    }

    // uma_run_count — raw number string
    const rawRunCount = localStorage.getItem(runCountKey())
    if (rawRunCount !== null) {
      const v = parseInt(rawRunCount, 10)
      set({ runCount: (Number.isInteger(v) && v >= -1) ? v : 1 })
    }

    // uma_burn_clocks — JSON boolean
    const rawBurnClocks = localStorage.getItem(burnKey())
    if (rawBurnClocks !== null) {
      set({ burnClocks: readLocalSetting<boolean>(rawBurnClocks, false) })
    }

    // uma_two_pal_deck — JSON boolean
    const rawTwoPalDeck = localStorage.getItem(twoPalDeckKey())
    if (rawTwoPalDeck !== null) {
      set({ twoPalDeck: readLocalSetting<boolean>(rawTwoPalDeck, false) })
    }

    // uma_spark_reroll — JSON boolean
    const rawSparkReroll = localStorage.getItem(sparkRerollKey())
    if (rawSparkReroll !== null) {
      set({ sparkReroll: readLocalSetting<boolean>(rawSparkReroll, false) })
    }

    // uma_dev_career — raw string "true"/"false"
    const rawDev = localStorage.getItem(devKey())
    if (rawDev !== null) {
      set({ devCareer: rawDev === 'true' })
    }

    // uma_scenario_id — raw number string; 4 = MANT / Trackblazer, 2 = Unity Cup
    const rawScenario = localStorage.getItem(scenarioKey())
    if (rawScenario !== null) {
      set({ scenarioId: normalizeScenarioId(rawScenario, get().scenarios.map((scenario) => scenario.id)) })
    }
  },
}))
