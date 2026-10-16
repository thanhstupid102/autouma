import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { BotConfigResponse } from '@/api/types'
import { botConfigValueAt, resetBotConfigStoreForTests, useBotConfig } from './botConfig'

vi.mock('@/api/botConfig', () => ({
  getBotConfig: vi.fn(),
  saveBotConfig: vi.fn(),
  resetBotConfig: vi.fn(),
}))

import { getBotConfig, resetBotConfig, saveBotConfig } from '@/api/botConfig'

const mockGetBotConfig = vi.mocked(getBotConfig)
const mockSaveBotConfig = vi.mocked(saveBotConfig)
const mockResetBotConfig = vi.mocked(resetBotConfig)

function response(restThreshold = 48): BotConfigResponse {
  const config = {
    version: 1,
    scenarios: {
      '4': {
        rest_threshold: restThreshold,
        mant_config: { tier_count: 8 },
      },
      '2': {
        min_train_score: 1.0,
      },
    },
  }
  return {
    success: true,
    config,
    default_config: {
      version: 1,
      scenarios: {
        '4': {
          rest_threshold: 48,
          mant_config: { tier_count: 8 },
        },
        '2': {
          min_train_score: 1.0,
        },
      },
    },
    scenarios: [
      { scenario_id: 4, name: 'MANT / Make a New Track' },
      { scenario_id: 2, name: 'Unity Cup' },
    ],
    fields: {
      '4': [
        { key: 'rest_threshold', label: 'Rest vital threshold', kind: 'number', default: 48, category: 'General' },
        { key: 'mant_config.tier_count', label: 'Tier count', kind: 'number', default: 8, category: 'Nested / item policy' },
      ],
      '2': [
        { key: 'min_train_score', label: 'Minimum training score', kind: 'number', default: 1.0, category: 'General' },
      ],
    },
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  resetBotConfigStoreForTests()
})

describe('bot config store', () => {
  it('loads global config, scenarios, and field specs', async () => {
    mockGetBotConfig.mockResolvedValueOnce(response())

    await useBotConfig.getState().load()

    const state = useBotConfig.getState()
    expect(state.config?.scenarios['4'].rest_threshold).toBe(48)
    expect(state.scenarios.map((scenario) => scenario.scenario_id)).toEqual([4, 2])
    expect(state.fields['4']).toHaveLength(2)
  })

  it('updates flat and nested selected-scenario fields immutably', async () => {
    mockGetBotConfig.mockResolvedValueOnce(response())
    await useBotConfig.getState().load()

    useBotConfig.getState().updateField('rest_threshold', 60)
    useBotConfig.getState().updateField('mant_config.tier_count', 10)

    const values = useBotConfig.getState().config?.scenarios['4']
    expect(botConfigValueAt(values, 'rest_threshold')).toBe(60)
    expect(botConfigValueAt(values, 'mant_config.tier_count')).toBe(10)
    expect(useBotConfig.getState().isDirty()).toBe(true)
  })

  it('saves the active config through the API and adopts the response', async () => {
    mockGetBotConfig.mockResolvedValueOnce(response())
    mockSaveBotConfig.mockResolvedValueOnce(response(64))
    await useBotConfig.getState().load()
    useBotConfig.getState().updateField('rest_threshold', 64)

    await useBotConfig.getState().save()

    expect(mockSaveBotConfig).toHaveBeenCalledWith({
      config: expect.objectContaining({ version: 1 }),
    })
    expect(useBotConfig.getState().config?.scenarios['4'].rest_threshold).toBe(64)
    expect(useBotConfig.getState().isDirty()).toBe(false)
  })

  it('resets to backend defaults', async () => {
    mockGetBotConfig.mockResolvedValueOnce(response(60))
    mockResetBotConfig.mockResolvedValueOnce(response(48))
    await useBotConfig.getState().load()

    await useBotConfig.getState().reset()

    expect(mockResetBotConfig).toHaveBeenCalledOnce()
    expect(useBotConfig.getState().config?.scenarios['4'].rest_threshold).toBe(48)
  })
})
