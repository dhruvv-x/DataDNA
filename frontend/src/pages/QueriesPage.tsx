import { Link, useSearchParams } from 'react-router-dom'
import { listQueries } from '../api/endpoints'
import type { QueryStatus } from '../api/types'
import { useAuth } from '../auth/context'
import { SelectField } from '../components/Fields'
import { Badge, ErrorBox, Loading } from '../components/Feedback'
import { KIND_LABEL, QUERY_STATUS_LABEL, formatDateTime, queryStatusText, queryTone } from '../lib/format'
import { useAsync } from '../lib/useAsync'

const STATUS_OPTIONS = (Object.keys(QUERY_STATUS_LABEL) as QueryStatus[]).map((s) => ({ value: s, label: QUERY_STATUS_LABEL[s] }))

/** Faculty: their own queries. HOD: the department's. Dean: everyone's. The server limits the list. */
export function QueriesPage() {
  const { user } = useAuth()
  const [params, setParams] = useSearchParams()
  const waiting = params.get('waiting') === '1'
  const status = (params.get('status') ?? '') as QueryStatus | ''

  const list = useAsync(
    () => listQueries({ status: status || undefined, waiting_for_me: waiting, limit: 200 }),
    `queries:${status}|${waiting}`,
  )
  if (!user) return null

  function change(next: { waiting?: boolean; status?: string }) {
    const p = new URLSearchParams(params)
    if (next.waiting !== undefined) {
      if (next.waiting) p.set('waiting', '1')
      else p.delete('waiting')
    }
    if (next.status !== undefined) {
      if (next.status) p.set('status', next.status)
      else p.delete('status')
    }
    setParams(p, { replace: true })
  }

  const rows = list.data?.queries ?? []
  const filtered = waiting || status !== ''

  return (
    <>
      <p><Link to="/">&larr; Back to dashboard</Link></p>
      <h1>Queries</h1>
      <p className="muted">
        A query is a faculty member saying a flag is wrong. The HOD looks first, the Dean decides if the HOD cannot.
        Every step is recorded.
      </p>

      <div className="toolbar" role="group" aria-label="Filters">
        <SelectField label="Status" value={status} onChange={(v) => change({ status: v })} placeholder="Any status" options={STATUS_OPTIONS} />
        <div className="field">
          <span>Show</span>
          <button type="button" className="btn" aria-pressed={waiting} onClick={() => change({ waiting: !waiting })}>
            Waiting for me
          </button>
        </div>
      </div>

      {list.error && <ErrorBox message={list.error} onRetry={list.reload} />}
      {list.loading && !list.data && <Loading />}
      {list.data && rows.length === 0 && (
        <div className="card">
          <p>
            {filtered
              ? 'No queries match these filters.'
              : user.role === 'FACULTY'
                ? 'You have not raised any query. If a flag on your course file is wrong, open it there and choose "Dispute this flag".'
                : 'No queries yet.'}
          </p>
        </div>
      )}
      {list.data && rows.length > 0 && (
        <>
          <p className="muted small">Showing {rows.length} of {list.data.total}.</p>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Course</th>
                  {user.role !== 'FACULTY' && <th>Faculty</th>}
                  <th>Flag</th>
                  <th>Status</th>
                  <th>Last activity</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((q) => (
                  <tr key={q.id}>
                    <td><Link to={`/queries/${q.id}`}>{q.subject_code} {q.subject_name}</Link>{q.division && <span className="muted small"> (div {q.division})</span>}</td>
                    {user.role !== 'FACULTY' && <td>{q.faculty_name}</td>}
                    <td>{KIND_LABEL[q.flag_kind]}{q.template_code && <span className="muted small"> {q.template_code}</span>}</td>
                    <td><Badge tone={queryTone(q)}>{queryStatusText(q)}</Badge>{q.appealed && <> <Badge tone="info">Appealed</Badge></>}</td>
                    <td className="small">{formatDateTime(q.last_activity_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  )
}
