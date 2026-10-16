import { describe, it, expect } from 'vitest'
import {
  categoryToColour,
  countStars,
  countNamedStars,
  isSparkFilterActive,
  parentMatchesSpark,
  collectSparkNamesByColour,
  BLUE_STATS,
  PINK_APTITUDES,
  EMPTY_SPARK_FILTER,
  type SparkFilter,
} from './sparkFilter'
import type { ParentInfo } from '@/api/types'

type F = { name: string; stars: number; category: string }
const f = (name: string, stars: number, category: string): F => ({ name, stars, category })

function makeParent(self: F[], p1: F[] = [], p2: F[] = [], gp1: F[] = []): ParentInfo {
  return {
    instance_id: 'x',
    card_id: '100101',
    name: 'P',
    tree: {
      self: { factors: self },
      p1: { factors: p1 },
      p2: { factors: p2 },
      gp1: { factors: gp1 },
    },
  } as unknown as ParentInfo
}

const treeOf = (p: ParentInfo) => (p as { tree: unknown }).tree

describe('categoryToColour', () => {
  it('maps stat→blue, aptitude→pink, unique→green', () => {
    expect(categoryToColour('stat')).toBe('blue')
    expect(categoryToColour('aptitude')).toBe('pink')
    expect(categoryToColour('unique')).toBe('green')
  })
  it('maps skill, race and scenario all to white', () => {
    expect(categoryToColour('skill')).toBe('white')
    expect(categoryToColour('race')).toBe('white')
    expect(categoryToColour('scenario')).toBe('white')
  })
  it('returns null for other/unknown/undefined', () => {
    expect(categoryToColour('other')).toBeNull()
    expect(categoryToColour('nope')).toBeNull()
    expect(categoryToColour(undefined)).toBeNull()
  })
})

describe('countStars (colour totals)', () => {
  it('sums stars of a colour across self+p1+p2', () => {
    const p = makeParent(
      [f('Speed', 3, 'stat'), f('Stamina', 2, 'stat')],
      [f('Power', 1, 'stat')],
      [f('Guts', 2, 'stat')],
    )
    expect(countStars(treeOf(p), 'blue')).toBe(8)
  })
  it('EXCLUDES grandparent factors', () => {
    const p = makeParent([f('Speed', 1, 'stat')], [], [], [f('Speed', 3, 'stat')])
    expect(countStars(treeOf(p), 'blue')).toBe(1)
  })
  it('separates colours (white = skill/race/scenario)', () => {
    const p = makeParent([f('Turf', 3, 'aptitude'), f('Corner', 2, 'skill'), f('Some Race', 1, 'race')])
    expect(countStars(treeOf(p), 'pink')).toBe(3)
    expect(countStars(treeOf(p), 'white')).toBe(3)
    expect(countStars(treeOf(p), 'blue')).toBe(0)
  })
})

describe('countNamedStars (summed per type)', () => {
  it('sums one named factor across self+p1+p2', () => {
    const p = makeParent([f('Speed', 3, 'stat')], [f('Speed', 3, 'stat')], [f('Speed', 1, 'stat')])
    expect(countNamedStars(treeOf(p), 'Speed')).toBe(7)
  })
  it('matches by normalized name and ignores grandparents', () => {
    const p = makeParent([f('Front Runner', 2, 'aptitude')], [], [], [f('Front Runner', 3, 'aptitude')])
    expect(countNamedStars(treeOf(p), 'front runner')).toBe(2)
  })
  it('returns 0 for an absent factor', () => {
    expect(countNamedStars(treeOf(makeParent([f('Speed', 3, 'stat')])), 'Wit')).toBe(0)
  })
})

describe('parentMatchesSpark', () => {
  const p = makeParent(
    [f('Speed', 3, 'stat'), f('Turf', 2, 'aptitude')],
    [f('Speed', 3, 'stat')],
    [f('Corner Recovery', 2, 'skill')],
  )

  it('passes when the blue total meets the minimum', () => {
    expect(parentMatchesSpark(p, { ...EMPTY_SPARK_FILTER, minBlue: 6 })).toBe(true)
    expect(parentMatchesSpark(p, { ...EMPTY_SPARK_FILTER, minBlue: 7 })).toBe(false)
  })

  it('legacy include mode behaves as >= minStars', () => {
    expect(
      parentMatchesSpark(p, {
        ...EMPTY_SPARK_FILTER,
        conditions: [{ colour: 'blue', name: 'Speed', mode: 'include', minStars: 6 }],
      }),
    ).toBe(true)
    expect(
      parentMatchesSpark(p, {
        ...EMPTY_SPARK_FILTER,
        conditions: [{ colour: 'blue', name: 'Speed', mode: 'include', minStars: 7 }],
      }),
    ).toBe(false)
  })

  it('atleast (>=) needs the SUMMED stars of that type to reach minStars', () => {
    // Speed total = 6 across self+p1
    expect(
      parentMatchesSpark(p, {
        ...EMPTY_SPARK_FILTER,
        conditions: [{ colour: 'blue', name: 'Speed', mode: 'atleast', minStars: 6 }],
      }),
    ).toBe(true)
    expect(
      parentMatchesSpark(p, {
        ...EMPTY_SPARK_FILTER,
        conditions: [{ colour: 'blue', name: 'Speed', mode: 'atleast', minStars: 7 }],
      }),
    ).toBe(false)
  })

  it('library conditions AND together (every condition must hold)', () => {
    // Speed atleast 6 (true) AND Wit has (false) -> overall false
    expect(
      parentMatchesSpark(p, {
        ...EMPTY_SPARK_FILTER,
        conditions: [
          { colour: 'blue', name: 'Speed', mode: 'atleast', minStars: 6 },
          { colour: 'blue', name: 'Wit', mode: 'include', minStars: 1 },
        ],
      }),
    ).toBe(false)
  })

  it('exclude condition fails a parent that has any of that spark', () => {
    expect(
      parentMatchesSpark(p, {
        ...EMPTY_SPARK_FILTER,
        conditions: [{ colour: 'pink', name: 'Turf', mode: 'exclude', minStars: 1 }],
      }),
    ).toBe(false)
  })

  it('ANDs every active condition + total together', () => {
    const filter: SparkFilter = {
      minBlue: 6,
      minPink: 2,
      minWhite: 2,
      minGreen: 0,
      conditions: [{ colour: 'white', name: 'Corner Recovery', mode: 'include', minStars: 2 }],
    }
    expect(parentMatchesSpark(p, filter)).toBe(true)
  })
})

describe('isSparkFilterActive', () => {
  it('is false for the empty filter, true otherwise', () => {
    expect(isSparkFilterActive(EMPTY_SPARK_FILTER)).toBe(false)
    expect(isSparkFilterActive({ ...EMPTY_SPARK_FILTER, minWhite: 1 })).toBe(true)
    expect(
      isSparkFilterActive({
        ...EMPTY_SPARK_FILTER,
        conditions: [{ colour: 'blue', name: 'Speed', mode: 'include', minStars: 1 }],
      }),
    ).toBe(true)
  })
  it('ignores blank-named conditions', () => {
    expect(
      isSparkFilterActive({
        ...EMPTY_SPARK_FILTER,
        conditions: [{ colour: 'blue', name: '', mode: 'include', minStars: 1 }],
      }),
    ).toBe(false)
  })
})

describe('collectSparkNamesByColour', () => {
  it('uses fixed lists for blue/pink and present names for green/white', () => {
    const a = makeParent([f('Speed', 3, 'stat'), f('Arc Maestro', 1, 'unique')])
    const b = makeParent([f('Corner Recovery', 1, 'skill'), f('Some Race', 1, 'race')])
    const opts = collectSparkNamesByColour([a, b])

    expect(opts.blue).toEqual([...BLUE_STATS])
    expect(opts.pink).toEqual([...PINK_APTITUDES])
    expect(opts.green).toEqual(['Arc Maestro'])
    expect(opts.white).toEqual(['Corner Recovery', 'Some Race'])
  })
})
