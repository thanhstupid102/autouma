/**
 * RunConfirmDialog — exact port of app.js:2079-2097 openRunConfirm.
 *
 * formatRunEstimate: ~30-37 min per career (app.js:2071-2075).
 */
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogClose,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'

// ---------------------------------------------------------------------------
// Helpers (module-local: a component file must export components only, or Vite
// fast-refresh loses its component boundary — react-refresh/only-export-components)
// ---------------------------------------------------------------------------

function formatRunEstimate(n: number): string {
  const fmt = (m: number) =>
    m < 90 ? `${Math.round(m)} min` : `${(m / 60).toFixed(1)} hr`
  return `${fmt(n * 30)} – ${fmt(n * 37)}`
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface RunConfirmDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  runCount: number
  activeCareer: boolean
  onConfirm: () => void
}

export function RunConfirmDialog({
  open,
  onOpenChange,
  runCount,
  activeCareer,
  onConfirm,
}: RunConfirmDialogProps) {
  const n = runCount
  const lead = activeCareer ? 'Resume the active career, then run ' : 'The bot will run '
  const stopAfterSpDump = n === -1
  const isInfinite = n === 0

  const okLabel = stopAfterSpDump ? 'YES, STOP AFTER SP DUMP' : isInfinite ? 'YES, RUN ∞' : `YES, RUN ${n}×`

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent showCloseButton={false}>
        <DialogHeader>
          <DialogTitle>Confirm Run</DialogTitle>
        </DialogHeader>

        <div className="py-2 text-sm">
          {stopAfterSpDump ? (
            <>
              <p className="font-semibold text-yellow-500">⚠️ SP DUMP STOP MODE</p>
              <p className="mt-1">
                {lead}<strong>one career</strong> until final SP dump, then stop before{' '}
                <strong>finish submit</strong>.
              </p>
            </>
          ) : isInfinite ? (
            <>
              <p className="font-semibold text-yellow-500">⚠️ INFINITE MODE</p>
              <p className="mt-1">
                {lead}careers <strong>continuously</strong> until you click{' '}
                <strong>STOP</strong>. It won&apos;t stop on its own.
              </p>
            </>
          ) : n === 1 ? (
            <>
              <p>
                {lead}
                <strong>1 career</strong> (single run), then stop.
              </p>
              <p className="mt-1 text-muted-foreground">
                Est. ~{formatRunEstimate(1)}
              </p>
            </>
          ) : (
            <>
              <p>
                {lead}
                <strong>{n} careers</strong> back-to-back, then stop automatically.
              </p>
              <p className="mt-1 text-muted-foreground">
                Est. total ~{formatRunEstimate(n)}
              </p>
            </>
          )}
        </div>

        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline" size="sm">
              Cancel
            </Button>
          </DialogClose>
          <Button
            size="sm"
            variant={isInfinite || stopAfterSpDump ? 'destructive' : 'default'}
            onClick={() => {
              onOpenChange(false)
              onConfirm()
            }}
          >
            {okLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
