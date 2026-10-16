import { useState, type FormEvent } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { transitionCodeChain } from '@/api/auth'
import type { TransitionLinkReason } from '@/api/types'
import { transitionLinkErrorMessage } from './transitionLinkErrors'

function trainerIdErrors(value: string): string[] {
  const errors: string[] = []
  if (value.length < 9 || value.length > 12) {
    errors.push('Trainer ID must be 9 to 12 digits long.')
  }
  if (!/^[0-9]*$/.test(value)) {
    errors.push('Trainer ID must contain ASCII digits only.')
  }
  return errors
}

function passwordErrors(value: string): string[] {
  const errors: string[] = []
  if (value.length < 8 || value.length > 16) {
    errors.push('Link password must be 8 to 16 characters long.')
  }
  if (!/^[0-9A-Za-z]*$/.test(value)) {
    errors.push('Link password must use ASCII letters and digits only.')
  }
  if (!/[0-9]/.test(value)) errors.push('Link password must include a digit.')
  if (!/[a-z]/.test(value)) errors.push('Link password must include a lowercase letter.')
  if (!/[A-Z]/.test(value)) errors.push('Link password must include an uppercase letter.')
  return errors
}

interface TransitionLinkPanelProps {
  account?: string
  reason?: TransitionLinkReason
  initialTrainerId?: number | string
  onSuccess?: () => void
  onBackToSteam?: () => void
}

export default function TransitionLinkPanel({
  account,
  reason,
  initialTrainerId,
  onSuccess,
  onBackToSteam,
}: TransitionLinkPanelProps) {
  const queryClient = useQueryClient()
  const [trainerId, setTrainerId] = useState(() => String(initialTrainerId ?? ''))
  const [password, setPassword] = useState('')
  const [validationErrors, setValidationErrors] = useState<string[]>([])
  const [error, setError] = useState('')
  const [verifiedName, setVerifiedName] = useState('')
  const [requestUserName, setRequestUserName] = useState('')
  const [working, setWorking] = useState(false)

  function resetVerification() {
    setVerifiedName('')
    setRequestUserName('')
    setError('')
  }

  async function verify(e: FormEvent) {
    e.preventDefault()
    const errors = [...trainerIdErrors(trainerId), ...passwordErrors(password)]
    setValidationErrors(errors)
    setError('')
    if (errors.length) return

    setWorking(true)
    try {
      const result = await transitionCodeChain({
        input_viewer_id: trainerId,
        password,
        verify_only: true,
      }, account)
      if (result.success && result.state === 'verified') {
        setVerifiedName(result.name?.trim() || 'Unnamed trainer')
        setRequestUserName(result.request_user_name?.trim() || '')
      } else {
        setError(transitionLinkErrorMessage(result.error_code, result.detail))
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Network error while verifying the account.')
    } finally {
      setWorking(false)
    }
  }

  async function commitLink() {
    setError('')
    setWorking(true)
    try {
      const result = await transitionCodeChain({
        input_viewer_id: trainerId,
        password,
        verify_only: false,
      }, account)
      if (result.state === 'authenticated' || (result.success && !result.state)) {
        await queryClient.invalidateQueries({ queryKey: ['session'] })
        onSuccess?.()
      } else {
        setError(transitionLinkErrorMessage(result.error_code, result.detail))
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Network error while linking the account.')
    } finally {
      setWorking(false)
    }
  }

  if (verifiedName) {
    return (
      <div className="flex flex-col gap-4">
        <div className="rounded-md border border-border bg-muted/40 p-3">
          <p className="text-xs text-muted-foreground">Trainer account</p>
          <p className="font-semibold text-foreground">{verifiedName}</p>
          {requestUserName && (
            <p className="mt-1 text-xs text-muted-foreground">Requested by {requestUserName}</p>
          )}
        </div>
        <p className="text-sm leading-relaxed text-foreground">
          Linking binds this device to that trainer account and cannot be undone from the app.
        </p>
        {error && <p className="text-xs text-destructive">{error}</p>}
        <Button type="button" disabled={working} onClick={commitLink} className="w-full">
          {working ? 'LINKING...' : 'Link this account'}
        </Button>
        <Button
          type="button"
          variant="outline"
          disabled={working}
          onClick={() => {
            setVerifiedName('')
            setRequestUserName('')
            setError('')
          }}
          className="w-full"
        >
          Check a different Trainer ID
        </Button>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <div>
        {reason === 'steam_link_removed' ? (
          <>
            <p className="text-sm font-semibold text-foreground">Uma link removed</p>
            <p className="mt-1 text-xs text-muted-foreground">
              This account's Uma link was removed. Its Trainer ID and link password are
              now the way back in.
            </p>
          </>
        ) : (
          <>
            <p className="text-sm font-semibold text-foreground">Link an existing trainer account</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Enter the Trainer ID and link password configured for that account.
            </p>
          </>
        )}
      </div>
      <form onSubmit={verify} className="flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <Label htmlFor="transition-trainer-id">Trainer ID</Label>
          <Input
            id="transition-trainer-id"
            inputMode="numeric"
            autoComplete="off"
            value={trainerId}
            disabled={working}
            onChange={(event) => {
              setTrainerId(event.target.value)
              setValidationErrors([])
              resetVerification()
            }}
          />
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="transition-link-password">Link password</Label>
          <Input
            id="transition-link-password"
            type="password"
            autoComplete="off"
            value={password}
            disabled={working}
            onChange={(event) => {
              setPassword(event.target.value)
              setValidationErrors([])
              resetVerification()
            }}
          />
        </div>
        {validationErrors.length > 0 && (
          <div className="text-xs text-destructive" role="alert">
            {validationErrors.map((message) => <p key={message}>{message}</p>)}
          </div>
        )}
        {error && <p className="text-xs text-destructive">{error}</p>}
        <Button type="submit" disabled={working} className="w-full">
          {working ? 'VERIFYING...' : 'Verify account'}
        </Button>
      </form>
      {onBackToSteam && (
        <Button
          type="button"
          variant="ghost"
          onClick={onBackToSteam}
          className="w-full"
        >
          Back to Steam login
        </Button>
      )}
    </div>
  )
}
