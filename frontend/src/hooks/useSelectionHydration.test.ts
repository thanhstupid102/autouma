import { describe, expect, it } from 'vitest'

import type { ParentInfo, Selection } from '@/api/types'
import { withCanonicalVeterans } from './useSelectionHydration'

describe('withCanonicalVeterans', () => {
  it('replaces saved veterans with fresh session parents by instance_id', () => {
    const saved: Selection = { veterans: [{ instance_id: '1', tree: { self: { factors: [] } } }] as ParentInfo[] }
    const fresh = [{ instance_id: '1', tree: { gp1: { factors: [{ name: 'Speed', stars: 3, category: 'stat' }] } } }] as ParentInfo[]

    const repaired = withCanonicalVeterans(saved, fresh)

    expect(repaired.veterans?.[0]).toBe(fresh[0])
    expect(repaired.veterans?.[0].tree?.gp1?.factors?.[0].name).toBe('Speed')
  })
})