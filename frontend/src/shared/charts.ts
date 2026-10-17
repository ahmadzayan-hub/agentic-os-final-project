/* Geometry for the hand-drawn SVG charts. Kept apart from the components
   so that the arithmetic a reader trusts can be tested on its own. */

/** Bars measured from zero in both directions, inside a band from `top`
 *  to `bottom` (SVG units, y grows downwards). A contribution chart holds
 *  decreases as well as increases; a bar drawn up from the bottom edge
 *  would give a negative value a negative height, and it would vanish. */
export function barGeometry(values: number[], top = 4, bottom = 50) {
  const max = Math.max(...values, 0)
  const min = Math.min(...values, 0)
  const span = max - min || 1
  const zero = top + (max / span) * (bottom - top)
  return {
    zero,
    bars: values.map((value) => {
      const height = (Math.abs(value) / span) * (bottom - top)
      return { y: value >= 0 ? zero - height : zero, height, negative: value < 0 }
    }),
  }
}
