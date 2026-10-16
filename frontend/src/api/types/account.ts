// Account dashboard snapshot returned by GET /api/accounts (and embedded in
// the session/career payloads). Lives in the api-types layer so api modules
// never have to import a type from a Zustand store; the store re-exports it.
export interface AccountSnapshot {
  name: string
  logged_in: boolean
  running: boolean
  loop_active: boolean
  account: unknown | null
  runner: unknown | null
  steam_unbound_at?: number | null
}
