import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import QrPanel from '@/components/login/QrPanel'
import PasswordPanel from '@/components/login/PasswordPanel'
import TransitionLinkPanel from '@/components/login/TransitionLinkPanel'
import { useAccountStore } from '@/stores/account'
import type { SessionData } from '@/api/types'

type Mode = 'setup' | 'qr' | 'password' | 'transition'

function sanitizeAccountName(raw: string): string {
  const cleaned = raw.trim().replace(/[^A-Za-z0-9_.-]/g, '_').replace(/^\.+|\.+$/g, '')
  return cleaned || 'account'
}

export default function AddAccountDialog() {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [mode, setMode] = useState<Mode>('setup')
  const [transitionState, setTransitionState] = useState<SessionData | null>(null)
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const setSelected = useAccountStore((state) => state.setSelected)
  const account = sanitizeAccountName(name)

  function resetDialog() {
    setName('')
    setMode('setup')
    setTransitionState(null)
  }

  function showTransitionLink(result: SessionData) {
    setTransitionState(result)
    setMode('transition')
  }

  function handleOpenChange(nextOpen: boolean) {
    setOpen(nextOpen)
    if (!nextOpen) resetDialog()
  }

  async function handleAdded() {
    await queryClient.invalidateQueries({ queryKey: ['accounts'] })
    setSelected(account)
    setOpen(false)
    resetDialog()
    navigate(`/account/${encodeURIComponent(account)}`)
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button size="sm" variant="outline">Add account</Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Add account</DialogTitle>
        </DialogHeader>

        {mode === 'setup' && (
          <div className="flex flex-col gap-4 py-2">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="new-account-name">Account name</Label>
              <Input
                id="new-account-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="e.g. main or alt"
                autoComplete="off"
              />
              <p className="text-xs text-muted-foreground">
                A local label for this account. Steam sign-in is the first step.
              </p>
            </div>
            <Button disabled={!name.trim()} onClick={() => setMode('qr')}>
              Use Steam QR
            </Button>
            <Button
              variant="outline"
              disabled={!name.trim()}
              onClick={() => setMode('password')}
            >
              Use Steam password
            </Button>
          </div>
        )}

        {mode !== 'setup' && (
          <div className="flex flex-col gap-4 py-2">
            <p className="text-xs text-muted-foreground">
              Signing in as local account <span className="font-mono">{account}</span>
            </p>
            {mode === 'qr' && (
              <QrPanel
                account={account}
                onUsePassword={() => setMode('password')}
                onNeedsTransitionLink={showTransitionLink}
                onSuccess={handleAdded}
              />
            )}
            {mode === 'password' && (
              <PasswordPanel
                account={account}
                onBackToQr={() => setMode('qr')}
                onNeedsTransitionLink={showTransitionLink}
                onSuccess={handleAdded}
              />
            )}
            {mode === 'transition' && (
              <TransitionLinkPanel
                account={account}
                reason={transitionState?.reason}
                initialTrainerId={transitionState?.viewer_id}
                onBackToSteam={() => {
                  setTransitionState(null)
                  setMode('qr')
                }}
                onSuccess={handleAdded}
              />
            )}
            <Button size="sm" variant="ghost" onClick={() => setMode('setup')}>
              Change account name
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
