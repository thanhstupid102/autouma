// ---------------------------------------------------------------------------
// Skills
// ---------------------------------------------------------------------------

export interface SkillEntry {
  id?: string | number
  name: string
  rarity?: number
  tags?: (number | string)[]
  [k: string]: unknown
}
