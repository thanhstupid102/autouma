/**
 * GridCard — shared thumbnail card used by all library grids.
 *
 * Shows: image via /api/images/{imgId}.png (hidden on error),
 * optional rank badge (top-left), kicker text, name.
 * Selected state: ring-2 ring-primary.
 * Disabled state: opacity-40 cursor-not-allowed (used for vet-full).
 */

import { cn } from '@/lib/utils'

interface GridCardProps {
  imgId?: string | number
  name?: string
  kicker?: string
  rankBadge?: string
  selected?: boolean
  disabled?: boolean
  onClick?: () => void
  /** extra data-testid suffix for tests */
  testId?: string
  children?: React.ReactNode
}

export function GridCard({
  imgId,
  name,
  kicker,
  rankBadge,
  selected,
  disabled,
  onClick,
  testId,
  children,
}: GridCardProps) {
  const effectiveImgId = imgId ?? '10001'

  return (
    <div
      role={onClick ? 'button' : undefined}
      tabIndex={onClick && !disabled ? 0 : undefined}
      data-testid={testId}
      aria-pressed={selected}
      aria-disabled={disabled}
      onClick={!disabled ? onClick : undefined}
      onKeyDown={
        onClick && !disabled
          ? e => { if (e.key === 'Enter' || e.key === ' ') onClick() }
          : undefined
      }
      className={cn(
        'relative flex flex-col overflow-hidden rounded-lg border border-border bg-card',
        'transition-all select-none',
        onClick && !disabled && 'cursor-pointer hover:border-primary/50',
        selected && 'ring-2 ring-primary border-primary',
        disabled && 'opacity-40 cursor-not-allowed',
      )}
    >
      {/* Rank badge */}
      {rankBadge !== undefined && (
        <span className="absolute left-1 top-1 z-10 rounded bg-black/70 px-1 py-0.5 text-[10px] font-bold text-white leading-none">
          {rankBadge}
        </span>
      )}

      {/* Image */}
      <div className="aspect-square w-full overflow-hidden bg-muted">
        <img
          src={`/api/images/${effectiveImgId}.png`}
          alt={name ?? ''}
          className="h-full w-full max-w-full object-cover"
          onError={e => {
            ;(e.currentTarget as HTMLImageElement).style.display = 'none'
          }}
          draggable={false}
        />
      </div>

      {/* Overlay */}
      <div className="flex flex-col gap-0.5 px-1.5 py-1 bg-card/95 border-t border-border/50">
        {kicker && (
          <span className="truncate text-[10px] text-muted-foreground">{kicker}</span>
        )}
        <span className="truncate text-xs font-medium text-foreground leading-snug">
          {name ?? 'Unknown'}
        </span>
      </div>

      {children}
    </div>
  )
}
