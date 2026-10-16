import { useEffect } from 'react'
import { useAccountStore } from '@/stores/account'
import { usePresets } from '@/stores/presets'
import { useRacePresets } from '@/stores/racePresets'
import { useRunSettings } from '@/stores/runSettings'
import { useSelection } from '@/stores/selection'

/**
 * Re-resolve all PER-ACCOUNT UI state whenever the selected account changes.
 *
 * The preset / race-preset / run-settings stores persist their selection to
 * account-scoped localStorage keys, so reloading them after a switch surfaces
 * the new account's own choices instead of the previous account's. The team
 * selection is reset (it's per-account and not carried over).
 *
 * Mount once, high in the tree (AppShell).
 */
export function useAccountScopedReload(): void {
  const selected = useAccountStore((s) => s.selected)

  useEffect(() => {
    void usePresets.getState().load()
    void useRacePresets.getState().load()
    useRunSettings.getState().loadLegacy()
    // Clear the team immediately so the previous account's picks don't bleed across
    // the switch; useSelectionHydration then restores THIS account's saved team from
    // the server once its session loads.
    useSelection.getState().clear()
  }, [selected])
}
