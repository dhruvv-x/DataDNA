import { useState } from 'react'
import { Link } from 'react-router-dom'
import { getFlags, listDepartments, listTemplates } from '../api/endpoints'
import type { Flag, FlagKind, FlagStatus } from '../api/types'
import { useAuth } from '../auth/context'
import { WaiveDialog, WaiveLateDialog } from '../components/ExceptionDialogs'
import { SelectField } from '../components/Fields'
import { Badge, ErrorBox, Loading } from '../components/Feedback'
import { KIND_LABEL, formatDateTime } from '../lib/format'
import { canGrantException, canWaiveLate } from '../lib/permissions'
import { useAsync } from '../lib/useAsync'

const STATUS_OPTIONS = [
  { value: 'OPEN', label: 'Open' },
  { value: 'WAIVED', label: 'Waived' },
  { value: 'CLEARED', label: 'Cleared' },
]
const KIND_OPTIONS = (Object.keys(KIND_LABEL) as FlagKind[]).map((k) => ({ value: k, label: KIND_LABEL[k] }))

/** Every flag of the current semester that the caller may see. HOD: own department. Dean: all. */
export function FlagsPage() {
  const { user } = useAuth()
  const isDean = user?.role === 'DEAN'
  const [status, setStatus] = useState<FlagStatus | ''>('OPEN')
  const [kind, setKind] = useState<FlagKind | ''>('')
  const [departmentId, setDepartmentId] = useState('')
  const [waiving, setWaiving] = useState<Flag | null>(null)
  const [bulk, setBulk] = useState(false)

  const departments = useAsync(() => (isDean ? listDepartments() : Promise.resolve([])), `flags-depts:${isDean}`)
  const templates = useAsync(() => (isDean ? listTemplates() : Promise.resolve([])), `flags-templates:${isDean}`)
  const flags = useAsync(
    () => getFlags({ status: status || undefined, kind: kind || undefined, department_id: departmentId, limit: 200 }),
    `flags:${status}|${kind}|${departmentId}`,
  )
  if (!user) return null

  const rows = flags.data?.flags ?? []
  const mayWaive = canGrantException(user.role, true) // this list is the current semester, where a HOD may act too
  const semesterId = flags.data?.semester_id ?? null

  return (
    <>
      <p><Link to="/">&larr; Back to dashboard</Link></p>
      <div className="head-row">
        <div>
          <h1>Flags</h1>
          <p className="muted">Current semester. A flag is a thing that needs attention. Waiving one needs a reason, and it stays in the record.</p>
        </div>
        {canWaiveLate(user.role) && semesterId && (
          <button className="btn" onClick={() => setBulk(true)}>Waive late flags of one item</button>
        )}
      </div>

      <div className="toolbar" role="group" aria-label="Filters">
        <SelectField label="Status" value={status} onChange={(v) => setStatus(v as FlagStatus | '')} placeholder="Any status" options={STATUS_OPTIONS} />
        <SelectField label="Kind" value={kind} onChange={(v) => setKind(v as FlagKind | '')} placeholder="Any kind" options={KIND_OPTIONS} />
        {isDean && (
          <SelectField
            label="Department"
            value={departmentId}
            onChange={setDepartmentId}
            placeholder="All departments"
            options={(departments.data ?? []).map((d) => ({ value: d.id, label: `${d.code} ${d.name}` }))}
          />
        )}
      </div>

      {flags.error && <ErrorBox message={flags.error} onRetry={flags.reload} />}
      {flags.loading && !flags.data && <Loading />}
      {flags.data && rows.length === 0 && (
        <div className="card"><p>{status === 'OPEN' && kind === '' && departmentId === '' ? 'No open flags. Nothing needs attention.' : 'No flags match these filters.'}</p></div>
      )}
      {flags.data && rows.length > 0 && (
        <>
          <p className="muted small">Showing {rows.length} of {flags.data.total}.</p>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Subject</th>
                  <th>Faculty</th>
                  {isDean && <th>Dept</th>}
                  <th>Item</th>
                  <th>Flag</th>
                  <th>Raised</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((f) => (
                  <tr key={f.id}>
                    <td>
                      <Link to={`/course-files/${f.course_file_id}`}>{f.subject_code} - {f.subject_name}</Link>
                      {f.division && <span className="muted small"> (div {f.division})</span>}
                    </td>
                    <td>{f.faculty_name}</td>
                    {isDean && <td>{f.department_code}</td>}
                    <td>{f.template_code ? `${f.template_code} ${f.template_title ?? ''}` : <span className="muted">Whole course file</span>}</td>
                    <td>
                      <Badge tone={f.status === 'OPEN' ? 'bad' : 'muted'}>{KIND_LABEL[f.kind]}: {f.status.toLowerCase()}</Badge>
                      <div className="muted small">{f.reason}</div>
                    </td>
                    <td>{formatDateTime(f.raised_at)}</td>
                    <td className="actions">
                      {mayWaive && f.status === 'OPEN' && f.kind !== 'ANOMALY' && (
                        <button className="btn btn-small" onClick={() => setWaiving(f)}>Waive</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {waiving && (
        <WaiveDialog
          flagId={waiving.id}
          label={`${KIND_LABEL[waiving.kind]}${waiving.template_code ? ` ${waiving.template_code}` : ''}`}
          onClose={() => setWaiving(null)}
          onDone={flags.reload}
        />
      )}
      {bulk && semesterId && (
        <WaiveLateDialog
          semesterId={semesterId}
          templates={(templates.data ?? []).filter((t) => t.is_active)}
          onClose={() => setBulk(false)}
          onDone={flags.reload}
        />
      )}
    </>
  )
}
