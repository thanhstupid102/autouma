// ---------------------------------------------------------------------------
// Settings — turn delay
// ---------------------------------------------------------------------------

export interface TurnDelaySettings {
  min: number
  max: number
  disabled?: boolean
  restore_min?: number
  restore_max?: number
  [k: string]: unknown
}

// ---------------------------------------------------------------------------
// Settings — Discord webhook
// ---------------------------------------------------------------------------

export interface DiscordWebhookData {
  configured?: boolean
  webhook_preview?: string | null
  error_mention?: string | null
  [k: string]: unknown
}

export interface SaveWebhookBody {
  webhook_url?: string
  error_mention?: string | null
}
