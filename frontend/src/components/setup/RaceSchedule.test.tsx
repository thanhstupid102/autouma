import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { RaceSchedule } from './RaceSchedule'

const LONG_RACE_NAME = 'Tokyo Sports Hai Junior Stakes'

const mocks = vi.hoisted(() => ({
  racePresetsStore: {
    selectedName: 'Mobile schedule',
    getActive: vi.fn(),
    saveRaces: vi.fn(),
  },
  toastError: vi.fn(),
}))

vi.mock('@/stores/racePresets', () => ({
  useRacePresets: () => mocks.racePresetsStore,
}))
vi.mock('sonner', () => ({
  toast: { error: mocks.toastError },
}))

beforeEach(() => {
  vi.clearAllMocks()
  mocks.racePresetsStore.getActive.mockReturnValue({
    name: 'Mobile schedule',
    extra_race_list: [],
  })
  mocks.racePresetsStore.saveRaces.mockResolvedValue(undefined)
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      json: vi.fn().mockResolvedValue({
        races: [
          {
            id: 100635,
            name: LONG_RACE_NAME,
            date: 'Junior Year Early Jan',
            type: 'G3',
            terrain: 'Turf',
            distance: 'Mile',
          },
        ],
      }),
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('RaceSchedule mobile layout', () => {
  it('keeps four readable columns, contains a long real race name, and still saves it', async () => {
    render(<RaceSchedule />)

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
    const juniorHeading = screen.getByRole('heading', { name: 'Junior Year' })
    const juniorBlock = juniorHeading.parentElement!
    const earlyJanuary = within(juniorBlock).getByRole('button', { name: /Early Jan/ })
    const grid = earlyJanuary.parentElement

    expect(grid).toHaveClass(
      'min-w-0',
      'max-w-full',
      'grid-cols-4',
      'sm:grid-cols-6',
      'md:grid-cols-8',
    )
    expect(earlyJanuary).toHaveClass(
      'min-h-24',
      'min-w-0',
      'max-w-full',
      'overflow-hidden',
      'md:min-h-[72px]',
    )
    expect(within(earlyJanuary).getByText('Early Jan')).toHaveClass(
      'text-[11px]',
      'md:text-[9px]',
    )

    fireEvent.click(earlyJanuary)
    const raceButton = await screen.findByRole('button', { name: new RegExp(LONG_RACE_NAME) })
    fireEvent.click(raceButton)
    fireEvent.click(screen.getByRole('button', { name: 'Done' }))

    const selectedName = within(juniorBlock).getByText(LONG_RACE_NAME)
    expect(selectedName).toHaveClass(
      'line-clamp-2',
      'max-w-full',
      'break-words',
      'text-xs',
      'md:line-clamp-1',
      'md:text-[9px]',
    )
    expect(selectedName.closest('button')).toHaveClass(
      'min-w-0',
      'max-w-full',
      'overflow-hidden',
    )

    fireEvent.click(screen.getByRole('button', { name: 'SAVE RACES' }))
    await waitFor(() =>
      expect(mocks.racePresetsStore.saveRaces).toHaveBeenCalledWith(
        'Mobile schedule',
        [100635],
      ),
    )
  })
})
