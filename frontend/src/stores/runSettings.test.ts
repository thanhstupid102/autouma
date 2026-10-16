import { describe, it, expect, beforeEach } from 'vitest'
import { useRunSettings } from './runSettings'

beforeEach(() => {
  localStorage.clear()
  // Reset store to defaults before each test
  useRunSettings.setState(useRunSettings.getInitialState())
})

describe('runSettings', () => {
  it('defaults: delay 1.6–3.7, runCount 1, toggles off', () => {
    const s = useRunSettings.getState()
    expect(s.delayMin).toBe(1.6)
    expect(s.delayMax).toBe(3.7)
    expect(s.runCount).toBe(1)
    expect(s.noCd).toBe(false)
    expect(s.burnClocks).toBe(false)
    expect(s.sparkReroll).toBe(false)
    expect(s.devCareer).toBe(false)
    expect(s.scenarioId).toBe(4)
    expect(s.eventEnabled).toBe(false)
    expect(s.eventLevel).toBe(1)
    expect(s.eventBoost).toBe(false)
  })

  it('hydrates from legacy uma_turn_delay_settings', () => {
    // Legacy stores the full normalized object: { min, max, restoreMin, restoreMax, disabled }
    localStorage.setItem('uma_turn_delay_settings__default', JSON.stringify({ min: 2, max: 5, restoreMin: 2, restoreMax: 5, disabled: false }))
    localStorage.setItem('uma_run_count__default', '3')
    localStorage.setItem('uma_burn_clocks__default', 'true')
    localStorage.setItem('uma_spark_reroll__default', 'true')
    localStorage.setItem('uma_dev_career__default', 'true')
    localStorage.setItem('uma_scenario_id__default', '2')
    useRunSettings.getState().loadLegacy()
    const s = useRunSettings.getState()
    expect(s.delayMin).toBe(2)
    expect(s.delayMax).toBe(5)
    expect(s.runCount).toBe(3)
    expect(s.burnClocks).toBe(true)
    expect(s.sparkReroll).toBe(true)
    expect(s.devCareer).toBe(true)
    expect(s.scenarioId).toBe(2)
  })

  it('persists scenarioId to uma_scenario_id and normalizes invalid values', () => {
    useRunSettings.getState().setScenarioId(2)
    expect(useRunSettings.getState().scenarioId).toBe(2)
    expect(localStorage.getItem('uma_scenario_id__default')).toBe('2')

    useRunSettings.getState().setScenarioId(3)
    expect(useRunSettings.getState().scenarioId).toBe(3)
    expect(localStorage.getItem('uma_scenario_id__default')).toBe('3')

    useRunSettings.getState().setScenarioId(999)
    expect(useRunSettings.getState().scenarioId).toBe(4)
    expect(localStorage.getItem('uma_scenario_id__default')).toBe('4')

    localStorage.setItem('uma_scenario_id__default', 'bad')
    useRunSettings.getState().loadLegacy()
    expect(useRunSettings.getState().scenarioId).toBe(4)
  })

  it('persists runCount to uma_run_count', () => {
    useRunSettings.getState().setRunCount(-1)
    expect(localStorage.getItem('uma_run_count__default')).toBe('-1')
    useRunSettings.getState().setRunCount(0)
    expect(localStorage.getItem('uma_run_count__default')).toBe('0')
    useRunSettings.getState().setRunCount(5)
    expect(localStorage.getItem('uma_run_count__default')).toBe('5')
  })

  it('normalizes runCount: -1 is valid; lower negatives/non-integers fall back to 1', () => {
    useRunSettings.getState().setRunCount(-1)
    expect(useRunSettings.getState().runCount).toBe(-1)
    useRunSettings.getState().setRunCount(-2)
    expect(useRunSettings.getState().runCount).toBe(1)
    // 0 is valid (infinite)
    useRunSettings.getState().setRunCount(0)
    expect(useRunSettings.getState().runCount).toBe(0)
  })

  it('clamps/swaps invalid delay bounds like legacy normalizeDelayBounds', () => {
    // Negative → clamped to 0
    useRunSettings.getState().setDelay(-1, -2)
    expect(useRunSettings.getState().delayMin).toBe(0)
    expect(useRunSettings.getState().delayMax).toBe(0)

    // min > max → max is raised to equal min (left > right → right = left)
    useRunSettings.getState().setDelay(5, 2)
    expect(useRunSettings.getState().delayMin).toBe(5)
    expect(useRunSettings.getState().delayMax).toBe(5)

    // Normal range passes through
    useRunSettings.getState().setDelay(1, 3)
    expect(useRunSettings.getState().delayMin).toBe(1)
    expect(useRunSettings.getState().delayMax).toBe(3)
  })

  it('noCd zeroes delays and restores previous values when toggled off', () => {
    // Set known values first
    useRunSettings.getState().setDelay(1.5, 4.0)
    expect(useRunSettings.getState().delayMin).toBe(1.5)
    expect(useRunSettings.getState().delayMax).toBe(4.0)

    // Enable noCd: delays become 0, restore values saved
    useRunSettings.getState().setNoCd(true)
    const s1 = useRunSettings.getState()
    expect(s1.noCd).toBe(true)
    expect(s1.delayMin).toBe(0)
    expect(s1.delayMax).toBe(0)
    expect(s1.restoreMin).toBe(1.5)
    expect(s1.restoreMax).toBe(4.0)

    // Disable noCd: delays restored from restoreMin/restoreMax
    useRunSettings.getState().setNoCd(false)
    const s2 = useRunSettings.getState()
    expect(s2.noCd).toBe(false)
    expect(s2.delayMin).toBe(1.5)
    expect(s2.delayMax).toBe(4.0)
  })

  it('persists burnClocks + sparkReroll + devCareer to legacy keys', () => {
    useRunSettings.getState().setBurnClocks(true)
    // Legacy: writeLocalSetting(key, value) → JSON.stringify(value)
    expect(localStorage.getItem('uma_burn_clocks__default')).toBe('true')

    useRunSettings.getState().setSparkReroll(true)
    expect(localStorage.getItem('uma_spark_reroll__default')).toBe('true')

    useRunSettings.getState().setDevCareer(true)
    expect(localStorage.getItem('uma_dev_career__default')).toBe('true')

    useRunSettings.getState().setBurnClocks(false)
    expect(localStorage.getItem('uma_burn_clocks__default')).toBe('false')

    useRunSettings.getState().setSparkReroll(false)
    expect(localStorage.getItem('uma_spark_reroll__default')).toBe('false')
  })

  it('persists delay settings to uma_turn_delay_settings as normalized JSON', () => {
    useRunSettings.getState().setDelay(2.0, 4.5)
    const stored = JSON.parse(localStorage.getItem('uma_turn_delay_settings__default')!)
    // Legacy normalizeDelayBounds stores: { min, max, restoreMin, restoreMax, disabled }
    expect(stored.min).toBe(2.0)
    expect(stored.max).toBe(4.5)
    expect(stored.disabled).toBe(false)
    expect(stored.restoreMin).toBe(2.0)
    expect(stored.restoreMax).toBe(4.5)
  })

  it('hydrates noCd (disabled) state from legacy uma_turn_delay_settings', () => {
    // When disabled=true, legacy stores { min:0, max:0, restoreMin, restoreMax, disabled:true }
    localStorage.setItem('uma_turn_delay_settings__default', JSON.stringify({ min: 0, max: 0, restoreMin: 1.6, restoreMax: 3.7, disabled: true }))
    useRunSettings.getState().loadLegacy()
    const s = useRunSettings.getState()
    expect(s.noCd).toBe(true)
    expect(s.delayMin).toBe(0)
    expect(s.delayMax).toBe(0)
    expect(s.restoreMin).toBe(1.6)
    expect(s.restoreMax).toBe(3.7)
  })
})
