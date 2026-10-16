/**
 * useSparkFilterableGrid — shared search + spark-filter state/logic for the
 * parent-lineage grids (ParentGrid, FriendParentGrid). Both grids let the
 * user narrow a list of "parent-shaped" items by free-text name search and
 * by spark (factor) totals/conditions; this hook owns that state and derives
 * the filtered list plus the flags each grid uses to decide whether to show
 * its search box / "Showing X of Y" caption.
 */

import { useMemo, useState } from 'react'

import {
  EMPTY_SPARK_FILTER,
  collectSparkNamesByColour,
  isSparkFilterActive,
  parentMatchesSpark,
  type SparkFilter,
} from './sparkFilter'
import type { SparkSubject } from '@/api/types'

interface UseSparkFilterableGridOptions<T> {
  items: T[]
  /** Extract the spark-lineage-bearing subject used for spark-filter matching/options. */
  getSparkSubject: (item: T) => SparkSubject
  /** Whether an item matches the (already trimmed + lowercased) search term. */
  matchesSearch: (item: T, term: string) => boolean
  /** Spark filter bar starts expanded — matches both ParentGrid and FriendParentGrid. */
  initialSparkFilterOpen?: boolean
}

export function useSparkFilterableGrid<T>({
  items,
  getSparkSubject,
  matchesSearch,
  initialSparkFilterOpen = true,
}: UseSparkFilterableGridOptions<T>) {
  const [search, setSearch] = useState('')
  const [sparkFilterOpen, setSparkFilterOpen] = useState(initialSparkFilterOpen)
  const [sparkFilter, setSparkFilter] = useState<SparkFilter>(EMPTY_SPARK_FILTER)

  const sparkOptions = useMemo(
    () => collectSparkNamesByColour(items.map(getSparkSubject)),
    [items, getSparkSubject],
  )
  const sparkActive = isSparkFilterActive(sparkFilter)
  const searchActive = search.trim().length > 0

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase()
    return items.filter((item) => {
      if (term && !matchesSearch(item, term)) return false
      if (sparkActive && !parentMatchesSpark(getSparkSubject(item), sparkFilter)) return false
      return true
    })
  }, [items, search, sparkActive, sparkFilter, matchesSearch, getSparkSubject])

  const showFilteredCount = sparkActive || searchActive

  return {
    search,
    setSearch,
    sparkFilterOpen,
    setSparkFilterOpen,
    sparkFilter,
    setSparkFilter,
    sparkOptions,
    sparkActive,
    searchActive,
    filtered,
    showFilteredCount,
  }
}
