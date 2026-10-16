import {
  BookOpen,
  CalendarClock,
  LayoutDashboard,
  LayoutGrid,
  Settings,
  Settings2,
  SlidersHorizontal,
  type LucideIcon,
} from 'lucide-react'

export interface NavigationItem {
  to: string
  label: string
  icon: LucideIcon
  end?: boolean
  mobilePrimary?: boolean
}

export function getNavigationItems(selected: string): NavigationItem[] {
  const base = selected ? `/account/${encodeURIComponent(selected)}` : ''

  return [
    { to: '/', label: 'Accounts', icon: LayoutGrid, end: true },
    ...(base
      ? [
          { to: base, label: 'Dashboard', icon: LayoutDashboard, end: true, mobilePrimary: true },
          { to: `${base}/setup`, label: 'Setup', icon: Settings2, mobilePrimary: true },
          { to: `${base}/library`, label: 'Library', icon: BookOpen, mobilePrimary: true },
          { to: `${base}/events`, label: 'Events', icon: CalendarClock, mobilePrimary: true },
          { to: `${base}/bot-configuration`, label: 'Bot Configuration', icon: SlidersHorizontal },
          { to: `${base}/settings`, label: 'Settings', icon: Settings },
        ]
      : []),
  ]
}
