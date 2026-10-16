import '@testing-library/jest-dom/vitest'

// Radix UI components (Select, etc.) call scrollIntoView internally; jsdom
// does not implement it so we provide a no-op to prevent test crashes.
if (typeof Element !== 'undefined' && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {}
}

// Several Radix UI components (Checkbox, Select, ...) use ResizeObserver, which jsdom
// does not implement. Provide a no-op so those components render in tests.
if (typeof globalThis.ResizeObserver === 'undefined') {
  class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  globalThis.ResizeObserver = ResizeObserver as unknown as typeof globalThis.ResizeObserver
}

// jsdom under vitest does not always provide a functional Storage (localStorage
// can be a bare {} without getItem/setItem/clear). Install a minimal in-memory
// implementation so store tests that rely on the real Web Storage API work.
if (typeof localStorage === 'undefined' || typeof localStorage.clear !== 'function') {
  class MemoryStorage implements Storage {
    private store = new Map<string, string>()
    get length() {
      return this.store.size
    }
    clear() {
      this.store.clear()
    }
    getItem(key: string) {
      return this.store.has(key) ? this.store.get(key)! : null
    }
    key(index: number) {
      return Array.from(this.store.keys())[index] ?? null
    }
    removeItem(key: string) {
      this.store.delete(key)
    }
    setItem(key: string, value: string) {
      this.store.set(key, String(value))
    }
  }
  Object.defineProperty(globalThis, 'localStorage', {
    value: new MemoryStorage(),
    configurable: true,
    writable: true,
  })
}
