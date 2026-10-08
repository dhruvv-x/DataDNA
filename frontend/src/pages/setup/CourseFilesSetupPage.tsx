import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { createCourseFiles, listCourseFiles, listSemesters, listSubjects, listUsers } from '../../api/endpoints'
import { EmptyState, SelectField, TextField } from '../../components/Fields'
import { ErrorBox, Loading } from '../../components/Feedback'
import { semesterLabel } from '../../lib/format'
import { useAction } from '../../lib/useAction'
import { useAsync } from '../../lib/useAsync'

interface Staged {
  subject_id: string
  faculty_id: string
  division: string | null
}

/** Connects a subject, a faculty and a semester. Creating a course file also creates all its checklist rows. */
export function CourseFilesSetupPage() {
  const semesters = useAsync(listSemesters, 'semesters')
  const subjects = useAsync(listSubjects, 'subjects')
  const users = useAsync(listUsers, 'users')
  const [picked, setPicked] = useState('')
  const [subjectId, setSubjectId] = useState('')
  const [facultyId, setFacultyId] = useState('')
  const [division, setDivision] = useState('')
  const [staged, setStaged] = useState<Staged[]>([])
  const [created, setCreated] = useState<number | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const create = useAction()

  const semesterId = picked || semesters.data?.find((s) => s.is_current)?.id || semesters.data?.[0]?.id || ''
  const existing = useAsync(() => (semesterId ? listCourseFiles(semesterId) : Promise.resolve([])), `course-files:${semesterId}`)

  const activeSubjects = (subjects.data ?? []).filter((s) => s.is_active)
  const subject = activeSubjects.find((s) => s.id === subjectId)
  const faculty = (users.data ?? []).filter((u) => u.role === 'FACULTY' && u.is_active && (!subject || u.department_id === subject.department_id))
  const subjectOf = new Map((subjects.data ?? []).map((s) => [s.id, s]))
  const facultyOf = new Map((users.data ?? []).map((u) => [u.id, u]))

  function stage(e: FormEvent) {
    e.preventDefault()
    setFormError(null)
    setCreated(null)
    const div = division.trim() || null
    const same = (x: Staged) => x.subject_id === subjectId && x.faculty_id === facultyId && x.division === div
    const already = existing.data?.some((x) => x.subject_id === subjectId && x.faculty_id === facultyId && (x.division ?? null) === div)
    if (staged.some(same) || already) return setFormError('This faculty already has a course file for this subject and division.')
    setStaged([...staged, { subject_id: subjectId, faculty_id: facultyId, division: div }])
    setDivision('')
  }

  async function submit() {
    setCreated(null)
    const done = await create.run(() => createCourseFiles(staged.map((s) => ({ ...s, semester_id: semesterId }))))
    if (done) {
      setCreated(done.created)
      setStaged([])
      existing.reload()
    }
  }

  const loadError = semesters.error ?? subjects.error ?? users.error
  const ready = semesters.data && subjects.data && users.data
  const noSemester = semesters.data && semesters.data.length === 0

  return (
    <>
      <p className="muted">One course file per faculty, subject, semester and division. Add several to the list, then create them in one go. If one is wrong, none is created.</p>
      {loadError && <ErrorBox message={loadError} onRetry={() => { semesters.reload(); subjects.reload(); users.reload() }} />}
      {!ready && !loadError && <Loading />}
      {noSemester && <EmptyState>Add a semester first (Semesters tab).</EmptyState>}
      {ready && !noSemester && (
        <>
          <div className="toolbar">
            <SelectField label="Semester" value={semesterId} onChange={(v) => { setPicked(v); setStaged([]); setCreated(null) }}
              options={semesters.data!.map((s) => ({ value: s.id, label: semesterLabel(s.academic_year, s.term) + (s.is_current ? ' (current)' : '') }))} />
          </div>
          {activeSubjects.length === 0 && <EmptyState>No active subjects. Add subjects first (Subjects tab).</EmptyState>}
          {activeSubjects.length > 0 && !(users.data ?? []).some((u) => u.role === 'FACULTY' && u.is_active) && (
            <EmptyState>No faculty yet. Create faculty first (Users tab).</EmptyState>
          )}
          <form className="inline-form" onSubmit={stage} aria-label="Add course file">
            <SelectField label="Subject" value={subjectId} onChange={(v) => { setSubjectId(v); setFacultyId('') }} placeholder="Choose..."
              options={activeSubjects.map((s) => ({ value: s.id, label: `${s.code} - ${s.name}` }))} />
            <SelectField label="Faculty (same department)" value={facultyId} onChange={setFacultyId} placeholder="Choose..." disabled={!subjectId}
              options={faculty.map((u) => ({ value: u.id, label: u.full_name }))} />
            <TextField label="Division (optional)" value={division} onChange={setDivision} maxLength={40} />
            <button className="btn" type="submit" disabled={!subjectId || !facultyId}>Add to list</button>
          </form>
          {formError && <ErrorBox message={formError} />}
          {staged.length > 0 && (
            <div className="card">
              <strong>To create ({staged.length})</strong>
              <ul className="plain-list">
                {staged.map((s, i) => (
                  <li key={i}>
                    {subjectOf.get(s.subject_id)?.code} - {facultyOf.get(s.faculty_id)?.full_name}{s.division ? ` (div ${s.division})` : ''}{' '}
                    <button className="linklike" onClick={() => setStaged(staged.filter((_, j) => j !== i))}>remove</button>
                  </li>
                ))}
              </ul>
              {create.error && <ErrorBox message={create.error} />}
              <div className="modal-actions">
                <button className="btn btn-primary" onClick={() => void submit()} disabled={create.busy}>
                  {create.busy ? 'Creating...' : `Create ${staged.length} course file${staged.length > 1 ? 's' : ''}`}
                </button>
              </div>
            </div>
          )}
          {created !== null && <div className="alert alert-good" role="status">Created {created} course file{created === 1 ? '' : 's'}. The checklist rows were made too.</div>}
          <h2>Existing in this semester</h2>
          {existing.error && <ErrorBox message={existing.error} onRetry={existing.reload} />}
          {existing.data && existing.data.length === 0 && <EmptyState>No course files in this semester yet.</EmptyState>}
          {existing.data && existing.data.length > 0 && (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Subject</th><th>Faculty</th><th>Dept</th><th>Division</th></tr></thead>
                <tbody>
                  {existing.data.map((c) => (
                    <tr key={c.id}>
                      <td><Link to={`/course-files/${c.id}`}>{c.subject_code} - {c.subject_name}</Link></td>
                      <td>{c.faculty_name}</td>
                      <td>{c.department_code}</td>
                      <td>{c.division ?? '-'}</td>
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
