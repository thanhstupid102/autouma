/**
 * RacePresetPanel — Race preset selector + CRUD + Export/Import + RaceSchedule.
 *
 * Reads/writes via the `useRacePresets` Zustand store which is the single
 * source of truth for race presets and writes localStorage `uma_selected_race_preset`.
 */

import { useEffect, useState } from 'react'

import { useRacePresets } from '@/stores/racePresets'
import { saveRacePreset } from '@/api/presets'
import type { RacePreset } from '@/api/types'
import { useJsonImport } from '@/hooks/useJsonImport'
import { NewPresetDialog } from './NewPresetDialog'
import { DeletePresetDialog } from './DeletePresetDialog'
import { PresetSelectorCard } from './PresetSelectorCard'
import { RaceSchedule } from './RaceSchedule'
import { downloadJson, slugify } from './presetIO'
import { formatPresetImportSummary } from './presetImportSummary'

// ---------------------------------------------------------------------------
// RacePresetPanel
// ---------------------------------------------------------------------------

export function RacePresetPanel() {
  const { presets, selectedName, select, create, remove, getActive, load } = useRacePresets()

  const [newOpen, setNewOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)

  useEffect(() => {
    load()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const active = getActive()

  // -------------------------------------------------------------------------
  // Export
  // -------------------------------------------------------------------------
  function handleExport() {
    if (!active) return
    downloadJson(`${slugify(active.name)}.json`, active)
  }

  // -------------------------------------------------------------------------
  // Import
  // -------------------------------------------------------------------------
  const { isImporting, handleImportFile } = useJsonImport<RacePreset>({
    // Minimal validation: must have name string + extra_race_list array
    validate: (raw): raw is RacePreset =>
      typeof raw === 'object' &&
      raw !== null &&
      typeof (raw as Record<string, unknown>).name === 'string' &&
      Boolean((raw as Record<string, unknown>).name) &&
      Array.isArray((raw as Record<string, unknown>).extra_race_list),
    invalidMessage:
      'Import failed: JSON must have a "name" string and "extra_race_list" array.',
    save: async (preset) => {
      const res = await saveRacePreset({ preset })
      if (!res.success) {
        return res.detail ?? 'Import failed: server rejected the race preset.'
      }
    },
    onDone: async (preset) => {
      await load()
      select(preset.name)
    },
    successMessage: (preset) => `Imported race preset "${preset.name}"`,
    errorFallback: 'Import failed',
    batchSummary: (result) => formatPresetImportSummary(result, 'race preset', presets),
  })

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------
  return (
    <>
      {/* ------------------------------------------------------------------ */}
      {/* Race preset selector                                                 */}
      {/* ------------------------------------------------------------------ */}
      <PresetSelectorCard
        title="Race Presets"
        placeholder="No race presets — create one"
        presets={presets}
        selectedName={selectedName}
        onSelect={select}
        onNew={() => setNewOpen(true)}
        onDelete={() => setDeleteOpen(true)}
        onExport={handleExport}
        canExport={Boolean(active)}
        isImporting={isImporting}
        onImportFile={handleImportFile}
      />

      {/* ------------------------------------------------------------------ */}
      {/* Race schedule grid (bound to active race preset)                     */}
      {/* ------------------------------------------------------------------ */}
      <RaceSchedule />

      {/* ------------------------------------------------------------------ */}
      {/* Dialogs                                                              */}
      {/* ------------------------------------------------------------------ */}
      <NewPresetDialog
        open={newOpen}
        onOpenChange={setNewOpen}
        create={create}
        title="New Race Preset"
        label="Race preset name"
        inputId="new-race-preset-name"
        placeholder="e.g. G1 focus"
        errorFallback="Failed to save new race preset."
      />
      <DeletePresetDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        name={selectedName}
        remove={remove}
        title="Delete Race Preset?"
        noun="race preset"
        errorFallback="Failed to delete race preset."
      />
    </>
  )
}
