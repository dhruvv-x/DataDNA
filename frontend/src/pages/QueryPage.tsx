import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getQuery } from '../api/endpoints'
import type { QueryDetail } from '../api/types'
import { useAuth } from '../auth/context'
import { Badge, ErrorBox, Loading } from '../components/Feedback'
import { QueryActionPanel } from '../components/QueryActionPanel'
import { QueryTimeline } from '../components/QueryTimeline'
import { KIND_LABEL, QUERY_LEVEL_LABEL, QUERY_STATUS_LABEL, formatDateTime, queryTone } from '../lib/format'
import { useAsync } from '../lib/useAsync'

function flagWhatHappened(q: QueryDetail): string | null {
  if (q.status === 'RESOLVED_OVERTURNED') return 'The flag was overturned and set aside as waived. It no longer costs points.'
  if (q.status === 'RESOLVED_UPHELD') return 'The flag stays and keeps counting in the score.'
  return null
}

export function QueryPage() {
  const { id = '' } = useParams()
  const { user } = useAuth()
  const loaded = useAsync(() => getQuery(id), `query:${id}`)
  // After an action the server sends the fresh query back. Show that without waiting for a reload.
  const [fresh, setFresh] = useState<QueryDetail | null>(null)
  if (!user) return null

  if (loaded.error) {
    return (
      <>
        <p><Link to="/queries">&larr; Back to queries</Link></p>
        <ErrorBox message={loaded.error} onRetry={loaded.reload} />
      </>
    )
  }
  const q = fresh && fresh.id === id ? fresh : loaded.data
  if (!q) return <Loading what="Loading query" />

  const result = flagWhatHappened(q)
  const waitingOn = q.status === 'OPEN' ? QUERY_LEVEL_LABEL[q.current_level].replace('With the', 'the') : null

  return (
    <>
      <p><Link to="/queries">&larr; Back to queries</Link></p>
      <div className="head-row">
        <div>
          <h1>Query: {q.subject_code} - {q.subject_name}{q.division && <span className="muted"> (div {q.division})</span>}</h1>
          <p className="muted">
            {q.faculty_name} &middot; {q.department_code}{' '}
            <Badge tone={queryTone(q)}>{q.status === 'OPEN' ? `Open, ${QUERY_LEVEL_LABEL[q.current_level].toLowerCase()}` : QUERY_STATUS_LABEL[q.status]}</Badge>
            {q.appealed && <> <Badge tone="info">Appealed</Badge></>}
          </p>
        </div>
      </div>

      <section className="card">
        <h2>The flag</h2>
        <div>
          <Badge tone={q.flag_status === 'OPEN' ? 'bad' : 'muted'}>{KIND_LABEL[q.flag_kind]}: {q.flag_status.toLowerCase()}</Badge>{' '}
          <strong>{q.template_code ? `${q.template_code} ${q.template_title ?? ''}` : 'Whole course file'}</strong>
        </div>
        <div>{q.flag_reason}</div>
        <p><Link to={`/course-files/${q.course_file_id}`}>Open the course file</Link></p>
        {result && <p className="alert alert-good" role="status">{result}</p>}
        {q.resolved_at && <p className="muted small">Decided {formatDateTime(q.resolved_at)}.</p>}
      </section>

      <h2>Steps</h2>
      <QueryTimeline steps={q.steps} />

      {waitingOn && !q.can.reply && <p className="muted">Waiting for {waitingOn}. Nothing for you to do right now.</p>}
      <QueryActionPanel key={`${q.id}:${q.steps.length}`} query={q} isDean={user.role === 'DEAN'} onChanged={setFresh} />
      {q.status !== 'OPEN' && !q.can.appeal && <p className="muted small">This query is closed.</p>}
    </>
  )
}
