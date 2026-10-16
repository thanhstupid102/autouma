/**
 * MasterDataCard — master.mdb path configuration.
 *
 * Ported from app.js:262-335.
 * Pure status-text logic lives in masterDataStatus.ts (unit tested).
 */

import { useState, useEffect, useRef } from 'react'
import { toast } from 'sonner'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

import { getMasterDataStatus, setMasterDataPath } from '@/api/settings'
import { masterDataStatusText } from './masterDataStatus'
import type { StatusResult } from './masterDataStatus'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function StatusLine({ status }: { status: StatusResult | null }) {
  if (!status) return null
  return (
    <p
      className={
        status.kind === 'ok'
          ? 'text-xs text-green-600 dark:text-green-400'
          : 'text-xs text-amber-600 dark:text-amber-400'
      }
    >
      {status.text}
    </p>
  )
}

// ---------------------------------------------------------------------------
// MasterDataCard
// ---------------------------------------------------------------------------

export function MasterDataCard() {
  const [path, setPath] = useState('')
  const [needsAction, setNeedsAction] = useState(false)
  const [status, setStatus] = useState<StatusResult | null>(null)
  const [saving, setSaving] = useState(false)

  // Track whether the component is still mounted to avoid state updates after
  // unmount (async loads).
  const mountedRef = useRef(true)
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  // -------------------------------------------------------------------------
  // Load status on mount
  // -------------------------------------------------------------------------
  useEffect(() => {
    getMasterDataStatus()
      .then((data) => {
        if (!mountedRef.current) return
        if (data.master_mdb_path) setPath(data.master_mdb_path)
        setNeedsAction(!data.exists)
        setStatus(masterDataStatusText(data))
      })
      .catch(() => {
        if (!mountedRef.current) return
        setStatus({ text: 'Unable to read master data status', kind: 'warn' })
      })
  }, [])

  // -------------------------------------------------------------------------
  // Save handler
  // -------------------------------------------------------------------------
  async function handleSave() {
    const trimmed = path.trim()
    if (!trimmed) {
      toast.warning('Enter the full path to master.mdb')
      setStatus({ text: 'Enter the full path to master.mdb', kind: 'warn' })
      setNeedsAction(true)
      return
    }

    setSaving(true)
    setStatus({ text: 'Saving path and generating data...', kind: 'warn' })
    try {
      const data = await setMasterDataPath({ master_mdb_path: trimmed })
      if (!mountedRef.current) return
      const next = masterDataStatusText(data)
      setStatus(next)
      setNeedsAction(!data.exists)
      if (data.master_mdb_path) setPath(data.master_mdb_path)
      if (next.kind === 'ok') {
        toast.success(next.text)
      } else {
        toast.warning(next.text)
      }
    } catch (e) {
      if (!mountedRef.current) return
      const msg = e instanceof Error ? e.message : 'Unable to save master.mdb path'
      setStatus({ text: msg, kind: 'warn' })
      setNeedsAction(true)
      toast.error(msg)
    } finally {
      if (mountedRef.current) setSaving(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Master Data</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-1.5">
          <Label htmlFor="master-mdb-path">Path to master.mdb</Label>
          <Input
            id="master-mdb-path"
            value={path}
            onChange={(e) => {
              setPath(e.target.value)
              setNeedsAction(false)
            }}
            placeholder="/path/to/master.mdb"
            className={needsAction ? 'ring-2 ring-destructive' : ''}
          />
        </div>
        <StatusLine status={status} />
        <Button onClick={handleSave} disabled={saving} size="sm">
          {saving ? 'Saving path and generating data...' : 'Save Path'}
        </Button>
      </CardContent>
    </Card>
  )
}
