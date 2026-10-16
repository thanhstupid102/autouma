import { Outlet, useParams } from 'react-router-dom'
import { useAccountStore } from '@/stores/account'

/**
 * Layout for every per-account page (/account/:name/*). Binds the selected
 * account to the URL: setting `selected` here scopes the preset / race-preset /
 * run-settings stores and the X-Account header to this account, and triggers
 * AppShell's useAccountScopedReload. All child pages (dashboard/setup/library/
 * events/settings) inherit the account from the route, so editing e.g. a preset
 * on /account/A/setup never affects /account/B.
 *
 * The store is updated SYNCHRONOUSLY during render (not in an effect): child
 * hooks (useSession/useRunner) key their queries on `selected`, so an effect
 * would run too late and the first render would fetch the previous/empty
 * account — flashing the wrong data / login. Guarded so it only writes on a
 * real change (no render loop). Zustand setState outside a hook is safe here.
 */
export default function AccountLayout() {
  const { name } = useParams()
  if (name && useAccountStore.getState().selected !== name) {
    useAccountStore.setState({ selected: name })
  }
  return <Outlet />
}
