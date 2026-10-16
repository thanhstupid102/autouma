export const PARENT_AUTO_REFRESH_STALE_MS = 5 * 60_000

const lastAttemptByAccount = new Map<string, number>()
const inFlightByAccount = new Map<string, Promise<unknown>>()

interface ParentRefreshOptions {
  force?: boolean
  now?: number
}

/** Share in-flight work and throttle automatic load/index calls across remounts. */
export function requestParentRosterRefresh<T>(
  account: string,
  request: () => Promise<T>,
  { force = false, now = Date.now() }: ParentRefreshOptions = {},
): Promise<T> | null {
  if (!account) return null

  const inFlight = inFlightByAccount.get(account)
  if (inFlight) return inFlight as Promise<T>

  const lastAttempt = lastAttemptByAccount.get(account)
  if (!force && lastAttempt !== undefined && now - lastAttempt < PARENT_AUTO_REFRESH_STALE_MS) {
    return null
  }

  lastAttemptByAccount.set(account, now)
  const pending = request().finally(() => {
    if (inFlightByAccount.get(account) === pending) {
      inFlightByAccount.delete(account)
    }
  })
  inFlightByAccount.set(account, pending)
  return pending
}

export function resetParentRosterRefreshThrottleForTests(): void {
  lastAttemptByAccount.clear()
  inFlightByAccount.clear()
}
