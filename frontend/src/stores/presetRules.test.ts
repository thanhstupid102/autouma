import { describe, it, expect } from 'vitest'
import {
  normalizePresetName,
  presetNameExists,
  newPresetTemplate,
} from './presetRules'
import type { Preset } from '@/api/types'

// ---------------------------------------------------------------------------
// normalizePresetName
// ---------------------------------------------------------------------------
describe('normalizePresetName', () => {
  it('trims leading/trailing whitespace', () => {
    expect(normalizePresetName('  hello  ')).toBe('hello')
  })

  it('strips chars not in [a-zA-Z0-9._ -]', () => {
    expect(normalizePresetName('hello!@#world')).toBe('helloworld')
    expect(normalizePresetName('abc/def:ghi')).toBe('abcdefghi')
  })

  it('collapses multiple spaces to a single space', () => {
    expect(normalizePresetName('foo   bar  baz')).toBe('foo bar baz')
  })

  it('allows dots, underscores, and hyphens', () => {
    expect(normalizePresetName('Speed_build-v1.0')).toBe('Speed_build-v1.0')
  })

  it('returns empty string for empty input', () => {
    expect(normalizePresetName('')).toBe('')
    expect(normalizePresetName('   ')).toBe('')
  })

  it('handles null/undefined gracefully', () => {
    expect(normalizePresetName(null)).toBe('')
    expect(normalizePresetName(undefined)).toBe('')
  })

  it('strips then collapses: leading/trailing spaces after strip', () => {
    // '!hello!' → 'hello'
    expect(normalizePresetName('!hello!')).toBe('hello')
    // ' ! hello ! ' → 'hello' (spaces around stripped chars)
    expect(normalizePresetName(' ! hello ! ')).toBe('hello')
  })
})

// ---------------------------------------------------------------------------
// presetNameExists
// ---------------------------------------------------------------------------
describe('presetNameExists', () => {
  const presets: Preset[] = [
    { name: 'Speed' },
    { name: 'Stamina Build' },
    { name: 'Guts.Config' },
  ]

  it('returns true for exact match', () => {
    expect(presetNameExists('Speed', presets)).toBe(true)
  })

  it('is case-insensitive', () => {
    expect(presetNameExists('speed', presets)).toBe(true)
    expect(presetNameExists('SPEED', presets)).toBe(true)
    expect(presetNameExists('sPeEd', presets)).toBe(true)
  })

  it('returns false for non-existent name', () => {
    expect(presetNameExists('Power', presets)).toBe(false)
  })

  it('normalizes input before comparison', () => {
    // 'STAMINA  BUILD' → 'STAMINA BUILD' after collapse → matches 'Stamina Build'
    expect(presetNameExists('STAMINA  BUILD', presets)).toBe(true)
  })

  it('returns false for empty/blank name', () => {
    expect(presetNameExists('', presets)).toBe(false)
    expect(presetNameExists('   ', presets)).toBe(false)
  })

  it('returns false against empty preset list', () => {
    expect(presetNameExists('Speed', [])).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// newPresetTemplate
// ---------------------------------------------------------------------------
describe('newPresetTemplate', () => {
  it('returns the exact default object', () => {
    const template = newPresetTemplate('TestPreset')
    expect(template).toEqual({
      name: 'TestPreset',
      running_style: 1,
      learn_skill_list: [],
      learn_skill_blacklist: [],
      extra_race_list: [],
      learn_skill_threshold: 888,
    })
  })

  it('uses the given name verbatim', () => {
    expect(newPresetTemplate('My Preset').name).toBe('My Preset')
  })

  it('returns new array instances each call', () => {
    const a = newPresetTemplate('A')
    const b = newPresetTemplate('B')
    expect(a.learn_skill_list).not.toBe(b.learn_skill_list)
    expect(a.extra_race_list).not.toBe(b.extra_race_list)
  })

  // -------------------------------------------------------------------------
  // scenario_id — never written by the template. The scenario a run uses is
  // picked per-run in RunBar; `hydrate_preset` stamps MANT server-side for a
  // preset that stores none.
  // -------------------------------------------------------------------------
  it('omits scenario_id entirely', () => {
    expect(newPresetTemplate('NoScenario')).not.toHaveProperty('scenario_id')
  })
})
