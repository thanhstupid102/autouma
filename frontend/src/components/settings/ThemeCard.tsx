/**
 * ThemeCard — light / dark theme selector.
 *
 * Bound to src/lib/theme.ts (getTheme / setTheme).
 * The sidebar also has a quick toggle — mentioned here for discoverability.
 */

import { useState } from 'react'

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'

import { getTheme, setTheme } from '@/lib/theme'
import type { Theme } from '@/lib/theme'

// ---------------------------------------------------------------------------
// ThemeCard
// ---------------------------------------------------------------------------

export function ThemeCard() {
  const [current, setCurrent] = useState<Theme>(getTheme)

  function handleChange(t: Theme) {
    setTheme(t)
    setCurrent(t)
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Theme</CardTitle>
        <CardDescription>Quick toggle also available in the sidebar.</CardDescription>
      </CardHeader>
      <CardContent>
        <fieldset className="flex flex-wrap gap-2 md:gap-6">
          <legend className="sr-only">Choose theme</legend>
          {(['light', 'dark'] as const).map((t) => (
            <label
              key={t}
              className="flex min-h-11 cursor-pointer select-none items-center gap-2 rounded-lg px-3 py-2 md:min-h-0 md:px-0 md:py-0"
            >
              <input
                type="radio"
                name="theme"
                value={t}
                checked={current === t}
                onChange={() => handleChange(t)}
                className="accent-primary"
              />
              <span className="text-sm font-medium capitalize cursor-pointer">{t}</span>
            </label>
          ))}
        </fieldset>
      </CardContent>
    </Card>
  )
}
