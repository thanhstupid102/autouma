const STORAGE_KEY = 'theme'

// Legacy values from the old pink/blue theme system
const LEGACY_VALUES = new Set(['pink', 'blue'])

export type Theme = 'light' | 'dark'

export function getTheme(): Theme {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === 'dark') return 'dark'
    if (stored === 'light') return 'light'
    // Legacy migration: 'pink' | 'blue' → treat as 'light'
    if (stored && LEGACY_VALUES.has(stored)) return 'light'
  } catch {
    // localStorage not available (SSR / private browsing)
  }
  return 'light'
}

export function setTheme(t: Theme): void {
  try {
    localStorage.setItem(STORAGE_KEY, t)
  } catch {
    // ignore
  }
  if (t === 'dark') {
    document.documentElement.classList.add('dark')
  } else {
    document.documentElement.classList.remove('dark')
  }
}

export function toggleTheme(): Theme {
  const next = getTheme() === 'dark' ? 'light' : 'dark'
  setTheme(next)
  return next
}

/** Apply stored theme before first paint — call once on app init. */
export function initTheme(): void {
  setTheme(getTheme())
}
