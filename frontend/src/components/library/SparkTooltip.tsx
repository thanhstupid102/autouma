/**
 * SparkTooltip — responsive spark lineage details (self/p1/p2 factor trees).
 *
 * Fine pointers retain the card-wide hover tooltip. Touch users get an
 * explicit button that opens the same content in a viewport-safe popover.
 *
 * Factor chips are colour-coded by category for quick scanning:
 *   stat → blue · aptitude → pink · unique → green · scenario → amber · other → muted
 * (mirrors legacy styles.css .f-stat / .f-aptitude / .f-unique)
 *
 * Tree shape mirrors ParentInfo.tree / rental_parent.tree.
 *
 * Legacy ref: app.js:2497-2516 renderParentSparks, styles.css:1532-1547
 */

import type { ReactElement } from 'react'
import { Info } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { ResponsiveDetails } from '@/components/ui/responsive-details'
import type {
  ParentLineageFactor,
  ParentLineageNode,
  ParentLineageTree,
  ParentLineageWins,
} from '@/api/types'

type SparkFactor = ParentLineageFactor
type SparkWins = ParentLineageWins
type SparkNode = ParentLineageNode

export type SparkTree = ParentLineageTree

const LINEAGE_KEYS = ['self', 'p1', 'p2'] as const
const LINEAGE_LABEL: Record<(typeof LINEAGE_KEYS)[number], string> = {
  self: 'Self',
  p1: 'Parent 1',
  p2: 'Parent 2',
}

interface SparkTooltipProps {
  tree?: SparkTree | null | Record<string, unknown>
  children: ReactElement
  label?: string
}

/** Category → chip colour (legacy .f-* palette). */
function factorClass(category?: string): string {
  switch (category) {
    case 'stat':
      return 'bg-sky-500 text-white'
    case 'aptitude':
      return 'bg-pink-500 text-white'
    case 'unique':
      return 'bg-green-500 text-white'
    case 'scenario':
      return 'bg-amber-400 text-black'
    default:
      // skill / race / chara / unknown
      return 'bg-muted text-foreground'
  }
}

function starCount(value: SparkFactor['stars']): number {
  const n = Number(value)
  return Number.isFinite(n) && n > 0 ? Math.trunc(n) : 0
}

function hasNodeIdentity(node: SparkNode): boolean {
  const cardId = String(node.card_id ?? '').trim()
  const name = String(node.name ?? '').trim()
  return (!!cardId && cardId !== '0') || !!name
}

function nodeFactors(node: SparkNode): SparkFactor[] {
  return Array.isArray(node.factors) ? node.factors : []
}

function isRenderableNode(node: SparkNode): boolean {
  return hasNodeIdentity(node) || nodeFactors(node).length > 0
}

export function SparkTooltip({ tree, children, label = 'Spark details' }: SparkTooltipProps) {
  const nodes = !tree
    ? []
    : LINEAGE_KEYS
        .map(key => {
          const node = (tree as Record<string, unknown>)[key] as SparkNode | undefined
          if (!node || !isRenderableNode(node)) return null
          const factors = nodeFactors(node)
          const cardId = String(node.card_id ?? '').trim()
          const nodeName = String(node.name ?? '').trim() || cardId || key
          return {
            key,
            nodeName,
            displayName: `${LINEAGE_LABEL[key]}: ${nodeName}`,
            factors,
            wins: node.wins,
            cardId: cardId && cardId !== '0' ? node.card_id : undefined,
          }
        })
        .filter(Boolean) as Array<{
        key: string
        nodeName: string
        displayName: string
        factors: SparkFactor[]
        wins?: SparkWins
        cardId?: number | string
      }>

  // No spark data → render the card without a tooltip.
  if (nodes.length === 0) return <>{children}</>

  const content = (
    <div className="w-auto max-w-[calc(100vw-2rem)] rounded-md border border-border bg-popover p-2.5 text-popover-foreground shadow-lg">
      {/* Category legend */}
      <div className="mb-2 flex flex-wrap gap-2.5 text-[10px] text-muted-foreground">
        <span className="flex items-center gap-1"><span className="size-2 rounded-full bg-sky-500" />Stat</span>
        <span className="flex items-center gap-1"><span className="size-2 rounded-full bg-pink-500" />Aptitude</span>
        <span className="flex items-center gap-1"><span className="size-2 rounded-full bg-green-500" />Unique</span>
      </div>

      {/* Lineage columns: hovered parent + its two parents. */}
      <div className="max-w-full overflow-x-auto overscroll-x-contain">
        <div className="flex items-start gap-2">
          {nodes.map(node => (
            <div key={node.key} className="w-40 shrink-0">
              {/* Node header: portrait + name + wins */}
              <div className="mb-1 flex items-center gap-1.5 border-b border-border/60 pb-1">
                {node.cardId && (
                  <img
                    src={`/api/images/${node.cardId}.png`}
                    alt={node.nodeName}
                    width={20}
                    height={20}
                    className="size-5 max-w-full shrink-0 rounded bg-muted object-cover"
                    onError={e => { (e.currentTarget as HTMLImageElement).style.display = 'none' }}
                  />
                )}
                <span className="truncate text-[11px] font-semibold text-foreground">{node.displayName}</span>
                {node.wins && (!!node.wins.g1 || !!node.wins.g2 || !!node.wins.g3) && (
                  <span className="ml-auto shrink-0 text-[9px] text-muted-foreground">
                    {[node.wins.g1 && `G1×${node.wins.g1}`, node.wins.g2 && `G2×${node.wins.g2}`, node.wins.g3 && `G3×${node.wins.g3}`].filter(Boolean).join(' ')}
                  </span>
                )}
              </div>

              {/* Factor list — one per row, coloured by category */}
              <div className="flex flex-col gap-0.5">
                {node.factors.map((f, i) => {
                  const stars = starCount(f.stars)
                  return (
                    <span
                      key={i}
                      className={`flex items-center justify-between gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium leading-tight ${factorClass(f.category)}`}
                    >
                      <span className="truncate">{f.name ?? '?'}</span>
                      {stars > 0 && <span className="shrink-0 text-amber-300">{'★'.repeat(stars)}</span>}
                    </span>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )

  return (
    <ResponsiveDetails
      content={content}
      contentVariant="panel"
      label={label}
      className="min-w-0 max-w-full"
      touchTrigger={(
        <Button
          type="button"
          variant="secondary"
          size="icon-xs"
          className="absolute bottom-1 right-1 z-20 border border-border bg-background/90 shadow-sm"
          aria-label={label}
          onPointerDown={(event) => event.stopPropagation()}
          onClick={(event) => event.stopPropagation()}
        >
          <Info />
        </Button>
      )}
    >
      {children}
    </ResponsiveDetails>
  )
}
