/**
 * GridSearch — small search input for client-side filtering per grid section.
 */

import { Input } from '@/components/ui/input'

interface GridSearchProps {
  value: string
  onChange: (v: string) => void
  placeholder?: string
}

export function GridSearch({ value, onChange, placeholder = 'Search…' }: GridSearchProps) {
  return (
    <Input
      type="search"
      value={value}
      onChange={e => onChange(e.target.value)}
      placeholder={placeholder}
      className="w-full text-base md:h-7 md:w-40 md:text-xs"
      aria-label={placeholder}
    />
  )
}
