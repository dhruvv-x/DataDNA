import type { SnapshotRow } from '../api/types'

/** Score over time, oldest on the left. Only snapshots that have a number are drawn. */
export function Sparkline({ snapshots }: { snapshots: SnapshotRow[] }) {
  const pts = [...snapshots].reverse().filter((s) => s.total !== null)
  if (pts.length < 2) return <p className="muted small">Not enough changes yet to draw a line.</p>
  const w = 320
  const h = 70
  const xy = pts.map((s, i) => `${(i / (pts.length - 1)) * (w - 10) + 5},${h - 5 - ((s.total as number) / 100) * (h - 10)}`)
  return (
    <svg width="100%" viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Score history" className="sparkline">
      <line x1="0" y1={h - 5} x2={w} y2={h - 5} stroke="var(--border)" />
      <polyline points={xy.join(' ')} fill="none" stroke="var(--accent)" strokeWidth="2" />
    </svg>
  )
}
