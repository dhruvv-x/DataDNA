import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { downloadVersion, getChecklist, getCourseFileFlags, getScore, getScoreHistory, listQueries } from '../api/endpoints'
import { ApiError } from '../api/client'
import type { ChecklistRow, Flag, ScoreItem } from '../api/types'
import { PARTS } from '../api/types'
import { useAuth } from '../auth/context'
import { Badge, ErrorBox, Loading, StateBadge } from '../components/Feedback'
import { PartBars } from '../components/PartBars'
import { ScoreGauge } from '../components/ScoreGauge'
import { Sparkline } from '../components/Sparkline'
import { ExtendDialog, WaiveDialog } from '../components/ExceptionDialogs'
import { RaiseQueryDialog } from '../components/RaiseQueryDialog'
import { UploadDialog } from '../components/UploadDialog'
import { VersionsDialog } from '../components/VersionsDialog'
import { KIND_LABEL, STATE_LABEL, formatDateTime, formatPoints, queryStatusText, semesterLabel } from '../lib/format'
import { canGrantException, canRaiseQuery, canUpload } from '../lib/permissions'
import { useAsync } from '../lib/useAsync'

export function CourseFilePage() {
  const { id = '' } = useParams()
  const { user } = useAuth()
  const score = useAsync(() => getScore(id), `score:${id}`)
  const checklist = useAsync(() => getChecklist(id), `check:${id}`)
  const flags = useAsync(() => getCourseFileFlags(id), `flags:${id}`)
  const history = useAsync(() => getScoreHistory(id), `hist:${id}`)
  // Queries of this course file, so each flag can show its query. A failure here only hides that link.
  const queries = useAsync(() => listQueries({ course_file_id: id, limit: 500 }), `cfqueries:${id}`)
  const navigate = useNavigate()
  const [disputeFlag, setDisputeFlag] = useState<Flag | null>(null)
  const [uploadRow, setUploadRow] = useState<ChecklistRow | null>(null)
  const [versionsRow, setVersionsRow] = useState<ChecklistRow | null>(null)
  const [extendRow, setExtendRow] = useState<ChecklistRow | null>(null)
  const [waiveFlagRow, setWaiveFlagRow] = useState<Flag | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  if (!user) return null

  const reloadAll = () => {
    score.reload()
    checklist.reload()
    flags.reload()
    history.reload()
    queries.reload()
  }

  if (score.error) {
    return (
      <>
        <p><Link to="/">&larr; Back</Link></p>
        <ErrorBox message={score.error} onRetry={score.reload} />
      </>
    )
  }
  const s = score.data
  if (!s) return <Loading what="Loading course file" />

  const mayGrant = canGrantException(user.role, s.semester_is_current)
  const itemOf = new Map<string, ScoreItem>(s.items.map((i) => [i.submission_id, i]))
  const queryOfFlag = new Map((queries.data?.queries ?? []).map((q) => [q.flag_id, q]))

  async function download(row: ChecklistRow) {
    setActionError(null)
    if (!row.current_version_id) return
    try {
      await downloadVersion(row.current_version_id, row.original_filename ?? 'file')
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Download failed.')
    }
  }

  return (
    <>
      <p><Link to="/">&larr; Back to dashboard</Link></p>
      <div className="head-row">
        <div>
          <h1>{s.subject_code} - {s.subject_name}{s.division && <span className="muted"> (div {s.division})</span>}</h1>
          <p className="muted">
            {s.faculty_name} &middot; {s.department_code} &middot; {semesterLabel(s.academic_year, s.term)}{' '}
            {s.semester_is_current
              ? <Badge tone="info">Current semester</Badge>
              : s.source === 'snapshot'
                ? <Badge tone="muted">Closed, score of record</Badge>
                : <Badge tone="warn">Closed, not frozen</Badge>}
          </p>
        </div>
      </div>

      <section className="card score-card">
        <ScoreGauge total={s.total} />
        <div className="score-main">
          <h2>Trust score</h2>
          {s.notes.map((n) => <p key={n} className="muted small">{n}</p>)}
          {s.status === 'SCORED' && <PartBars parts={s.parts} />}
          <p className="muted small">As of {formatDateTime(s.as_of)}. {s.items_pending} of {s.items_total} items not due or not submitted yet (no penalty).</p>
        </div>
      </section>

      <h2>Checklist</h2>
      {actionError && <ErrorBox message={actionError} />}
      {checklist.error && <ErrorBox message={checklist.error} onRetry={checklist.reload} />}
      {checklist.loading && !checklist.data && <Loading />}
      {checklist.data && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr><th>Item</th><th>Deadline</th><th>Status</th><th>File</th><th>Points lost</th><th /></tr>
            </thead>
            <tbody>
              {checklist.data.filter((r) => r.template_active).map((r) => {
                const item = itemOf.get(r.submission_id)
                const lost = item ? PARTS.reduce((sum, p) => sum + item.lost[p], 0) : 0
                const mayUpload = canUpload(user.role, s.semester_is_current, r.template_active)
                return (
                  <tr key={r.submission_id}>
                    <td>
                      <strong>{r.code}</strong> {r.title}
                      {item && item.state !== 'OK' && item.state !== 'PENDING' && item.reasons.map((reason) => (
                        <div key={reason} className="muted small">{reason}</div>
                      ))}
                    </td>
                    <td>
                      {r.due_at ? formatDateTime(r.effective_due_at) : <span className="muted">No deadline</span>}
                      {r.extended_to && <div className="muted small">Extended</div>}
                    </td>
                    <td>{item ? <StateBadge state={item.state} label={STATE_LABEL[item.state]} /> : '-'}</td>
                    <td>
                      {r.current_version_id ? (
                        <>
                          {r.original_filename} <span className="muted small">v{r.version_no} of {r.version_count}</span>
                          <div className="muted small">
                            {formatDateTime(r.uploaded_at)}{r.uploaded_by_role === 'DEAN' && ' (uploaded by Dean)'}
                          </div>
                        </>
                      ) : <span className="muted">Nothing uploaded</span>}
                    </td>
                    <td>{lost > 0 ? formatPoints(lost) : '-'}</td>
                    <td className="actions">
                      {mayUpload && (
                        <button className="btn btn-small btn-primary" onClick={() => setUploadRow(r)}>
                          {r.current_version_id ? 'Replace' : 'Upload'}
                        </button>
                      )}
                      {r.current_version_id && <button className="btn btn-small" onClick={() => void download(r)}>Download</button>}
                      {r.version_count > 0 && <button className="btn btn-small" onClick={() => setVersionsRow(r)}>Versions</button>}
                      {mayGrant && r.due_at && <button className="btn btn-small" onClick={() => setExtendRow(r)}>Extend deadline</button>}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <h2>Flags</h2>
      {flags.error && <ErrorBox message={flags.error} onRetry={flags.reload} />}
      {flags.data && flags.data.length === 0 && <p className="muted">No flags. Nothing needs attention.</p>}
      {flags.data && flags.data.length > 0 && (
        <ul className="flag-list">
          {[...flags.data].sort((a, b) => Number(b.status === 'OPEN') - Number(a.status === 'OPEN')).map((f) => (
            <li key={f.id} className="card">
              <div>
                <Badge tone={f.status === 'OPEN' ? 'bad' : 'muted'}>{KIND_LABEL[f.kind]}: {f.status.toLowerCase()}</Badge>{' '}
                <strong>{f.template_code ? `${f.template_code} ${f.template_title ?? ''}` : 'Whole course file'}</strong>
              </div>
              <div>{f.reason}</div>
              <div className="muted small">Raised {formatDateTime(f.raised_at)}{f.cleared_at && `, cleared ${formatDateTime(f.cleared_at)}`}</div>
              {mayGrant && f.status === 'OPEN' && f.kind !== 'ANOMALY' && (
                <div><button className="btn btn-small" onClick={() => setWaiveFlagRow(f)}>Waive</button></div>
              )}
              {(() => {
                const q = queryOfFlag.get(f.id)
                if (q) return <div><Link to={`/queries/${q.id}`}>Query: {queryStatusText(q).toLowerCase()}</Link></div>
                if (canRaiseQuery(user.role, user.id, s.faculty_id, f.status === 'OPEN', s.semester_is_current, false)) {
                  return <div><button className="btn btn-small" onClick={() => setDisputeFlag(f)}>Dispute this flag</button></div>
                }
                return null
              })()}
              {f.exceptions.map((e) => (
                <div key={e.id} className="muted small">{e.kind === 'WAIVER' ? 'Waived' : 'Extension'} by {e.granted_by_name} on {formatDateTime(e.granted_at)}: {e.reason}</div>
              ))}
            </li>
          ))}
        </ul>
      )}

      <h2>Score history</h2>
      {history.error && <ErrorBox message={history.error} onRetry={history.reload} />}
      {history.data && (
        <div className="card">
          <Sparkline snapshots={history.data.snapshots} />
          <ul className="plain-list">
            {history.data.snapshots.slice(0, 10).map((h) => (
              <li key={h.id} className="small">
                {formatDateTime(h.created_at)}: <strong>{h.total === null ? 'no score' : formatPoints(h.total)}</strong>
                {h.is_final && <> <Badge tone="muted">final</Badge></>}
              </li>
            ))}
            {history.data.snapshots.length === 0 && <li className="muted small">No changes recorded yet.</li>}
          </ul>
        </div>
      )}

      {uploadRow && (
        <UploadDialog row={uploadRow} role={user.role} onClose={() => setUploadRow(null)} onUploaded={reloadAll} />
      )}
      {versionsRow && <VersionsDialog row={versionsRow} onClose={() => setVersionsRow(null)} />}
      {extendRow && (
        <ExtendDialog
          submissionId={extendRow.submission_id}
          label={`${extendRow.code} ${extendRow.title}`}
          effectiveDueAt={extendRow.effective_due_at}
          onClose={() => setExtendRow(null)}
          onDone={reloadAll}
        />
      )}
      {disputeFlag && (
        <RaiseQueryDialog
          flagId={disputeFlag.id}
          label={`${KIND_LABEL[disputeFlag.kind]}${disputeFlag.template_code ? ` ${disputeFlag.template_code}` : ''}`}
          onClose={() => setDisputeFlag(null)}
          onRaised={(queryId) => navigate(`/queries/${queryId}`)}
        />
      )}
      {waiveFlagRow && (
        <WaiveDialog
          flagId={waiveFlagRow.id}
          label={`${KIND_LABEL[waiveFlagRow.kind]}${waiveFlagRow.template_code ? ` ${waiveFlagRow.template_code}` : ''}`}
          onClose={() => setWaiveFlagRow(null)}
          onDone={reloadAll}
        />
      )}
    </>
  )
}
