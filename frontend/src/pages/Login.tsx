import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useLocation, useNavigate } from 'react-router-dom'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { login } from '@/api/auth'
import QrPanel from '@/components/login/QrPanel'
import PasswordPanel from '@/components/login/PasswordPanel'
import TransitionLinkPanel from '@/components/login/TransitionLinkPanel'
import { transitionLinkErrorMessage } from '@/components/login/transitionLinkErrors'
import type { SessionData } from '@/api/types'

type Mode = 'checking' | 'qr' | 'password' | 'transition' | 'failed'

interface LoginProps {
  forceSteamLogin?: boolean
}

export default function Login({ forceSteamLogin = false }: LoginProps) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const location = useLocation()
  const [mode, setMode] = useState<Mode>('checking')
  const [needsSteamGuard, setNeedsSteamGuard] = useState(false)
  const [loginError, setLoginError] = useState('')
  const [transitionState, setTransitionState] = useState<SessionData | null>(null)
  const autoAttemptedRef = useRef(false)

  function handleSuccess() {
    if (forceSteamLogin) {
      navigate(location.pathname, { replace: true, state: null })
    }
  }

  function showTransitionLink(result: SessionData) {
    setTransitionState(result)
    setMode('transition')
  }

  useEffect(() => {
    if (autoAttemptedRef.current) return
    autoAttemptedRef.current = true

    login({})
      .then(async result => {
        if (result.state === 'authenticated' || (result.success && !result.state)) {
          await queryClient.invalidateQueries({ queryKey: ['session'] })
          return
        }
        if (result.state === 'needs_steam_guard') {
          setNeedsSteamGuard(true)
          setMode('password')
          return
        }
        if (result.state === 'needs_transition_link') {
          showTransitionLink(result)
          return
        }
        if (result.state === 'needs_steam_login') {
          setMode('qr')
          return
        }
        if (result.state === 'steam_signup_disabled') {
          setLoginError(
            'The game server refused Steam-based account creation for this Steam account, so a new account cannot be created here. Import an existing account bundle or link it in the official game client first.',
          )
          setMode('failed')
          return
        }
        if (result.state === 'failed') {
          setLoginError(transitionLinkErrorMessage(
            result.error_code,
            result.detail || 'Steam login failed.',
          ))
          setMode('failed')
          return
        }
        setLoginError('Could not check the saved Steam session.')
        setMode('failed')
      })
      .catch(() => {
        setLoginError('Could not check the saved Steam session.')
        setMode('failed')
      })
  }, [forceSteamLogin, queryClient])

  return (
    <div className="flex min-h-dvh items-center justify-center bg-background">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-center">
            <span className="font-bold">ManhattanCafe</span>
            <span className="font-bold text-primary">Auto</span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loginError && (
            <p className="mb-4 text-xs text-destructive" role="alert">{loginError}</p>
          )}
          {mode === 'checking' && (
            <p className="text-center text-sm text-muted-foreground">Checking the saved Steam session...</p>
          )}
          {mode === 'qr' && (
            <QrPanel
              onUsePassword={() => {
                setLoginError('')
                setMode('password')
              }}
              onNeedsTransitionLink={showTransitionLink}
              onSuccess={handleSuccess}
            />
          )}
          {mode === 'password' && (
            <PasswordPanel
              initialNeedsSteamGuard={needsSteamGuard}
              onBackToQr={() => {
                setNeedsSteamGuard(false)
                setLoginError('')
                setMode('qr')
              }}
              onNeedsTransitionLink={showTransitionLink}
              onSuccess={handleSuccess}
            />
          )}
          {mode === 'transition' && (
            <TransitionLinkPanel
              reason={transitionState?.reason}
              initialTrainerId={transitionState?.viewer_id}
              onBackToSteam={() => {
                setTransitionState(null)
                setMode('qr')
              }}
              onSuccess={handleSuccess}
            />
          )}
        </CardContent>
      </Card>
    </div>
  )
}
