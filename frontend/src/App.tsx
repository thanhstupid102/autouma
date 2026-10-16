import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { Eye, EyeOff, KeyRound, ShieldCheck } from 'lucide-react'
import { toast } from 'sonner'

import { getAuthGateStatus } from './api/authGate'
import { getApiToken, storeApiToken, subscribeApiToken } from './api/apiToken'
import { Button } from './components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from './components/ui/card'
import { Input } from './components/ui/input'
import { Label } from './components/ui/label'
import AppShell from './components/layout/AppShell'
import AccountLayout from './components/layout/AccountLayout'
import Overview from './pages/Overview'
import Dashboard from './pages/Dashboard'
import Setup from './pages/Setup'
import Library from './pages/Library'
import Settings from './pages/Settings'
import Events from './pages/Events'
import BotConfiguration from './pages/BotConfiguration'

function GateScreen({ children }: { children: ReactNode }) {
  return (
    <main className="relative flex min-h-dvh items-center justify-center overflow-hidden bg-background px-4">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,var(--color-primary)_0,transparent_34%)] opacity-10" />
      <div className="relative w-full max-w-md">{children}</div>
    </main>
  )
}

function TokenEntryScreen() {
  const [token, setToken] = useState('')
  const [tokenVisible, setTokenVisible] = useState(false)

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!token.trim()) {
      toast.error('Enter the API token configured on the server.')
      return
    }
    storeApiToken(token)
    toast.success('API token saved in this browser.')
  }

  return (
    <GateScreen>
      <Card className="shadow-xl">
        <CardHeader className="space-y-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-full bg-primary/10 text-primary">
            <KeyRound className="h-5 w-5" />
          </div>
          <div className="space-y-1">
            <CardTitle>API token required</CardTitle>
            <p className="text-sm text-muted-foreground">
              This server protects its API. Enter the operator token to open the dashboard.
            </p>
          </div>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={submit}>
            <div className="space-y-1.5">
              <Label htmlFor="dashboard-access-code">API token</Label>
              <div className="relative">
                <Input
                  id="dashboard-access-code"
                  name="dashboard-access-code"
                  type="text"
                  autoComplete="new-password"
                  className={tokenVisible ? 'pr-12' : 'pr-12 [-webkit-text-security:disc]'}
                  value={token}
                  onChange={(event) => setToken(event.target.value)}
                  autoFocus
                />
                <Button
                  aria-label={tokenVisible ? 'Hide API token' : 'Show API token'}
                  aria-pressed={tokenVisible}
                  className="absolute right-0 top-0"
                  size="icon"
                  type="button"
                  variant="ghost"
                  onClick={() => setTokenVisible((visible) => !visible)}
                >
                  {tokenVisible ? <EyeOff /> : <Eye />}
                </Button>
              </div>
            </div>
            <Button className="w-full" type="submit">Unlock dashboard</Button>
            <p className="text-xs text-muted-foreground">
              The token stays in this browser's local storage and is sent only in API request headers.
            </p>
          </form>
        </CardContent>
      </Card>
    </GateScreen>
  )
}

function DashboardRoutes() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<AppShell />}>
          <Route index element={<Overview />} />
          {/* Every page is scoped to an account in the URL so its per-account
              state (preset, team, run-settings, events) is bound to that account. */}
          <Route path="account/:name" element={<AccountLayout />}>
            <Route index element={<Dashboard />} />
            <Route path="setup" element={<Setup />} />
            <Route path="library" element={<Library />} />
            <Route path="events" element={<Events />} />
            <Route path="bot-configuration" element={<BotConfiguration />} />
            <Route path="settings" element={<Settings />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

export default function App() {
  const queryClient = useQueryClient()
  const [gateRequired, setGateRequired] = useState<boolean | null>(null)
  const [gateError, setGateError] = useState<string | null>(null)
  const [token, setToken] = useState(getApiToken)
  const [loadAttempt, setLoadAttempt] = useState(0)

  useEffect(() => subscribeApiToken((reason) => {
    setToken(getApiToken())
    queryClient.clear()
    if (reason === 'unauthorized') {
      toast.error('The API token was rejected. Enter it again.')
    }
  }), [queryClient])

  useEffect(() => {
    let active = true
    getAuthGateStatus()
      .then((status) => {
        if (active) setGateRequired(status.gate_required)
      })
      .catch((error: unknown) => {
        if (!active) return
        setGateError(error instanceof Error ? error.message : 'Could not read API gate status')
      })
    return () => { active = false }
  }, [loadAttempt])

  const retryGateStatus = useCallback(() => {
    // Reset here rather than in the effect body: setState inside an effect
    // costs a cascading render, and retry is the only path that needs a reset.
    setGateError(null)
    setGateRequired(null)
    setLoadAttempt((attempt) => attempt + 1)
  }, [])

  if (gateError) {
    return (
      <GateScreen>
        <Card>
          <CardHeader>
            <CardTitle>Cannot reach the API</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm text-muted-foreground">{gateError}</p>
            <Button onClick={retryGateStatus}>Retry</Button>
          </CardContent>
        </Card>
      </GateScreen>
    )
  }

  if (gateRequired === null) {
    return (
      <GateScreen>
        <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground">
          <ShieldCheck className="h-4 w-4" />
          Checking API access...
        </div>
      </GateScreen>
    )
  }

  if (gateRequired && !token) return <TokenEntryScreen />

  // "Forget API token" lives in the sidebar footer beside the other
  // session-level actions, not in a fixed overlay -- a fixed top-right button
  // sat on top of each page's own header controls (it covered Add account on
  // the accounts page).
  return <DashboardRoutes />
}
