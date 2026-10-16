import type { JsonImportBatchResult } from '@/hooks/useJsonImport'
import { normalizePresetName } from '@/stores/presetRules'

const MAX_NAMED_DETAILS = 5

/**
 * Make an imported name match the backend's serialized preset filename.
 * The backend falls back to "preset" when normalization removes every character.
 */
function presetStorageName(name: string): string {
  return normalizePresetName(name) || 'preset'
}

function formatDetails(details: string[], remainingLabel: string): string {
  const shown = details.slice(0, MAX_NAMED_DETAILS)
  const remaining = details.length - shown.length
  if (remaining === 0) return shown.join('; ')
  return `${shown.join('; ')}; and ${remaining} more ${remainingLabel}${remaining === 1 ? '' : 's'}`
}

function formatFailure(fileName: string, reason: string): string {
  // The summary supplies sentence punctuation, so imported error strings do not double it.
  return `${fileName} (${reason.replace(/[.?!]+$/, '')})`
}

function collisionDetails<T extends { name: string }>(
  result: JsonImportBatchResult<T>,
  existingPresets: { name: string }[],
): string[] {
  const occupied = new Map<string, string>()
  for (const preset of existingPresets) {
    occupied.set(presetStorageName(preset.name), preset.name)
  }

  const importedKeys = new Set<string>()
  const collisions: string[] = []
  for (const { value } of result.successes) {
    const storageName = presetStorageName(value.name)
    const previousName = occupied.get(storageName)
    if (previousName) {
      const target = importedKeys.has(storageName)
        ? `the earlier import "${previousName}"`
        : `the existing preset "${previousName}"`
      collisions.push(`"${value.name}" overwrites ${target}`)
    }
    occupied.set(storageName, value.name)
    importedKeys.add(storageName)
  }
  return collisions
}

/** Format the preset-specific aggregate toast for a multi-file import. */
export function formatPresetImportSummary<T extends { name: string }>(
  result: JsonImportBatchResult<T>,
  itemLabel: string,
  existingPresets: { name: string }[],
): string {
  const pluralLabel = result.files.length === 1 ? itemLabel : `${itemLabel}s`
  const { successes, failures } = result
  const prefix = failures.length === 0
    ? `Imported ${successes.length} ${pluralLabel}.`
    : `Imported ${successes.length} of ${result.files.length} ${pluralLabel}.`
  const parts = [prefix]

  if (failures.length > 0) {
    const details = failures.map(({ file, reason }) => formatFailure(file.name, reason))
    parts.push(`Failed: ${formatDetails(details, 'failed file')}.`)
  }

  const collisions = collisionDetails(result, existingPresets)
  if (collisions.length > 0) {
    parts.push(`Name collisions: ${formatDetails(collisions, 'name collision')}.`)
  }

  return parts.join(' ')
}
