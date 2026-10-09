import type { QueryStep } from '../api/types'
import { QUERY_ACTION_LABEL, ROLE_LABEL, formatDateTime } from '../lib/format'
import { Badge } from './Feedback'

/** Every step of a query, oldest first. Nothing in it can be edited. */
export function QueryTimeline({ steps }: { steps: QueryStep[] }) {
  return (
    <ol className="timeline" aria-label="Steps of this query">
      {steps.map((s) => (
        <li key={s.id} className="card">
          <div>
            <strong>{s.actor_name}</strong> <span className="muted small">({ROLE_LABEL[s.actor_role]})</span>{' '}
            {QUERY_ACTION_LABEL[s.action]}
            {s.outcome && <> <Badge tone={s.outcome === 'OVERTURNED' ? 'good' : 'muted'}>{s.outcome === 'OVERTURNED' ? 'Flag overturned' : 'Flag stays'}</Badge></>}
            {s.override && <> <Badge tone="info">Dean stepped in at HOD level</Badge></>}
          </div>
          <p className="query-message">{s.message}</p>
          <div className="muted small">{formatDateTime(s.created_at)}</div>
        </li>
      ))}
    </ol>
  )
}
