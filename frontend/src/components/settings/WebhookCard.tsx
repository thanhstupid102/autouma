/**
 * WebhookCard — Discord webhook configuration and test.
 *
 * Ported from app.js:336-390.
 */

import { useState, useEffect, useRef } from 'react'
import { toast } from 'sonner'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

import { getDiscordWebhook, saveDiscordWebhook, testDiscordWebhook } from '@/api/settings'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type StatusKind = 'ok' | 'warn' | 'idle'

interface InlineStatus {
  text: string
  kind: StatusKind
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function StatusLine({ status }: { status: InlineStatus | null }) {
  if (!status || !status.text) return null
  const cls =
    status.kind === 'ok'
      ? 'text-xs text-green-600 dark:text-green-400'
      : status.kind === 'warn'
        ? 'text-xs text-amber-600 dark:text-amber-400'
        : 'text-xs text-muted-foreground'
  return <p className={cls}>{status.text}</p>
}

// ---------------------------------------------------------------------------
// WebhookCard
// ---------------------------------------------------------------------------

export function WebhookCard() {
  const [url, setUrl] = useState('')
  const [errorMention, setErrorMention] = useState('')
  const [configured, setConfigured] = useState<boolean | null>(null)
  const [webhookPreview, setWebhookPreview] = useState<string | null>(null)
  const [savedErrorMention, setSavedErrorMention] = useState<string | null>(null)
  const [status, setStatus] = useState<InlineStatus | null>(null)
  const [saving, setSaving] = useState(false)
  const [removing, setRemoving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [savingErrorMention, setSavingErrorMention] = useState(false)
  const [removingErrorMention, setRemovingErrorMention] = useState(false)

  const mountedRef = useRef(true)
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  // -------------------------------------------------------------------------
  // Load on mount
  // -------------------------------------------------------------------------
  useEffect(() => {
    getDiscordWebhook()
      .then((data) => {
        if (!mountedRef.current) return
        setConfigured(!!data.configured)
        setWebhookPreview(data.webhook_preview ?? null)
        setErrorMention(data.error_mention ?? '')
        setSavedErrorMention(data.error_mention ?? null)
      })
      .catch(() => {
        if (!mountedRef.current) return
        setStatus({ text: 'Could not read webhook status', kind: 'warn' })
      })
  }, [])

  // -------------------------------------------------------------------------
  // Save
  // -------------------------------------------------------------------------
  async function handleSave() {
    const trimmed = url.trim()
    if (!trimmed) {
      setStatus({
        text:
          configured === true
            ? 'Enter a new URL or use Remove webhook.'
            : 'Enter a webhook URL.',
        kind: 'warn',
      })
      return
    }

    setSaving(true)
    setStatus({ text: 'Saving...', kind: 'idle' })
    try {
      const data = await saveDiscordWebhook({ webhook_url: trimmed })
      if (!mountedRef.current) return
      setConfigured(!!data.configured)
      setWebhookPreview(null)
      setUrl('')
      const text = data.configured ? 'Webhook saved' : 'Webhook cleared'
      const kind: StatusKind = data.configured ? 'ok' : 'idle'
      setStatus({ text, kind })
      if (data.configured) {
        toast.success(text)
      } else {
        toast.info(text)
      }
    } catch (e) {
      if (!mountedRef.current) return
      const msg = e instanceof Error ? e.message : 'Failed to save webhook'
      setStatus({ text: msg, kind: 'warn' })
      toast.error(msg)
    } finally {
      if (mountedRef.current) setSaving(false)
    }
  }

  // -------------------------------------------------------------------------
  // Remove
  // -------------------------------------------------------------------------
  async function handleRemove() {
    if (configured !== true) return

    setRemoving(true)
    setStatus({ text: 'Removing webhook...', kind: 'idle' })
    try {
      const data = await saveDiscordWebhook({ webhook_url: '' })
      if (!mountedRef.current) return
      setConfigured(!!data.configured)
      setWebhookPreview(null)
      setUrl('')
      if (data.configured) {
        const text = 'Webhook could not be removed'
        setStatus({ text, kind: 'warn' })
        toast.warning(text)
      } else {
        const text = 'Webhook removed'
        setStatus({ text, kind: 'idle' })
        toast.info(text)
      }
    } catch (e) {
      if (!mountedRef.current) return
      const msg = e instanceof Error ? e.message : 'Failed to remove webhook'
      setStatus({ text: msg, kind: 'warn' })
      toast.error(msg)
    } finally {
      if (mountedRef.current) setRemoving(false)
    }
  }

  // -------------------------------------------------------------------------
  // Career error ping target
  // -------------------------------------------------------------------------
  async function handleSaveErrorMention() {
    const trimmed = errorMention.trim()
    if (!trimmed) {
      setStatus({ text: 'Enter a Discord user or role mention.', kind: 'warn' })
      return
    }

    setSavingErrorMention(true)
    setStatus({ text: 'Saving error ping target...', kind: 'idle' })
    try {
      const data = await saveDiscordWebhook({ error_mention: trimmed })
      if (!mountedRef.current) return
      const saved = data.error_mention ?? trimmed
      setErrorMention(saved)
      setSavedErrorMention(saved)
      setStatus({ text: 'Career error ping saved', kind: 'ok' })
      toast.success('Career error ping saved')
    } catch (e) {
      if (!mountedRef.current) return
      const msg = e instanceof Error ? e.message : 'Failed to save error ping'
      setStatus({ text: msg, kind: 'warn' })
      toast.error(msg)
    } finally {
      if (mountedRef.current) setSavingErrorMention(false)
    }
  }

  async function handleRemoveErrorMention() {
    if (savedErrorMention === null) return

    setRemovingErrorMention(true)
    setStatus({ text: 'Removing error ping target...', kind: 'idle' })
    try {
      await saveDiscordWebhook({ error_mention: null })
      if (!mountedRef.current) return
      setErrorMention('')
      setSavedErrorMention(null)
      setStatus({ text: 'Career error ping removed', kind: 'idle' })
      toast.info('Career error ping removed')
    } catch (e) {
      if (!mountedRef.current) return
      const msg = e instanceof Error ? e.message : 'Failed to remove error ping'
      setStatus({ text: msg, kind: 'warn' })
      toast.error(msg)
    } finally {
      if (mountedRef.current) setRemovingErrorMention(false)
    }
  }

  // -------------------------------------------------------------------------
  // Test
  // -------------------------------------------------------------------------
  async function handleTest() {
    setTesting(true)
    setStatus({ text: 'Sending test message...', kind: 'idle' })
    try {
      const data = await testDiscordWebhook()
      if (!mountedRef.current) return
      if (data.success) {
        const text = 'Test message sent — check your Discord channel'
        setStatus({ text, kind: 'ok' })
        toast.success(text)
      } else {
        const text = data.detail ?? 'Failed to send test'
        setStatus({ text, kind: 'warn' })
        toast.warning(text)
      }
    } catch (e) {
      if (!mountedRef.current) return
      const msg = e instanceof Error ? e.message : 'Failed to send test'
      setStatus({ text: msg, kind: 'warn' })
      toast.error(msg)
    } finally {
      if (mountedRef.current) setTesting(false)
    }
  }

  const configurationStatus: InlineStatus | null =
    configured === null
      ? null
      : configured
        ? {
            text: `Configured: ${webhookPreview ?? 'URL hidden'}`,
            kind: 'ok',
          }
        : { text: 'Not configured', kind: 'idle' }
  const errorMentionStatus: InlineStatus = savedErrorMention
    ? { text: `Career error ping: ${savedErrorMention}`, kind: 'ok' }
    : { text: 'Career error ping disabled', kind: 'idle' }
  const busy = saving || removing || testing || savingErrorMention || removingErrorMention

  return (
    <Card>
      <CardHeader>
        <CardTitle>Discord Webhook</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-1.5">
          <Label htmlFor="discord-webhook-url">Webhook URL</Label>
          <Input
            id="discord-webhook-url"
            value={url}
            onChange={(e) => {
              setUrl(e.target.value)
              setStatus(null)
            }}
            placeholder="https://discord.com/api/webhooks/..."
          />
        </div>
        <StatusLine status={configurationStatus} />
        <div className="space-y-1.5">
          <Label htmlFor="discord-error-mention">Career error ping target</Label>
          <Input
            id="discord-error-mention"
            value={errorMention}
            onChange={(e) => {
              setErrorMention(e.target.value)
              setStatus(null)
            }}
            placeholder="12345678901234567 or <@12345678901234567>"
          />
        </div>
        <StatusLine status={errorMentionStatus} />
        <StatusLine status={status} />
        <div data-testid="webhook-actions" className="flex flex-wrap gap-2">
          <Button onClick={handleSave} disabled={busy} size="sm">
            {saving ? 'Saving...' : 'Save Webhook'}
          </Button>
          <Button
            onClick={handleTest}
            disabled={busy}
            variant="outline"
            size="sm"
          >
            {testing ? 'Testing...' : 'Test'}
          </Button>
          {configured === true && (
            <Button
              onClick={handleRemove}
              disabled={busy}
              variant="destructive"
              size="sm"
            >
              {removing ? 'Removing...' : 'Remove webhook'}
            </Button>
          )}
          <Button onClick={handleSaveErrorMention} disabled={busy} size="sm">
            {savingErrorMention ? 'Saving...' : 'Save Error Ping'}
          </Button>
          {savedErrorMention !== null && (
            <Button
              onClick={handleRemoveErrorMention}
              disabled={busy}
              variant="outline"
              size="sm"
            >
              {removingErrorMention ? 'Removing...' : 'Remove Error Ping'}
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
