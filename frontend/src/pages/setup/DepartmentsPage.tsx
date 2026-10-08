import { useState } from 'react'
import type { FormEvent } from 'react'
import { createDepartment, listDepartments, renameDepartment } from '../../api/endpoints'
import type { Department } from '../../api/types'
import { EmptyState, TextField } from '../../components/Fields'
import { ErrorBox, Loading } from '../../components/Feedback'
import { Modal } from '../../components/Modal'
import { useAction } from '../../lib/useAction'
import { useAsync } from '../../lib/useAsync'

export function DepartmentsPage() {
  const list = useAsync(listDepartments, 'departments')
  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [editing, setEditing] = useState<Department | null>(null)
  const [newName, setNewName] = useState('')
  const add = useAction()
  const rename = useAction()

  async function submit(e: FormEvent) {
    e.preventDefault()
    const done = await add.run(() => createDepartment(code.trim(), name.trim()))
    if (done) {
      setCode('')
      setName('')
      list.reload()
    }
  }

  async function saveName(e: FormEvent) {
    e.preventDefault()
    if (!editing) return
    const done = await rename.run(() => renameDepartment(editing.id, newName.trim()))
    if (done) {
      setEditing(null)
      list.reload()
    }
  }

  return (
    <>
      <p className="muted">Start here. Every subject and every HOD or faculty belongs to a department. Departments are never deleted.</p>
      <form className="inline-form" onSubmit={(e) => void submit(e)} aria-label="Add department">
        <TextField label="Code (for example IT)" value={code} onChange={setCode} maxLength={20} disabled={add.busy} />
        <TextField label="Name" value={name} onChange={setName} maxLength={120} disabled={add.busy} />
        <button className="btn btn-primary" type="submit" disabled={add.busy || !code.trim() || !name.trim()}>Add department</button>
      </form>
      {add.error && <ErrorBox message={add.error} />}
      {list.error && <ErrorBox message={list.error} onRetry={list.reload} />}
      {list.loading && !list.data && <Loading />}
      {list.data && list.data.length === 0 && <EmptyState>No departments yet. Add the first one above.</EmptyState>}
      {list.data && list.data.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Code</th><th>Name</th><th /></tr></thead>
            <tbody>
              {list.data.map((d) => (
                <tr key={d.id}>
                  <td>{d.code}</td>
                  <td>{d.name}</td>
                  <td><button className="btn btn-small" onClick={() => { setEditing(d); setNewName(d.name); rename.setError(null) }}>Rename</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editing && (
        <Modal title={`Rename ${editing.code}`} onClose={() => setEditing(null)}>
          <form className="form" onSubmit={(e) => void saveName(e)}>
            <TextField label="Name" value={newName} onChange={setNewName} maxLength={120} disabled={rename.busy} />
            {rename.error && <ErrorBox message={rename.error} />}
            <div className="modal-actions">
              <button type="button" className="btn" onClick={() => setEditing(null)}>Cancel</button>
              <button type="submit" className="btn btn-primary" disabled={rename.busy || !newName.trim()}>Save</button>
            </div>
          </form>
        </Modal>
      )}
    </>
  )
}
