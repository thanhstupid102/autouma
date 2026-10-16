export const DISPLAY_LOCALE = 'en-US'

const numberFormatter = new Intl.NumberFormat(DISPLAY_LOCALE, {
  style: 'decimal',
  useGrouping: true,
  maximumFractionDigits: 3,
})

const displayCollator = new Intl.Collator(DISPLAY_LOCALE, {
  usage: 'sort',
  sensitivity: 'variant',
  ignorePunctuation: false,
  numeric: false,
  caseFirst: 'false',
})

export function formatNumber(value: number): string {
  return numberFormatter.format(value)
}

export function compareDisplayText(left: string, right: string): number {
  return displayCollator.compare(left, right)
}
