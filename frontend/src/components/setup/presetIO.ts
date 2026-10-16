/**
 * presetIO — client-side export/import helpers for skill and race presets.
 *
 * downloadJson — serialises an object to JSON and triggers a browser download.
 * readJsonFile — reads a File object and parses it as JSON.
 *
 * Both are pure (no store/DOM side-effects except the anchor click for download)
 * so they are easy to unit test.
 */

// ---------------------------------------------------------------------------
// downloadJson
// ---------------------------------------------------------------------------

/**
 * Trigger a browser download of `obj` as a JSON file.
 * @param filename  e.g. "my-preset.json"
 * @param obj       Any JSON-serialisable value.
 */
export function downloadJson(filename: string, obj: unknown): void {
  const json = JSON.stringify(obj, null, 2)
  const blob = new Blob([json], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

// ---------------------------------------------------------------------------
// readJsonFile
// ---------------------------------------------------------------------------

/**
 * Read a File and resolve with the parsed JSON value.
 * Rejects if the file cannot be read or if JSON.parse throws.
 */
export function readJsonFile(file: File): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = (e) => {
      const text = e.target?.result
      if (typeof text !== 'string') {
        reject(new Error('Failed to read file'))
        return
      }
      try {
        resolve(JSON.parse(text))
      } catch {
        reject(new Error('Invalid JSON in file'))
      }
    }
    reader.onerror = () => reject(new Error('Failed to read file'))
    reader.readAsText(file)
  })
}

// ---------------------------------------------------------------------------
// slugify — build a safe filename from a preset name
// ---------------------------------------------------------------------------

/**
 * Convert a preset name to a safe filename slug.
 * e.g. "Speed Build v1.0" → "speed-build-v1.0"
 */
export function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/\s+/g, '-')
    .replace(/[^a-z0-9._-]/g, '')
}
