/** The dashboard's charts (ADR 0032): drawn as SVG or plain boxes from
 *  design tokens, no library. Each is an image with a text alternative;
 *  the numbers, and the way to the rows behind them, are in the table
 *  that every chart carries. Axes read left to right in both languages. */
import type { ReactNode } from 'react'
import { useI18n } from '../../i18n'
import { usePack } from '../../i18n/pack'
import { dashMessages } from './messages'

export interface Point {
  label: string
  value: number | null
}

function span(values: number[]) {
  const max = Math.max(0, ...values)
  const min = Math.min(0, ...values)
  return { min, max, range: max - min || 1 }
}

/** A figure: its title, the chart, and the same numbers as a table. */
export function Figure({ title, chart, table, open = false }: {
  title: string
  chart: ReactNode
  table: ReactNode
  open?: boolean
}) {
  const { t, isRtl } = usePack(dashMessages)
  return (
    <figure className="dash-figure">
      <figcaption className="field__label" dir="auto">
        {title}
      </figcaption>
      <div dir="ltr">{chart}</div>
      <details className="runchart__data" dir={isRtl ? 'rtl' : 'ltr'} open={open}>
        <summary>{t('dash.numbers')}</summary>
        <div className="evidence__table">{table}</div>
      </details>
    </figure>
  )
}

/** Horizontal bars from a zero line, largest first as given. */
export function Bars({ items, label }: { items: Point[]; label: string }) {
  const { formatNumber } = useI18n()
  const values = items.map((item) => item.value ?? 0)
  const { min, range } = span(values)
  const zero = (-min / range) * 100
  return (
    <div className="dash-bars" role="img" aria-label={label}>
      {items.map((item, index) => {
        const value = values[index]
        const width = (Math.abs(value) / range) * 100
        return (
          <div className="dash-bars__row" key={`${item.label}-${index}`}>
            <span className="dash-bars__label" dir="auto">
              {item.label || '—'}
            </span>
            <span className="dash-bars__track">
              <span
                className={`dash-bars__fill${value < 0 ? ' dash-bars__fill--negative' : ''}`}
                style={{ insetInlineStart: `${value < 0 ? zero - width : zero}%`, width: `${width}%` }}
              />
            </span>
            <span className="dash-bars__value">{item.value === null ? '—' : formatNumber(item.value, { maximumFractionDigits: 2 })}</span>
          </div>
        )
      })}
    </div>
  )
}

/** A line over periods; empty periods break the line. */
export function Line({ points, label }: { points: Point[]; label: string }) {
  const { formatNumber } = useI18n()
  const values = points.map((p) => p.value).filter((v): v is number => v !== null)
  const { min, max, range } = span(values)
  const x = (index: number) => (points.length > 1 ? (index / (points.length - 1)) * 92 + 6 : 50)
  const y = (value: number) => 46 - ((value - min) / range) * 40
  const segments: string[][] = [[]]
  points.forEach((point, index) => {
    if (point.value === null) segments.push([])
    else segments[segments.length - 1].push(`${x(index)},${y(point.value)}`)
  })
  return (
    <svg viewBox="0 0 100 58" role="img" aria-label={label} className="dash-svg">
      <line x1="6" y1={y(0)} x2="98" y2={y(0)} stroke="var(--border-strong)" strokeWidth="0.4" />
      {segments.filter((s) => s.length > 1).map((segment, index) => (
        <polyline key={index} points={segment.join(' ')} fill="none" stroke="var(--accent-solid)" strokeWidth="1.2" />
      ))}
      {points.length <= 40
        ? points.map((point, index) =>
            point.value === null ? null : (
              <circle key={index} cx={x(index)} cy={y(point.value)} r="0.9" fill="var(--accent-solid)" />
            ),
          )
        : null}
      <text x="5" y={y(max) + 1} fontSize="3" textAnchor="end" fill="var(--text-faint)">
        {formatNumber(max, { notation: 'compact' })}
      </text>
      <text x="6" y="55" fontSize="3.2" fill="var(--text-faint)">
        {points[0]?.label}
      </text>
      <text x="98" y="55" fontSize="3.2" textAnchor="end" fill="var(--text-faint)">
        {points[points.length - 1]?.label}
      </text>
    </svg>
  )
}

/** Counts per equal-width bin. */
export function Histogram({ bins, label }: { bins: Array<{ from: number; to: number; count: number }>; label: string }) {
  const { formatNumber } = useI18n()
  const max = Math.max(1, ...bins.map((b) => b.count))
  const width = 92 / Math.max(bins.length, 1)
  return (
    <svg viewBox="0 0 100 58" role="img" aria-label={label} className="dash-svg">
      {bins.map((bin, index) => {
        const height = (bin.count / max) * 44
        return (
          <rect key={index} x={6 + index * width + width * 0.08} y={48 - height} width={width * 0.84}
            height={height} fill="var(--accent-solid)" rx="0.6" />
        )
      })}
      <line x1="6" y1="48" x2="98" y2="48" stroke="var(--border-strong)" strokeWidth="0.4" />
      <text x="6" y="55" fontSize="3.2" fill="var(--text-faint)">
        {bins.length ? formatNumber(bins[0].from, { notation: 'compact' }) : ''}
      </text>
      <text x="98" y="55" fontSize="3.2" textAnchor="end" fill="var(--text-faint)">
        {bins.length ? formatNumber(bins[bins.length - 1].to, { notation: 'compact' }) : ''}
      </text>
    </svg>
  )
}

/** One point per sampled record. */
export function Scatter({ points, label }: { points: Array<{ x: number; y: number }>; label: string }) {
  const { formatNumber } = useI18n()
  const xs = span(points.map((p) => p.x))
  const ys = span(points.map((p) => p.y))
  return (
    <svg viewBox="0 0 100 58" role="img" aria-label={label} className="dash-svg">
      <line x1="6" y1="48" x2="98" y2="48" stroke="var(--border-strong)" strokeWidth="0.4" />
      <line x1="6" y1="4" x2="6" y2="48" stroke="var(--border-strong)" strokeWidth="0.4" />
      {points.map((point, index) => (
        <circle key={index} cx={6 + ((point.x - xs.min) / xs.range) * 92} cy={48 - ((point.y - ys.min) / ys.range) * 44}
          r="0.8" fill="var(--accent-solid)" fillOpacity="0.55" />
      ))}
      <text x="6" y="55" fontSize="3.2" fill="var(--text-faint)">{formatNumber(xs.min, { notation: 'compact' })}</text>
      <text x="98" y="55" fontSize="3.2" textAnchor="end" fill="var(--text-faint)">{formatNumber(xs.max, { notation: 'compact' })}</text>
      <text x="5" y="6" fontSize="3" textAnchor="end" fill="var(--text-faint)">{formatNumber(ys.max, { notation: 'compact' })}</text>
    </svg>
  )
}
