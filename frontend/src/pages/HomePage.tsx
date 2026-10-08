import { useState } from 'react'
import { Link } from 'react-router-dom'
import { getFlags, getScores, listDepartments, listSemesters, listSubjects } from '../api/endpoints'
import { useAuth } from '../auth/context'
import { SelectField } from '../components/Fields'
import { ErrorBox, Loading } from '../components/Feedback'
import { formatPoints, semesterLabel, trustGaugeColor } from '../lib/format'
import { canOpenFlagsPage } from '../lib/permissions'
import { useAsync } from '../lib/useAsync'

const TITLE = { FACULTY: 'My courses', HOD: 'Department courses', DEAN: 'All courses' } as const

export function HomePage() {
  const { user } = useAuth()
  const isDean = user?.role === 'DEAN'
  const canFilter = user?.role === 'HOD' || isDean
  const [semesterId, setSemesterId] = useState('')
  const [departmentId, setDepartmentId] = useState('')
  const [subjectId, setSubjectId] = useState('')
  const [lowestFirst, setLowestFirst] = useState(false)

  // The filter lists are only loaded for roles that have filters. The server limits what each role gets back.
  const departments = useAsync(() => (isDean ? listDepartments() : Promise.resolve([])), `home-depts:${isDean}`)
  const semesters = useAsync(() => (isDean ? listSemesters() : Promise.resolve([])), `home-sems:${isDean}`)
  const subjects = useAsync(() => (canFilter ? listSubjects() : Promise.resolve([])), `home-subjects:${canFilter}`)

  const filterKey = `${semesterId}|${departmentId}|${subjectId}`
  const scores = useAsync(
    () => getScores({ semester_id: semesterId, department_id: departmentId, subject_id: subjectId }),
    `scores:${filterKey}`,
  )
  const flags = useAsync(
    () => getFlags({ status: 'OPEN', limit: 1, semester_id: semesterId, department_id: departmentId }),
    `open-flags:${semesterId}|${departmentId}`,
  )
  if (!user) return null

  let rows = scores.data?.scores ?? []
  if (lowestFirst) rows = [...rows].sort((a, b) => (a.total ?? Infinity) - (b.total ?? Infinity))
  const scored = rows.filter((r) => r.total !== null)
  const average = scored.length ? scored.reduce((sum, r) => sum + (r.total as number), 0) / scored.length : null
  // The flags list has no subject filter, so with a subject chosen the card counts the problem items of the rows shown.
  const problemsOfRows = rows.reduce((sum, r) => sum + r.open_problems, 0)
  const subjectOptions = (subjects.data ?? [])
    .filter((s) => !departmentId || s.department_id === departmentId)
    .map((s) => ({ value: s.id, label: `${s.code} ${s.name}` }))
  const viewingOther = semesterId !== ''
  const filtered = departmentId !== '' || subjectId !== '' || viewingOther

  return (
    <>
      <h1>{TITLE[user.role]}</h1>
      <p className="muted">
        {viewingOther ? 'A semester you chose.' : 'Current semester.'} Scores only go down when something is open: a missing, late, incomplete or wrongly formatted item.
      </p>

      {canFilter && (
        <div className="toolbar" role="group" aria-label="Filters">
          {isDean && (
            <SelectField
              label="Semester"
              value={semesterId}
              onChange={setSemesterId}
              placeholder="Current semester"
              options={(semesters.data ?? []).map((s) => ({ value: s.id, label: `${semesterLabel(s.academic_year, s.term)}${s.is_current ? ' (current)' : ''}` }))}
            />
          )}
          {isDean && (
            <SelectField
              label="Department"
              value={departmentId}
              onChange={(v) => {
                setDepartmentId(v)
                setSubjectId('')
              }}
              placeholder="All departments"
              options={(departments.data ?? []).map((d) => ({ value: d.id, label: `${d.code} ${d.name}` }))}
            />
          )}
          <SelectField label="Subject" value={subjectId} onChange={setSubjectId} placeholder="All subjects" options={subjectOptions} />
          <div className="field">
            <span>Order</span>
            <button type="button" className="btn" aria-pressed={lowestFirst} onClick={() => setLowestFirst((v) => !v)}>
              Lowest score first
            </button>
          </div>
        </div>
      )}

      {scores.error && <ErrorBox message={scores.error} onRetry={scores.reload} />}
      {scores.loading && !scores.data && <Loading />}
      {scores.data && (
        <>
          <div className="cards">
            <div className="card stat"><div className="stat-n">{scores.data.total}</div><div className="muted">Course files</div></div>
            <div className="card stat"><div className="stat-n">{average === null ? '-' : formatPoints(average)}</div><div className="muted">Average score</div></div>
            {subjectId === '' ? (
              <div className="card stat"><div className="stat-n">{flags.data ? flags.data.total : '-'}</div><div className="muted">Open flags</div></div>
            ) : (
              <div className="card stat"><div className="stat-n">{problemsOfRows}</div><div className="muted">Open problems</div></div>
            )}
          </div>
          {canOpenFlagsPage(user.role) && <p><Link to="/flags">See all flags</Link></p>}
          {rows.length === 0 ? (
            <div className="card">
              {filtered ? (
                <p>No course files match these filters.</p>
              ) : isDean ? (
                <p>No course files in the current semester yet. Start in <Link to="/setup">Setup</Link>: departments, a semester, subjects, people, then course files.</p>
              ) : (
                <p>No course files in the current semester yet.</p>
              )}
            </div>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Subject</th>
                    {user.role !== 'FACULTY' && <th>Faculty</th>}
                    {isDean && <th>Dept</th>}
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
                      {isDean && <td>{r.department_code}</td>}
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
