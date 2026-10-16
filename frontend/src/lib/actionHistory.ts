import type { ActionHistoryRow } from '../api/types'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Minimal shape of a log item from RunnerStatus.log */
export interface LogItem {
  action: string
  turn?: number
  detail?: string
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const ALLOWED_ACTIONS = [
  'command',
  'race',
  'race_progress',
  'finish',
  'api_delay',
  'turn_delay',
  'complex_delay',
] as const

const RECREATION_FACILITIES = ['301', '302', '303', '304', '305', '390'] as const

// ---------------------------------------------------------------------------
// deriveActionHistory — ported 1:1 from public/app.js:2304-2331
// ---------------------------------------------------------------------------

/**
 * Filters a runner log to displayable action rows and derives normalized
 * action/facility values from command detail strings.
 *
 * Ported from legacy app.js lines 2304-2331.
 */
export function deriveActionHistory(log: LogItem[]): ActionHistoryRow[] {
  return log
    .filter(item => (ALLOWED_ACTIONS as readonly string[]).includes(item.action))
    .map(item => {
      const detail = String(item.detail ?? '')
      let action = item.action
      let facility = ''

      if (action === 'command') {
        if (detail.startsWith('training ')) {
          action = 'train'
          facility = detail.replace('training ', '')
        } else if (detail.startsWith('rest ')) {
          action = 'rest'
          facility = detail.replace('rest ', '')
          if ((RECREATION_FACILITIES as readonly string[]).includes(facility)) {
            action = 'recreation'
          }
        } else if (detail.startsWith('challenge ')) {
          action = 'rest'
          facility = detail.replace('challenge ', '')
        } else if (detail.startsWith('recreation ')) {
          action = 'recreation'
          facility = detail.replace('recreation ', '')
        } else if (detail.startsWith('command 8:')) {
          action = 'medic'
        }
      } else if (action === 'race_progress') {
        action = 'race'
      }

      const turn: number | string = item.turn ?? ''
      return { turn, action, facility, detail } satisfies Omit<ActionHistoryRow, 'stats'>
    })
}

// ---------------------------------------------------------------------------
// normalizeHistoryAction — ported 1:1 from public/app.js:2332-2338
// ---------------------------------------------------------------------------

/**
 * Post-normalizes a single history row: if action is 'rest' and facility
 * is in the recreation set, upgrades action to 'recreation'.
 *
 * Ported from legacy app.js lines 2332-2338.
 */
export function normalizeHistoryAction(row: ActionHistoryRow): ActionHistoryRow {
  const facility = String(row.facility ?? '')
  if (
    row.action === 'rest' &&
    (RECREATION_FACILITIES as readonly string[]).includes(facility)
  ) {
    return { ...row, action: 'recreation' }
  }
  return row
}
