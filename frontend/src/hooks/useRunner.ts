import { useQuery } from '@tanstack/react-query'
import { getRunner } from '../api/career'
import { useAccountStore } from '../stores/account'
import type { RunnerStatus } from '../api/types'

// Shape of data returned by getRunner
type RunnerData = { success: boolean; runner?: RunnerStatus }

/**
 * Polls /api/career/runner at 2 s while the runner is active (running or
 * loop_active), falling back to 10 s when idle.
 *
 * @param enabled — pass `false` to suspend polling (e.g. no active session).
 *
 * Consecutive failure count is available on the returned query result via
 * `result.failureCount` (TanStack Query v5 exposes it on the UseQueryResult
 * directly). Consumers can use this to show an offline banner:
 *
 *   const runner = useRunner(enabled)
 *   const isOffline = runner.failureCount >= 3
 */
export function useRunner(enabled: boolean) {
  const selected = useAccountStore((s) => s.selected)
  return useQuery<RunnerData>({
    queryKey: ['runner', selected],
    queryFn: () => getRunner(selected),
    enabled,
    // TanStack Query v5: refetchInterval callback receives the Query object.
    // query.state.data holds the last successful data; query.state.fetchFailureCount
    // holds consecutive failures. We read via query.state.data for the interval
    // decision — failureCount is exposed on the UseQueryResult for consumers.
    refetchInterval(query) {
      const data = query.state.data as RunnerData | undefined
      const r = data?.runner
      return r?.running || r?.loop_active ? 2_000 : 10_000
    },
    retry: false,
  })
}
