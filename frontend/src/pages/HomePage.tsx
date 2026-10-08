import { Link } from 'react-router-dom'
import { getFlags, getScores } from '../api/endpoints'
import { useAuth } from '../auth/context'
import { ErrorBox, Loading } from '../components/Feedback'
import { formatPoints, trustGaugeColor } from '../lib/format'
import { useAsync } from '../lib/useAsync'

const TITLE = { FACULTY: 'My courses', HOD: 'Department courses', DEAN: 'All courses' } as const

export function HomePage() {
  const { user } = useAuth()
  const scores = useAsync(getScores, 'scores')
  const flags = useAsync(() => getFlags({ status: 'OPEN', limit: 1 }), 'open-flags')
  if (!user) return null

  const rows = scores.data?.scores ?? []
  const scored = rows.filter((r) => r.total !== null)
  const average = scored.length ? scored.reduce((sum, r) => sum + (r.total as number), 0) / scored.length : null

  return (
    <>
      <h1>{TITLE[user.role]}</h1>
      <p className="muted">Current semester. Scores only go down when something is open: a missing, late, incomplete or wrongly formatted item.</p>
      {scores.error && <ErrorBox message={scores.error} onRetry={scores.reload} />}
      {scores.loading && !scores.data && <Loading />}
      {scores.data && (
        <>
          <div className="cards">
            <div className="card stat"><div className="stat-n">{scores.data.total}</div><div className="muted">Course files</div></div>
            <div className="card stat"><div className="stat-n">{average === null ? '-' : formatPoints(average)}</div><div className="muted">Average score</div></div>
            <div className="card stat"><div className="stat-n">{flags.data ? flags.data.total : '-'}</div><div className="muted">Open flags</div></div>
          </div>
          {rows.length === 0 ? (
            <div className="card"><p>No course files in the current semester yet.</p></div>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Subject</th>
                    {user.role !== 'FACULTY' && <th>Faculty</th>}
                    {user.role === 'DEAN' && <th>Dept</th>}
                    <th>Score</th>
                    <th>Open problems</th>
                    <th>Pending items</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.course_file_id}>
                      <td>
                        <Link to={`/course-files/${r.course_file_id}`}>{r.subject_code} - {r.subject_name}</Link>
                        {r.division && <span className="muted small"> (div {r.division})</span>}
                      </td>
                      {user.role !== 'FACULTY' && <td>{r.faculty_name}</td>}
                      {user.role === 'DEAN' && <td>{r.department_code}</td>}
                      <td>
                        {r.total === null
                          ? <span className="muted">No score yet</span>
                          : <strong style={{ color: trustGaugeColor(r.total) }}>{formatPoints(r.total)}</strong>}
                      </td>
                      <td>{r.open_problems}</td>
                      <td>{r.items_pending} of {r.items_total}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </>
  )
}
