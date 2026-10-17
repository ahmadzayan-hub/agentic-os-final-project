import { describe, expect, it } from 'vitest'
import { barGeometry } from '../shared/charts'

describe('barGeometry', () => {
  it('draws all-positive bars up from a zero line at the bottom', () => {
    const { zero, bars } = barGeometry([10, 5], 4, 50)
    expect(zero).toBe(50)
    expect(bars[0]).toEqual({ y: 4, height: 46, negative: false })
    expect(bars[1].height).toBeCloseTo(23)
  })

  it('draws negative bars down from zero instead of losing them', () => {
    const { zero, bars } = barGeometry([30, -10], 4, 50)
    // 30 of the 40-unit span sits above zero: three quarters of the band.
    expect(zero).toBeCloseTo(4 + 46 * 0.75)
    expect(bars[1].negative).toBe(true)
    expect(bars[1].y).toBeCloseTo(zero)
    expect(bars[1].height).toBeGreaterThan(0)
    expect(bars[1].height).toBeCloseTo(46 * 0.25)
  })

  it('handles all-negative and all-zero values', () => {
    expect(barGeometry([-4, -2], 4, 50).zero).toBe(4)
    const flat = barGeometry([0, 0], 4, 50)
    expect(flat.bars.every((bar) => bar.height === 0)).toBe(true)
  })
})
