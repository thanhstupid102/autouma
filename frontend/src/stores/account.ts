import { create } from 'zustand'

import type { AccountSnapshot } from '../api/types/account'

// Re-exported so existing `@/stores/account` consumers keep importing it here.
export type { AccountSnapshot }

interface AccountStore {
  accounts: AccountSnapshot[]
  selected: string
  setAccounts: (a: AccountSnapshot[]) => void
  setSelected: (name: string) => void
}

export const useAccountStore = create<AccountStore>()((set) => ({
  accounts: [],
  selected: '',
  setAccounts: (accounts) => set({ accounts }),
  setSelected: (selected) => set({ selected }),
}))

/** Read the current selection outside React (used by the api client). */
export function getSelectedAccount(): string {
  return useAccountStore.getState().selected
}
