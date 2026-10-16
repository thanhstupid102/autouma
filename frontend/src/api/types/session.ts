import type { Account } from './library'
import type { DeckInfo, FriendInfo, TraineeInfo, ParentInfo } from './library'
import type { SupportCard } from './library'

// ---------------------------------------------------------------------------
// Selection
// ---------------------------------------------------------------------------

export interface EventSelection {
  enabled: boolean
  level: number
  boost: boolean
}

export interface Selection {
  deck?: DeckInfo | null
  friend?: FriendInfo | null
  trainee?: TraineeInfo | null
  veterans?: ParentInfo[]
  rental?: number | string | null
  event?: EventSelection
  [k: string]: unknown
}

// ---------------------------------------------------------------------------
// Session / dashboard data
// ---------------------------------------------------------------------------

export type TransitionLinkReason = 'steam_link_removed'

export interface SessionData {
  success: boolean
  state?:
    | 'authenticated'
    | 'needs_steam_login'
    | 'needs_steam_guard'
    | 'needs_transition_link'
    | 'pre_signup_complete'
    | 'steam_signup_disabled'
    | 'failed'
  account?: Account
  selection?: Selection
  decks?: DeckInfo[]
  umas?: TraineeInfo[]
  supports?: SupportCard[]
  parents?: ParentInfo[]
  friends?: FriendInfo[]
  friend_exclude_ids?: (number | string)[]
  needs_2fa?: boolean
  reason?: TransitionLinkReason
  viewer_id?: number | string
  error_code?: string
  detail?: string
  [k: string]: unknown
}

export interface SyncSelectionBody {
  selection: Selection
}
