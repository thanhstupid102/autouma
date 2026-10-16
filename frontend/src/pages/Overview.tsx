import { useAccounts } from '@/hooks/useAccounts'
import { useAccountStore } from '@/stores/account'
import AccountCard from '@/components/accounts/AccountCard'
import AddAccountDialog from '@/components/accounts/AddAccountDialog'
import ImportExportControls from '@/components/accounts/ImportExportControls'

export default function Overview() {
  useAccounts()
  const accounts = useAccountStore((s) => s.accounts)

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Header */}
      <div
        data-testid="overview-header"
        className="flex flex-col items-stretch gap-3 sm:flex-row sm:items-center sm:justify-between"
      >
        <h1 className="text-lg font-semibold text-foreground">Accounts</h1>
        <div
          data-testid="overview-actions"
          className="flex w-full flex-wrap items-center gap-2 sm:w-auto sm:justify-end"
        >
          <ImportExportControls />
          <AddAccountDialog />
        </div>
      </div>

      {/* Grid */}
      {accounts.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No accounts yet. Add one to get started.
        </p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {accounts.map((acc) => (
            <AccountCard key={acc.name} acc={acc} />
          ))}
        </div>
      )}
    </div>
  )
}
