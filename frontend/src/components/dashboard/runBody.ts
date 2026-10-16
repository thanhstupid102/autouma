/**
 * buildRunBody — pure function, no DOM/store access.
 * Exported for unit testing.
 *
 * Exact port of app.js:2117-2141 startCareer body construction.
 * Now accepts an optional `racePresetName` for the race preset split.
 */

import type {
  RunCareerBody,
  RunCareerResumeBody,
  RunCareerNewBody,
  DeckInfo,
  FriendInfo,
  TraineeInfo,
  ParentInfo,
} from '@/api/types'

export interface BuildRunBodyArgs {
  activeCareer: boolean
  selectedPreset: string
  racePresetName?: string
  burnClocks: boolean
  twoPalDeck: boolean
  sparkReroll?: boolean
  scenarioId?: number
  runCount: number
  /** Required when activeCareer === false */
  trainee?: TraineeInfo | null
  deck?: DeckInfo | null
  friend?: FriendInfo | null
  veterans?: ParentInfo[]
  rental?: number | string | null
}

export function buildRunBody(args: BuildRunBodyArgs): RunCareerBody {
  const {
    activeCareer,
    selectedPreset,
    racePresetName,
    burnClocks,
    twoPalDeck,
    sparkReroll = false,
    scenarioId = 4,
    runCount,
    trainee,
    deck,
    friend,
    veterans = [],
    rental,
  } = args

  if (activeCareer) {
    const body: RunCareerResumeBody = {
      preset_name: selectedPreset,
      max_steps: 2500,
      burn_clocks: burnClocks,
      two_pal_deck: twoPalDeck,
      spark_reroll: sparkReroll,
      run_count: runCount,
    }
    if (racePresetName) body.race_preset_name = racePresetName
    return body
  }

  // New career — requires full selection
  if (!trainee || !deck || !friend || veterans.length < 2) {
    // Should not happen if caller checks getStartMissingReason first, but be safe
    throw new Error('Incomplete selection for new career')
  }

  const body: RunCareerNewBody = {
    card_id: Number(trainee.id),
    support_card_ids: deck.cards.map((c) => Number(c.id)),
    friend_viewer_id: Number(friend.viewer_id),
    friend_card_id: Number(friend.support_card_id),
    parent_id_1: Number(veterans[0].instance_id),
    parent_id_2: Number(veterans[1].instance_id),
    deck_id: Number(deck.id),
    scenario_id: scenarioId,
    use_tp: 30,
    difficulty_id: 0,
    difficulty: 0,
    is_boost: 0,
    boost_story_event_id: 0,
    preset_name: selectedPreset,
    max_steps: 2500,
    burn_clocks: burnClocks,
    two_pal_deck: twoPalDeck,
    spark_reroll: sparkReroll,
    run_count: runCount,
    rental_friend_viewer_id: Number(rental || 0),
  }
  if (racePresetName) body.race_preset_name = racePresetName
  return body
}
