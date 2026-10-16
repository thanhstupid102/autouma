import type { CareerStatus } from './career'

// ---------------------------------------------------------------------------
// Account
// ---------------------------------------------------------------------------

export interface Account {
  tp?: { current: number; max: number }
  carrots?: { total: number; [k: string]: unknown }
  gold?: number
  clocks?: number
  career?: CareerStatus
  [k: string]: unknown
}

// ---------------------------------------------------------------------------
// Support cards / decks / friends / trainees
// ---------------------------------------------------------------------------

export interface SupportCard {
  id: string | number
  name?: string
  type?: string
  rarity?: number | string
  [k: string]: unknown
}

export interface DeckInfo {
  id: number | string
  name: string
  cards: SupportCard[]
  [k: string]: unknown
}

export interface FriendInfo {
  viewer_id: number | string
  name?: string
  support_card_id: number | string
  support_name?: string
  type?: string
  limit_break_count?: number
  rental_parent?: RentalParent
  [k: string]: unknown
}

export interface TraineeInfo {
  id: number | string
  name?: string
  [k: string]: unknown
}

// ---------------------------------------------------------------------------
// Parents / lineage
// ---------------------------------------------------------------------------

export interface ParentLineageFactor {
  name?: string
  stars?: number | string
  category?: string
  [k: string]: unknown
}

export interface ParentLineageWins {
  total?: number
  g1?: number
  g2?: number
  g3?: number
  [k: string]: unknown
}

export interface ParentLineageNode {
  card_id?: number | string
  name?: string
  factors?: ParentLineageFactor[]
  wins?: ParentLineageWins
  [k: string]: unknown
}

export interface ParentLineageTree {
  self?: ParentLineageNode
  p1?: ParentLineageNode
  p2?: ParentLineageNode
  gp1?: ParentLineageNode
  gp2?: ParentLineageNode
  gp3?: ParentLineageNode
  gp4?: ParentLineageNode
  [key: string]: ParentLineageNode | undefined
}

export interface SparkSubject {
  tree?: ParentLineageTree
  [k: string]: unknown
}

export interface RentalParent extends SparkSubject {
  card_id?: number | string
  name?: string
  rank?: number
  trained_chara_id: number | string
}

export interface ParentInfo extends SparkSubject {
  instance_id: number | string
  card_id?: number | string
  /** 1 = locked (memo) — cannot be removed without unlocking first. */
  is_locked?: number
}

export interface DeleteParentsBody {
  instance_ids: (number | string)[]
  /** Unlock locked (memo) veterans before removing them. */
  unlock_locked?: boolean
}

export interface AutoDeleteCondition {
  name: string
  /** include = has · atleast = >= min_stars · exclude = not. */
  mode: 'include' | 'atleast' | 'exclude'
  min_stars: number
  /** Spark colour the factor belongs to — used for grouping + OR-within-colour. */
  colour?: 'blue' | 'pink' | 'white' | 'green'
}

export interface AutoDeleteConfig {
  enabled: boolean
  min_blue: number
  min_pink: number
  min_white: number
  min_green: number
  conditions: AutoDeleteCondition[]
}

// ---------------------------------------------------------------------------
// Rental quota
// ---------------------------------------------------------------------------

export interface RentalQuota {
  used: number
  max: number
  remaining: number
}

export interface GetFriendsBody {
  exclude_viewer_ids: (number | string)[]
}
