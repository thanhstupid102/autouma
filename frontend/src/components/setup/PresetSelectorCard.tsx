/**
 * PresetSelectorCard — the shared "pick a preset + act on it" card.
 *
 * PresetPanel and RacePresetPanel rendered byte-identical copies of this Card:
 * the Select, the NEW / DEL / Export / Import row, and the hidden file input.
 * Only the card title and the empty-list placeholder differed, so those are
 * props. Same shape as the NewPresetDialog / DeletePresetDialog extractions that
 * already back both panels' NEW and DEL buttons — this component owns no store
 * subscription; the parent stays the single reader of its own store and passes
 * state and callbacks down.
 *
 * The hidden `<input type="file">` lives here because nothing outside this card
 * touches it: the Import button is the only thing that clicks it, so the ref
 * never has to leave.
 */

import { useRef } from 'react'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

interface PresetSelectorCardProps {
  /** Card heading, e.g. "Skill Presets". */
  title: string
  /** Select placeholder shown when the list is empty. */
  placeholder: string
  /** The list to choose from — anything with a `name`. */
  presets: { name: string }[]
  selectedName: string
  onSelect: (name: string) => void
  /** Opens the parent's NewPresetDialog. */
  onNew: () => void
  /** Opens the parent's DeletePresetDialog. */
  onDelete: () => void
  onExport: () => void
  /** False disables Export — the parent's "there is an active preset" test. */
  canExport: boolean
  /** From useJsonImport — disables Import and swaps its label while running. */
  isImporting: boolean
  onImportFile: (e: React.ChangeEvent<HTMLInputElement>) => void
}

export function PresetSelectorCard({
  title,
  placeholder,
  presets,
  selectedName,
  onSelect,
  onNew,
  onDelete,
  onExport,
  canExport,
  isImporting,
  onImportFile,
}: PresetSelectorCardProps) {
  const importInputRef = useRef<HTMLInputElement>(null)

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">{title}</CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-2 md:flex md:flex-wrap md:items-center">
        <Select
          value={selectedName}
          onValueChange={onSelect}
          disabled={presets.length === 0}
        >
          <SelectTrigger className="col-span-2 w-full min-w-0 md:w-fit md:min-w-[180px] md:flex-1">
            <SelectValue placeholder={placeholder} />
          </SelectTrigger>
          <SelectContent>
            {presets.map((p) => (
              <SelectItem key={p.name} value={p.name}>
                {p.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Button className="w-full md:w-auto" size="sm" variant="outline" onClick={onNew}>
          NEW
        </Button>

        <Button
          size="sm"
          variant="destructive"
          className="w-full md:w-auto"
          disabled={!selectedName}
          onClick={onDelete}
        >
          DEL
        </Button>

        <Button
          size="sm"
          variant="outline"
          className="w-full md:w-auto"
          disabled={!canExport}
          onClick={onExport}
        >
          Export
        </Button>

        <Button
          size="sm"
          variant="outline"
          className="w-full md:w-auto"
          disabled={isImporting}
          onClick={() => importInputRef.current?.click()}
        >
          {isImporting ? 'Importing…' : 'Import'}
        </Button>

        {/* Hidden file input */}
        <input
          ref={importInputRef}
          type="file"
          accept="application/json"
          multiple
          className="hidden"
          onChange={onImportFile}
        />
      </CardContent>
    </Card>
  )
}
