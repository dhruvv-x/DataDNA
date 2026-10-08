import { formatPoints, trustGaugeColor } from '../lib/format'

/** Ring with the number inside. total null = no score yet. */
export function ScoreGauge({ total, size = 120 }: { total: number | null; size?: number }) {
  const r = 52
  const circ = 2 * Math.PI * r
  const pct = total === null ? 0 : Math.max(0, Math.min(100, total))
  const color = total === null ? 'var(--border)' : trustGaugeColor(total)
  return (
    <svg width={size} height={size} viewBox="0 0 120 120" role="img" aria-label={total === null ? 'No score yet' : `Score ${formatPoints(total)} out of 100`}>
      <circle cx="60" cy="60" r={r} fill="none" stroke="var(--border)" strokeWidth="10" />
      <circle
        cx="60" cy="60" r={r} fill="none" stroke={color} strokeWidth="10" strokeLinecap="round"
        strokeDasharray={`${(pct / 100) * circ} ${circ}`} transform="rotate(-90 60 60)"
      />
      <text x="60" y={total === null ? 66 : 68} textAnchor="middle" fontSize={total === null ? 16 : 28} fontWeight="700" fill={color === 'var(--border)' ? 'var(--text)' : color}>
        {total === null ? 'No score' : formatPoints(total)}
      </text>
      {total !== null && <text x="60" y="86" textAnchor="middle" fontSize="11" fill="var(--text)">out of 100</text>}
    </svg>
  )
}
