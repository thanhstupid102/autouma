import { useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { Sun, Moon, RefreshCw, LogOut, KeyRound } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { leaveSession, refreshSession } from '@/api/auth'
import { forgetApiToken, getApiToken, subscribeApiToken } from '@/api/apiToken'
import { getTheme, toggleTheme } from '@/lib/theme'
import { formatNumber } from '@/lib/locale'
import { cn } from '@/lib/utils'
import { useEffect, useState } from 'react'
import type { Account } from '@/api/types'

function fmt(n: number | undefined): string {
  if (n == null) return '—'
  return formatNumber(n)
}

interface Props {
  account?: Account
  variant?: 'compact' | 'drawer'
}

export default function AccountFooter({ account, variant = 'compact' }: Props) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [isDark, setIsDark] = useState(() => getTheme() === 'dark')
  const [refreshing, setRefreshing] = useState(false)
  const [leavingSession, setLeavingSession] = useState(false)
  // Only meaningful when this browser actually holds a token; nothing to forget
  // otherwise. Subscribing keeps it in step when a rejected token is cleared.
  const [hasApiToken, setHasApiToken] = useState(() => getApiToken() !== null)
  useEffect(
    () => subscribeApiToken(() => setHasApiToken(getApiToken() !== null)),
    [],
  )

  async function handleRefresh() {
    setRefreshing(true)
    try {
      const res = await refreshSession()
      if (res.success) {
        await queryClient.invalidateQueries({ queryKey: ['session'] })
        toast.success('Session refreshed')
      } else {
        toast.error('Refresh failed')
      }
    } catch {
      toast.error('Refresh failed')
    } finally {
      setRefreshing(false)
    }
  }

  async function handleLeaveSession() {
    setLeavingSession(true)
    try {
      await leaveSession()
    } catch {
      // The local cache still needs to leave the session if the request failed.
    } finally {
      queryClient.clear()
      navigate('/login', { replace: true })
      setLeavingSession(false)
    }
  }

  function handleThemeToggle() {
    const next = toggleTheme()
    setIsDark(next === 'dark')
  }

  const isDrawer = variant === 'drawer'
  const themeLabel = isDark ? 'Switch to light mode' : 'Switch to dark mode'
  const actionClassName = isDrawer
    ? 'min-h-11 w-full justify-start gap-3 px-3'
    : 'h-7 w-7 shrink-0'

  return (
    <div className={cn('flex shrink-0 flex-col gap-2', isDrawer ? 'py-4' : 'px-3 py-3')}>
      <Separator />

      {/* Resource summary */}
      {account && (
        <div className="text-xs text-muted-foreground space-y-0.5 py-1">
          {account.tp && (
            <div className="flex justify-between">
              <span>TP</span>
              <span className="font-mono">{fmt(account.tp.current)}/{fmt(account.tp.max)}</span>
            </div>
          )}
          {account.carrots != null && (
            <div className="flex justify-between">
              <span>Carrots</span>
              <span className="font-mono">{fmt(account.carrots.total)}</span>
            </div>
          )}
          {account.gold != null && (
            <div className="flex justify-between">
              <span>Gold</span>
              <span className="font-mono">{fmt(account.gold)}</span>
            </div>
          )}
          {account.clocks != null && (
            <div className="flex justify-between">
              <span>Clocks</span>
              <span className="font-mono">{fmt(account.clocks)}</span>
            </div>
          )}
          {account.career != null && (
            <div className="flex justify-between">
              <span>Career</span>
              <span className={account.career.active ? 'text-primary font-medium' : ''}>
                {account.career.active ? 'ONGOING' : 'NONE'}
              </span>
            </div>
          )}
        </div>
      )}

      {/* Action buttons */}
      <div className={cn(isDrawer ? 'space-y-1' : 'flex items-center gap-1')}>
        <Button
          variant="ghost"
          size={isDrawer ? 'default' : 'icon'}
          className={actionClassName}
          title={isDrawer ? undefined : themeLabel}
          aria-label={themeLabel}
          onClick={handleThemeToggle}
        >
          {isDark ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
          {isDrawer && <span>{themeLabel}</span>}
        </Button>

        <Button
          variant="ghost"
          size={isDrawer ? 'default' : 'icon'}
          className={actionClassName}
          title={isDrawer ? undefined : 'Refresh session'}
          aria-label="Refresh session"
          disabled={refreshing}
          onClick={handleRefresh}
        >
          <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? 'animate-spin' : ''}`} />
          {isDrawer && <span>Refresh session</span>}
        </Button>

        {hasApiToken && (
          <Button
            variant="ghost"
            size={isDrawer ? 'default' : 'icon'}
            className={actionClassName}
            title={isDrawer ? undefined : 'Forget API token'}
            aria-label="Forget API token"
            onClick={() => {
              forgetApiToken()
              toast.info('API token forgotten on this browser.')
            }}
          >
            <KeyRound className="h-3.5 w-3.5" />
            {isDrawer && <span>Forget API token</span>}
          </Button>
        )}

        <Button
          variant="ghost"
          size={isDrawer ? 'default' : 'icon'}
          className={cn(actionClassName, 'text-destructive hover:text-destructive')}
          title={isDrawer ? undefined : 'Leave session'}
          aria-label="Leave session"
          disabled={leavingSession}
          onClick={handleLeaveSession}
        >
          <LogOut className="h-3.5 w-3.5" />
          {isDrawer && <span>Leave session</span>}
        </Button>
      </div>
    </div>
  )
}
