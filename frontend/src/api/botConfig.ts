import { apiJson } from './client'
import type { BotConfigResponse, SaveBotConfigBody } from './types'

/** GET /api/bot-config — read the global active bot scoring preset. */
export const getBotConfig = () =>
  apiJson<BotConfigResponse>('/api/bot-config')

/** POST /api/bot-config — validate and persist the global active bot config. */
export const saveBotConfig = (body: SaveBotConfigBody) =>
  apiJson<BotConfigResponse>('/api/bot-config', {
    method: 'POST',
    body,
  })

/** POST /api/bot-config/reset — remove active override and return defaults. */
export const resetBotConfig = () =>
  apiJson<BotConfigResponse>('/api/bot-config/reset', {
    method: 'POST',
  })
