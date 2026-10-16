import { apiJson } from './client'
import type { ScenarioOption } from './types/scenario'

export const listScenarios = () =>
  apiJson<{ success: boolean; scenarios: ScenarioOption[] }>('/api/scenarios')
