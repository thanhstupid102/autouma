import { NavLink } from 'react-router-dom'
import { useAccounts } from '@/hooks/useAccounts'
import { useAccountStore } from '@/stores/account'
import { cn } from '@/lib/utils'

interface Props {
  variant?: 'sidebar' | 'drawer'
  onNavigate?: () => void
}

export default function AccountSwitcher({ variant = 'sidebar', onNavigate }: Props) {
  useAccounts()
  const accounts = useAccountStore((s) => s.accounts)
  const isDrawer = variant === 'drawer'
  return (
    <div className={cn('shrink-0 border-t border-border', isDrawer ? 'py-4' : 'px-2 py-2')}>
      <div className={cn('mb-1 text-[10px] uppercase text-muted-foreground', isDrawer ? 'px-3 font-medium tracking-wider' : 'px-2')}>
        Accounts
      </div>
      {accounts.map((a) => {
        const dot = a.running ? 'bg-green-500' : a.loop_active ? 'bg-yellow-500' : 'bg-muted-foreground'
        return (
          // AccountLayout (/account/:name) sets the selected account from the route.
          <NavLink key={a.name} to={`/account/${encodeURIComponent(a.name)}`}
            onClick={onNavigate}
            className={({ isActive }) => cn(
              'flex items-center gap-2 rounded-md text-sm',
              isDrawer ? 'min-h-11 px-3' : 'px-2 py-1.5',
              isActive ? 'bg-primary/10 text-primary' : 'hover:bg-sidebar-accent',
            )}>
            <span className={`h-2 w-2 rounded-full ${dot}`} />{a.name}
          </NavLink>
        )
      })}
    </div>
  )
}
