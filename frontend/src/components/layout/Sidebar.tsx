import { NavLink } from 'react-router-dom'
import { cn } from '@/lib/utils'
import AccountFooter from './AccountFooter'
import AccountSwitcher from '@/components/accounts/AccountSwitcher'
import { useAccountStore } from '@/stores/account'
import type { Account } from '@/api/types'
import { getNavigationItems } from './navigation'

interface Props {
  account?: Account
}

export default function Sidebar({ account }: Props) {
  const selected = useAccountStore((s) => s.selected)
  // Nav is scoped to the selected account: Setup/Library/Events/Settings link
  // to /account/:name/... so each page edits that account's own state. When no
  // account is selected (Overview), only the Accounts link shows.
  const navItems = getNavigationItems(selected)
  return (
    <aside
      className="sticky top-0 hidden h-dvh w-[200px] shrink-0 flex-col overflow-y-auto border-r border-border bg-sidebar md:flex"
      data-testid="desktop-sidebar"
    >
      {/* Brand */}
      <div className="shrink-0 px-4 py-4 border-b border-border">
        <span className="text-base font-bold text-sidebar-foreground">ManhattanCafe</span>
        <span className="text-base font-bold text-primary">Auto</span>
      </div>

      {/* Nav */}
      <nav className="min-h-0 flex-1 px-2 py-3 space-y-0.5 overflow-y-auto">
        {navItems.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-2.5 px-2.5 py-2 rounded-md text-sm transition-colors',
                isActive
                  ? 'bg-primary/10 text-primary font-medium'
                  : 'text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground',
              )
            }
          >
            <Icon className="h-4 w-4 shrink-0" />
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Account switcher */}
      <AccountSwitcher />

      {/* Footer */}
      <AccountFooter account={account} />
    </aside>
  )
}
