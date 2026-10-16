import { describe, it, expect, vi, afterEach } from 'vitest'
import { downloadJson, readJsonFile, slugify } from './presetIO'

// ---------------------------------------------------------------------------
// downloadJson
// ---------------------------------------------------------------------------

describe('downloadJson', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    document.querySelectorAll('a[download]').forEach((el) => el.remove())
  })

  it('creates a blob URL and triggers a download with the given filename', () => {
    const mockUrl = 'blob:http://localhost/fake-url'
    const capturedBlobs: (Blob | MediaSource)[] = []
    vi.spyOn(URL, 'createObjectURL').mockImplementation((obj) => {
      capturedBlobs.push(obj)
      return mockUrl
    })
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})

    const clickSpy = vi.fn()
    const origCreateElement = document.createElement.bind(document)
    vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const el = origCreateElement(tag)
      if (tag === 'a') {
        el.click = clickSpy
      }
      return el
    })

    downloadJson('my-preset.json', { name: 'Test', extra_race_list: [1, 2] })

    expect(capturedBlobs).toHaveLength(1)
    const blob = capturedBlobs[0]
    expect(blob).toBeInstanceOf(Blob)
    expect((blob as Blob).type).toBe('application/json')
    expect(clickSpy).toHaveBeenCalledOnce()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith(mockUrl)
  })

  it('sets the correct download filename on the anchor', () => {
    const mockUrl = 'blob:http://localhost/fake-url-2'
    vi.spyOn(URL, 'createObjectURL').mockReturnValue(mockUrl)
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})

    let capturedA: HTMLAnchorElement | null = null
    const origCreateElement = document.createElement.bind(document)
    vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const el = origCreateElement(tag)
      if (tag === 'a') {
        capturedA = el as HTMLAnchorElement
        capturedA.click = vi.fn()
      }
      return el
    })

    downloadJson('speed-build.json', { name: 'Speed Build' })

    expect(capturedA).not.toBeNull()
    expect(capturedA!.download).toBe('speed-build.json')
    expect(capturedA!.href).toContain(mockUrl)
  })

  it('serialises the object as pretty JSON', async () => {
    const capturedBlobs: (Blob | MediaSource)[] = []
    vi.spyOn(URL, 'createObjectURL').mockImplementation((obj) => {
      capturedBlobs.push(obj)
      return 'blob:test'
    })
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    const origCreateElement = document.createElement.bind(document)
    vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const el = origCreateElement(tag)
      if (tag === 'a') el.click = vi.fn()
      return el
    })

    const obj = { name: 'Test', extra_race_list: [10, 20] }
    downloadJson('test.json', obj)

    expect(capturedBlobs).toHaveLength(1)
    const blob = capturedBlobs[0] as Blob
    const text = await blob.text()
    expect(JSON.parse(text)).toEqual(obj)
    expect(text).toContain('\n') // pretty-printed
  })
})

// ---------------------------------------------------------------------------
// readJsonFile
// ---------------------------------------------------------------------------

describe('readJsonFile', () => {
  it('resolves with parsed JSON for a valid file', async () => {
    const obj = { name: 'Test', extra_race_list: [1, 2, 3] }
    const file = new File([JSON.stringify(obj)], 'test.json', { type: 'application/json' })

    const result = await readJsonFile(file)
    expect(result).toEqual(obj)
  })

  it('rejects with "Invalid JSON in file" for malformed JSON', async () => {
    const file = new File(['not valid json {{{'], 'bad.json', { type: 'application/json' })

    await expect(readJsonFile(file)).rejects.toThrow('Invalid JSON in file')
  })

  it('resolves with null for a JSON null file', async () => {
    const file = new File(['null'], 'null.json', { type: 'application/json' })
    const result = await readJsonFile(file)
    expect(result).toBeNull()
  })

  it('resolves with an array for a JSON array file', async () => {
    const file = new File(['[1,2,3]'], 'arr.json', { type: 'application/json' })
    const result = await readJsonFile(file)
    expect(result).toEqual([1, 2, 3])
  })
})

// ---------------------------------------------------------------------------
// slugify
// ---------------------------------------------------------------------------

describe('slugify', () => {
  it('lowercases and replaces spaces with hyphens', () => {
    expect(slugify('Speed Build')).toBe('speed-build')
  })

  it('preserves dots, underscores, hyphens, digits', () => {
    expect(slugify('Speed_build-v1.0')).toBe('speed_build-v1.0')
  })

  it('strips characters not in [a-z0-9._-]', () => {
    expect(slugify('Hello! World@2024')).toBe('hello-world2024')
  })

  it('collapses multiple spaces to a single hyphen', () => {
    // \s+ → one hyphen
    expect(slugify('foo   bar')).toBe('foo-bar')
  })

  it('handles empty string', () => {
    expect(slugify('')).toBe('')
  })
})
