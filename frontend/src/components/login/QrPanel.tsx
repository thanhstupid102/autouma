import { useEffect, useRef, useState, useCallback } from 'react'
import QRCode from 'qrcode'
import { useQueryClient } from '@tanstack/react-query'
import { Copy, ExternalLink } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { qrStart, qrPoll, login } from '@/api/auth'
import type { SessionData } from '@/api/types'
import type { StatusState } from './types'
import { transitionLinkErrorMessage } from './transitionLinkErrors'

interface QrPanelProps {
  onUsePassword: () => void
  onSuccess?: () => void
  onNeedsTransitionLink?: (result: SessionData) => void
  /** Target account for the QR login (X-Account). Omit to use the selected account. */
  account?: string
}

const MAX_CONSECUTIVE_POLL_FAILURES = 3

export default function QrPanel({
  onUsePassword,
  onSuccess,
  onNeedsTransitionLink,
  account,
}: QrPanelProps) {
  const queryClient = useQueryClient()
  const [qrDataUrl, setQrDataUrl] = useState<string | null>(null)
  const [challengeUrl, setChallengeUrl] = useState<string | null>(null)
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'error'>('idle')
  const [showNewQr, setShowNewQr] = useState(false)
  const [status, setStatus] = useState<StatusState>({ kind: 'working', message: 'Generating QR...' })
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const consecutivePollFailuresRef = useRef(0)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      if (pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
    }
  }, [])

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  const startQr = useCallback(async () => {
    stopPolling()
    consecutivePollFailuresRef.current = 0
    setQrDataUrl(null)
    setChallengeUrl(null)
    setCopyState('idle')
    setShowNewQr(false)
    setStatus({ kind: 'working', message: 'Generating QR...' })

    try {
      const data = await qrStart(account)
      if (!mountedRef.current) return

      if (!data.challenge_url) {
        setStatus({ kind: 'error', message: 'Could not start QR. Use password.' })
        setShowNewQr(true)
        return
      }

      const dataUrl = await QRCode.toDataURL(data.challenge_url, { width: 200 })
      if (!mountedRef.current) return

      setQrDataUrl(dataUrl)
      setChallengeUrl(data.challenge_url)
      setStatus({ kind: 'working', message: 'Scan with the Steam Mobile app.' })

      pollRef.current = setInterval(async () => {
        if (!mountedRef.current) {
          stopPolling()
          return
        }
        try {
          const poll = await qrPoll(account)
          if (!mountedRef.current) return
          consecutivePollFailuresRef.current = 0

          if (poll.status === 'pending') {
            setStatus({ kind: 'working', message: 'Waiting for phone confirmation...' })
          } else if (poll.status === 'confirmed') {
            stopPolling()
            setStatus({ kind: 'working', message: 'Confirmed. Logging in...' })
            try {
              const result = await login({}, account)
              if (!mountedRef.current) return
              if (result.state === 'authenticated' || (result.success && !result.state)) {
                await queryClient.invalidateQueries({ queryKey: ['session'] })
                onSuccess?.()
              } else if (result.state === 'needs_transition_link') {
                onNeedsTransitionLink?.(result)
              } else {
                const msg = transitionLinkErrorMessage(result.error_code, result.detail) + ' Try password.'
                setStatus({ kind: 'error', message: msg })
                setShowNewQr(true)
              }
            } catch {
              if (!mountedRef.current) return
              setStatus({ kind: 'error', message: 'Login failed after scan. Try password.' })
              setShowNewQr(true)
            }
          } else if (poll.status === 'expired' || poll.status === 'error') {
            stopPolling()
            const msg = (poll.error ?? 'QR expired') + ' - tap New QR.'
            setStatus({ kind: 'error', message: msg })
            setShowNewQr(true)
          }
        } catch {
          if (!mountedRef.current) return
          consecutivePollFailuresRef.current += 1
          if (consecutivePollFailuresRef.current >= MAX_CONSECUTIVE_POLL_FAILURES) {
            stopPolling()
            setStatus({
              kind: 'error',
              message: 'Could not check QR status after 3 attempts. Check your connection and tap New QR.',
            })
            setShowNewQr(true)
          }
        }
      }, 2000)
    } catch {
      if (!mountedRef.current) return
      setStatus({ kind: 'error', message: 'Could not start QR. Use password.' })
      setShowNewQr(true)
    }
  }, [queryClient, stopPolling, account, onNeedsTransitionLink, onSuccess])

  // Start on mount
  useEffect(() => {
    // The QR challenge is an external subscription whose status is reflected locally.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    startQr()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const copyChallengeLink = useCallback(async () => {
    if (!challengeUrl) return
    try {
      await navigator.clipboard.writeText(challengeUrl)
      setCopyState('copied')
    } catch {
      setCopyState('error')
    }
  }, [challengeUrl])

  const statusColor =
    status.kind === 'error'
      ? 'text-destructive'
      : status.kind === 'ok'
        ? 'text-green-600'
        : 'text-muted-foreground'

  return (
    <div className="flex flex-col items-center gap-4">
      <p className="text-sm font-semibold text-foreground">Scan with Steam Mobile</p>

      {qrDataUrl ? (
        <img
          src={qrDataUrl}
          alt="Steam QR code"
          width={200}
          height={200}
          className="max-w-full rounded-md border border-border"
        />
      ) : (
        <div className="w-[200px] h-[200px] flex items-center justify-center rounded-md border border-border bg-muted">
          <span className="text-xs text-muted-foreground">
            {status.kind === 'error' ? '—' : '…'}
          </span>
        </div>
      )}

      <p className={`text-xs text-center ${statusColor}`}>{status.message}</p>

      {challengeUrl && (
        <div className="grid w-full gap-2 sm:grid-cols-2">
          <Button asChild variant="outline" className="w-full">
            <a href={challengeUrl} target="_blank" rel="noreferrer">
              <ExternalLink />
              Open in Steam
            </a>
          </Button>
          <Button type="button" variant="outline" className="w-full" onClick={copyChallengeLink}>
            <Copy />
            {copyState === 'copied' ? 'Copied' : 'Copy link'}
          </Button>
        </div>
      )}

      {copyState === 'error' && (
        <p className="text-center text-xs text-destructive" role="alert">
          Could not copy the Steam link. Open it directly instead.
        </p>
      )}

      {showNewQr && (
        <Button size="sm" variant="outline" onClick={startQr}>
          New QR
        </Button>
      )}

      <Button
        type="button"
        variant="ghost"
        onClick={onUsePassword}
        className="mt-1 w-full"
      >
        Use password instead
      </Button>
    </div>
  )
}
