/**
 * Setup page — skill preset CRUD, running-style config, skill/race editors.
 *
 * RUN CAREER lives on the Dashboard — see the sidebar to navigate there.
 */

import { PresetPanel } from '@/components/setup/PresetPanel'
import { RacePresetPanel } from '@/components/setup/RacePresetPanel'

export default function Setup() {
  return (
    <div className="mx-auto max-w-2xl space-y-6 p-4 md:p-6">
      <div>
        <h1 className="text-2xl font-semibold">Setup</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Configure presets, running style, and skill filters.
          To start a career run, go to the{' '}
          <a
            href="/"
            className="underline underline-offset-3 hover:text-foreground"
          >
            Dashboard
          </a>
          .
        </p>
      </div>

      <PresetPanel />
      <RacePresetPanel />
    </div>
  )
}
