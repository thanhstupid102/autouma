/**
 * racePresets store — single source of truth for race preset list + selected race preset.
 *
 * localStorage key: `uma_selected_race_preset`, scoped per account by `accountKey()`.
 *
 * The load/select/create/remove/update/getActive bodies live in
 * `createPresetStore.ts`, shared with the skill-preset store — this file holds
 * the race-preset config (API module, key, template, messages) plus the one
 * action that is genuinely race-only: `saveRaces`.
 *
 * A race preset stores name + races ONLY. There is deliberately no scenario
 * field: the scenario a run uses is chosen per-run in RunBar.
 *
 * Action contracts:
 *   load()          — GET list; resolve selected; write localStorage
 *   select(name)    — set selectedName + write localStorage
 *   create(name)    — normalise → validate → POST → reload; throws on error
 *   remove(name)    — DELETE /api/presets/{name}?kind=race → reload; throws on error
 *   update(preset)  — POST full RacePreset (replace by name); optimistic update
 *   saveRaces(n, r) — PUT the race schedule only; the single owner of race-list
 *                     persistence (one mutation per user save)
 *   getActive()     — selector → RacePreset | undefined
 */

import { create } from 'zustand'
import { getRacePresets, saveRacePreset, deleteRacePreset, saveRacesToRacePreset } from '@/api/presets'
import type { RacePreset } from '@/api/types'
import {
  createPresetSlice,
  type PresetSlice,
  type PresetSliceActions,
  type PresetSliceState,
  type PresetStoreConfig,
} from './createPresetStore'

// ---------------------------------------------------------------------------
// Store types
// ---------------------------------------------------------------------------
export type RacePresetsState = PresetSliceState<RacePreset>

export type RacePresetsActions = PresetSliceActions<RacePreset> & {
  /**
   * Persist ONLY the race schedule of a preset. This is the single owner of
   * race-list persistence: it issues one mutation (the race-list endpoint) and
   * mirrors the result into the store. Callers must not additionally save the
   * whole preset -- doing both was two mutations for one user action, and the
   * second could clobber server-side fields from a stale local copy.
   */
  saveRaces: (name: string, races: number[]) => Promise<void>
}

export type RacePresetsStore = PresetSlice<RacePreset> & Pick<RacePresetsActions, 'saveRaces'>

// ---------------------------------------------------------------------------
// Config — everything that differs from the skill-preset store
// ---------------------------------------------------------------------------
const RACE_PRESET_CONFIG: PresetStoreConfig<RacePreset> = {
  storageKey: 'uma_selected_race_preset',
  list: () => getRacePresets(),
  save: (body) => saveRacePreset(body),
  remove: (body) => deleteRacePreset(body),
  // A race preset is name + races only — no scenario field.
  newPreset: (name) => ({ name, extra_race_list: [] }),
  errors: {
    emptyName: 'Race preset name cannot be empty.',
    duplicateName: 'A race preset with that name already exists.',
    saveFailed: 'Failed to save new race preset.',
    deleteFailed: 'Failed to delete race preset.',
  },
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------
export const useRacePresets = create<RacePresetsStore>()((set, get) => ({
  ...createPresetSlice(RACE_PRESET_CONFIG)(set, get),

  // -------------------------------------------------------------------------
  // saveRaces — race-only, so it stays here rather than in the shared slice.
  // Single owner of race-schedule persistence: ONE mutation (the race-list
  // endpoint), then mirror the saved list into the store so other consumers see
  // it. Previously the caller also POSTed the whole preset, which made one user
  // save two mutations (inconsistent on partial failure) and could overwrite
  // server-side fields from a stale local copy.
  // -------------------------------------------------------------------------
  async saveRaces(name, races) {
    const res = await saveRacesToRacePreset({ preset_name: name, races })
    if (res && res.success === false) {
      throw new Error(res.detail ?? 'Save failed')
    }
    set((s) => ({
      presets: s.presets.map((p) =>
        p.name === name ? { ...p, extra_race_list: [...races] } : p,
      ),
    }))
  },
}))
