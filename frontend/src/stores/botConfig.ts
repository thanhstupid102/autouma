import { create } from 'zustand'

import { getBotConfig, resetBotConfig, saveBotConfig } from '@/api/botConfig'
import type {
  BotConfigDocument,
  BotConfigFieldSpec,
  BotConfigJsonValue,
  BotConfigResponse,
  BotConfigScenarioInfo,
  BotConfigScenarioValues,
} from '@/api/types'

const DEFAULT_SCENARIO_ID = '4'

function cloneConfig(config: BotConfigDocument): BotConfigDocument {
  return JSON.parse(JSON.stringify(config)) as BotConfigDocument
}

function isPlainObject(value: unknown): value is Record<string, BotConfigJsonValue> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function botConfigValueAt(
  values: BotConfigScenarioValues | undefined,
  path: string,
): BotConfigJsonValue | undefined {
  let cursor: BotConfigJsonValue | undefined = values
  for (const part of path.split('.')) {
    if (!isPlainObject(cursor)) return undefined
    cursor = cursor[part]
  }
  return cursor
}

function setBotConfigValueAt(
  values: BotConfigScenarioValues,
  path: string,
  value: BotConfigJsonValue,
) {
  const parts = path.split('.').filter(Boolean)
  if (!parts.length) return
  let cursor: Record<string, BotConfigJsonValue> = values
  for (const part of parts.slice(0, -1)) {
    if (!isPlainObject(cursor[part])) cursor[part] = {}
    cursor = cursor[part] as Record<string, BotConfigJsonValue>
  }
  cursor[parts[parts.length - 1]] = value
}

function scenarioKey(id: string | number | undefined): string {
  return String(id || DEFAULT_SCENARIO_ID)
}

function resolveScenarioId(scenarios: BotConfigScenarioInfo[], current: string): string {
  if (scenarios.some((scenario) => scenarioKey(scenario.scenario_id) === current)) {
    return current
  }
  return scenarioKey(scenarios[0]?.scenario_id)
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Bot configuration request failed.'
}

function stateFromResponse(
  response: BotConfigResponse,
  currentScenarioId: string,
): Pick<BotConfigState, 'config' | 'savedConfig' | 'defaultConfig' | 'scenarios' | 'fields' | 'selectedScenarioId'> {
  const scenarios = response.scenarios ?? []
  return {
    config: response.config,
    savedConfig: cloneConfig(response.config),
    defaultConfig: response.default_config,
    scenarios,
    fields: response.fields ?? {},
    selectedScenarioId: resolveScenarioId(scenarios, currentScenarioId),
  }
}

export interface BotConfigState {
  config?: BotConfigDocument
  savedConfig?: BotConfigDocument
  defaultConfig?: BotConfigDocument
  scenarios: BotConfigScenarioInfo[]
  fields: Record<string, BotConfigFieldSpec[]>
  selectedScenarioId: string
  loading: boolean
  saving: boolean
  error: string
}

export interface BotConfigActions {
  load: () => Promise<void>
  selectScenario: (scenarioId: string | number) => void
  updateField: (path: string, value: BotConfigJsonValue) => void
  replaceConfig: (config: BotConfigDocument) => void
  save: (config?: BotConfigDocument) => Promise<void>
  reset: () => Promise<void>
  getScenarioValues: () => BotConfigScenarioValues
  getFieldValue: (path: string) => BotConfigJsonValue | undefined
  isDirty: () => boolean
}

export type BotConfigStore = BotConfigState & BotConfigActions

const INITIAL_STATE: BotConfigState = {
  config: undefined,
  savedConfig: undefined,
  defaultConfig: undefined,
  scenarios: [],
  fields: {},
  selectedScenarioId: DEFAULT_SCENARIO_ID,
  loading: false,
  saving: false,
  error: '',
}

export const useBotConfig = create<BotConfigStore>()((set, get) => ({
  ...INITIAL_STATE,

  async load() {
    set({ loading: true, error: '' })
    try {
      const response = await getBotConfig()
      set({
        ...stateFromResponse(response, get().selectedScenarioId),
        loading: false,
        error: '',
      })
    } catch (error) {
      const message = errorMessage(error)
      set({ loading: false, error: message })
      throw error
    }
  },

  selectScenario(scenarioId) {
    set({ selectedScenarioId: scenarioKey(scenarioId) })
  },

  updateField(path, value) {
    const { config, selectedScenarioId } = get()
    if (!config) return
    const next = cloneConfig(config)
    next.scenarios[selectedScenarioId] = next.scenarios[selectedScenarioId] ?? {}
    setBotConfigValueAt(next.scenarios[selectedScenarioId], path, value)
    set({ config: next })
  },

  replaceConfig(config) {
    set({ config: cloneConfig(config), error: '' })
  },

  async save(configOverride) {
    const config = configOverride ?? get().config
    if (!config) return
    set({ saving: true, error: '' })
    try {
      const response = await saveBotConfig({ config })
      set({
        ...stateFromResponse(response, get().selectedScenarioId),
        saving: false,
        error: '',
      })
    } catch (error) {
      const message = errorMessage(error)
      set({ saving: false, error: message })
      throw error
    }
  },

  async reset() {
    set({ saving: true, error: '' })
    try {
      const response = await resetBotConfig()
      set({
        ...stateFromResponse(response, get().selectedScenarioId),
        saving: false,
        error: '',
      })
    } catch (error) {
      const message = errorMessage(error)
      set({ saving: false, error: message })
      throw error
    }
  },

  getScenarioValues() {
    const { config, selectedScenarioId } = get()
    return config?.scenarios?.[selectedScenarioId] ?? {}
  },

  getFieldValue(path) {
    return botConfigValueAt(get().getScenarioValues(), path)
  },

  isDirty() {
    const { config, savedConfig } = get()
    if (!config || !savedConfig) return false
    return JSON.stringify(config) !== JSON.stringify(savedConfig)
  },
}))

export function resetBotConfigStoreForTests() {
  useBotConfig.setState(INITIAL_STATE)
}
