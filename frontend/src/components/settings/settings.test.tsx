/**
 * Tests for Settings components (Task 14).
 *
 * Coverage:
 *   1. masterDataStatusText — pure function, all 4 branches
 *   2. MasterDataCard — renders; prefills path from status response
 *   3. WebhookCard — renders and saves webhook and career-error ping settings
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react'

// ---------------------------------------------------------------------------
// Pure function tests — no React needed
// ---------------------------------------------------------------------------

import { masterDataStatusText } from './masterDataStatus'
import type { MasterDataStatus } from '@/api/types'

describe('masterDataStatusText', () => {
  it('exists && generation_error → warn with error text', () => {
    const data: MasterDataStatus = {
      exists: true,
      generation_error: 'Schema mismatch',
    }
    const result = masterDataStatusText(data)
    expect(result.text).toBe('Schema mismatch')
    expect(result.kind).toBe('warn')
  })

  it('exists && generated (no error) → ok "master.mdb found; data generated"', () => {
    const data: MasterDataStatus = { exists: true, generated: true }
    const result = masterDataStatusText(data)
    expect(result.text).toBe('master.mdb found; data generated')
    expect(result.kind).toBe('ok')
  })

  it('exists but not generated and no error → ok "master.mdb found"', () => {
    const data: MasterDataStatus = { exists: true }
    const result = masterDataStatusText(data)
    expect(result.text).toBe('master.mdb found')
    expect(result.kind).toBe('ok')
  })

  it('!exists with access_error → warn with access_error text', () => {
    const data: MasterDataStatus = {
      exists: false,
      access_error: 'Permission denied',
    }
    const result = masterDataStatusText(data)
    expect(result.text).toBe('Permission denied')
    expect(result.kind).toBe('warn')
  })

  it('!exists without access_error → warn with default message', () => {
    const data: MasterDataStatus = { exists: false }
    const result = masterDataStatusText(data)
    expect(result.text).toBe('master.mdb not found; update the path')
    expect(result.kind).toBe('warn')
  })
})

// ---------------------------------------------------------------------------
// Mock api/settings before importing components
// ---------------------------------------------------------------------------

vi.mock('@/api/settings', () => ({
  getMasterDataStatus: vi.fn(),
  setMasterDataPath: vi.fn(),
  getDiscordWebhook: vi.fn(),
  saveDiscordWebhook: vi.fn(),
  testDiscordWebhook: vi.fn(),
  getTurnDelay: vi.fn(),
  saveTurnDelay: vi.fn(),
}))

// Also mock sonner so toast calls don't error in jsdom
vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
  },
}))

import * as settingsApi from '@/api/settings'
import { MasterDataCard } from './MasterDataCard'
import { ThemeCard } from './ThemeCard'
import { WebhookCard } from './WebhookCard'

// ---------------------------------------------------------------------------
// MasterDataCard — render tests
// ---------------------------------------------------------------------------

describe('MasterDataCard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('prefills path input with master_mdb_path from status response', async () => {
    vi.mocked(settingsApi.getMasterDataStatus).mockResolvedValue({
      master_mdb_path: 'C:\\games\\master.mdb',
      exists: true,
      generated: true,
    })

    render(<MasterDataCard />)

    await waitFor(() => {
      const input = screen.getByPlaceholderText(/master\.mdb/i) as HTMLInputElement
      expect(input.value).toBe('C:\\games\\master.mdb')
      expect(input.placeholder).toBe('/path/to/master.mdb')
    })
  })

  it('shows status text "master.mdb found; data generated" when exists+generated', async () => {
    vi.mocked(settingsApi.getMasterDataStatus).mockResolvedValue({
      exists: true,
      generated: true,
    })

    render(<MasterDataCard />)

    await waitFor(() => {
      expect(screen.getByText('master.mdb found; data generated')).toBeInTheDocument()
    })
  })

  it('shows warn status when !exists', async () => {
    vi.mocked(settingsApi.getMasterDataStatus).mockResolvedValue({
      exists: false,
      access_error: 'File not found at path',
    })

    render(<MasterDataCard />)

    await waitFor(() => {
      expect(screen.getByText('File not found at path')).toBeInTheDocument()
    })
  })

  it('shows error status when getMasterDataStatus rejects', async () => {
    vi.mocked(settingsApi.getMasterDataStatus).mockRejectedValue(new Error('network'))

    render(<MasterDataCard />)

    await waitFor(() => {
      expect(screen.getByText(/unable to read master data status/i)).toBeInTheDocument()
    })
  })
})

// ---------------------------------------------------------------------------
// WebhookCard — render and save tests
// ---------------------------------------------------------------------------

describe('WebhookCard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('keeps the input empty and shows the redacted configured webhook', async () => {
    vi.mocked(settingsApi.getDiscordWebhook).mockResolvedValue({
      configured: true,
      webhook_preview: 'https://discord.com/api/webhooks/123/••••••••',
    })

    render(<WebhookCard />)

    await waitFor(() => {
      const input = screen.getByPlaceholderText(/discord\.com/i) as HTMLInputElement
      expect(input.value).toBe('')
      expect(
        screen.getByText('Configured: https://discord.com/api/webhooks/123/••••••••'),
      ).toBeInTheDocument()
    })
  })

  it('shows the configured state when configured=true without a preview', async () => {
    vi.mocked(settingsApi.getDiscordWebhook).mockResolvedValue({
      configured: true,
    })

    render(<WebhookCard />)

    await waitFor(() => {
      expect(screen.getByText('Configured: URL hidden')).toBeInTheDocument()
    })
  })

  it('shows "Not configured" when configured=false', async () => {
    vi.mocked(settingsApi.getDiscordWebhook).mockResolvedValue({
      configured: false,
    })

    render(<WebhookCard />)

    await waitFor(() => {
      expect(screen.getByText('Not configured')).toBeInTheDocument()
    })
  })

  it('SAVE calls saveDiscordWebhook with trimmed value', async () => {
    vi.mocked(settingsApi.getDiscordWebhook).mockResolvedValue({ configured: false })
    vi.mocked(settingsApi.saveDiscordWebhook).mockResolvedValue({ configured: true })

    render(<WebhookCard />)

    // Wait for mount to settle
    await waitFor(() => screen.getByText('Not configured'))

    const input = screen.getByPlaceholderText(/discord\.com/i)
    await act(async () => {
      fireEvent.change(input, {
        target: { value: '  https://discord.com/api/webhooks/999/xyz  ' },
      })
    })

    const saveBtn = screen.getByRole('button', { name: /save webhook/i })
    await act(async () => {
      fireEvent.click(saveBtn)
    })

    await waitFor(() => {
      expect(settingsApi.saveDiscordWebhook).toHaveBeenCalledWith({
        webhook_url: 'https://discord.com/api/webhooks/999/xyz',
      })
    })
  })

  it('an untouched configured form cannot wipe the webhook', async () => {
    vi.mocked(settingsApi.getDiscordWebhook).mockResolvedValue({
      configured: true,
      webhook_preview: 'https://discord.com/api/webhooks/123/••••••••',
    })

    render(<WebhookCard />)
    await waitFor(() => screen.getByRole('button', { name: /remove webhook/i }))

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /save webhook/i }))
    })

    expect(settingsApi.saveDiscordWebhook).not.toHaveBeenCalled()
    expect(screen.getByText('Enter a new URL or use Remove webhook.')).toBeInTheDocument()
  })

  it('removes a configured webhook only through the remove action', async () => {
    vi.mocked(settingsApi.getDiscordWebhook).mockResolvedValue({
      configured: true,
      webhook_preview: 'https://discord.com/api/webhooks/123/••••••••',
    })
    vi.mocked(settingsApi.saveDiscordWebhook).mockResolvedValue({ configured: false })

    render(<WebhookCard />)
    await waitFor(() => screen.getByRole('button', { name: /remove webhook/i }))

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /remove webhook/i }))
    })

    await waitFor(() => {
      expect(settingsApi.saveDiscordWebhook).toHaveBeenCalledWith({ webhook_url: '' })
      expect(screen.getByText('Webhook removed')).toBeInTheDocument()
      expect(screen.getByText('Not configured')).toBeInTheDocument()
    })
  })

  it('saves a career-error ping target through the webhook settings flow', async () => {
    vi.mocked(settingsApi.getDiscordWebhook).mockResolvedValue({ configured: false })
    vi.mocked(settingsApi.saveDiscordWebhook).mockResolvedValue({
      configured: false,
      error_mention: '<@&12345678901234567>',
    })

    render(<WebhookCard />)
    await waitFor(() => screen.getByText('Not configured'))

    const input = screen.getByLabelText('Career error ping target')
    await act(async () => {
      fireEvent.change(input, {
        target: { value: '  <@&12345678901234567>  ' },
      })
    })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /save error ping/i }))
    })

    await waitFor(() => {
      expect(settingsApi.saveDiscordWebhook).toHaveBeenCalledWith({
        error_mention: '<@&12345678901234567>',
      })
      expect(screen.getByText('Career error ping saved')).toBeInTheDocument()
    })
  })

  it('shows the backend validation error for a bad career-error ping target', async () => {
    vi.mocked(settingsApi.getDiscordWebhook).mockResolvedValue({ configured: false })
    vi.mocked(settingsApi.saveDiscordWebhook).mockRejectedValue(
      new Error('Enter a 17-20 digit Discord user ID, user mention, or role mention.'),
    )

    render(<WebhookCard />)
    await waitFor(() => screen.getByText('Not configured'))

    await act(async () => {
      fireEvent.change(screen.getByLabelText('Career error ping target'), {
        target: { value: '@everyone' },
      })
      fireEvent.click(screen.getByRole('button', { name: /save error ping/i }))
    })

    await waitFor(() => {
      expect(
        screen.getByText('Enter a 17-20 digit Discord user ID, user mention, or role mention.'),
      ).toBeInTheDocument()
    })
  })

  it('wraps webhook actions so all controls remain in the card on phones', async () => {
    vi.mocked(settingsApi.getDiscordWebhook).mockResolvedValue({ configured: true })

    render(<WebhookCard />)
    await waitFor(() => screen.getByRole('button', { name: /remove webhook/i }))

    expect(screen.getByTestId('webhook-actions')).toHaveClass('flex-wrap')
  })
})

describe('ThemeCard', () => {
  it('gives each theme choice a phone touch target and restores compact md spacing', () => {
    render(<ThemeCard />)

    for (const name of ['light', 'dark']) {
      const label = screen.getByRole('radio', { name }).closest('label')
      expect(label).toHaveClass(
        'min-h-11',
        'px-3',
        'py-2',
        'md:min-h-0',
        'md:px-0',
        'md:py-0',
      )
    }
  })
})

describe('settings mobile form contracts', () => {
  it('keeps each label and input in a vertically stacked phone wrapper', () => {
    vi.mocked(settingsApi.getMasterDataStatus).mockResolvedValue({ exists: false })
    vi.mocked(settingsApi.getDiscordWebhook).mockResolvedValue({ configured: false })

    render(
      <>
        <MasterDataCard />
        <WebhookCard />
      </>,
    )

    for (const input of [
      screen.getByLabelText('Path to master.mdb'),
      screen.getByLabelText('Webhook URL'),
      screen.getByLabelText('Career error ping target'),
    ]) {
      expect(input.parentElement).toHaveClass('space-y-1.5')
      expect(input.parentElement?.querySelector('label')).toBeInTheDocument()
    }
  })
})
