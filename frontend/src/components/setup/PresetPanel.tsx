/**
 * PresetPanel — Skill preset selector + CRUD + config fields.
 *
 * Reads/writes via the `usePresets` Zustand store which is the single
 * source of truth for skill presets and writes localStorage `uma_selected_preset`
 * on every select/create.
 *
 * Scenario is deliberately NOT edited here. Presets still round-trip a
 * `scenario_id` server-side (career_bot.planning.presets persists it, and that
 * is what stops a read-mutate-write from silently downgrading a non-MANT preset
 * to MANT), but the scenario a run actually uses is chosen per-run in RunBar
 * and sent in the career body — so a second, stickier control here was just a
 * way to disagree with it.
 */

import { useEffect, useState } from 'react'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

import { usePresets } from '@/stores/presets'
import { savePreset } from '@/api/presets'
import type { Preset } from '@/api/types'
import { useJsonImport } from '@/hooks/useJsonImport'
import { NewPresetDialog } from './NewPresetDialog'
import { DeletePresetDialog } from './DeletePresetDialog'
import { PresetSelectorCard } from './PresetSelectorCard'
import { SkillEditorDialog } from './SkillEditorDialog'
import { downloadJson, slugify } from './presetIO'
import { formatPresetImportSummary } from './presetImportSummary'

// ---------------------------------------------------------------------------
// Running style options
// ---------------------------------------------------------------------------
const RUNNING_STYLES = [
  { value: '1', label: 'Front Runner' },
  { value: '2', label: 'Pace Chaser' },
  { value: '3', label: 'Late Surger' },
  { value: '4', label: 'End Closer' },
] as const

// ---------------------------------------------------------------------------
// PresetPanel
// ---------------------------------------------------------------------------

export function PresetPanel() {
  const { presets, selectedName, select, create, update, remove, getActive, load } = usePresets()

  const [newOpen, setNewOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [skillEditorOpen, setSkillEditorOpen] = useState(false)

  const [threshold, setThreshold] = useState<string>('')

  useEffect(() => {
    load()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const active = getActive()

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setThreshold(String(active?.learn_skill_threshold ?? 888))
  }, [active?.name, active?.learn_skill_threshold])

  // -------------------------------------------------------------------------
  // Persist helpers
  // -------------------------------------------------------------------------
  function persistRunningStyle(val: string) {
    if (!active) return
    const rs = parseInt(val, 10) || 1
    update({ ...active, running_style: rs })
  }

  function persistThreshold() {
    if (!active) return
    const t = parseInt(threshold, 10) || 888
    setThreshold(String(t))
    update({ ...active, learn_skill_threshold: t })
  }

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
  const { isImporting, handleImportFile } = useJsonImport<Preset>({
    // Minimal validation: must have a name string
    validate: (raw): raw is Preset =>
      typeof raw === 'object' &&
      raw !== null &&
      typeof (raw as Record<string, unknown>).name === 'string' &&
      Boolean((raw as Record<string, unknown>).name),
    invalidMessage: 'Import failed: JSON must have a "name" string field.',
    save: async (preset) => {
      const res = await savePreset({ preset })
      if (!res.success) {
        return res.detail ?? 'Import failed: server rejected the preset.'
      }
    },
    onDone: async (preset) => {
      await load()
      select(preset.name)
    },
    successMessage: (preset) => `Imported skill preset "${preset.name}"`,
    errorFallback: 'Import failed',
    batchSummary: (result) => formatPresetImportSummary(result, 'skill preset', presets),
  })

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------
  return (
    <>
      {/* ------------------------------------------------------------------ */}
      {/* Skill preset selector                                                */}
      {/* ------------------------------------------------------------------ */}
      <PresetSelectorCard
        title="Skill Presets"
        placeholder="No presets — create one"
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
      {/* Skill preset config fields                                           */}
      {/* ------------------------------------------------------------------ */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Preset Config</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {/* Running Style */}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="running-style">Running Style</Label>
            <Select
              value={String(active?.running_style ?? 1)}
              onValueChange={persistRunningStyle}
              disabled={!active}
            >
              <SelectTrigger id="running-style">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {RUNNING_STYLES.map((rs) => (
                  <SelectItem key={rs.value} value={rs.value}>
                    {rs.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Min Skill PT */}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="skill-threshold">Min Skill PT</Label>
            <Input
              id="skill-threshold"
              type="number"
              min={0}
              value={threshold}
              onChange={(e) => setThreshold(e.target.value)}
              onBlur={persistThreshold}
              disabled={!active}
              placeholder="888"
            />
          </div>

          {/* CONFIGURE SKILLS */}
          <div className="flex flex-col gap-1.5 sm:col-span-2">
            <Button
              variant="outline"
              disabled={!active}
              className="w-full sm:w-auto"
              onClick={() => setSkillEditorOpen(true)}
            >
              CONFIGURE SKILLS
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* ------------------------------------------------------------------ */}
      {/* Dialogs                                                              */}
      {/* ------------------------------------------------------------------ */}
      <NewPresetDialog
        open={newOpen}
        onOpenChange={setNewOpen}
        create={create}
        title="New Skill Preset"
        label="Preset name"
        inputId="new-preset-name"
        placeholder="e.g. Speed build"
        errorFallback="Failed to save new preset."
      />
      <DeletePresetDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        name={selectedName}
        remove={remove}
        title="Delete Skill Preset?"
        noun="preset"
        errorFallback="Failed to delete preset."
      />
      <SkillEditorDialog open={skillEditorOpen} onOpenChange={setSkillEditorOpen} />
    </>
  )
}
