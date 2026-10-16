/**
 * createPresetSlice — the shared engine behind BOTH preset stores.
 *
 * `stores/presets.ts` (skill presets) and `stores/racePresets.ts` (race presets)
 * were ~85% identical: the same selectedKey/writeSelected pair and the same
 * load / select / create / remove / update / getActive contracts, in the same
 * order. They differ ONLY in four things, which are exactly the config fields:
 *
 *   * the API module they call            → list / save / remove
 *   * the localStorage BASE key           → storageKey
 *   * the template POSTed for a new item  → newPreset
 *   * the four user-visible messages      → errors
 *
 * Everything else is shared here verbatim, including the ordering of the
 * localStorage write relative to `set()`, and the reload-after-mutate sequence.
 *
 * localStorage — the base key is passed through `accountKey()` AT CALL TIME
 * (never captured at module load), so a mid-session account switch resolves to
 * the new account's key exactly as it did before. The base strings are preserved
 * from the legacy UI (`uma_selected_preset` / `uma_selected_race_preset`) so a
 * pre-React selection still loads.
 *
 * Action identity — the slice object is built exactly once, inside the single
 * `create()` initialiser at each call site, so every action keeps a stable
 * function reference for the life of the store. Components pass these actions
 * as props (DeletePresetDialog.remove, NewPresetDialog.create) and rely on that.
 */

import { accountKey } from '@/lib/accountKey'
import { normalizePresetName, presetNameExists } from './presetRules'

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

/** Minimum shape a preset must have to be managed by this slice. */
export interface NamedPreset {
  name: string
}

/** Response shape of the list endpoint (both stores' GETs satisfy this). */
export interface PresetListResponse<T> {
  success: boolean
  presets?: T[]
}

/** Response shape of the save endpoint. */
export interface PresetSaveResponse<T> {
  success: boolean
  preset?: T
  detail?: string
}

/** Response shape of the delete endpoint. */
export interface PresetDeleteResponse {
  success: boolean
  detail?: string
}

/**
 * The user-visible strings. They are per-store because they name the thing
 * being edited ("preset" vs "race preset") and surface directly in toasts.
 */
export interface PresetErrorMessages {
  /** create() with a blank / whitespace-only name. */
  emptyName: string
  /** create() with a name that already exists (case-insensitive). */
  duplicateName: string
  /** create() when the POST throws, or the server returns !success with no detail. */
  saveFailed: string
  /** remove() when the DELETE throws, or the server returns !success with no detail. */
  deleteFailed: string
}

export interface PresetStoreConfig<T extends NamedPreset> {
  /**
   * localStorage BASE key — the exact legacy string. Scoped per account by
   * `accountKey()` on every read and write.
   */
  storageKey: string
  list: () => Promise<PresetListResponse<T>>
  save: (body: { preset: T }) => Promise<PresetSaveResponse<T>>
  remove: (body: { name: string }) => Promise<PresetDeleteResponse>
  /** The object POSTed by create() for a brand-new preset. */
  newPreset: (name: string) => T
  errors: PresetErrorMessages
}

// ---------------------------------------------------------------------------
// Slice types
// ---------------------------------------------------------------------------

export interface PresetSliceState<T> {
  presets: T[]
  selectedName: string
}

export interface PresetSliceActions<T> {
  /** GET list; resolve selected; write localStorage. Never throws. */
  load: () => Promise<void>
  /** Set selectedName + write localStorage. */
  select: (name: string) => void
  /** normalise → validate → POST → reload; throws on error. */
  create: (name: string) => Promise<void>
  /** DELETE → reload; throws on error. */
  remove: (name: string) => Promise<void>
  /** POST a full preset (replace by name); optimistic, reloads on failure. */
  update: (preset: T) => Promise<void>
  /** Selector → the currently selected preset, or undefined. */
  getActive: () => T | undefined
}

export type PresetSlice<T> = PresetSliceState<T> & PresetSliceActions<T>

/** zustand's `set`, narrowed to what this slice actually writes. */
export type PresetSliceSet<T> = (
  partial:
    | Partial<PresetSliceState<T>>
    | ((state: PresetSliceState<T>) => Partial<PresetSliceState<T>>),
) => void

/** zustand's `get`, narrowed to what this slice actually reads. */
export type PresetSliceGet<T> = () => PresetSlice<T>

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

/**
 * Build the shared preset slice for `config`. Returns a zustand initialiser
 * `(set, get) => slice`, so a store that needs extra actions (racePresets'
 * `saveRaces`) can spread the slice and add them in the SAME `create()` call —
 * which is what keeps every action's identity stable.
 */
export function createPresetSlice<T extends NamedPreset>(config: PresetStoreConfig<T>) {
  // -------------------------------------------------------------------------
  // localStorage key — resolved per call so an account switch is picked up.
  // -------------------------------------------------------------------------
  function selectedKey(): string {
    return accountKey(config.storageKey)
  }

  function writeSelected(name: string): void {
    try {
      if (name) {
        localStorage.setItem(selectedKey(), name)
      } else {
        localStorage.removeItem(selectedKey())
      }
    } catch { /* QuotaExceededError etc. — ignore */ }
  }

  return (set: PresetSliceSet<T>, get: PresetSliceGet<T>): PresetSlice<T> => ({
    presets: [],
    selectedName: '',

    // -----------------------------------------------------------------------
    // load — app.js:1939-1971
    // -----------------------------------------------------------------------
    async load() {
      try {
        const res = await config.list()
        if (res.success && res.presets && res.presets.length > 0) {
          const list = res.presets
          const saved = localStorage.getItem(selectedKey())
          const chosen =
            saved && list.some((p) => p.name === saved)
              ? saved
              : list[0].name
          writeSelected(chosen)
          set({ presets: list, selectedName: chosen })
        } else {
          // No presets on server
          writeSelected('')
          set({ presets: [], selectedName: '' })
        }
      } catch {
        writeSelected('')
        set({ presets: [], selectedName: '' })
      }
    },

    // -----------------------------------------------------------------------
    // select — app.js:1749-1755
    // -----------------------------------------------------------------------
    select(name) {
      writeSelected(name)
      set({ selectedName: name })
    },

    // -----------------------------------------------------------------------
    // create — app.js:1880-1916
    // Throws a string error message for the UI to toast.
    // -----------------------------------------------------------------------
    async create(name) {
      const normalized = normalizePresetName(name)
      if (!normalized) throw new Error(config.errors.emptyName)

      const { presets } = get()
      if (presetNameExists(normalized, presets)) {
        throw new Error(config.errors.duplicateName)
      }

      const template = config.newPreset(normalized)
      let res: PresetSaveResponse<T>
      try {
        res = await config.save({ preset: template })
      } catch {
        throw new Error(config.errors.saveFailed)
      }

      if (!res.success || !res.preset?.name) {
        throw new Error(res.detail ?? config.errors.saveFailed)
      }

      const savedName = res.preset.name
      writeSelected(savedName)
      set({ selectedName: savedName })
      // Reload to get the full server list
      await get().load()
    },

    // -----------------------------------------------------------------------
    // remove — app.js:1919-1936
    // Throws a string error message for the UI to toast.
    // -----------------------------------------------------------------------
    async remove(name) {
      let res: PresetDeleteResponse
      try {
        res = await config.remove({ name })
      } catch {
        throw new Error(config.errors.deleteFailed)
      }
      if (!res.success) {
        throw new Error(res.detail ?? config.errors.deleteFailed)
      }
      await get().load()
    },

    // -----------------------------------------------------------------------
    // update — app.js:1719-1733 (savePresetConfig)
    // Accepts a full preset and replaces by name. Optimistic + reload.
    // -----------------------------------------------------------------------
    async update(preset) {
      // Optimistic update so UI reflects change immediately
      set((s) => ({
        presets: s.presets.map((p) => (p.name === preset.name ? preset : p)),
      }))
      try {
        await config.save({ preset })
      } catch {
        // On failure reload from server to re-sync
        await get().load()
      }
    },

    // -----------------------------------------------------------------------
    // getActive — selector
    // -----------------------------------------------------------------------
    getActive() {
      const { presets, selectedName } = get()
      return presets.find((p) => p.name === selectedName)
    },
  })
}
