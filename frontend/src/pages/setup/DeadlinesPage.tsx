import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getDeadlines, listSemesters, listTemplates, putDeadlines } from '../../api/endpoints'
import { EmptyState } from '../../components/Fields'
import { Badge, ErrorBox, Loading } from '../../components/Feedback'
import { isoToIstInput, istInputToIso, semesterLabel } from '../../lib/format'
import { useAction } from '../../lib/useAction'
import { useAsync } from '../../lib/useAsync'

/** One deadline per checklist item for one semester. Times are India time. Only the rows you changed are sent. */
export function DeadlinesPage() {
  const { id = '' } = useParams()
  const semesters = useAsync(listSemesters, 'semesters')
  const templates = useAsync(listTemplates, 'templates')
  const deadlines = useAsync(() => getDeadlines(id), `deadlines:${id}`)
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [allowPast, setAllowPast] = useState(false)
  const [saved, setSaved] = useState(false)
  const [openedAt] = useState(() => Date.now()) // only a hint; the server checks again
  const save = useAction()

  const semester = semesters.data?.find((s) => s.id === id)
  const original = new Map((deadlines.data ?? []).map((d) => [d.template_id, isoToIstInput(d.due_at)]))
  const changed = Object.entries(edits).filter(([tid, v]) => v !== '' && v !== (original.get(tid) ?? ''))
  const pastCount = changed.filter(([, v]) => new Date(istInputToIso(v)).getTime() <= openedAt).length

  async function submit() {
    setSaved(false)
    const items = changed.map(([template_id, v]) => ({ template_id, due_at: istInputToIso(v) }))
    const done = await save.run(() => putDeadlines(id, items, allowPast))
    if (done) {
      setEdits({})
      setAllowPast(false)
      setSaved(true)
      deadlines.reload()
    }
  }

  const loadError = semesters.error ?? templates.error ?? deadlines.error
  const ready = semesters.data && templates.data && deadlines.data

  return (
    <>
      <p><Link to="/setup/semesters">&larr; Semesters</Link></p>
      <h2>Deadlines{semester ? `: ${semesterLabel(semester.academic_year, semester.term)}` : ''}</h2>
      <p className="muted">
        Times are India time. An item without a deadline never gets a late or missing flag. Moving a deadline never removes a lateness flag that already exists.
      </p>
      {loadError && <ErrorBox message={loadError} onRetry={() => { semesters.reload(); templates.reload(); deadlines.reload() }} />}
      {!ready && !loadError && <Loading />}
      {ready && templates.data!.length === 0 && <EmptyState>No checklist items yet. Add them under Checklist items first.</EmptyState>}
      {ready && templates.data!.length > 0 && (
        <>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Item</th><th>Deadline (India time)</th></tr></thead>
              <tbody>
                {templates.data!.map((t) => {
                  const value = edits[t.id] ?? original.get(t.id) ?? ''
                  return (
                    <tr key={t.id}>
                      <td>
                        {t.code} - {t.title} {!t.is_active && <Badge tone="muted">switched off</Badge>}
                      </td>
                      <td>
                        <input type="datetime-local" aria-label={`Deadline for ${t.code}`} value={value}
                          onChange={(e) => { setSaved(false); setEdits({ ...edits, [t.id]: e.target.value }) }} />
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          {pastCount > 0 && (
            <div className="alert alert-warn">
              <label>
                <input type="checkbox" checked={allowPast} onChange={(e) => setAllowPast(e.target.checked)} />{' '}
                {pastCount} deadline{pastCount > 1 ? 's are' : ' is'} in the past. Every empty item would be flagged MISSING at once. I want that.
              </label>
            </div>
          )}
          {save.error && <ErrorBox message={save.error} />}
          {saved && <div className="alert alert-good" role="status">Deadlines saved.</div>}
          <div className="modal-actions">
            <button className="btn btn-primary" onClick={() => void submit()} disabled={save.busy || changed.length === 0 || (pastCount > 0 && !allowPast)}>
              {save.busy ? 'Saving...' : `Save ${changed.length} change${changed.length === 1 ? '' : 's'}`}
            </button>
          </div>
        </>
      )}
    </>
  )
}
