import { useId, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { TriangleAlert, Unlink } from 'lucide-react'
import { toast } from 'sonner'
import { steamUnbind } from '@/api/auth'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { transitionLinkErrorMessage } from '@/components/login/transitionLinkErrors'

interface Props {
  account: string
  disabled?: boolean
  disabledReason?: string
  showDisabledReason?: boolean
}

export default function RemoveUmaLinkDialog({
  account,
  disabled = false,
  disabledReason = 'Log in and stop the run before removing the Uma link.',
  showDisabledReason = true,
}: Props) {
  const queryClient = useQueryClient()
  const inputId = useId()
  const [open, setOpen] = useState(false)
  const [step, setStep] = useState<1 | 2>(1)
  const [confirmation, setConfirmation] = useState('')
  const [error, setError] = useState('')
  const [working, setWorking] = useState(false)

  const nameMatches = confirmation === account

  function resetDialog() {
    setStep(1)
    setConfirmation('')
    setError('')
    setWorking(false)
  }

  function handleOpenChange(nextOpen: boolean) {
    setOpen(nextOpen)
    if (!nextOpen) resetDialog()
  }

  async function performUnbind() {
    if (!nameMatches) return
    setWorking(true)
    setError('')
    try {
      const result = await steamUnbind({
        confirm_account_name: confirmation,
      }, account)
      if (result.success && result.state === 'unbound') {
        await queryClient.invalidateQueries({ queryKey: ['accounts'] })
        toast.success('Uma link removed.')
        setOpen(false)
        resetDialog()
      } else {
        setError(transitionLinkErrorMessage(result.error_code, result.detail))
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not remove the Uma link.')
    } finally {
      setWorking(false)
    }
  }

  return (
    <div className="flex min-w-0 flex-col gap-1" onClick={(event) => event.stopPropagation()}>
      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogTrigger asChild>
          <Button
            className="w-full sm:w-auto"
            size="sm"
            variant="outline"
            disabled={disabled}
            onClick={(event) => event.stopPropagation()}
          >
            <Unlink className="h-3.5 w-3.5" />
            Remove Uma link
          </Button>
        </DialogTrigger>
        <DialogContent className="sm:max-w-lg" onClick={(event) => event.stopPropagation()}>
          <DialogHeader>
            <DialogTitle>Remove Uma link</DialogTitle>
            <DialogDescription>Account: {account}</DialogDescription>
          </DialogHeader>

          {step === 1 ? (
            <div className="flex flex-col gap-4 py-2">
              <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm leading-relaxed">
                <div className="mb-2 flex items-center gap-2 font-semibold text-destructive">
                  <TriangleAlert className="h-4 w-4" />
                  Steam will stop finding this account
                </div>
                <p>
                  This removes the link between this Steam account and this Umamusume account.
                  Afterward, a plain Steam login will not find this account. You can get back in
                  by re-linking from the game client, or with Trainer ID and link password.
                </p>
              </div>
              <DialogFooter>
                <Button variant="ghost" onClick={() => handleOpenChange(false)}>Cancel</Button>
                <Button variant="destructive" onClick={() => setStep(2)}>
                  I understand
                </Button>
              </DialogFooter>
            </div>
          ) : (
            <div className="flex flex-col gap-4 py-2">
              <p className="text-sm text-muted-foreground">
                Type the local account name to confirm this removal.
              </p>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor={`${inputId}-account`}>Type {account} to confirm</Label>
                <Input
                  id={`${inputId}-account`}
                  autoComplete="off"
                  value={confirmation}
                  disabled={working}
                  onChange={(event) => {
                    setConfirmation(event.target.value)
                    setError('')
                  }}
                />
                {confirmation && !nameMatches && (
                  <p className="text-xs text-destructive">The account name must match exactly.</p>
                )}
              </div>

              {error && <p role="alert" className="text-sm text-destructive">{error}</p>}

              <Button
                variant="destructive"
                disabled={!nameMatches || working}
                onClick={performUnbind}
              >
                {working ? 'Removing Uma link...' : 'Remove Uma link'}
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>
      {disabled && showDisabledReason && (
        <p className="text-xs text-muted-foreground">{disabledReason}</p>
      )}
    </div>
  )
}
