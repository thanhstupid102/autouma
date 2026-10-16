import { useQuery } from '@tanstack/react-query'
import { getSession } from '../api/auth'
import { ApiError } from '../api/client'
import { useAccountStore } from '../stores/account'
import type { SessionData } from '../api/types'

/**
 * Polls the current session every 30 seconds.
 * Returns the raw TanStack Query result; consumers can read `.data`, `.isLoading`, etc.
 *
 * Keyed by the selected account so switching accounts refetches the new
 * account's session instead of flashing the previous account's cached data.
 * (Partial-key `invalidateQueries(['session'])` still matches `['session', name]`.)
 *
 * A 400 ("No account selected") is treated as "not logged in" rather than an
 * error, so the app never crashes when no account is selected.
 */
export const useSession = () => {
  const selected = useAccountStore((s) => s.selected)
  return useQuery({
    queryKey: ['session', selected],
    queryFn: async (): Promise<SessionData> => {
      try {
        return await getSession(selected)
      } catch (err) {
        if (err instanceof ApiError && err.status === 400) {
          return { success: false } as SessionData
        }
        throw err
      }
    },
    refetchInterval: 30_000,
    retry: 1,
  })
}
