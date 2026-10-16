import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { listAccounts } from '../api/accounts'
import { useAccountStore } from '../stores/account'

export function useAccounts() {
  const setAccounts = useAccountStore((s) => s.setAccounts)
  const q = useQuery({ queryKey: ['accounts'], queryFn: listAccounts, refetchInterval: 3000 })
  useEffect(() => {
    if (q.data?.accounts) setAccounts(q.data.accounts)
  }, [q.data, setAccounts])
  return q
}
