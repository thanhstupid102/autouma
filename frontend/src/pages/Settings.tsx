/**
 * Settings page — master.mdb path, Discord webhook, theme.
 *
 * Task 14: composed from three sub-cards.
 */

import { MasterDataCard } from '@/components/settings/MasterDataCard'
import { WebhookCard } from '@/components/settings/WebhookCard'
import { ThemeCard } from '@/components/settings/ThemeCard'

export default function Settings() {
  return (
    <div className="mx-auto max-w-2xl space-y-6 p-4 md:p-6">
      <div>
        <h1 className="text-2xl font-semibold">Settings</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Configure master data, notifications, and appearance.
        </p>
      </div>
      <MasterDataCard />
      <WebhookCard />
      <ThemeCard />
    </div>
  )
}
