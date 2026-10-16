/**
 * presets store — single source of truth for preset list + selected preset.
 *
 * localStorage key: `uma_selected_preset` (exact string — preserved from the
 * legacy UI so a pre-React selection still resolves), scoped per account by
 * `accountKey()`.
 *
 * The action bodies live in `createPresetStore.ts`, shared with racePresets —
 * this file is just the skill-preset half of the config (API module, key,
 * template, messages).
 *
 * Action contracts:
 *   load()          — GET list; resolve selected; write localStorage
 *   select(name)    — set selectedName + write localStorage
 *   create(name)    — normalise → validate → POST → reload; throws on error
 *   remove(name)    — DELETE /api/presets/{name} → reload; throws on error
 *   update(preset)  — POST full Preset (replace by name); optimistic update.
 *                     SkillEditorDialog calls this with a modified copy of the
 *                     active preset. (The race schedule does NOT: it persists
 *                     through the separate racePresets store's saveRaces.)
 *   getActive()     — selector → Preset | undefined
 */

import { create } from 'zustand'
import { getPresets, savePreset, deletePreset } from '@/api/presets'
import type { Preset } from '@/api/types'
import { newPresetTemplate } from './presetRules'
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
export type PresetsState = PresetSliceState<Preset>
export type PresetsActions = PresetSliceActions<Preset>
export type PresetsStore = PresetSlice<Preset>

// ---------------------------------------------------------------------------
// Config — everything that differs from the race-preset store
// ---------------------------------------------------------------------------
const SKILL_PRESET_CONFIG: PresetStoreConfig<Preset> = {
  storageKey: 'uma_selected_preset',
  list: () => getPresets(),
  save: (body) => savePreset(body),
  remove: (body) => deletePreset(body),
  newPreset: (name) => newPresetTemplate(name),
  errors: {
    emptyName: 'Preset name cannot be empty.',
    duplicateName: 'A preset with that name already exists.',
    saveFailed: 'Failed to save new preset.',
    deleteFailed: 'Failed to delete preset.',
  },
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------
export const usePresets = create<PresetsStore>()((set, get) =>
  createPresetSlice(SKILL_PRESET_CONFIG)(set, get),
)
