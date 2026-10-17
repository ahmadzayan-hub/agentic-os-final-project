/* Formatting shared by more than one view. Numbers go through the
   locale's own formatter (`useI18n().formatNumber`), so digits and
   separators match the interface language. */

type FormatNumber = (value: number, options?: Intl.NumberFormatOptions) => string

/** A size in decimal units. The unit symbols stay Latin in both
 *  languages: they are symbols, not words. */
export function formatBytes(bytes: number, formatNumber: FormatNumber): string {
  if (bytes < 1000) return `${formatNumber(bytes)} B`
  if (bytes < 1_000_000) return `${formatNumber(bytes / 1000, { maximumFractionDigits: 1 })} kB`
  return `${formatNumber(bytes / 1_000_000, { maximumFractionDigits: 1 })} MB`
}
