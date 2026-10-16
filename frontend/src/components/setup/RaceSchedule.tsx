/**
 * RaceSchedule — 3-year × 24-slot race selection grid + picker dialog.
 *
 * Ported from app.js:1148-1353.
 * Pure logic lives in raceRules.ts (unit tested).
 *
 * Data flow:
 *   1. Fetch race data once from /assets/data/uma_race_data.json on mount.
 *   2. Sync selectedRaces from active RACE PRESET's extra_race_list.
 *   3. Render 3-year grid of 24 cells each.
 *   4. Cell click → RacePickerDialog for that slot.
 *   5. Toggle in picker → update local selectedRaces + mark dirty.
 *   6. Save Races → PUT /api/presets/{name}/races?kind=race + update race preset store.
 */

import { useState, useEffect, useCallback } from 'react'
import { toast } from 'sonner'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'

import { useRacePresets } from '@/stores/racePresets'

import {
  YEAR_LABELS,
  getYearSlots,
  raceKeys,
  toggleRaceInSlot,
  syncFromPreset,
} from './raceRules'
import type { Race, Slot } from './raceRules'
import { RacePickerDialog } from './RacePickerDialog'

// ---------------------------------------------------------------------------
// Scenario constant — only MANT is the active path
// ---------------------------------------------------------------------------
const SCENARIO = 'Mant'

// ---------------------------------------------------------------------------
// Race data fetch hook — loads once, cached in module scope
// ---------------------------------------------------------------------------
let _raceDataCache: Race[] | null = null

async function fetchRaceData(): Promise<Race[]> {
  if (_raceDataCache) return _raceDataCache
  const res = await fetch('/assets/data/uma_race_data.json')
  const data = await res.json()
  _raceDataCache = Array.isArray(data.races) ? data.races : []
  return _raceDataCache!
}

// ---------------------------------------------------------------------------
// RaceSchedule
// ---------------------------------------------------------------------------

export function RaceSchedule() {
  const { getActive, selectedName, saveRaces } = useRacePresets()

  const [raceData, setRaceData] = useState<Race[]>([])
  const [selectedRaces, setSelectedRaces] = useState<number[]>([])
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveStatus, setSaveStatus] = useState<string>('')

  // Picker dialog state
  const [pickerOpen, setPickerOpen] = useState(false)
  const [pickerSlot, setPickerSlot] = useState<Slot | null>(null)

  // -------------------------------------------------------------------------
  // Load race data on mount
  // -------------------------------------------------------------------------
  useEffect(() => {
    fetchRaceData()
      .then(setRaceData)
      .catch(() => {
        toast.error('Failed to load race data')
        setRaceData([])
      })
  }, [])

  // -------------------------------------------------------------------------
  // Sync selectedRaces from active race preset when preset changes
  // -------------------------------------------------------------------------
  const activePreset = getActive()
  const activeName = activePreset?.name

  useEffect(() => {
    const races = syncFromPreset(activePreset?.extra_race_list)
    setSelectedRaces(races)
    setDirty(false)
    setSaveStatus('')
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeName])

  // -------------------------------------------------------------------------
  // Toggle handler — called by RacePickerDialog
  // -------------------------------------------------------------------------
  const handleToggle = useCallback(
    (race: Race, slotIds: number[]) => {
      setSelectedRaces((prev) => {
        const next = toggleRaceInSlot(prev, race, slotIds, SCENARIO)
        return next
      })
      setDirty(true)
      setSaveStatus('')
    },
    [],
  )

  // -------------------------------------------------------------------------
  // Open picker for a slot
  // -------------------------------------------------------------------------
  function openPicker(slot: Slot) {
    setPickerSlot(slot)
    setPickerOpen(true)
  }

  // -------------------------------------------------------------------------
  // Save races to race preset
  // -------------------------------------------------------------------------
  async function handleSave() {
    if (!selectedName) {
      setSaveStatus('Select a race preset first')
      return
    }
    setSaving(true)
    setSaveStatus('Saving...')
    try {
      // One store action owns race-schedule persistence: it issues the single
      // race-list mutation and mirrors the result into the store for other
      // consumers (see stores/racePresets.ts:saveRaces).
      await saveRaces(selectedName, selectedRaces)
      setDirty(false)
      setSaveStatus(`✓ Saved (${selectedRaces.length} races)`)
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Failed to save'
      setSaveStatus(msg)
    } finally {
      setSaving(false)
    }
  }

  // -------------------------------------------------------------------------
  // No race preset selected — show placeholder
  // -------------------------------------------------------------------------
  if (!selectedName) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Race Schedule</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Select or create a race preset first.
          </p>
        </CardContent>
      </Card>
    )
  }

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------
  return (
    <>
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <CardTitle className="text-base">Race Schedule</CardTitle>
            <div className="flex items-center gap-2">
              {dirty && (
                <span className="text-xs text-amber-500 font-medium">● Unsaved</span>
              )}
              {!dirty && saveStatus && (
                <span className="text-xs text-muted-foreground">{saveStatus}</span>
              )}
              {dirty && saveStatus && saveStatus !== '● Unsaved' && (
                <span className="text-xs text-muted-foreground">{saveStatus}</span>
              )}
              <Button
                size="sm"
                onClick={handleSave}
                disabled={saving || !selectedName}
              >
                {saving ? 'Saving…' : 'SAVE RACES'}
              </Button>
            </div>
          </div>
        </CardHeader>

        <CardContent className="space-y-6">
          {YEAR_LABELS.map((yearLabel, yi) => (
            <YearBlock
              key={yearLabel}
              yearLabel={yearLabel}
              yearIdx={yi}
              raceData={raceData}
              selectedRaces={selectedRaces}
              onCellClick={openPicker}
            />
          ))}
        </CardContent>
      </Card>

      <RacePickerDialog
        open={pickerOpen}
        onOpenChange={setPickerOpen}
        slot={pickerSlot}
        selectedRaces={selectedRaces}
        onToggle={handleToggle}
      />
    </>
  )
}

// ---------------------------------------------------------------------------
// YearBlock — one year (label + 24-cell grid)
// ---------------------------------------------------------------------------

interface YearBlockProps {
  yearLabel: string
  yearIdx: number
  raceData: Race[]
  selectedRaces: number[]
  onCellClick: (slot: Slot) => void
}

function YearBlock({ yearLabel, yearIdx, raceData, selectedRaces, onCellClick }: YearBlockProps) {
  const slots = getYearSlots(yearIdx, raceData)
  return (
    <div>
      <h3 className="text-sm font-semibold text-muted-foreground mb-2">{yearLabel}</h3>
      <div className="grid min-w-0 max-w-full grid-cols-4 gap-1 sm:grid-cols-6 md:grid-cols-8">
        {slots.map((slot) => (
          <SlotCell
            key={slot.label}
            slot={slot}
            selectedRaces={selectedRaces}
            onClick={() => onCellClick(slot)}
          />
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// SlotCell — single 24-cell entry
// ---------------------------------------------------------------------------

interface SlotCellProps {
  slot: Slot
  selectedRaces: number[]
  onClick: () => void
}

function SlotCell({ slot, selectedRaces, onClick }: SlotCellProps) {
  const slotIds = slot.races.flatMap((r) => raceKeys(r))
  const selectedInSlot = selectedRaces.filter((id) => slotIds.includes(id))
  const mainRaceId = selectedInSlot[0]
  const selected = slot.races.find((r) => raceKeys(r).includes(mainRaceId))

  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        'flex min-h-24 min-w-0 max-w-full flex-col items-center gap-0.5 overflow-hidden rounded border p-1 md:min-h-[72px]',
        'text-center transition-colors cursor-pointer',
        'hover:bg-accent/50',
        selected
          ? 'border-primary/30 bg-accent/20'
          : 'border-border/40 bg-card',
      ].join(' ')}
    >
      <span className="text-[11px] leading-none text-muted-foreground md:text-[9px]">
        {slot.label}
      </span>

      {selected ? (
        <>
          <SlotCellImage race={selected} />
          <Badge
            variant="secondary"
            className={`h-auto px-1 py-0 text-[11px] font-bold md:text-[8px] badge-${selected.type.toLowerCase().replace(/-/g, '')}`}
          >
            {selected.type}
          </Badge>
          <span
            className="line-clamp-2 w-full max-w-full break-words text-center text-xs leading-tight md:line-clamp-1 md:text-[9px]"
            title={selected.name}
          >
            {selected.name}
          </span>
        </>
      ) : (
        <span className="text-muted-foreground/40 text-lg leading-none mt-auto mb-auto">+</span>
      )}
    </button>
  )
}

// ---------------------------------------------------------------------------
// SlotCellImage — race image with type-text fallback
// ---------------------------------------------------------------------------

interface SlotCellImageProps {
  race: Race
}

function SlotCellImage({ race }: SlotCellImageProps) {
  const [errored, setErrored] = useState(false)

  return (
    <div className="relative w-full aspect-[161/80] rounded overflow-hidden bg-muted flex items-center justify-center">
      {!errored ? (
        <img
          src={`/races/${encodeURIComponent(race.name)}.png`}
          alt={race.name}
          className="object-cover w-full h-full"
          onError={() => setErrored(true)}
        />
      ) : (
        <span className="px-0.5 text-center text-[11px] font-bold text-muted-foreground md:text-[8px]">
          {race.type}
        </span>
      )}
    </div>
  )
}
