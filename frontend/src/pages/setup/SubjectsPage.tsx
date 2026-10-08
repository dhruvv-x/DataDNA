import { useState } from 'react'
import type { FormEvent } from 'react'
import { createSubject, listDepartments, listSubjects, updateSubject } from '../../api/endpoints'
import type { Subject, SubjectType } from '../../api/types'
import { EmptyState, SelectField, TextField } from '../../components/Fields'
import { Badge, ErrorBox, Loading } from '../../components/Feedback'
import { Modal } from '../../components/Modal'
import { SUBJECT_TYPE_LABEL } from '../../lib/format'
import { useAction } from '../../lib/useAction'
import { useAsync } from '../../lib/useAsync'

const TYPE_OPTIONS = (Object.keys(SUBJECT_TYPE_LABEL) as SubjectType[]).map((v) => ({ value: v, label: SUBJECT_TYPE_LABEL[v] }))

export function SubjectsPage() {
  const subjects = useAsync(listSubjects, 'subjects')
  const departments = useAsync(listDepartments, 'departments')
  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [dept, setDept] = useState('')
  const [type, setType] = useState<SubjectType>('THEORY')
  const [filter, setFilter] = useState('')
  const [editing, setEditing] = useState<Subject | null>(null)
  const [editName, setEditName] = useState('')
  const [editType, setEditType] = useState<SubjectType>('THEORY')
  const add = useAction()
  const edit = useAction()
  const toggle = useAction()

  const deptCode = new Map((departments.data ?? []).map((d) => [d.id, d.code]))
  const rows = (subjects.data ?? []).filter((s) => !filter || s.department_id === filter)

  async function submit(e: FormEvent) {
    e.preventDefault()
    const done = await add.run(() => createSubject({ code: code.trim(), name: name.trim(), department_id: dept, subject_type: type }))
    if (done) {
      setCode('')
      setName('')
      subjects.reload()
    }
  }

  async function saveEdit(e: FormEvent) {
    e.preventDefault()
    if (!editing) return
    const body: { name?: string; subject_type?: SubjectType } = {}
    if (editName.trim() !== editing.name) body.name = editName.trim()
    if (editType !== editing.subject_type) body.subject_type = editType
    const done = await edit.run(() => updateSubject(editing.id, body))
    if (done) {
      setEditing(null)
      subjects.reload()
    }
  }

  async function flip(s: Subject) {
    const done = await toggle.run(() => updateSubject(s.id, { is_active: !s.is_active }))
    if (done) subjects.reload()
  }

  return (
    <>
      <p className="muted">A subject belongs to one department. Switch a subject off instead of deleting it.</p>
      <form className="inline-form" onSubmit={(e) => void submit(e)} aria-label="Add subject">
        <TextField label="Code (IT101)" value={code} onChange={setCode} maxLength={30} disabled={add.busy} />
        <TextField label="Name" value={name} onChange={setName} maxLength={120} disabled={add.busy} />
        <SelectField label="Department" value={dept} onChange={setDept} placeholder="Choose..." disabled={add.busy}
          options={(departments.data ?? []).map((d) => ({ value: d.id, label: d.code }))} />
        <SelectField label="Type" value={type} onChange={(v) => setType(v as SubjectType)} options={TYPE_OPTIONS} disabled={add.busy} />
        <button className="btn btn-primary" type="submit" disabled={add.busy || !code.trim() || !name.trim() || !dept}>Add subject</button>
      </form>
      {add.error && <ErrorBox message={add.error} />}
      {toggle.error && <ErrorBox message={toggle.error} />}
      {(subjects.error ?? departments.error) && <ErrorBox message={(subjects.error ?? departments.error) as string} onRetry={() => { subjects.reload(); departments.reload() }} />}
      {subjects.loading && !subjects.data && <Loading />}
      {departments.data && departments.data.length === 0 && <EmptyState>Add a department first (Departments tab).</EmptyState>}
      {subjects.data && subjects.data.length === 0 && departments.data && departments.data.length > 0 && <EmptyState>No subjects yet. Add the first one above.</EmptyState>}
      {subjects.data && subjects.data.length > 0 && (
        <>
          <div className="toolbar">
            <SelectField label="Show department" value={filter} onChange={setFilter} placeholder="All"
              options={(departments.data ?? []).map((d) => ({ value: d.id, label: d.code }))} />
          </div>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Code</th><th>Name</th><th>Dept</th><th>Type</th><th>Status</th><th /></tr></thead>
              <tbody>
                {rows.map((s) => (
                  <tr key={s.id}>
                    <td>{s.code}</td>
                    <td>{s.name}</td>
                    <td>{deptCode.get(s.department_id) ?? '-'}</td>
                    <td>{SUBJECT_TYPE_LABEL[s.subject_type]}</td>
                    <td>{s.is_active ? <Badge tone="good">Active</Badge> : <Badge tone="muted">Off</Badge>}</td>
                    <td className="actions">
                      <button className="btn btn-small" onClick={() => { setEditing(s); setEditName(s.name); setEditType(s.subject_type); edit.setError(null) }}>Edit</button>
                      <button className="btn btn-small" onClick={() => void flip(s)} disabled={toggle.busy}>{s.is_active ? 'Switch off' : 'Switch on'}</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {editing && (
        <Modal title={`Edit ${editing.code}`} onClose={() => setEditing(null)}>
          <form className="form" onSubmit={(e) => void saveEdit(e)}>
            <TextField label="Name" value={editName} onChange={setEditName} maxLength={120} disabled={edit.busy} />
            <SelectField label="Type (cannot change once course files exist)" value={editType} onChange={(v) => setEditType(v as SubjectType)} options={TYPE_OPTIONS} disabled={edit.busy} />
            {edit.error && <ErrorBox message={edit.error} />}
            <div className="modal-actions">
              <button type="button" className="btn" onClick={() => setEditing(null)}>Cancel</button>
              <button type="submit" className="btn btn-primary" disabled={edit.busy || !editName.trim() || (editName.trim() === editing.name && editType === editing.subject_type)}>Save</button>
            </div>
          </form>
        </Modal>
      )}
    </>
  )
}
