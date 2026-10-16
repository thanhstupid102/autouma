/**
 * DeletePresetDialog — shared confirm-delete shell for both preset panels.
 *
 * PresetPanel and RacePresetPanel had byte-identical copies of this dialog that
 * differed only in the title, the noun in the sentence, the fallback error text
 * and which store's `remove` they called — so those are the props. Same shape as
 * the NewPresetDialog extraction that already backs both panels' NEW button.
 */
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogClose,
} from '@/components/ui/dialog'

interface DeletePresetDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Name of the preset to delete — also rendered in the confirmation sentence. */
  name: string
  /** Store action that performs the delete; rejects with a message on failure. */
  remove: (name: string) => Promise<void>
  title: string
  /** Noun used in the sentence, e.g. "preset" / "race preset". */
  noun: string
  errorFallback: string
}

export function DeletePresetDialog({
  open,
  onOpenChange,
  name,
  remove,
  title,
  noun,
  errorFallback,
}: DeletePresetDialogProps) {
  const [isDeleting, setIsDeleting] = useState(false)

  async function handleDelete() {
    if (isDeleting) return
    setIsDeleting(true)
    try {
      await remove(name)
      onOpenChange(false)
    } catch (e) {
      const msg = e instanceof Error ? e.message : errorFallback
      toast.error(msg)
    } finally {
      setIsDeleting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent showCloseButton={false}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <DialogBody>
          <p className="text-sm text-muted-foreground">
            Delete {noun}{' '}
            <span className="font-medium text-foreground [overflow-wrap:anywhere]">
              "{name}"
            </span>
            ? This cannot be undone.
          </p>
        </DialogBody>
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline" size="sm" disabled={isDeleting}>
              Cancel
            </Button>
          </DialogClose>
          <Button
            size="sm"
            variant="destructive"
            disabled={isDeleting}
            onClick={handleDelete}
          >
            {isDeleting ? 'Deleting…' : 'Delete'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
