/**
 * runRules — pure functions, no DOM/store access.
 * Exact port of app.js:852-878.
 * Exported for unit testing.
 *
 * NOTE: Both skill preset and race preset are now optional for starting a run.
 * The backend falls back gracefully when preset_name or race_preset_name are absent.
 */

import type { DeckInfo, FriendInfo, TraineeInfo, ParentInfo } from '@/api/types'

// ---------------------------------------------------------------------------
// runCountHint — hint text under the RUNS input.
// Lives here rather than in RunOptions.tsx so that component file exports
// components only (react-refresh/only-export-components).
// ---------------------------------------------------------------------------

export function runCountHint(n: number): string {
  if (n === -1) return 'SP dump stop (no finish submit)'
  if (n === 0) return '∞ (infinite)'
  if (n === 1) return '1 career'
  return `${n} careers`
}

// ---------------------------------------------------------------------------
// getParentLineageCards — app.js:866-871
// ---------------------------------------------------------------------------

export function getParentLineageCards(parent: ParentInfo): number[] {
  if (!parent || !parent.tree) return []
  return (['self', 'p1', 'p2', 'gp1', 'gp2', 'gp3', 'gp4'] as const)
    .map((key) => Number(parent.tree![key] && parent.tree![key]!.card_id))
    .filter(Boolean)
}

// ---------------------------------------------------------------------------
// getParentSelectionError — app.js:872-879
// Checks if either parent's direct card (tree.self.card_id) equals the trainee.
// ---------------------------------------------------------------------------

export function getParentSelectionError(args: {
  trainee: TraineeInfo | null
  veterans: ParentInfo[]
}): string {
  const { trainee, veterans } = args
  if (!trainee) return ''
  const traineeId = Number(trainee.id)
  const lineages = veterans.map(getParentLineageCards)
  if (lineages.length < 2) return ''
  // Direct parent check: lineages[i][0] is tree.self.card_id
  if (lineages.some((cards) => cards[0] === traineeId)) return 'Direct parent is trainee'
  return ''
}

// ---------------------------------------------------------------------------
// getStartMissingReason — app.js:852-865
//
// Preset is now optional (both skill and race). Only team selection is required
// for a new career run. Active career requires nothing beyond the call itself.
// ---------------------------------------------------------------------------

export interface GetStartMissingReasonArgs {
  selectedPreset?: string
  activeCareer: boolean
  deck: DeckInfo | null
  friend: FriendInfo | null
  trainee: TraineeInfo | null
  veterans: ParentInfo[]
}

export function getStartMissingReason(args: GetStartMissingReasonArgs): string {
  const { activeCareer, deck, friend, trainee, veterans } = args
  if (activeCareer) return '' // active career can always be resumed
  if (!deck) return 'Select a deck'
  if (!friend) return 'Select a friend support'
  if (!trainee) return 'Select a trainee'
  if (veterans.length < 2) return 'Select two parents'
  const parentError = getParentSelectionError({ trainee, veterans })
  if (parentError) return parentError
  return ''
}
