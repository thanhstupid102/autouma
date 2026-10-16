import { type MouseEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Trash2, ChevronRight, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { useAccountStore } from '@/stores/account'
import type { AccountSnapshot } from '@/stores/account'
import { deleteAccount } from '@/api/accounts'
import { pauseRunner, resumeRunner } from '@/api/career'
import RemoveUmaLinkDialog from './RemoveUmaLinkDialog'

interface Props {
  acc: AccountSnapshot
}

interface BlockedReason {
  cause: string
  message: string
}

function uniqueBlockedReasons(reasons: (BlockedReason | undefined)[]): BlockedReason[] {
  return Array.from(new Map(
    reasons
      .filter((reason): reason is BlockedReason => Boolean(reason))
      .map((reason) => [reason.cause, reason]),
  ).values())
}

function statusDotClass(acc: AccountSnapshot): string {
  if (acc.running) return 'bg-green-500'
  if (acc.loop_active && !acc.running) return 'bg-yellow-400'
  return 'bg-muted-foreground/40'
}

function statusLabel(acc: AccountSnapshot): string {
  if (!acc.logged_in) return 'Not logged in'
  if (acc.running) return 'Running'
  if (acc.loop_active && !acc.running) return 'Paused'
  return 'Idle'
}

export default function AccountCard({ acc }: Props) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const setSelected = useAccountStore((s) => s.setSelected)
  const selected = useAccountStore((s) => s.selected)
  function handleCardClick() {
    // AccountLayout (/account/:name) sets the selected account from the route.
    navigate('/account/' + encodeURIComponent(acc.name))
  }

  async function handlePause(e: MouseEvent) {
    e.stopPropagation()
    try {
      await pauseRunner(acc.name)
      await qc.invalidateQueries({ queryKey: ['accounts'] })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Pause failed')
    }
  }

  async function handleResume(e: MouseEvent) {
    e.stopPropagation()
    try {
      await resumeRunner(acc.name)
      await qc.invalidateQueries({ queryKey: ['accounts'] })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Resume failed')
    }
  }

  async function handleDelete(e: MouseEvent) {
    e.stopPropagation()
    if (!window.confirm(`Delete account "${acc.name}"? This cannot be undone.`)) return
    try {
      await deleteAccount(acc.name)
      // Stop polling the deleted account, otherwise useSession/useRunner keep
      // hitting /api/auth/session?X-Account=<name>, which lazily resurrects the
      // session and makes the account reappear in the list.
      if (selected === acc.name) setSelected('')
      await qc.invalidateQueries({ queryKey: ['accounts'] })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Delete failed')
    }
  }

  function handleReauth(e: MouseEvent) {
    e.stopPropagation()
    if (acc.running || acc.loop_active) return
    setSelected(acc.name)
    navigate('/account/' + encodeURIComponent(acc.name), {
      state: { forceSteamLogin: true },
    })
  }

  const isPaused = acc.loop_active && !acc.running
  const reauthBlocked = acc.running || acc.loop_active
  const activeRunReason = reauthBlocked
    ? {
        cause: 'active-run',
        message: 'Stop the run before changing this account.',
      }
    : undefined
  const removeUmaLinkReasons = [
    activeRunReason,
    !acc.logged_in
      ? {
          cause: 'not-logged-in',
          message: 'Log in before removing the Uma link.',
        }
      : undefined,
  ]
  const removeUmaLinkReason = removeUmaLinkReasons
    .filter((reason): reason is BlockedReason => Boolean(reason))
    .map((reason) => reason.message)
    .join(' ') || undefined
  const blockedReasons = uniqueBlockedReasons([
    activeRunReason,
    ...removeUmaLinkReasons,
  ])

  return (
    <Card
      className={cn(
        'h-full',
        'cursor-pointer transition-colors hover:bg-accent/50',
        'select-none',
      )}
      onClick={handleCardClick}
    >
      <CardContent className="flex h-full flex-col gap-3 py-3">
        <div className="flex min-w-0 items-center gap-3">
          <span
            className={cn('h-2.5 w-2.5 shrink-0 rounded-full', statusDotClass(acc))}
            aria-hidden
          />

          <div className="flex min-w-0 flex-1 flex-col">
            <span className="truncate text-sm font-medium text-foreground">{acc.name}</span>
            <span className="text-xs text-muted-foreground">{statusLabel(acc)}</span>
            {acc.steam_unbound_at && (
              <span className="text-xs font-medium text-amber-600 dark:text-amber-400">
                Uma link removed; reauth to check
              </span>
            )}
          </div>
        </div>

        <div
          data-testid="account-actions"
          className="grid w-full grid-cols-1 gap-2 border-t border-border/60 pt-3 sm:flex sm:flex-wrap sm:items-start"
          onClick={(event) => event.stopPropagation()}
        >
          {acc.running ? (
            <Button className="w-full sm:w-24" size="sm" variant="outline" onClick={handlePause}>
              Pause
            </Button>
          ) : isPaused ? (
            <Button className="w-full sm:w-24" size="sm" variant="outline" onClick={handleResume}>
              Resume
            </Button>
          ) : (
            <Button
              size="sm"
              variant="outline"
              onClick={(event) => {
                event.stopPropagation()
                navigate('/account/' + encodeURIComponent(acc.name))
              }}
              className="w-full sm:w-24"
            >
              Open <ChevronRight className="ml-0.5 h-3.5 w-3.5" />
            </Button>
          )}

          <Button
            className="w-full sm:w-auto"
            size="sm"
            variant="outline"
            disabled={reauthBlocked}
            onClick={handleReauth}
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Re-establish
          </Button>

          <RemoveUmaLinkDialog
            account={acc.name}
            disabled={Boolean(removeUmaLinkReason)}
            disabledReason={removeUmaLinkReason}
            showDisabledReason={false}
          />

          <Button
            aria-label={`Delete ${acc.name}`}
            className="w-full sm:w-auto"
            size="sm"
            variant="destructive"
            onClick={handleDelete}
          >
            <Trash2 className="h-3.5 w-3.5" />
            Delete
          </Button>
        </div>
        {blockedReasons.length > 0 && (
          <div data-testid="account-blocked-reasons" className="flex flex-col gap-1">
            {blockedReasons.map((reason) => (
              <p key={reason.cause} className="text-xs text-muted-foreground">
                {reason.message}
              </p>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
