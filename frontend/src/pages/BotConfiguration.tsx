import { useEffect, useMemo, useRef, useState } from 'react'
import { ChevronDown, Download, RotateCcw, Save, Upload } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { TouchControlRow } from '@/components/ui/touch-control-row'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { downloadJson, slugify } from '@/components/setup/presetIO'
import { useJsonImport } from '@/hooks/useJsonImport'
import { cn } from '@/lib/utils'
import type {
  BotConfigDocument,
  BotConfigFieldSpec,
  BotConfigJsonValue,
  BotConfigScenarioValues,
} from '@/api/types'
import { botConfigValueAt, useBotConfig } from '@/stores/botConfig'

function isPlainObject(value: unknown): value is Record<string, BotConfigJsonValue> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function cloneJson(value: BotConfigJsonValue): BotConfigJsonValue {
  return JSON.parse(JSON.stringify(value)) as BotConfigJsonValue
}

function jsonText(value: BotConfigJsonValue | undefined): string {
  return JSON.stringify(value ?? null, null, 2)
}

function defaultValueLabel(value: BotConfigJsonValue | undefined): string {
  if (Array.isArray(value) || isPlainObject(value)) return JSON.stringify(value)
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  return String(value ?? '')
}

function isBotConfigDocument(value: unknown): value is BotConfigDocument {
  return isPlainObject(value) && typeof value.version === 'number' && isPlainObject(value.scenarios)
}

interface ComplexJsonEditorProps {
  spec: BotConfigFieldSpec
  value: BotConfigJsonValue | undefined
  defaultValue: BotConfigJsonValue
  disabled?: boolean
  onChange: (value: BotConfigJsonValue) => void
}

function ComplexJsonEditor({ spec, value, defaultValue, disabled, onChange }: ComplexJsonEditorProps) {
  const [text, setText] = useState(() => jsonText(value ?? defaultValue))
  const [error, setError] = useState('')

  useEffect(() => {
    setText(jsonText(value ?? defaultValue))
    setError('')
  }, [spec.key, value, defaultValue])

  function applyJson() {
    try {
      const parsed = JSON.parse(text) as BotConfigJsonValue
      if (spec.kind === 'array' && !Array.isArray(parsed)) {
        throw new Error('Expected a JSON array')
      }
      if (spec.kind === 'object' && !isPlainObject(parsed)) {
        throw new Error('Expected a JSON object')
      }
      setError('')
      onChange(parsed)
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Invalid JSON')
    }
  }

  return (
    <div className="space-y-1">
      <textarea
        id={`bot-config-field-${spec.key.replace(/[^a-zA-Z0-9_-]/g, '-')}`}
        aria-label={spec.label}
        className="min-h-20 w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-base outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40 disabled:cursor-not-allowed disabled:opacity-50 md:text-xs"
        value={text}
        disabled={disabled}
        onChange={(event) => setText(event.target.value)}
        onBlur={applyJson}
      />
      {error ? <p className="text-xs text-destructive">{error}</p> : null}
    </div>
  )
}

interface FieldEditorProps {
  spec: BotConfigFieldSpec
  value: BotConfigJsonValue | undefined
  defaultValue: BotConfigJsonValue
  disabled?: boolean
  onChange: (value: BotConfigJsonValue) => void
}

function FieldEditor({ spec, value, defaultValue, disabled, onChange }: FieldEditorProps) {
  const effectiveValue = value ?? defaultValue

  if (spec.kind === 'boolean') {
    return (
      <TouchControlRow
        label={<span className="md:sr-only">{spec.label}</span>}
        disabled={disabled}
        disabledReason={disabled ? 'Saving is in progress.' : undefined}
        className="border bg-muted/30 md:inline-flex md:min-h-0 md:w-auto md:gap-0 md:border-0 md:bg-transparent md:p-0"
        control={(
          <input
            id={`bot-config-field-${spec.key.replace(/[^a-zA-Z0-9_-]/g, '-')}`}
            aria-label={spec.label}
            type="checkbox"
            className="size-5 accent-primary md:size-4"
            checked={Boolean(effectiveValue)}
            disabled={disabled}
            onChange={(event) => onChange(event.target.checked)}
          />
        )}
      />
    )
  }

  if (spec.kind === 'number') {
    const numberValue = typeof effectiveValue === 'number' ? effectiveValue : Number(effectiveValue || 0)
    return (
      <Input
        id={`bot-config-field-${spec.key.replace(/[^a-zA-Z0-9_-]/g, '-')}`}
        aria-label={spec.label}
        type="number"
        step="any"
        value={Number.isFinite(numberValue) ? String(numberValue) : ''}
        disabled={disabled}
        onChange={(event) => {
          const raw = event.target.value
          if (raw === '') return
          const parsed = Number(raw)
          if (!Number.isFinite(parsed)) return
          onChange(parsed)
        }}
      />
    )
  }

  if (spec.kind === 'string') {
    return (
      <Input
        id={`bot-config-field-${spec.key.replace(/[^a-zA-Z0-9_-]/g, '-')}`}
        aria-label={spec.label}
        value={typeof effectiveValue === 'string' ? effectiveValue : String(effectiveValue ?? '')}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      />
    )
  }

  return (
    <ComplexJsonEditor
      spec={spec}
      value={value}
      defaultValue={defaultValue}
      disabled={disabled}
      onChange={onChange}
    />
  )
}

interface FieldRowProps {
  spec: BotConfigFieldSpec
  values: BotConfigScenarioValues
  defaultValues: BotConfigScenarioValues
  saving: boolean
  onChange: (path: string, value: BotConfigJsonValue) => void
}

function FieldRow({ spec, values, defaultValues, saving, onChange }: FieldRowProps) {
  const value = botConfigValueAt(values, spec.key)
  const defaultValue = botConfigValueAt(defaultValues, spec.key) ?? spec.default
  const fieldId = `bot-config-field-${spec.key.replace(/[^a-zA-Z0-9_-]/g, '-')}`
  return (
    <div
      data-slot="bot-config-field-row"
      className="grid gap-3 border-t py-4 first:border-t-0 md:grid-cols-[minmax(0,1fr)_minmax(220px,320px)]"
    >
      <div className="space-y-1">
        <Label
          htmlFor={fieldId}
          className={cn('text-sm font-medium', spec.kind === 'boolean' && 'hidden md:block')}
        >
          {spec.label}
        </Label>
        <p className="break-all font-mono text-xs text-muted-foreground md:break-normal">{spec.key}</p>
        {spec.description ? (
          <p className="text-xs text-muted-foreground md:line-clamp-3">{spec.description}</p>
        ) : null}
        <p className="break-all text-xs text-muted-foreground md:line-clamp-2 md:break-normal">
          Default: <code>{defaultValueLabel(defaultValue)}</code>
        </p>
      </div>
      <div className="flex flex-col items-stretch gap-2 md:flex-row md:items-start">
        <div className="min-w-0 flex-1">
          <FieldEditor
            spec={spec}
            value={value}
            defaultValue={defaultValue}
            disabled={saving}
            onChange={(next) => onChange(spec.key, next)}
          />
        </div>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="w-full md:w-auto"
          disabled={saving}
          onClick={() => onChange(spec.key, cloneJson(defaultValue))}
        >
          Default
        </Button>
      </div>
    </div>
  )
}

export default function BotConfiguration() {
  const {
    config,
    defaultConfig,
    scenarios,
    fields,
    selectedScenarioId,
    loading,
    saving,
    error,
    load,
    save,
    reset,
    selectScenario,
    updateField,
    isDirty,
  } = useBotConfig()

  const importInputRef = useRef<HTMLInputElement>(null)
  const selectedScenario = scenarios.find((scenario) => String(scenario.scenario_id) === selectedScenarioId)
  // Memoised so the `?? []` fallback does not hand `groupedFields` a fresh array
  // identity on every render (react-hooks/exhaustive-deps).
  const selectedFields = useMemo(
    () => fields[selectedScenarioId] ?? [],
    [fields, selectedScenarioId],
  )
  const scenarioValues = config?.scenarios?.[selectedScenarioId] ?? {}
  const defaultScenarioValues = defaultConfig?.scenarios?.[selectedScenarioId] ?? {}
  const dirty = isDirty()

  const groupedFields = useMemo(() => {
    return selectedFields.reduce<Record<string, BotConfigFieldSpec[]>>((groups, spec) => {
      const category = spec.category || 'General'
      groups[category] = groups[category] ?? []
      groups[category].push(spec)
      return groups
    }, {})
  }, [selectedFields])
  const categoryNames = useMemo(() => Object.keys(groupedFields), [groupedFields])
  const [openCategory, setOpenCategory] = useState<string | null>(() => categoryNames[0] ?? null)

  useEffect(() => {
    setOpenCategory((current) => (
      current && categoryNames.includes(current) ? current : categoryNames[0] ?? null
    ))
  }, [categoryNames])

  useEffect(() => {
    load().catch((err) => toast.error(err instanceof Error ? err.message : 'Failed to load bot configuration.'))
  }, [load])

  async function handleSave() {
    try {
      await save()
      toast.success('Bot configuration saved.')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to save bot configuration.')
    }
  }

  async function handleReset() {
    try {
      await reset()
      toast.success('Bot configuration reset to defaults.')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to reset bot configuration.')
    }
  }

  function handleExport() {
    if (!config) return
    const suffix = selectedScenario ? slugify(selectedScenario.name) : 'preset'
    downloadJson(`bot-config-${suffix || 'preset'}.json`, config)
  }

  // `isImporting` is intentionally unused here: this page's Import button is
  // gated on the store's own `loading || saving`, exactly as before.
  const { handleImportFile } = useJsonImport<BotConfigDocument>({
    validate: isBotConfigDocument,
    invalidMessage: 'Import failed: JSON must contain version and scenarios fields.',
    save: async (raw) => {
      await save(raw)
    },
    successMessage: () => 'Bot configuration imported and saved.',
    errorFallback: 'Failed to import bot configuration.',
  })

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 md:p-6">
      <div>
        <h1 className="text-2xl font-semibold">Bot Configuration</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Edit the global scoring and train-decision preset used by every account. Changes apply on the next run or resume.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Active global preset</CardTitle>
          <CardDescription>
            Select a scenario to edit its bot parameters. The backend validates imported and saved JSON against the default schema.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
            <div className="space-y-2">
              <Label htmlFor="bot-config-scenario">Scenario</Label>
              <Select value={selectedScenarioId} onValueChange={selectScenario} disabled={loading || saving || !scenarios.length}>
                <SelectTrigger id="bot-config-scenario" className="w-full md:w-[280px]">
                  <SelectValue placeholder="Select scenario" />
                </SelectTrigger>
                <SelectContent>
                  {scenarios.map((scenario) => (
                    <SelectItem key={scenario.scenario_id} value={String(scenario.scenario_id)}>
                      {scenario.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-wrap gap-2">
              <input
                ref={importInputRef}
                type="file"
                accept="application/json,.json"
                className="hidden"
                onChange={handleImportFile}
              />
              <Button type="button" variant="outline" disabled={loading || saving} onClick={() => importInputRef.current?.click()}>
                <Upload className="h-4 w-4" />
                Import JSON
              </Button>
              <Button type="button" variant="outline" disabled={!config || loading} onClick={handleExport}>
                <Download className="h-4 w-4" />
                Export JSON
              </Button>
              <Button type="button" variant="outline" disabled={loading || saving} onClick={handleReset}>
                <RotateCcw className="h-4 w-4" />
                Reset defaults
              </Button>
              <Button type="button" disabled={!config || saving || loading || !dirty} onClick={handleSave}>
                <Save className="h-4 w-4" />
                {saving ? 'Saving…' : 'Save'}
              </Button>
            </div>
          </div>

          {selectedScenario?.description ? (
            <p className="rounded-md bg-muted px-3 py-2 text-sm text-muted-foreground">
              {selectedScenario.description}
            </p>
          ) : null}
          {error ? <p className="text-sm text-destructive">{error}</p> : null}
          {dirty ? <p className="text-xs text-muted-foreground">Unsaved changes are local until you click Save.</p> : null}
        </CardContent>
      </Card>

      {loading ? (
        <Card>
          <CardContent>Loading bot configuration…</CardContent>
        </Card>
      ) : selectedFields.length ? (
        <div
          data-testid="bot-config-sections"
          data-mobile-layout="accordion"
          data-desktop-layout="flat"
          className="space-y-4 md:space-y-6"
        >
          {Object.entries(groupedFields).map(([category, specs], index) => {
            const isOpen = openCategory === category
            const panelId = `bot-config-section-${index}`
            return (
              <Card key={category}>
                <CardHeader>
                  <button
                    type="button"
                    className="-m-2 flex min-h-11 items-center justify-between gap-3 rounded-lg p-2 text-left md:hidden"
                    aria-expanded={isOpen}
                    aria-controls={panelId}
                    onClick={() => setOpenCategory(isOpen ? null : category)}
                  >
                    <span className="min-w-0">
                      <span className="block font-heading text-base font-medium leading-snug">
                        {category}
                      </span>
                      <span className="mt-1 block text-sm text-muted-foreground">
                        {specs.length} configurable parameter{specs.length === 1 ? '' : 's'}.
                      </span>
                    </span>
                    <ChevronDown
                      className={cn('size-5 shrink-0 transition-transform', isOpen && 'rotate-180')}
                      aria-hidden="true"
                    />
                  </button>
                  <div className="hidden space-y-1 md:block">
                    <CardTitle>{category}</CardTitle>
                    <CardDescription>
                      {specs.length} configurable parameter{specs.length === 1 ? '' : 's'}.
                    </CardDescription>
                  </div>
                </CardHeader>
                <CardContent
                  id={panelId}
                  data-slot="bot-config-section-panel"
                  className={cn(isOpen ? 'block' : 'hidden', 'md:block')}
                >
                  {specs.map((spec) => (
                    <FieldRow
                      key={spec.key}
                      spec={spec}
                      values={scenarioValues}
                      defaultValues={defaultScenarioValues}
                      saving={saving}
                      onChange={updateField}
                    />
                  ))}
                </CardContent>
              </Card>
            )
          })}
        </div>
      ) : (
        <Card>
          <CardContent>No bot configuration fields are available for this scenario.</CardContent>
        </Card>
      )}
    </div>
  )
}
