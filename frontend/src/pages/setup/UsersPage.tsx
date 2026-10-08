import { useState } from 'react'
import type { FormEvent } from 'react'
import { createUser, listDepartments, listUsers, resetUserPassword, setUserActive } from '../../api/endpoints'
import type { ManagedUser, Role } from '../../api/types'
import { useAuth } from '../../auth/context'
import { EmptyState, SecretBox, SelectField, TextField } from '../../components/Fields'
import { Badge, ErrorBox, Loading } from '../../components/Feedback'
import { Modal } from '../../components/Modal'
import { ROLE_LABEL, formatDateTime } from '../../lib/format'
import { useAction } from '../../lib/useAction'
import { useAsync } from '../../lib/useAsync'

interface Secret {
  title: string
  email: string
  password: string
}

export function UsersPage() {
  const { user: me } = useAuth()
  const users = useAsync(listUsers, 'users')
  const departments = useAsync(listDepartments, 'departments')
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [role, setRole] = useState<'HOD' | 'FACULTY'>('FACULTY')
  const [dept, setDept] = useState('')
  const [code, setCode] = useState('')
  const [search, setSearch] = useState('')
  const [secret, setSecret] = useState<Secret | null>(null)
  const add = useAction()
  const act = useAction()
  if (!me) return null

  const isDean = me.role === 'DEAN'
  const department = isDean ? dept : (me.department_id ?? '')
  const effectiveRole: 'HOD' | 'FACULTY' = isDean ? role : 'FACULTY'
  const query = search.trim().toLowerCase()
  const rows = (users.data ?? []).filter((u) => !query || u.full_name.toLowerCase().includes(query) || u.email.includes(query))

  async function submit(e: FormEvent) {
    e.preventDefault()
    const made = await add.run(() => createUser({ email: email.trim(), full_name: name.trim(), role: effectiveRole, department_id: department, employee_code: code.trim() || null }))
    if (made) {
      setSecret({ title: `${ROLE_LABEL[made.role]} created`, email: made.email, password: made.temporary_password })
      setEmail('')
      setName('')
      setCode('')
      users.reload()
    }
  }

  async function flip(u: ManagedUser) {
    const done = await act.run(() => setUserActive(u.id, !u.is_active))
    if (done) users.reload()
  }

  async function reset(u: ManagedUser) {
    const done = await act.run(() => resetUserPassword(u.id))
    if (done) setSecret({ title: `New password for ${u.full_name}`, email: u.email, password: done.temporary_password })
  }

  // Dean rows are never managed here; a HOD manages faculty only; nobody manages themselves here.
  const canManage = (u: ManagedUser) => u.id !== me.id && u.role !== 'DEAN' && (isDean || u.role === 'FACULTY')

  return (
    <>
      <p className="muted">
        {isDean ? 'Create HODs and faculty.' : 'Create faculty for your department.'} The system makes a temporary password; the person must change it at first login.
      </p>
      <form className="inline-form" onSubmit={(e) => void submit(e)} aria-label="Add user">
        <TextField label="Email" type="email" value={email} onChange={setEmail} disabled={add.busy} />
        <TextField label="Full name" value={name} onChange={setName} maxLength={200} disabled={add.busy} />
        {isDean && <SelectField label="Role" value={role} onChange={(v) => setRole(v as 'HOD' | 'FACULTY')} disabled={add.busy}
          options={[{ value: 'FACULTY', label: 'Faculty' }, { value: 'HOD', label: 'HOD' }]} />}
        {isDean && <SelectField label="Department" value={dept} onChange={setDept} placeholder="Choose..." disabled={add.busy}
          options={(departments.data ?? []).map((d) => ({ value: d.id, label: d.code }))} />}
        <TextField label="Employee code (optional)" value={code} onChange={setCode} maxLength={50} disabled={add.busy} />
        <button className="btn btn-primary" type="submit" disabled={add.busy || !email.trim() || !name.trim() || !department}>Create user</button>
      </form>
      {add.error && <ErrorBox message={add.error} />}
      {act.error && <ErrorBox message={act.error} />}
      {isDean && departments.data && departments.data.length === 0 && <EmptyState>Add a department first (Departments tab). A HOD or faculty needs one.</EmptyState>}
      {users.error && <ErrorBox message={users.error} onRetry={users.reload} />}
      {users.loading && !users.data && <Loading />}
      {users.data && (
        <>
          <div className="toolbar"><TextField label="Search name or email" value={search} onChange={setSearch} /></div>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Dept</th><th>Status</th><th>Last login</th><th /></tr></thead>
              <tbody>
                {rows.map((u) => (
                  <tr key={u.id}>
                    <td>{u.full_name}</td>
                    <td>{u.email}</td>
                    <td>{ROLE_LABEL[u.role as Role]}</td>
                    <td>{u.department_code ?? '-'}</td>
                    <td>
                      {u.is_active ? <Badge tone="good">Active</Badge> : <Badge tone="muted">Off</Badge>}
                      {u.must_change_password && <> <Badge tone="warn">Temp password</Badge></>}
                    </td>
                    <td>{formatDateTime(u.last_login_at)}</td>
                    <td className="actions">
                      {canManage(u) && (
                        <>
                          <button className="btn btn-small" onClick={() => void flip(u)} disabled={act.busy}>{u.is_active ? 'Deactivate' : 'Reactivate'}</button>
                          <button className="btn btn-small" onClick={() => void reset(u)} disabled={act.busy}>Reset password</button>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {rows.length === 0 && <EmptyState>No users match.</EmptyState>}
        </>
      )}
      {secret && (
        <Modal title={secret.title} onClose={() => setSecret(null)}>
          <SecretBox email={secret.email} password={secret.password} />
          <p className="small muted">Give it to the person in person or by phone. It cannot be shown again; you can only make a new one.</p>
          <div className="modal-actions"><button className="btn btn-primary" onClick={() => setSecret(null)}>I have noted it</button></div>
        </Modal>
      )}
    </>
  )
}
