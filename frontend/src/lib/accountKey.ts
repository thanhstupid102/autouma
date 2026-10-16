import { getSelectedAccount } from '@/stores/account'

/**
 * Account-scoped localStorage key. Per-account UI selections (active preset,
 * race preset, run settings) are stored under `<base>__<account>` so switching
 * accounts shows that account's own choices instead of a shared global value.
 *
 * Falls back to `default` when no account is selected (e.g. the single-account
 * `--account` launch, or before a selection is made).
 */
export function accountKey(base: string): string {
  const acc = getSelectedAccount() || 'default'
  return `${base}__${acc}`
}
