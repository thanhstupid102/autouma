import { useState } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { SparkFilterBar } from './SparkFilterBar'
import {
  EMPTY_SPARK_FILTER,
  type SparkColourOptions,
  type SparkFilter,
} from './sparkFilter'

const options: SparkColourOptions = {
  blue: ['Speed', 'Stamina'],
  pink: ['Turf'],
  green: ['Arc Maestro'],
  white: ['Corner Recovery', 'Straightaway Adept', 'Some Race'],
}

function optionValues(select: HTMLSelectElement): string[] {
  return Array.from(select.options).map((option) => option.value)
}

describe('SparkFilterBar', () => {
  it('hides configured factor groups while keeping their total stepper', () => {
    const onChange = vi.fn()
    const value: SparkFilter = {
      ...EMPTY_SPARK_FILTER,
      conditions: [{ colour: 'green', name: 'Arc Maestro', mode: 'atleast', minStars: 2 }],
    }

    render(
      <SparkFilterBar
        value={value}
        onChange={onChange}
        options={options}
        hideFactorColours={['green']}
      />,
    )

    expect(screen.queryByTestId('spark-add-green')).not.toBeInTheDocument()
    expect(screen.queryByDisplayValue('Arc Maestro')).not.toBeInTheDocument()
    expect(screen.getByTestId('spark-minGreen')).toBeInTheDocument()

    fireEvent.change(screen.getByTestId('spark-minGreen'), { target: { value: '2' } })

    expect(onChange).toHaveBeenCalledWith({
      ...value,
      minGreen: 2,
      conditions: [],
    })
  })

  it('excludes names already used by sibling rows of the same colour', () => {
    const value: SparkFilter = {
      ...EMPTY_SPARK_FILTER,
      conditions: [
        { colour: 'white', name: 'Corner Recovery', mode: 'include', minStars: 1 },
        { colour: 'white', name: 'Straightaway Adept', mode: 'include', minStars: 1 },
      ],
    }

    render(<SparkFilterBar value={value} onChange={vi.fn()} options={options} />)

    const secondNameSelect = screen.getByTestId('spark-condition-name-1') as HTMLSelectElement
    const names = optionValues(secondNameSelect)

    expect(names).not.toContain('Corner Recovery')
    expect(names).toContain('Straightaway Adept')
    expect(names).toContain('Some Race')
  })

  it('defaults new rows to the first unused name and disables Add when exhausted', () => {
    const onChange = vi.fn()
    const value: SparkFilter = {
      ...EMPTY_SPARK_FILTER,
      conditions: [{ colour: 'white', name: 'Corner Recovery', mode: 'include', minStars: 1 }],
    }

    const { rerender } = render(<SparkFilterBar value={value} onChange={onChange} options={options} />)

    fireEvent.click(screen.getByTestId('spark-add-white'))

    expect(onChange).toHaveBeenCalledWith({
      ...value,
      conditions: [
        ...value.conditions,
        { colour: 'white', name: 'Straightaway Adept', mode: 'atleast', minStars: 1 },
      ],
    })

    rerender(
      <SparkFilterBar
        value={{
          ...EMPTY_SPARK_FILTER,
          conditions: options.white.map((name) => ({
            colour: 'white',
            name,
            mode: 'include',
            minStars: 1,
          })),
        }}
        onChange={onChange}
        options={options}
      />,
    )

    expect(screen.getByTestId('spark-add-white')).toBeDisabled()
  })

  it('offers >= / not and keeps the star editable except in not mode', () => {
    function Harness() {
      const [filter, setFilter] = useState<SparkFilter>(EMPTY_SPARK_FILTER)
      return <SparkFilterBar value={filter} onChange={setFilter} options={options} />
    }

    render(<Harness />)

    fireEvent.click(screen.getByTestId('spark-add-blue'))

    const modeSelect = screen.getByTestId('spark-condition-mode-0') as HTMLSelectElement
    expect(Array.from(modeSelect.options).map((option) => [option.value, option.textContent])).toEqual([
      ['atleast', '≥'],
      ['exclude', 'not'],
    ])

    // New rows default to >= with the star selector editable.
    expect(screen.getByTestId('spark-condition-stars-0')).not.toBeDisabled()

    fireEvent.change(modeSelect, { target: { value: 'exclude' } })
    expect(screen.getByTestId('spark-condition-stars-0')).toBeDisabled()

    fireEvent.change(screen.getByTestId('spark-condition-mode-0'), { target: { value: 'atleast' } })
    expect(screen.getByTestId('spark-condition-stars-0')).not.toBeDisabled()
  })

  it('stacks condition fields below md and restores the compact row at md', () => {
    function Harness() {
      const [filter, setFilter] = useState<SparkFilter>(EMPTY_SPARK_FILTER)
      return <SparkFilterBar value={filter} onChange={setFilter} options={options} />
    }

    render(<Harness />)
    fireEvent.click(screen.getByTestId('spark-add-blue'))

    const row = screen.getByTestId('spark-condition-0')
    const name = screen.getByTestId('spark-condition-name-0')
    expect(row).toHaveClass('grid-cols-1', 'md:grid-cols-[1fr_auto_auto_auto]')
    expect(name).toHaveClass('h-11', 'w-full', 'text-base', 'md:h-7', 'md:w-auto', 'md:text-xs')
  })
})
