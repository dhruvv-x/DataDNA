import type { Part, PartScore } from '../api/types'
import { PARTS } from '../api/types'
import { PART_LABEL, formatPoints } from '../lib/format'

export function PartBars({ parts }: { parts: Record<Part, PartScore> }) {
  return (
    <div className="parts">
      {PARTS.map((p) => {
        const part = parts[p]
        const off = part.effective_weight === 0
        const fill = off || part.points === null ? 0 : Math.min(100, (part.points / part.effective_weight) * 100)
        return (
          <div className="part" key={p}>
            <div className="part-head">
              <strong>{PART_LABEL[p]}</strong>
              <span>
                {off ? 'Off (not scored yet)' : `${formatPoints(part.points)} of ${formatPoints(part.effective_weight)}`}
              </span>
            </div>
            <div className="bar" aria-hidden="true"><div className="bar-fill" style={{ width: `${fill}%` }} /></div>
            {!off && part.lost !== null && part.lost > 0 && <div className="muted small">Lost {formatPoints(part.lost)} points</div>}
          </div>
        )
      })}
    </div>
  )
}
