/**
 * presetRules — pure helpers extracted for unit testing.
 * Ported from app.js:1162-1169 and app.js:1890-1897.
 *
 * Consumers: presetsStore (create action), racePresetsStore, tests.
 */

import type { Preset } from '@/api/types'

// ---------------------------------------------------------------------------
// normalizePresetName — app.js:1162-1164
// Trim, strip chars not [a-zA-Z0-9._ -], collapse spaces, trim again.
// ---------------------------------------------------------------------------
export function normalizePresetName(value: unknown): string {
  return String(value ?? '')
    .trim()
    .replace(/[^a-zA-Z0-9._ -]+/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

// ---------------------------------------------------------------------------
// presetNameExists — app.js:1166-1169
// Case-insensitive duplicate check against a list of named items.
// Accepts any list with a `name` string field (Preset, RacePreset, etc.).
// ---------------------------------------------------------------------------
export function presetNameExists(name: string, presets: { name: string }[]): boolean {
  const normalized = normalizePresetName(name).toLowerCase()
  return Boolean(
    normalized && presets.some((p) => p.name.toLowerCase() === normalized),
  )
}

// ---------------------------------------------------------------------------
// newPresetTemplate — app.js:1890-1897
// Returns the canonical default preset object for a given name.
//
// No scenario key is posted: the scenario a run uses is chosen per-run in
// RunBar, and `hydrate_preset` stamps MANT for a preset that stores none.
// ---------------------------------------------------------------------------
export type NewPresetTemplate = Required<
  Pick<
    Preset,
    | 'name'
    | 'running_style'
    | 'learn_skill_list'
    | 'learn_skill_blacklist'
    | 'extra_race_list'
    | 'learn_skill_threshold'
  >
>

export function newPresetTemplate(name: string): NewPresetTemplate {
  const template: NewPresetTemplate = {
    name,
    running_style: 1,
    learn_skill_list: [],
    learn_skill_blacklist: [],
    extra_race_list: [],
    learn_skill_threshold: 888,
  }
  return template
}
