import { useEffect, useState, useRef } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogClose,
} from '@/components/ui/dialog'

interface NewPresetDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  create: (name: string) => Promise<void>
  title: string
  label: string
  inputId: string
  placeholder: string
  errorFallback: string
}

export function NewPresetDialog({
  open,
  onOpenChange,
  create,
  title,
  label,
  inputId,
  placeholder,
  errorFallback,
}: NewPresetDialogProps) {
  const [nameValue, setNameValue] = useState('')
  const [isCreating, setIsCreating] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (open) {
      // Intentional: clear the field each time the dialog opens so a previous
      // (cancelled) name never leaks into the next create. The rule flags
      // setState-in-effect as a cascading-render risk, but this runs only on the
      // open transition. Behaviour predates the extraction -- both panels did
      // exactly this (unsuppressed) before they shared this component.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setNameValue('')
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }, [open])

  async function handleCreate() {
    if (isCreating) return
    setIsCreating(true)
    try {
      await create(nameValue)
      onOpenChange(false)
    } catch (e) {
      const msg = e instanceof Error ? e.message : errorFallback
      toast.error(msg)
    } finally {
      setIsCreating(false)
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter') void handleCreate()
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent showCloseButton={false}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>

        <DialogBody className="flex flex-col gap-2 py-1">
          <Label htmlFor={inputId}>{label}</Label>
          <Input
            id={inputId}
            ref={inputRef}
            value={nameValue}
            onChange={(e) => setNameValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            disabled={isCreating}
          />
        </DialogBody>

        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline" size="sm" disabled={isCreating}>
              Cancel
            </Button>
          </DialogClose>
          <Button size="sm" disabled={isCreating} onClick={handleCreate}>
            {isCreating ? 'Creating…' : 'Create'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
