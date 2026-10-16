/**
 * FriendParentGrid — derived from friends; shows friends that carry a rental_parent.
 *
 * - Each card: rank badge, img /api/images/{rental_parent.card_id}.png,
 *   kicker = friend display name, name = rental_parent.name
 * - Toggle selection by viewer_id → setRental
 * - Grid locked (pointer-events-none) when quota is exhausted
 * - Quota display: "{used}/{max} used today"
 * - Name + spark filters over rental_parent.tree
 *
 * Legacy ref:
 *   app.js:1671-1717 renderFriendParents
 *   app.js:1663-1668 setRentalChoice
 */

import { useMemo } from 'react'
import { Filter, RefreshCw } from 'lucide-react'

import { cn } from '@/lib/utils'
import { RANK_MAP, getRentalFriends, rentalQuotaExhausted, type RentalFriend } from './libraryRules'
import { GridCard } from './GridCard'
import { GridSearch } from './GridSearch'
import { SparkTooltip, type SparkTree } from './SparkTooltip'
import { SparkFilterBar } from './SparkFilterBar'
import { useSparkFilterableGrid } from './useSparkFilterableGrid'
import { Button } from '@/components/ui/button'
import type { FriendInfo, RentalQuota, SparkSubject } from '@/api/types'

function rentalParentAsSparkSubject(f: RentalFriend): SparkSubject {
  return f.rental_parent
}

function rentalFriendMatchesSearchTerm(f: RentalFriend, term: string): boolean {
  return (
    (f.rental_parent.name ?? '').toLowerCase().includes(term) ||
    (f.name ?? '').toLowerCase().includes(term)
  )
}

interface FriendParentGridProps {
  friends: FriendInfo[]
  loading: boolean
  source: string
  selectedRental: number | string | null
  onRentalSelect: (viewerId: number | string | null) => void
  onRefresh: () => void
  careerActive?: boolean
  quota: RentalQuota | null
}

export function FriendParentGrid({
  friends,
  loading,
  source,
  selectedRental,
  onRentalSelect,
  onRefresh,
  careerActive,
  quota,
}: FriendParentGridProps) {
  const rentalFriends = useMemo(() => getRentalFriends(friends), [friends])
  const exhausted = rentalQuotaExhausted(quota)
  const {
    search,
    setSearch,
    sparkFilterOpen,
    setSparkFilterOpen,
    sparkFilter,
    setSparkFilter,
    sparkOptions,
    filtered,
    showFilteredCount,
  } = useSparkFilterableGrid({
    items: rentalFriends,
    getSparkSubject: rentalParentAsSparkSubject,
    matchesSearch: rentalFriendMatchesSearchTerm,
  })

  function handleClick(f: { viewer_id: number | string }) {
    if (exhausted) return
    const vid = String(f.viewer_id)
    const current = selectedRental ? String(selectedRental) : '0'
    // Toggle off if re-clicked (legacy: next = already-selected ? 0 : vid)
    onRentalSelect(vid === current ? null : f.viewer_id)
  }

  return (
    <div className="flex flex-col gap-2">
      {/* Controls + quota row */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onRefresh}
            disabled={loading || !!careerActive}
            aria-label="Refresh friend parents"
          >
            <RefreshCw className={loading ? 'animate-spin' : ''} />
            {loading ? 'Loading...' : 'Refresh'}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="xs"
            onClick={() => setSparkFilterOpen((open) => !open)}
            aria-expanded={sparkFilterOpen}
            data-testid="friend-parent-spark-filter-toggle"
          >
            <Filter />
            Spark filters
          </Button>

          <span className="text-xs text-muted-foreground">
            {source && `${source}: `}{filtered.length}/{rentalFriends.length} visible
            {careerActive && ' (active career)'}
            {quota && (
              <span className={cn('ml-2', exhausted && 'text-destructive font-semibold')}>
                {quota.used}/{quota.max} used today
                {exhausted && ' - quota exhausted'}
              </span>
            )}
          </span>
        </div>

        {rentalFriends.length > 8 && (
          <GridSearch value={search} onChange={setSearch} placeholder="Search rental parents..." />
        )}
      </div>

      {sparkFilterOpen && (
        <SparkFilterBar
          value={sparkFilter}
          onChange={setSparkFilter}
          options={sparkOptions}
          conditionLimits={{ blue: 3, pink: 3, green: 3 }}
        />
      )}

      {filtered.length === 0 && (
        <p className="text-sm text-muted-foreground">
          {rentalFriends.length === 0 ? 'No rental parents available.' : 'No rental parents match the current filters.'}
        </p>
      )}

      {showFilteredCount && (
        <p className="text-xs text-muted-foreground">
          Showing {filtered.length} of {rentalFriends.length} rental parents.
        </p>
      )}

      <div
        className={cn(
          'grid min-w-0 max-w-full grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6',
        )}
      >
        {filtered.map(f => {
          const rp = f.rental_parent
          const isSelected = selectedRental && String(f.viewer_id) === String(selectedRental)
          const rank = typeof rp.rank === 'number' ? RANK_MAP[rp.rank] ?? '??' : '??'
          // f.name is the friend's display name; falls back to viewer_id if absent.
          const friendDisplayName = f.name ?? String(f.viewer_id)
          // rental_parent.tree may be present — cast to loose type (mirrors ParentGrid pattern)
          const rpTree = (rp as Record<string, unknown>).tree as SparkTree | undefined
          return (
            <SparkTooltip
              key={String(f.viewer_id)}
              tree={rpTree}
              label={`Spark details for ${String(rp.name ?? rp.card_id ?? 'Unknown')}`}
            >
              <div>
                <GridCard
                  imgId={rp.card_id ?? '100101'}
                  name={String(rp.name ?? rp.card_id ?? 'Unknown')}
                  kicker={friendDisplayName}
                  rankBadge={rank}
                  selected={!!isSelected}
                  disabled={exhausted}
                  onClick={() => handleClick(f)}
                  testId={`rental-card-${f.viewer_id}`}
                />
              </div>
            </SparkTooltip>
          )
        })}
      </div>
    </div>
  )
}
