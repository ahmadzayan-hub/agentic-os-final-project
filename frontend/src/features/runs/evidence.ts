export interface CalculationRow { name: string; value: string; method: string }

/** Read the report's own calculation tables. Do not infer an ID-to-row
 * mapping: the present API exposes references and tables separately. */
export function reportCalculations(report: string): CalculationRow[] {
  const rows: CalculationRow[] = []
  const seen = new Set<string>()
  let inTable = false
  for (const line of report.split('\n')) {
    const cells = line.trim().replace(/^\|/, '').replace(/\|$/, '').split(/(?<!\\)\|/).map((cell) => cell.trim())
    if (cells.length !== 3) { inTable = false; continue }
    if (/^(Figure|Metric|Measure|الرقم|المقياس|المؤشر)$/i.test(cells[0]) && /^(Value|القيمة)$/i.test(cells[1]) && /^(Method|الطريقة)$/i.test(cells[2])) { inTable = true; continue }
    if (!inTable || cells.every((cell) => /^:?-+:?$/.test(cell))) continue
    const key = cells.join('\u0000')
    if (!seen.has(key)) { rows.push({ name: cells[0], value: cells[1], method: cells[2] }); seen.add(key) }
  }
  return rows
}
