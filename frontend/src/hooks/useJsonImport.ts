/**
 * useJsonImport — the shared "import a JSON file" handler.
 *
 * PresetPanel, RacePresetPanel and BotConfiguration each had their own
 * `handleImportFile` with the identical shape:
 *
 *   pick file → reset the input → read+parse JSON → validate → save →
 *   (optional) refresh → success toast, with every failure surfacing as a toast
 *   and an `isImporting` flag guarding the button.
 *
 * They differed only in the validation predicate and the five strings, which is
 * exactly the options object. Every message stays owned by its call site — the
 * hook never invents text.
 *
 * The input is reset (`value = ''`) BEFORE the no-file early return, matching
 * what BotConfiguration already did. For the preset panels, which reset after
 * that check, this is a no-op: a file input with no selection already has
 * `value === ''`. The `File` handle is captured first, so clearing the input
 * does not invalidate the read.
 */

import { useState } from 'react'
import { toast } from 'sonner'

import { readJsonFile } from '@/components/setup/presetIO'

export interface UseJsonImportOptions<T> {
  /** Type guard run on the parsed JSON. `false` aborts with `invalidMessage`. */
  validate: (raw: unknown) => raw is T
  /** Toast shown when `validate` rejects the file. */
  invalidMessage: string
  /**
   * Persist the validated value. Return a string to abort and toast it as the
   * error (the "server returned !success" branch); return nothing on success.
   * Throwing works too — it lands in the shared catch.
   */
  save: (value: T) => Promise<string | undefined | void>
  /**
   * Runs after a successful save, before the success toast (e.g. reload + select).
   * Batch imports invoke it once with the last successfully saved value.
   */
  onDone?: (value: T) => Promise<void> | void
  /** Toast shown once `onDone` has finished. */
  successMessage: (value: T) => string
  /** Toast used when a thrown error carries no message of its own. */
  errorFallback: string
  /**
   * Builds the one aggregate toast shown when the file input supplies a batch.
   * Single-file imports never use this callback, preserving their existing UI.
   */
  batchSummary?: (result: JsonImportBatchResult<T>) => string
}

export interface JsonImportBatchSuccess<T> {
  file: File
  value: T
}

export interface JsonImportBatchFailure {
  file: File
  reason: string
}

export interface JsonImportBatchResult<T> {
  files: File[]
  successes: JsonImportBatchSuccess<T>[]
  failures: JsonImportBatchFailure[]
}

export interface JsonImport {
  /** True while a file is being read/saved — drives the button's disabled state. */
  isImporting: boolean
  /** Bind to the hidden `<input type="file">`'s onChange. */
  handleImportFile: (e: React.ChangeEvent<HTMLInputElement>) => Promise<void>
}

export function useJsonImport<T>(options: UseJsonImportOptions<T>): JsonImport {
  const [isImporting, setIsImporting] = useState(false)

  async function handleImportFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    const files = e.target.files ? Array.from(e.target.files) : []
    // Reset the input so the same file can be re-imported
    e.target.value = ''
    if (!file) return

    // Keep this path byte-for-byte equivalent in behavior to the original
    // single-file import, including its toast and onDone timing.
    if (files.length === 1) {
      setIsImporting(true)
      try {
        const raw = await readJsonFile(file)
        if (!options.validate(raw)) {
          toast.error(options.invalidMessage)
          return
        }
        const rejected = await options.save(raw)
        if (typeof rejected === 'string') {
          toast.error(rejected)
          return
        }
        await options.onDone?.(raw)
        toast.success(options.successMessage(raw))
      } catch (err) {
        const msg = err instanceof Error ? err.message : options.errorFallback
        toast.error(msg)
      } finally {
        setIsImporting(false)
      }
      return
    }

    setIsImporting(true)
    try {
      const successes: JsonImportBatchSuccess<T>[] = []
      const failures: JsonImportBatchFailure[] = []
      // Filename order makes sequential writes and the final selection stable.
      const sortedFiles = [...files].sort((a, b) => a.name.localeCompare(b.name))

      for (const batchFile of sortedFiles) {
        try {
          const raw = await readJsonFile(batchFile)
          if (!options.validate(raw)) {
            failures.push({ file: batchFile, reason: options.invalidMessage })
            continue
          }
          const rejected = await options.save(raw)
          if (typeof rejected === 'string') {
            failures.push({ file: batchFile, reason: rejected })
            continue
          }
          successes.push({ file: batchFile, value: raw })
        } catch (err) {
          failures.push({
            file: batchFile,
            reason: err instanceof Error ? err.message : options.errorFallback,
          })
        }
      }

      const lastSuccess = successes[successes.length - 1]
      if (lastSuccess) {
        await options.onDone?.(lastSuccess.value)
      }

      const result: JsonImportBatchResult<T> = {
        files: sortedFiles,
        successes,
        failures,
      }
      const summary = options.batchSummary?.(result) ?? defaultBatchSummary(result)
      if (failures.length === 0) {
        toast.success(summary)
      } else {
        toast.error(summary)
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : options.errorFallback
      toast.error(msg)
    } finally {
      setIsImporting(false)
    }
  }

  return { isImporting, handleImportFile }
}

function defaultBatchSummary<T>(result: JsonImportBatchResult<T>): string {
  const { files, successes, failures } = result
  if (failures.length === 0) {
    return `Imported ${successes.length} files.`
  }

  const details = failures
    .map(({ file, reason }) => `${file.name} (${reason})`)
    .join('; ')
  return `Imported ${successes.length} of ${files.length} files. Failed: ${details}`
}
