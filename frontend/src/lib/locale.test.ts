import { describe, expect, it } from 'vitest'

import { compareDisplayText, DISPLAY_LOCALE, formatNumber } from './locale'

describe('deterministic display locale', () => {
  it('pins separators instead of using the browser default locale', () => {
    expect(DISPLAY_LOCALE).toBe('en-US')
    expect(formatNumber(1234567)).toBe('1,234,567')
  })

  it('pins collation for names that sort differently by locale', () => {
    expect(new Intl.Collator('sv-SE').compare('ä', 'z')).toBeGreaterThan(0)
    expect(compareDisplayText('ä', 'z')).toBeLessThan(0)
  })
})
