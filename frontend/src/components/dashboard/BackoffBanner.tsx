/**
 * BackoffBanner — amber banner shown when runner.circuit_tripped is true.
 *
 * Always visible alongside the action history table when tripped.
 * During an automatic resume cooldown, the runner status supplies the pending
 * attempt and configured wait so the dashboard stays honest about what happens next.
 */
interface BackoffBannerProps {
  retryWaiting?: boolean
  retryAttempt?: number
  retryLimit?: number
  retryWaitSeconds?: number
}

function formatWait(seconds: number): string {
  if (seconds % 60 === 0) {
    const minutes = seconds / 60
    return `${minutes} minute${minutes === 1 ? '' : 's'}`
  }
  return `${seconds} seconds`
}

export function BackoffBanner({
  retryWaiting = false,
  retryAttempt = 0,
  retryLimit = 0,
  retryWaitSeconds = 0,
}: BackoffBannerProps) {
  return (
    <div
      role="alert"
      data-testid="backoff-banner"
      className="rounded-lg border border-amber-500/40 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:bg-amber-900/20 dark:text-amber-300"
    >
      {retryWaiting ? (
        <>
          🛑 Auto-backoff: waiting {formatWait(retryWaitSeconds)} before automatic resume
          attempt {retryAttempt}/{retryLimit}. Stop remains available during the cooldown.
        </>
      ) : (
        <>
          🛑 Auto-backoff: too many server errors in a short time. The bot stopped ITSELF to
          protect your account — this is intentional, not a crash. Wait a while (ideally
          hours) before running again.
        </>
      )}
    </div>
  )
}
