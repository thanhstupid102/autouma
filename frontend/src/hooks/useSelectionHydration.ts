import { useEffect, useRef } from 'react'
import { useAccountStore } from '@/stores/account'
import { useSession } from '@/hooks/useSession'
import { useSelection } from '@/stores/selection'
import type { ParentInfo, Selection } from '@/api/types'

export function withCanonicalVeterans(selection: Selection, parents?: ParentInfo[]): Selection {
  if (!selection.veterans?.length || !parents?.length) return selection
  const parentsById = new Map(parents.map((parent) => [String(parent.instance_id), parent] as const))
  return { ...selection, veterans: selection.veterans.map((veteran) => parentsById.get(String(veteran.instance_id)) ?? veteran) }
}

/**
 * Restore the remembered team (deck / trainee / friend / parents / event) from the
 * server ONCE per account when its session loads. The backend persists the selection
 * per account (uma_runtime/selections/<name>.json) and returns it on GET /api/auth/session;
 * this fills the in-memory selection store so opening /account/:name shows the last
 * team instead of an empty one.
 *
 * Hydrates only once per account (tracked in a ref) so the 30s session poll never
 * clobbers edits the user makes after opening the account. Mount once in AppShell.
 */
export function useSelectionHydration(): void {
  const selected = useAccountStore((s) => s.selected)
  const { data } = useSession()
  const hydratedFor = useRef<string | null>(null)

  useEffect(() => {
    if (!selected) {
      hydratedFor.current = null
      return
    }
    if (hydratedFor.current === selected) return
    if (data?.success && data.selection) {
      useSelection.getState().hydrate(withCanonicalVeterans(data.selection, data.parents))
      hydratedFor.current = selected
    }
  }, [selected, data])
}
