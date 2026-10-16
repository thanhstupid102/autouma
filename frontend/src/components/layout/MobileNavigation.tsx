import { useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { Dialog as DialogPrimitive } from 'radix-ui'
import { Menu, X } from 'lucide-react'

import AccountSwitcher from '@/components/accounts/AccountSwitcher'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { useAccountStore } from '@/stores/account'
import type { Account } from '@/api/types'
import AccountFooter from './AccountFooter'
import { getNavigationItems } from './navigation'

interface Props {
  account?: Account
}

const mobileRowClass = 'min-h-11'

export default function MobileNavigation({ account }: Props) {
  const selected = useAccountStore((state) => state.selected)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const navItems = getNavigationItems(selected)
  const primaryItems = selected
    ? navItems.filter((item) => item.mobilePrimary)
    : navItems
  const primaryPaths = new Set(primaryItems.map((item) => item.to))
  const drawerItems = navItems.filter((item) => !primaryPaths.has(item.to))
  const closeDrawer = () => setDrawerOpen(false)

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const desktopQuery = window.matchMedia('(min-width: 768px)')
    const closeAtDesktop = (event: MediaQueryListEvent) => {
      if (event.matches) setDrawerOpen(false)
    }
    desktopQuery.addEventListener('change', closeAtDesktop)
    return () => desktopQuery.removeEventListener('change', closeAtDesktop)
  }, [])

  return (
    <DialogPrimitive.Root open={drawerOpen} onOpenChange={setDrawerOpen}>
      <nav
        aria-label="Mobile primary navigation"
        className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-background/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden"
        data-testid="mobile-navigation"
      >
        <div className="grid h-16 grid-flow-col auto-cols-fr">
          {primaryItems.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) => cn(
                mobileRowClass,
                'flex min-w-0 flex-col items-center justify-center gap-1 px-1 py-1 text-[10px] font-medium transition-colors',
                isActive ? 'text-primary' : 'text-muted-foreground hover:text-foreground',
              )}
            >
              <Icon className="h-5 w-5 shrink-0" />
              <span className="max-w-full truncate">{label}</span>
            </NavLink>
          ))}

          <DialogPrimitive.Trigger asChild>
            <button
              type="button"
              className={cn(
                mobileRowClass,
                'flex min-w-0 flex-col items-center justify-center gap-1 px-1 py-1 text-[10px] font-medium text-muted-foreground transition-colors hover:text-foreground',
              )}
            >
              <Menu className="h-5 w-5 shrink-0" />
              <span>More</span>
            </button>
          </DialogPrimitive.Trigger>
        </div>
      </nav>

      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/35 md:hidden" />
        <DialogPrimitive.Content
          aria-describedby={undefined}
          className="fixed inset-y-0 right-0 z-50 flex h-dvh w-[min(20rem,calc(100%-2rem))] flex-col border-l border-border bg-background text-foreground shadow-2xl outline-none md:hidden"
        >
          <div className="flex min-h-14 shrink-0 items-center justify-between border-b border-border px-4">
            <DialogPrimitive.Title className="text-base font-semibold">
              ManhattanCafe<span className="text-primary">Auto</span>
            </DialogPrimitive.Title>
            <DialogPrimitive.Close asChild>
              <Button
                variant="ghost"
                size="icon"
                className={cn(mobileRowClass, 'min-w-11')}
                aria-label="Close navigation"
              >
                <X className="h-5 w-5" />
              </Button>
            </DialogPrimitive.Close>
          </div>

          <div className="flex-1 overflow-y-auto px-4 pb-[calc(1rem+env(safe-area-inset-bottom))]">
            {drawerItems.length > 0 && (
              <nav aria-label="More navigation" className="space-y-1 py-4">
                <div className="mb-2 px-3 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                  Navigation
                </div>
                {drawerItems.map(({ to, label, icon: Icon, end }) => (
                  <NavLink
                    key={to}
                    to={to}
                    end={end}
                    onClick={closeDrawer}
                    className={({ isActive }) => cn(
                      mobileRowClass,
                      'flex items-center gap-3 rounded-lg px-3 text-sm transition-colors',
                      isActive
                        ? 'bg-primary/10 font-medium text-primary'
                        : 'text-foreground hover:bg-muted',
                    )}
                  >
                    <Icon className="h-5 w-5 shrink-0" />
                    <span>{label}</span>
                  </NavLink>
                ))}
              </nav>
            )}

            <AccountSwitcher variant="drawer" onNavigate={closeDrawer} />
            <AccountFooter account={account} variant="drawer" />
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  )
}
