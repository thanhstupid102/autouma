// ---------------------------------------------------------------------------
// Bot Configuration — global scoring / train-decision preset
// ---------------------------------------------------------------------------

export type BotConfigPrimitive = string | number | boolean | null
export type BotConfigJsonValue =
  | BotConfigPrimitive
  | BotConfigJsonValue[]
  | { [key: string]: BotConfigJsonValue }

export type BotConfigScenarioValues = Record<string, BotConfigJsonValue>

export interface BotConfigDocument {
  version: number
  scenarios: Record<string, BotConfigScenarioValues>
}

export interface BotConfigScenarioInfo {
  scenario_id: number
  name: string
  description?: string
}

export interface BotConfigFieldSpec {
  key: string
  label: string
  description?: string
  kind: 'boolean' | 'number' | 'string' | 'array' | 'object'
  default: BotConfigJsonValue
  category: string
}

export interface BotConfigResponse {
  success: boolean
  config: BotConfigDocument
  default_config: BotConfigDocument
  scenarios: BotConfigScenarioInfo[]
  fields: Record<string, BotConfigFieldSpec[]>
  detail?: string
}

export interface SaveBotConfigBody {
  config: BotConfigDocument
}
