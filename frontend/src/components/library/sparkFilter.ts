import type { SparkSubject } from '@/api/types'
import { compareDisplayText } from '@/lib/locale'
import { normalizedCardName } from './libraryRules'

export type SparkColour = 'blue' | 'pink' | 'white' | 'green'

/**
 * A single per-factor requirement.
 *   include  = "has" (present, >= 1 star)
 *   atleast  = ">=" (present with >= minStars)
 *   exclude  = "not" (absent)
 */
export type SparkConditionMode = 'include' | 'atleast' | 'exclude'

export interface SparkCondition {
  colour: SparkColour
  name: string
  mode: SparkConditionMode
  minStars: number
}

export interface SparkFilter {
  /** Combined star totals across all factors of a colour (full lineage). */
  minBlue: number
  minPink: number
  minWhite: number
  minGreen: number
  /** Per-factor requirements. */
  conditions: SparkCondition[]
}

export type SparkColourOptions = Record<SparkColour, string[]>

export const EMPTY_SPARK_FILTER: SparkFilter = {
  minBlue: 0,
  minPink: 0,
  minWhite: 0,
  minGreen: 0,
  conditions: [],
}

/** Blue factors are the five stats — always offered regardless of what's loaded. */
export const BLUE_STATS = ['Speed', 'Stamina', 'Power', 'Guts', 'Wit'] as const

/** Pink factors are the aptitudes (surface / distance / strategy). */
export const PINK_APTITUDES = [
  'Turf',
  'Dirt',
  'Short',
  'Mile',
  'Medium',
  'Long',
  'Front Runner',
  'Pace Chaser',
  'Late Surger',
  'End Closer',
] as const

/** Max stars a single factor TYPE can reach across the counted nodes (3 nodes x 3). */
export const MAX_TYPE_STARS = 9

interface RawFactor {
  name?: string | number
  stars?: number | string
  category?: string
}

interface RawNode {
  factors?: RawFactor[]
}

const COUNT_NODES = ['self', 'p1', 'p2'] as const

const COLOUR_BY_CATEGORY: Record<string, SparkColour> = {
  stat: 'blue',
  aptitude: 'pink',
  skill: 'white',
  race: 'white',
  scenario: 'white',
  unique: 'green',
}

export function categoryToColour(category?: string): SparkColour | null {
  if (!category) return null
  return COLOUR_BY_CATEGORY[category.toLowerCase()] ?? null
}

function nodesOf(tree: unknown): RawNode[] {
  if (!tree || typeof tree !== 'object') return []
  const rawTree = tree as Record<string, unknown>
  return COUNT_NODES.map((key) => rawTree[key] as RawNode | undefined).filter(
    (node): node is RawNode => !!node && Array.isArray(node.factors),
  )
}

function numericStars(value: number | string | undefined): number {
  const n = Number(value)
  return Number.isFinite(n) ? n : 0
}

function numericMin(value: number): number {
  const n = Number(value)
  return Number.isFinite(n) && n > 0 ? n : 0
}

function hasConditionName(condition: SparkCondition): boolean {
  return normalizedCardName(condition.name).length > 0
}

/** Combined stars of a colour across self + p1 + p2. */
export function countStars(tree: unknown, colour: SparkColour): number {
  let total = 0
  for (const node of nodesOf(tree)) {
    for (const factor of node.factors ?? []) {
      if (categoryToColour(factor.category) === colour) {
        total += numericStars(factor.stars)
      }
    }
  }
  return total
}

/** Combined stars of one named factor (e.g. "Speed") across self + p1 + p2. */
export function countNamedStars(tree: unknown, name: string): number {
  const target = normalizedCardName(name)
  if (!target) return 0
  let total = 0
  for (const node of nodesOf(tree)) {
    for (const factor of node.factors ?? []) {
      if (normalizedCardName(factor.name ?? '') === target) {
        total += numericStars(factor.stars)
      }
    }
  }
  return total
}

export function isSparkFilterActive(filter: SparkFilter): boolean {
  return (
    numericMin(filter.minBlue) > 0 ||
    numericMin(filter.minPink) > 0 ||
    numericMin(filter.minWhite) > 0 ||
    numericMin(filter.minGreen) > 0 ||
    filter.conditions.some(hasConditionName)
  )
}

export function parentMatchesSpark(parent: SparkSubject, filter: SparkFilter): boolean {
  const tree = (parent as { tree?: unknown }).tree

  if (numericMin(filter.minBlue) > 0 && countStars(tree, 'blue') < numericMin(filter.minBlue)) return false
  if (numericMin(filter.minPink) > 0 && countStars(tree, 'pink') < numericMin(filter.minPink)) return false
  if (numericMin(filter.minWhite) > 0 && countStars(tree, 'white') < numericMin(filter.minWhite)) return false
  if (numericMin(filter.minGreen) > 0 && countStars(tree, 'green') < numericMin(filter.minGreen)) return false

  // Library filter: every condition must hold (AND).
  for (const condition of filter.conditions) {
    if (!hasConditionName(condition)) continue
    if (!conditionMet(tree, condition)) return false
  }

  return true
}

/**
 * Whether one factor condition is satisfied by the tree (self+p1+p2 summed).
 * exclude = absent; otherwise (>= / legacy "has") = summed stars meet minStars.
 */
export function conditionMet(tree: unknown, condition: SparkCondition): boolean {
  const total = countNamedStars(tree, condition.name)
  if (condition.mode === 'exclude') return total <= 0
  return total >= Math.max(1, numericStars(condition.minStars) || 1)
}

/**
 * Picker options per colour. Blue/pink use the fixed game lists (always offered);
 * green/white are derived from the names actually present on the loaded parents.
 */
export function collectSparkNamesByColour(parents: SparkSubject[]): SparkColourOptions {
  const green = new Map<string, string>()
  const white = new Map<string, string>()

  for (const parent of parents) {
    for (const node of nodesOf((parent as { tree?: unknown }).tree)) {
      for (const factor of node.factors ?? []) {
        const colour = categoryToColour(factor.category)
        if (colour !== 'green' && colour !== 'white') continue
        const name = String(factor.name ?? '').trim()
        const normalized = normalizedCardName(name)
        if (!normalized) continue
        const bucket = colour === 'green' ? green : white
        if (!bucket.has(normalized)) bucket.set(normalized, name)
      }
    }
  }

  const sorted = (m: Map<string, string>) =>
    Array.from(m.values()).sort(compareDisplayText)

  return {
    blue: [...BLUE_STATS],
    pink: [...PINK_APTITUDES],
    green: sorted(green),
    white: sorted(white),
  }
}
