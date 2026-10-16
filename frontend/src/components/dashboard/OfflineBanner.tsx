/**
 * OfflineBanner — shown when failureCount >= 3 consecutive poll failures.
 *
 * Distinct from BackoffBanner (which is a bot safety feature).
 * This signals that the server itself is unreachable.
 */
export function OfflineBanner() {
  return (
    <div
      role="alert"
      data-testid="offline-banner"
      className="rounded-lg border border-slate-400/40 bg-slate-100 px-4 py-3 text-sm text-slate-700 dark:bg-slate-800/40 dark:text-slate-300"
    >
      Server offline, reconnecting…
    </div>
  )
}
