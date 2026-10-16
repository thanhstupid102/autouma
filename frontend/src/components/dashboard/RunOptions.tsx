/**
 * RunOptions — run configuration panel.
 *
 * Behaviors ported from app.js:
 *   - Delay min/max inputs (normalizeDelayBounds on change)
 *   - RUNS count + hint text (-1→SP dump stop, 0→∞, 1→"1 career", n→"n careers")
 *   - EVENT toggle: fetches getEventInfo on mount; shows level select + boost
 *     checkbox when enabled. Wires to runSettings.setEvent AND selection.setEvent
 *     (mirrors app.js:814-824 syncEventControl).
 *   - NO CD toggle → setNoCd
 *   - BURN CLOCKS toggle → setBurnClocks + live POST when runner is running
 *   - 2Pal Deck toggle → explicit run flag; no deck auto-detect
 *     (app.js:745-760)
 *
 * loadLegacy called on mount once to hydrate from localStorage.
 */
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Checkbox } from '@/components/ui/checkbox'
import { TouchControlRow } from '@/components/ui/touch-control-row'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

import { getEventInfo, setBurnClocks as apiBurnClocks } from '@/api/career'
import { getTurnDelay, saveTurnDelay } from '@/api/settings'
import type { EventInfo } from '@/api/types'
import { useRunSettings } from '@/stores/runSettings'
import { useSelection } from '@/stores/selection'
import { useRunner } from '@/hooks/useRunner'
import { useSession } from '@/hooks/useSession'
import { runCountHint } from './runRules'

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function RunOptions() {
  // Stores
  const {
    delayMin,
    delayMax,
    noCd,
    runCount,
    eventEnabled,
    eventLevel,
    eventBoost,
    burnClocks,
    twoPalDeck,
    sparkReroll,
    setDelay,
    setNoCd,
    setRunCount,
    setEvent,
    setBurnClocks,
    setTwoPalDeck,
    setSparkReroll,
  } = useRunSettings()
  const selection = useSelection()

  // Session / runner
  const sessionQuery = useSession()
  const session = sessionQuery.data
  const runnerQuery = useRunner(!!session?.success)
  const runner = runnerQuery.data?.runner
  const isRunning = !!(runner?.running)

  // Event info from server
  const [eventInfo, setEventInfo] = useState<EventInfo>({
    success: false,
    available: false,
    max_level: 0,
  })
  // Per-account run settings (runCount/burn/event) are hydrated by
  // useAccountScopedReload (AppShell) on account change — not here, so this
  // panel never loads the wrong account's settings before the route resolves.
  useEffect(() => {
    // The turn delay lives on the BACKEND (career_bot/delay.py globals), not in the
    // run body. The old UI only wrote it to localStorage, so the "No CD" toggle did
    // nothing to the actual run pacing. Pull the backend's authoritative state on
    // mount so the toggle reflects (and from now on controls) reality.
    getTurnDelay()
      .then((d) => {
        if (d.disabled) setNoCd(true)
        else setDelay(Number(d.min) || 0, Number(d.max) || 0)
      })
      .catch(() => {/* leave store/localStorage state as-is */})
    getEventInfo()
      .then((info) => {
        setEventInfo(info)
        // If event not available and we're currently enabled, turn it off
        if (!info.available && eventEnabled) {
          const newEvent = { enabled: false, level: eventLevel, boost: eventBoost }
          setEvent(newEvent)
          selection.setEvent(newEvent)
        }
      })
      .catch(() => {
        setEventInfo({ success: false, available: false, max_level: 0 })
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ---------------------------------------------------------------------------
  // Delay handlers — every change is pushed to the backend (the engine reads the
  // delay from career_bot/delay.py globals, set via /api/settings/turn-delay).
  // ---------------------------------------------------------------------------
  function pushTurnDelay() {
    const { noCd: cd, delayMin: lo, delayMax: hi } = useRunSettings.getState()
    saveTurnDelay({ min: cd ? 0 : lo, max: cd ? 0 : hi, disabled: cd }).catch((e) => {
      toast.error(e instanceof Error ? e.message : 'Failed to update turn delay')
    })
  }

  function handleDelayMin(e: React.ChangeEvent<HTMLInputElement>) {
    const v = parseFloat(e.target.value)
    if (Number.isFinite(v)) {
      setDelay(v, delayMax)
      pushTurnDelay()
    }
  }
  function handleDelayMax(e: React.ChangeEvent<HTMLInputElement>) {
    const v = parseFloat(e.target.value)
    if (Number.isFinite(v)) {
      setDelay(delayMin, v)
      pushTurnDelay()
    }
  }

  function handleNoCd(checked: boolean) {
    setNoCd(checked)
    pushTurnDelay()
  }

  // ---------------------------------------------------------------------------
  // Run count handler
  // ---------------------------------------------------------------------------
  function handleRunCount(e: React.ChangeEvent<HTMLInputElement>) {
    const v = parseInt(e.target.value, 10)
    if (Number.isInteger(v) && v >= -1) setRunCount(v)
  }

  // ---------------------------------------------------------------------------
  // Event handlers — mirrors syncEventControl (app.js:814-824)
  // ---------------------------------------------------------------------------
  const maxLevel = Math.max(1, Number(eventInfo.max_level || 1))

  function syncEvent(overrides: Partial<{ enabled: boolean; level: number; boost: boolean }>) {
    const rawEnabled = overrides.enabled ?? eventEnabled
    const on = !!(rawEnabled && eventInfo.available)
    const newLevel = overrides.level ?? eventLevel
    const newBoost = overrides.boost ?? eventBoost
    const newEvent = { enabled: on, level: newLevel, boost: newBoost }
    setEvent(newEvent)
    selection.setEvent(newEvent)
  }

  // ---------------------------------------------------------------------------
  // Burn clocks handler — live POST when runner is running (app.js:745-760)
  // ---------------------------------------------------------------------------
  async function handleBurnClocks(checked: boolean) {
    setBurnClocks(checked)
    if (isRunning) {
      try {
        const data = await apiBurnClocks({ burn_clocks: checked })
        if (!data.success) throw new Error(data.detail || 'Failed to update burn_clocks')
        // Runner snapshot update is handled via the polling refetch
      } catch (e) {
        // Revert to current runner value on failure (app.js:758-760)
        const msg = e instanceof Error ? e.message : 'Failed to update burn_clocks'
        toast.error(msg)
        if (runner?.burn_clocks !== undefined) {
          setBurnClocks(runner.burn_clocks)
        }
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------
  return (
    <Card>
      <CardHeader>
        <CardTitle>Run Options</CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {/* DELAY */}
        <div className="flex flex-col gap-2">
          <Label className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Turn Delay (s)
          </Label>
          <div className="flex items-center gap-2">
            <div className="flex flex-col gap-1">
              <Label htmlFor="delay-min" className="text-xs">
                Min
              </Label>
              <Input
                id="delay-min"
                type="number"
                min={0}
                step={0.1}
                value={noCd ? 0 : delayMin}
                disabled={noCd}
                onChange={handleDelayMin}
                className="w-20"
              />
            </div>
            <span className="mt-5 text-muted-foreground">–</span>
            <div className="flex flex-col gap-1">
              <Label htmlFor="delay-max" className="text-xs">
                Max
              </Label>
              <Input
                id="delay-max"
                type="number"
                min={0}
                step={0.1}
                value={noCd ? 0 : delayMax}
                disabled={noCd}
                onChange={handleDelayMax}
                className="w-20"
              />
            </div>
          </div>
        </div>

        {/* RUNS */}
        <div className="flex flex-col gap-2">
          <Label htmlFor="run-count" className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Runs
          </Label>
          <Input
            id="run-count"
            type="number"
            min={-1}
            step={1}
            value={runCount}
            onChange={handleRunCount}
            className="w-24"
          />
          <span className="text-xs text-muted-foreground">{runCountHint(runCount)}</span>
        </div>

        {/* NO CD */}
        <TouchControlRow
          className="md:flex-row-reverse"
          label="No CD (zero delays)"
          control={<Switch checked={noCd} onCheckedChange={handleNoCd} />}
        />

        {/* BURN CLOCKS */}
        <TouchControlRow
          className="md:flex-row-reverse"
          label="Burn Clocks"
          control={<Switch checked={burnClocks} onCheckedChange={handleBurnClocks} />}
        />

        {/* 2PAL DECK */}
        <TouchControlRow
          className="md:flex-row-reverse"
          label="2Pal Deck"
          control={<Switch checked={twoPalDeck} onCheckedChange={setTwoPalDeck} />}
        />

        {/* SPARK REROLL */}
        <TouchControlRow
          className="md:flex-row-reverse"
          label="Spark Reroll (30 TP)"
          control={<Switch checked={sparkReroll} onCheckedChange={setSparkReroll} />}
        />

        {/* EVENT */}
        <div className="col-span-full flex flex-col gap-2 rounded-lg border border-border p-3">
          <TouchControlRow
            className="md:flex-row-reverse"
            label="Event Mode"
            disabled={!eventInfo.available}
            disabledReason="No event is currently active."
            control={(
              <Switch
                checked={eventEnabled}
                onCheckedChange={(checked) => syncEvent({ enabled: checked })}
              />
            )}
          />

          {eventEnabled && eventInfo.available && (
            <div className="flex flex-wrap items-center gap-4 pl-1">
              {/* Level select */}
              <div className="flex flex-col gap-1">
                <Label className="text-xs">Level</Label>
                <Select
                  value={String(eventLevel)}
                  onValueChange={(val) => syncEvent({ level: Number(val) })}
                >
                  <SelectTrigger size="sm" className="w-24">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {Array.from({ length: maxLevel }, (_, i) => i + 1).map((lv) => (
                      <SelectItem key={lv} value={String(lv)}>
                        Lv {lv}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* Boost checkbox */}
              <TouchControlRow
                className="md:w-fit md:flex-row-reverse"
                label="Boost"
                control={(
                  <Checkbox
                    checked={eventBoost}
                    onCheckedChange={(checked) =>
                      syncEvent({ boost: checked === true })
                    }
                  />
                )}
              />
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
