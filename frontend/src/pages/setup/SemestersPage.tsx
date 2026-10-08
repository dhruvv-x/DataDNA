import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { changeSemesterDates, createSemester, listSemesters, makeSemesterCurrent } from '../../api/endpoints'
import type { Semester, Term } from '../../api/types'
import { EmptyState, SelectField, TextField } from '../../components/Fields'
import { Badge, ErrorBox, Loading } from '../../components/Feedback'
import { Modal } from '../../components/Modal'
import { formatDate, semesterLabel } from '../../lib/format'
import { useAction } from '../../lib/useAction'
import { useAsync } from '../../lib/useAsync'

export function SemestersPage() {
  const list = useAsync(listSemesters, 'semesters')
  const [year, setYear] = useState('')
  const [term, setTerm] = useState<Term>('ODD')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [editing, setEditing] = useState<Semester | null>(null)
  const [editStart, setEditStart] = useState('')
  const [editEnd, setEditEnd] = useState('')
  const [switching, setSwitching] = useState<Semester | null>(null)
  const add = useAction()
  const dates = useAction()
  const current = useAction()

  async function submit(e: FormEvent) {
    e.preventDefault()
    const done = await add.run(() => createSemester({ academic_year: year.trim(), term, start_date: start, end_date: end }))
    if (done) {
      setYear('')
      setStart('')
      setEnd('')
      list.reload()
    }
  }

  async function saveDates(e: FormEvent) {
    e.preventDefault()
    if (!editing) return
    const done = await dates.run(() => changeSemesterDates(editing.id, editStart, editEnd))
    if (done) {
      setEditing(null)
      list.reload()
    }
  }

  async function confirmSwitch() {
    if (!switching) return
    const done = await current.run(() => makeSemesterCurrent(switching.id))
    if (done) {
      setSwitching(null)
      list.reload()
    }
  }

  const old = list.data?.find((s) => s.is_current)

  return (
    <>
      <p className="muted">Exactly one semester is current. Older semesters become history: their scores are frozen and faculty can no longer upload to them.</p>
      <form className="inline-form" onSubmit={(e) => void submit(e)} aria-label="Add semester">
        <TextField label="Academic year (2026-27)" value={year} onChange={setYear} maxLength={7} disabled={add.busy} />
        <SelectField label="Term" value={term} onChange={(v) => setTerm(v as Term)} disabled={add.busy}
          options={[{ value: 'ODD', label: 'Odd' }, { value: 'EVEN', label: 'Even' }]} />
        <TextField label="Start date" type="date" value={start} onChange={setStart} disabled={add.busy} />
        <TextField label="End date" type="date" value={end} onChange={setEnd} disabled={add.busy} />
        <button className="btn btn-primary" type="submit" disabled={add.busy || !year.trim() || !start || !end}>Add semester</button>
      </form>
      {add.error && <ErrorBox message={add.error} />}
      {list.error && <ErrorBox message={list.error} onRetry={list.reload} />}
      {list.loading && !list.data && <Loading />}
      {list.data && list.data.length === 0 && <EmptyState>No semesters yet. Add one above, then make it current.</EmptyState>}
      {list.data && list.data.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Semester</th><th>Dates</th><th>Status</th><th /></tr></thead>
            <tbody>
              {list.data.map((s) => (
                <tr key={s.id}>
                  <td>{semesterLabel(s.academic_year, s.term)}</td>
                  <td>{formatDate(s.start_date)} to {formatDate(s.end_date)}</td>
                  <td>{s.is_current ? <Badge tone="good">Current</Badge> : <Badge tone="muted">History or upcoming</Badge>}</td>
                  <td className="actions">
                    <Link className="btn btn-small" to={`/setup/semesters/${s.id}/deadlines`}>Deadlines</Link>
                    <button className="btn btn-small" onClick={() => { setEditing(s); setEditStart(s.start_date); setEditEnd(s.end_date); dates.setError(null) }}>Change dates</button>
                    {!s.is_current && <button className="btn btn-small" onClick={() => { setSwitching(s); current.setError(null) }}>Make current</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editing && (
        <Modal title={`Dates of ${semesterLabel(editing.academic_year, editing.term)}`} onClose={() => setEditing(null)}>
          <form className="form" onSubmit={(e) => void saveDates(e)}>
            <TextField label="Start date" type="date" value={editStart} onChange={setEditStart} disabled={dates.busy} />
            <TextField label="End date" type="date" value={editEnd} onChange={setEditEnd} disabled={dates.busy} />
            {dates.error && <ErrorBox message={dates.error} />}
            <div className="modal-actions">
              <button type="button" className="btn" onClick={() => setEditing(null)}>Cancel</button>
              <button type="submit" className="btn btn-primary" disabled={dates.busy || !editStart || !editEnd}>Save</button>
            </div>
          </form>
        </Modal>
      )}
      {switching && (
        <Modal title={`Make ${semesterLabel(switching.academic_year, switching.term)} current?`} onClose={() => setSwitching(null)}>
          <p>
            {old ? `${semesterLabel(old.academic_year, old.term)} will be closed: its final scores are frozen and faculty can no longer upload to it. ` : ''}
            Deadlines of the new semester that already passed are flagged at once. This cannot be undone from here.
          </p>
          {current.error && <ErrorBox message={current.error} />}
          <div className="modal-actions">
            <button className="btn" onClick={() => setSwitching(null)} disabled={current.busy}>Cancel</button>
            <button className="btn btn-primary" onClick={() => void confirmSwitch()} disabled={current.busy}>{current.busy ? 'Working...' : 'Yes, make it current'}</button>
          </div>
        </Modal>
      )}
    </>
  )
}
