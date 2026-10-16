// ---------------------------------------------------------------------------
// Login
// ---------------------------------------------------------------------------

export interface LoginBody {
  username?: string
  password?: string
  code?: string
}

// ---------------------------------------------------------------------------
// Trainer-ID transition link
// ---------------------------------------------------------------------------

export interface TransitionCodeChainBody {
  input_viewer_id: string
  password: string
  verify_only?: boolean
}

export interface TransitionCodeChainData {
  success: boolean
  state?: 'authenticated' | 'verified' | 'failed'
  name?: string | null
  request_user_name?: string | null
  error_code?: string
  detail?: string
  [k: string]: unknown
}

// ---------------------------------------------------------------------------
// Steam unbind
// ---------------------------------------------------------------------------

export interface SteamUnbindBody {
  confirm_account_name: string
  link_password?: string
}

export interface SteamUnbindPreflightBody extends SteamUnbindBody {
  link_password: string
}

export interface SteamUnbindData {
  success: boolean
  state?: 'verified' | 'unbound' | 'failed'
  recovery_verified?: 'verified' | 'not_checked'
  name?: string | null
  request_user_name?: string | null
  preflight_account?: string
  steam_unbound_at?: number
  error_code?: string
  detail?: string
}

// ---------------------------------------------------------------------------
// QR login
// ---------------------------------------------------------------------------

export interface QrStartData {
  challenge_url?: string
  [k: string]: unknown
}

export interface QrPollData {
  status: 'pending' | 'confirmed' | 'expired' | 'error'
  error?: string
  [k: string]: unknown
}
