import { useState } from 'react'
import type { FormEvent } from 'react'
import { getWeights, getWeightsHistory, setWeights } from '../../api/endpoints'
import type { Part, WeightSet } from '../../api/types'
import { PARTS } from '../../api/types'
import { ErrorBox, Loading } from '../../components/Feedback'
import { PART_LABEL, formatDateTime, formatPoints, semesterLabel } from '../../lib/format'
import { MIN_REASON } from '../../lib/permissions'
import { useAction } from '../../lib/useAction'
import { useAsync } from '../../lib/useAsync'

type Draft = Record<Part, string>

function toDraft(w: WeightSet): Draft {
  return { completeness: String(w.completeness), timeliness: String(w.timeliness), format: String(w.format), content: String(w.content) }
}

const num = (s: string) => (/^\d{1,3}$/.test(s.trim()) ? Number(s) : NaN)

export function WeightsPage() {
  const view = useAsync(getWeights, 'weights')
  const history = useAsync(getWeightsHistory, 'weights-history')
  const [draft, setDraft] = useState<Draft | null>(null)
  const [reason, setReason] = useState('')
  const [applyNow, setApplyNow] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const save = useAction()

  const latest = view.data?.latest
  const form: Draft | null = draft ?? (latest ? toDraft(latest) : null)
  const values = form ? PARTS.map((p) => num(form[p])) : []
  const sum = values.reduce((a, b) => a + b, 0)
  const sumOk = values.every((v) => !Number.isNaN(v)) && sum === 100
  const majorOk = form ? num(form.completeness) + num(form.timeliness) + num(form.format) >= 50 : false
  const changed = form && latest ? PARTS.some((p) => num(form[p]) !== latest[p]) : false
  const reasonOk = reason.trim().length >= MIN_REASON
  const canSave = sumOk && majorOk && changed && reasonOk && !save.busy

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!form) return
    const done = await save.run(() => setWeights({
      completeness: num(form.completeness), timeliness: num(form.timeliness), format: num(form.format), content: num(form.content),
      reason: reason.trim(), apply_now: applyNow,
    }))
    if (done) {
      setMessage(done.message)
      setDraft(null)
      setReason('')
      setApplyNow(false)
      view.reload()
      history.reload()
    }
  }

  const inForce = view.data?.current_semester?.weights ?? latest
  const eff = view.data?.effective_for_current_semester

  return (
    <>
      <p className="muted">
        How the 100 points are shared. A change is saved with your reason and applies from the next semester you make current, unless you tick "apply now".
        Old weights are never overwritten.
      </p>
      {view.error && <ErrorBox message={view.error} onRetry={view.reload} />}
      {view.loading && !view.data && <Loading />}
      {view.data && inForce && (
        <div className="card">
          <strong>In force for the current semester</strong>
          <div className="cards">
            {PARTS.map((p) => (
              <div key={p} className="stat">
                <div className="stat-n">{inForce[p]}</div>
                <div className="muted">{PART_LABEL[p]}{eff && eff[p] !== inForce[p] ? ` (counts as ${formatPoints(eff[p])})` : ''}</div>
              </div>
            ))}
          </div>
          {!view.data.content_scoring_enabled && <p className="small muted">Content checks are not live yet, so the Content weight is shared among the other three parts.</p>}
        </div>
      )}
      {form && (
        <form className="form card" onSubmit={(e) => void submit(e)} aria-label="Change weights">
          <strong>New weights</strong>
          <div className="inline-form">
            {PARTS.map((p) => (
              <label key={p} className="field">
                <span>{PART_LABEL[p]}</span>
                <input type="number" min={0} max={100} value={form[p]} disabled={save.busy} onChange={(e) => setDraft({ ...form, [p]: e.target.value })} />
              </label>
            ))}
          </div>
          <p className={sumOk ? 'sum-ok' : 'sum-bad'} role="status">Total: {Number.isNaN(sum) ? '?' : sum} of 100</p>
          {sumOk && !majorOk && <p className="sum-bad">Completeness, Timeliness and Format together must be at least 50.</p>}
          <label className="field">
            <span>Reason (at least {MIN_REASON} characters, kept forever)</span>
            <textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} disabled={save.busy} />
          </label>
          <label>
            <input type="checkbox" checked={applyNow} onChange={(e) => setApplyNow(e.target.checked)} disabled={save.busy} />{' '}
            Apply now to the current semester too (scores change mid-semester, so only do this with a good reason)
          </label>
          {save.error && <ErrorBox message={save.error} />}
          <div className="modal-actions"><button className="btn btn-primary" type="submit" disabled={!canSave}>{save.busy ? 'Saving...' : 'Save weights'}</button></div>
        </form>
      )}
      {message && <div className="alert alert-good" role="status">{message}</div>}
      <h2>History</h2>
      {history.error && <ErrorBox message={history.error} onRetry={history.reload} />}
      {history.data && (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>When</th><th>C / T / F / Content</th><th>By</th><th>Reason</th><th>Used by</th></tr></thead>
            <tbody>
              {history.data.weights.map((w) => (
                <tr key={w.id}>
                  <td>{formatDateTime(w.created_at)}</td>
                  <td>{w.completeness} / {w.timeliness} / {w.format} / {w.content}</td>
                  <td>{w.set_by_name ?? 'System'}</td>
                  <td>{w.reason ?? '-'}</td>
                  <td>{history.data!.semester_assignments.filter((a) => a.weights_id === w.id).map((a) => semesterLabel(a.academic_year, a.term)).join(', ') || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}
