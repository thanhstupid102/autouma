import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'

import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { getAutoDeleteConfig, setAutoDeleteConfig } from '@/api/career'
import type { AutoDeleteConfig } from '@/api/types'
import { SparkFilterBar } from './SparkFilterBar'
import {
  BLUE_STATS,
  EMPTY_SPARK_FILTER,
  PINK_APTITUDES,
  type SparkColour,
  type SparkColourOptions,
  type SparkFilter,
} from './sparkFilter'

interface AutoDeleteSettingsPanelProps {
  options: SparkColourOptions
}

/** Best-effort colour for a legacy saved condition that has no stored colour. */
function inferColour(name: string): SparkColour {
  if ((BLUE_STATS as readonly string[]).includes(name)) return 'blue'
  if ((PINK_APTITUDES as readonly string[]).includes(name)) return 'pink'
  return 'white'
}

type StatusKind = 'idle' | 'ok' | 'warn'

interface InlineStatus {
  text: string
  kind: StatusKind
}

const EMPTY_AUTO_DELETE_CONFIG: AutoDeleteConfig = {
  enabled: false,
  min_blue: 0,
  min_pink: 0,
  min_white: 0,
  min_green: 0,
  conditions: [],
}

const AUTO_DELETE_HIDDEN_FACTOR_COLOURS: SparkColour[] = ['green']

function isAutoDeleteFactorColourVisible(colour: SparkColour): boolean {
  return !AUTO_DELETE_HIDDEN_FACTOR_COLOURS.includes(colour)
}

function autoDeleteConfigToSparkFilter(config: AutoDeleteConfig): SparkFilter {
  return {
    minBlue: config.min_blue,
    minPink: config.min_pink,
    minWhite: config.min_white,
    minGreen: config.min_green,
    conditions: config.conditions.flatMap((condition) => {
      const colour = condition.colour ?? inferColour(condition.name)
      if (!isAutoDeleteFactorColourVisible(colour)) return []
      return [{
        colour,
        name: condition.name,
        mode: condition.mode,
        minStars: condition.min_stars,
      }]
    }),
  }
}

function sparkFilterToAutoDeleteConfig(filter: SparkFilter, enabled: boolean): AutoDeleteConfig {
  return {
    enabled,
    min_blue: filter.minBlue,
    min_pink: filter.minPink,
    min_white: filter.minWhite,
    min_green: filter.minGreen,
    conditions: filter.conditions
      .filter((condition) => isAutoDeleteFactorColourVisible(condition.colour))
      .map((condition) => ({
        name: condition.name,
        mode: condition.mode,
        min_stars: condition.minStars,
        colour: condition.colour,
      })),
  }
}

// Self-only: a single self factor maxes at 3 stars, so blue/pink/green totals
// (one factor each) cap at 3. White can have several skills, so leave it open.
function clampSelfTotal(value: unknown): number {
  return Math.max(0, Math.min(3, Number(value) || 0))
}

function normalizeMode(mode: unknown): 'include' | 'atleast' | 'exclude' {
  return mode === 'exclude' ? 'exclude' : 'atleast'
}

function normalizeAutoDeleteConfig(config?: Partial<AutoDeleteConfig>): AutoDeleteConfig {
  return {
    enabled: !!config?.enabled,
    min_blue: clampSelfTotal(config?.min_blue),
    min_pink: clampSelfTotal(config?.min_pink),
    min_white: Number(config?.min_white) || 0,
    min_green: clampSelfTotal(config?.min_green),
    conditions: (config?.conditions ?? []).flatMap((condition) => {
      const name = String(condition.name ?? '')
      const colour = condition.colour ?? inferColour(name)
      if (!isAutoDeleteFactorColourVisible(colour)) return []
      return [{
        name,
        mode: normalizeMode(condition.mode),
        min_stars: Math.max(1, Math.min(3, Number(condition.min_stars) || 1)),
        colour,
      }]
    }),
  }
}

function StatusLine({ status }: { status: InlineStatus | null }) {
  if (!status?.text) return null
  const className =
    status.kind === 'ok'
      ? 'text-xs text-green-600 dark:text-green-400'
      : status.kind === 'warn'
        ? 'text-xs text-amber-600 dark:text-amber-400'
        : 'text-xs text-muted-foreground'
  return <p className={className}>{status.text}</p>
}

export function AutoDeleteSettingsPanel({ options }: AutoDeleteSettingsPanelProps) {
  const [config, setConfig] = useState<AutoDeleteConfig>(EMPTY_AUTO_DELETE_CONFIG)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [status, setStatus] = useState<InlineStatus | null>({ text: 'Loading...', kind: 'idle' })
  const mountedRef = useRef(true)
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    mountedRef.current = true
    getAutoDeleteConfig()
      .then((response) => {
        if (!mountedRef.current) return
        if (!response.success) throw new Error(response.detail ?? 'Unable to load auto-delete settings')
        setConfig(normalizeAutoDeleteConfig(response.config))
        setStatus({ text: 'Loaded', kind: 'idle' })
      })
      .catch((error) => {
        if (!mountedRef.current) return
        const message = error instanceof Error ? error.message : 'Unable to load auto-delete settings'
        setStatus({ text: message, kind: 'warn' })
      })
      .finally(() => {
        if (mountedRef.current) setLoading(false)
      })

    return () => {
      mountedRef.current = false
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
    }
  }, [])

  async function persist(next: AutoDeleteConfig) {
    setSaving(true)
    setStatus({ text: 'Saving...', kind: 'idle' })
    try {
      const response = await setAutoDeleteConfig(next)
      if (!mountedRef.current) return
      if (!response.success) throw new Error(response.detail ?? 'Unable to save auto-delete settings')
      setConfig(normalizeAutoDeleteConfig(response.config))
      setStatus({ text: 'Saved', kind: 'ok' })
    } catch (error) {
      if (!mountedRef.current) return
      const message = error instanceof Error ? error.message : 'Unable to save auto-delete settings'
      setStatus({ text: message, kind: 'warn' })
      toast.error(message)
    } finally {
      if (mountedRef.current) setSaving(false)
    }
  }

  function queueSave(next: AutoDeleteConfig) {
    setConfig(next)
    setStatus({ text: 'Unsaved changes', kind: 'idle' })
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
    saveTimerRef.current = setTimeout(() => {
      void persist(next)
    }, 450)
  }

  function handleEnabledChange(enabled: boolean) {
    queueSave({ ...config, enabled })
  }

  function handleFilterChange(filter: SparkFilter) {
    queueSave(sparkFilterToAutoDeleteConfig(filter, config.enabled))
  }

  const filter = loading ? EMPTY_SPARK_FILTER : autoDeleteConfigToSparkFilter(config)

  return (
    <div data-testid="auto-delete-settings" className="flex flex-col gap-3 rounded-md border border-border bg-card p-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Switch
            id="auto-delete-enabled"
            data-testid="auto-delete-enabled"
            checked={config.enabled}
            disabled={loading}
            onCheckedChange={handleEnabledChange}
          />
          <Label htmlFor="auto-delete-enabled" className="cursor-pointer text-sm font-medium">
            Auto-delete just-finished veterans
          </Label>
        </div>
        <StatusLine status={saving ? { text: 'Saving...', kind: 'idle' } : status} />
      </div>

      {/* Note: explain exactly what auto-delete does and its safety boundary. */}
      <p className="rounded-md border border-amber-500/30 bg-amber-500/10 px-2.5 py-2 text-[11px] leading-relaxed text-muted-foreground">
        <span className="font-medium text-amber-500">Note:</span> after each career, this
        checks the <span className="font-medium text-foreground">just-finished</span> uma's
        own sparks (self only — its parents&apos; sparks are ignored). If they do{' '}
        <span className="font-medium text-foreground">not</span> meet the filter below, that
        uma is deleted automatically. Only the veteran you just trained is ever deleted —
        your other veterans are never touched. Leave the filter empty to keep everything.
      </p>

      <SparkFilterBar
        value={filter}
        onChange={handleFilterChange}
        options={options}
        maxStars={3}
        totalMaxByColour={{ blue: 3, pink: 3, green: 3 }}
        hideFactorColours={AUTO_DELETE_HIDDEN_FACTOR_COLOURS}
        scopeLabel="self"
        disabled={loading}
      />
    </div>
  )
}
