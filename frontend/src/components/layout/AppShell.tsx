import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'
import { useSession } from '@/hooks/useSession'
import { useAccountScopedReload } from '@/hooks/useAccountScopedReload'
import { useSelectionHydration } from '@/hooks/useSelectionHydration'
import MobileNavigation from './MobileNavigation'

export default function AppShell() {
  const { data } = useSession()
  const account = data?.account
  // Reload preset / race-preset / run-settings and reset team on account switch.
  useAccountScopedReload()
  // Then restore this account's remembered team (deck/trainee/friend/parents/event).
  useSelectionHydration()

  return (
    <div className="flex h-dvh overflow-hidden bg-background" data-testid="app-shell">
      <Sidebar account={account} />
      <main className="min-w-0 w-full flex-1 overflow-y-auto pb-[calc(4rem+env(safe-area-inset-bottom))] md:w-auto md:pb-0">
        <Outlet />
      </main>
      <MobileNavigation account={account} />
    </div>
  )
}
