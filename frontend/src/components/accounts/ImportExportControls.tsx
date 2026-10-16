import { useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Upload, Download } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { TouchControlRow } from '@/components/ui/touch-control-row'
import { exportAccounts, importAccounts } from '@/api/accounts'
import { useAccountStore } from '@/stores/account'

export default function ImportExportControls() {
  const qc = useQueryClient()
  const accounts = useAccountStore((s) => s.accounts)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Export dialog state
  const [exportOpen, setExportOpen] = useState(false)
  const [selected, setSelected] = useState<Record<string, boolean>>({})
  const [passphrase, setPassphrase] = useState('')
  const [exporting, setExporting] = useState(false)

  function openExport() {
    // Default: all accounts selected.
    const all: Record<string, boolean> = {}
    for (const a of accounts) all[a.name] = true
    setSelected(all)
    setPassphrase('')
    setExportOpen(true)
  }

  const chosenNames = accounts.map((a) => a.name).filter((n) => selected[n])

  async function handleExport() {
    if (chosenNames.length === 0) {
      toast.info('Select at least one account to export.')
      return
    }
    if (!passphrase) {
      toast.info('A passphrase is required.')
      return
    }
    setExporting(true)
    try {
      const blob = await exportAccounts(chosenNames, passphrase)
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = chosenNames.length === 1 ? `${chosenNames[0]}.umaacct` : 'accounts.umaacct'
      document.body.appendChild(anchor)
      anchor.click()
      document.body.removeChild(anchor)
      URL.revokeObjectURL(url)
      setExportOpen(false)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Export failed')
    } finally {
      setExporting(false)
    }
  }

  function handleImportClick() {
    fileInputRef.current?.click()
  }

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return

    const pw = window.prompt('Passphrase to decrypt the import bundle')
    if (pw === null) {
      if (fileInputRef.current) fileInputRef.current.value = ''
      return
    }
    if (pw === '') {
      toast.info('Import cancelled — a passphrase is required.')
      if (fileInputRef.current) fileInputRef.current.value = ''
      return
    }

    try {
      const res = await importAccounts(file, pw, false)
      const imported = res.imported?.length ?? 0
      const skipped = res.skipped?.length ?? 0
      toast.success(`Imported ${imported} account${imported !== 1 ? 's' : ''}${skipped ? `, skipped ${skipped}` : ''}`)
      await qc.invalidateQueries({ queryKey: ['accounts'] })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Import failed')
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button size="sm" variant="outline" onClick={openExport} disabled={accounts.length === 0}>
        <Download className="mr-1.5 h-3.5 w-3.5" />
        Export
      </Button>
      <Button size="sm" variant="outline" onClick={handleImportClick}>
        <Upload className="mr-1.5 h-3.5 w-3.5" />
        Import
      </Button>
      <input
        ref={fileInputRef}
        type="file"
        accept=".umaacct"
        className="hidden"
        onChange={handleFileChange}
        aria-hidden
      />

      <Dialog open={exportOpen} onOpenChange={setExportOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Export accounts</DialogTitle>
          </DialogHeader>
          <DialogBody className="flex flex-col gap-3 py-1">
            <div className="flex flex-col gap-2">
              <Label>Accounts to export</Label>
              {accounts.map((a) => (
                <TouchControlRow
                  key={a.name}
                  label={a.name}
                  control={(
                    <Checkbox
                      checked={!!selected[a.name]}
                      onCheckedChange={(v) =>
                        setSelected((prev) => ({ ...prev, [a.name]: v === true }))
                      }
                    />
                  )}
                />
              ))}
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="export-passphrase">Passphrase</Label>
              <Input
                id="export-passphrase"
                type="password"
                value={passphrase}
                onChange={(e) => setPassphrase(e.target.value)}
                placeholder="Encrypts the bundle"
                autoComplete="new-password"
                onKeyDown={(e) => { if (e.key === 'Enter' && !exporting) handleExport() }}
              />
              <p className="text-xs text-muted-foreground">
                The bundle contains LIVE Steam credentials — keep it safe.
              </p>
            </div>
          </DialogBody>
          <DialogFooter>
            <Button variant="ghost" size="sm" onClick={() => setExportOpen(false)}>Cancel</Button>
            <Button
              size="sm"
              disabled={exporting || chosenNames.length === 0 || !passphrase}
              onClick={handleExport}
            >
              {exporting ? 'Exporting…' : `Export ${chosenNames.length || ''}`.trim()}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
