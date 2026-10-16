import { describe, it, expect, beforeEach } from 'vitest'
import { useAccountStore, getSelectedAccount } from './account'

describe('account store', () => {
  beforeEach(() => useAccountStore.setState({ accounts: [], selected: '' }))

  it('selects an account and exposes it to the api layer', () => {
    useAccountStore.getState().setSelected('lewpie')
    expect(useAccountStore.getState().selected).toBe('lewpie')
    expect(getSelectedAccount()).toBe('lewpie')
  })
})
