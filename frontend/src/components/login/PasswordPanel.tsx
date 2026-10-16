import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Separator } from '@/components/ui/separator'
import { login } from '@/api/auth'
import type { SessionData } from '@/api/types'
import { transitionLinkErrorMessage } from './transitionLinkErrors'

interface PasswordPanelProps {
  onBackToQr: () => void
  onSuccess?: () => void
  onNeedsTransitionLink?: (result: SessionData) => void
  initialNeedsSteamGuard?: boolean
  /** Target account for credential login (X-Account). Omit to use the selected account. */
  account?: string
}

export default function PasswordPanel({
  onBackToQr,
  onSuccess,
  onNeedsTransitionLink,
  initialNeedsSteamGuard = false,
  account,
}: PasswordPanelProps) {
  const queryClient = useQueryClient()
  const mountedRef = useRef(true)
  const [username, setUsername] = useState(() => localStorage.getItem('saved_username') ?? '')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [needs2fa, setNeeds2fa] = useState(initialNeedsSteamGuard)
  const [working, setWorking] = useState(false)
  const [loginError, setLoginError] = useState('')
  const accountForLogin = account?.trim() || undefined

  useEffect(() => {
    localStorage.removeItem('saved_password')
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setLoginError('')
    setWorking(true)

    try {
      const result = await login({
        username,
        password,
        code: code || undefined,
      }, accountForLogin)
      if (!mountedRef.current) return

      if (result.state === 'authenticated' || (result.success && !result.state)) {
        await queryClient.invalidateQueries({ queryKey: ['session'] })
        onSuccess?.()
      } else if (result.state === 'needs_steam_guard' || result.needs_2fa) {
        setNeeds2fa(true)
        setWorking(false)
      } else if (result.state === 'needs_transition_link') {
        setWorking(false)
        onNeedsTransitionLink?.(result)
      } else {
        setLoginError(transitionLinkErrorMessage(result.error_code, result.detail))
        setWorking(false)
      }
    } catch {
      if (!mountedRef.current) return
      setLoginError('NETWORK ERROR')
      setWorking(false)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <Label htmlFor="login-username">Username</Label>
          <Input
            id="login-username"
            type="text"
            autoComplete="username"
            value={username}
            onChange={e => setUsername(e.target.value)}
            disabled={working}
          />
        </div>

        <div className="flex flex-col gap-1">
          <Label htmlFor="login-password">Password</Label>
          <Input
            id="login-password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            disabled={working}
          />
        </div>

        {needs2fa && (
          <div className="flex flex-col gap-1">
            <Label htmlFor="login-code">Steam Guard Code</Label>
            <Input
              id="login-code"
              type="text"
              autoComplete="one-time-code"
              maxLength={5}
              placeholder="XXXXX"
              value={code}
              onChange={e => setCode(e.target.value.toUpperCase())}
              disabled={working}
            />
          </div>
        )}

        {loginError && <p className="text-xs text-destructive">{loginError}</p>}

        <Button type="submit" disabled={working} className="w-full">
          {working ? 'WORKING...' : 'LOGIN'}
        </Button>
      </form>

      <Separator />

      <Button
        type="button"
        variant="ghost"
        onClick={onBackToQr}
        className="w-full"
      >
        Back to QR
      </Button>
    </div>
  )
}
