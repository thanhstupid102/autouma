/**
 * FriendGrid — presentational component for friend support cards.
 *
 * Data is fetched by the parent (Library.tsx) on mount regardless of
 * whether this section is open. Props replace the old internal load effect.
 *
 * - Shows visible count / total count + source label
 * - friendAllowed filter applied client-side (re-applied when deck/trainee changes)
 * - Toggle-selects a friend (onFriendSelect callback)
 * - clearInvalidFriendSelection: drops current friend if no longer allowed
 *
 * Legacy ref:
 *   app.js:1973-2005 renderFriends
 *   app.js:2014-2056 loadFriends
 *   app.js:2057-2068 attachFriendHandlers
 *   app.js:1067-1101 friendKey / friendAllowed / clearInvalidFriend
 */

import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { GridCard } from './GridCard'
import { GridSearch } from './GridSearch'
import { friendKey, friendAllowed } from './libraryRules'
import type { FriendInfo, DeckInfo, TraineeInfo } from '@/api/types'

interface FriendGridProps {
  /** All loaded friends (from Library) */
  friends: FriendInfo[]
  /** Whether Library is currently fetching friends */
  loading: boolean
  /** Source label from last fetch ('initial' | 'refresh' | 'error' | '') */
  source: string
  selectedDeck: DeckInfo | null
  selectedTrainee: TraineeInfo | null
  selectedFriend: FriendInfo | null
  onFriendSelect: (f: FriendInfo | null) => void
  /** Trigger a refresh (Library will re-call getFriends with exclude ids) */
  onRefresh: () => void
  /** If true, the REFRESH button is disabled (active career) */
  careerActive?: boolean
}

export function FriendGrid({
  friends,
  loading,
  source,
  selectedDeck,
  selectedTrainee,
  selectedFriend,
  onFriendSelect,
  onRefresh,
  careerActive,
}: FriendGridProps) {
  const [search, setSearch] = useState('')

  const visibleFriends = friends.filter(f => friendAllowed(f, selectedDeck, selectedTrainee))

  // Clear invalid friend selection when deck/trainee changes
  useEffect(() => {
    if (selectedFriend && !friendAllowed(selectedFriend, selectedDeck, selectedTrainee)) {
      onFriendSelect(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedDeck?.id, selectedTrainee?.id])

  const filtered = search.trim()
    ? visibleFriends.filter(f =>
        (f.support_name ?? '').toLowerCase().includes(search.toLowerCase()),
      )
    : visibleFriends

  function handleSelect(f: FriendInfo) {
    const already = selectedFriend && friendKey(selectedFriend) === friendKey(f)
    onFriendSelect(already ? null : f)
  }

  return (
    <div className="flex flex-col gap-2">
      {/* Controls row */}
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={onRefresh}
          disabled={loading || !!careerActive}
          aria-label="Refresh friends"
        >
          <RefreshCw className={loading ? 'animate-spin' : ''} />
          {loading ? 'Loading…' : 'Refresh'}
        </Button>

        <span className="text-xs text-muted-foreground">
          {source && `${source}: `}{visibleFriends.length}/{friends.length} visible
          {careerActive && ' (active career)'}
        </span>

        {friends.length > 8 && (
          <div className="ml-auto">
            <GridSearch value={search} onChange={setSearch} placeholder="Search friends…" />
          </div>
        )}
      </div>

      {filtered.length === 0 && !loading && (
        <p className="text-sm text-muted-foreground">
          {friends.length === 0 ? 'No friends loaded.' : 'All friends filtered by current deck/trainee.'}
        </p>
      )}

      <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6">
        {filtered.map(f => {
          const lb = f.limit_break_count ?? '?'
          const isSelected =
            selectedFriend && friendKey(selectedFriend) === friendKey(f)
          return (
            <GridCard
              key={friendKey(f)}
              imgId={f.support_card_id ?? '10001'}
              name={f.support_name ?? 'Unknown'}
              kicker={`${f.type ?? '?'} | LB${lb}`}
              selected={!!isSelected}
              onClick={() => handleSelect(f)}
              testId={`friend-card-${f.viewer_id}`}
            />
          )
        })}
      </div>
    </div>
  )
}
