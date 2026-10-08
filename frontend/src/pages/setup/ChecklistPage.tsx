import { useState } from 'react'
import type { FormEvent } from 'react'
import { createTemplate, listTemplates, updateTemplate } from '../../api/endpoints'
import type { AppliesTo, Template } from '../../api/types'
import { EmptyState, SelectField, TextField } from '../../components/Fields'
import { Badge, ErrorBox, Loading } from '../../components/Feedback'
import { Modal } from '../../components/Modal'
import { APPLIES_LABEL, SUPPORTED_EXTENSIONS } from '../../lib/format'
import { useAction } from '../../lib/useAction'
import { useAsync } from '../../lib/useAsync'

interface Draft {
  code: string
  title: string
  description: string
  applies_to: AppliesTo
  extensions: string[]
  max_size_mb: string
  sort_order: string
}

const EMPTY: Draft = { code: '', title: '', description: '', applies_to: 'BOTH', extensions: ['pdf'], max_size_mb: '10', sort_order: '0' }
const APPLIES_OPTIONS = (Object.keys(APPLIES_LABEL) as AppliesTo[]).map((v) => ({ value: v, label: APPLIES_LABEL[v] }))

function Form({ draft, setDraft, isNew, busy }: { draft: Draft; setDraft: (d: Draft) => void; isNew: boolean; busy: boolean }) {
  const toggle = (ext: string) =>
    setDraft({ ...draft, extensions: draft.extensions.includes(ext) ? draft.extensions.filter((e) => e !== ext) : [...draft.extensions, ext] })
  return (
    <>
      {isNew && <TextField label="Code (D01)" value={draft.code} onChange={(v) => setDraft({ ...draft, code: v })} maxLength={40} disabled={busy} />}
      <TextField label="Title" value={draft.title} onChange={(v) => setDraft({ ...draft, title: v })} maxLength={200} disabled={busy} />
      <TextField label="Description (optional)" value={draft.description} onChange={(v) => setDraft({ ...draft, description: v })} maxLength={2000} disabled={busy} />
      {isNew && <SelectField label="Applies to" value={draft.applies_to} onChange={(v) => setDraft({ ...draft, applies_to: v as AppliesTo })} options={APPLIES_OPTIONS} disabled={busy} />}
      <fieldset className="field">
        <span>Allowed file types</span>
        <div className="checks">
          {SUPPORTED_EXTENSIONS.map((ext) => (
            <label key={ext}><input type="checkbox" checked={draft.extensions.includes(ext)} onChange={() => toggle(ext)} disabled={busy} /> {ext}</label>
          ))}
        </div>
      </fieldset>
      <TextField label="Largest file (MB, 1 to 500)" type="number" value={draft.max_size_mb} onChange={(v) => setDraft({ ...draft, max_size_mb: v })} disabled={busy} />
      <TextField label="Order in the list" type="number" value={draft.sort_order} onChange={(v) => setDraft({ ...draft, sort_order: v })} disabled={busy} />
    </>
  )
}

function valid(d: Draft, isNew: boolean): boolean {
  const size = Number(d.max_size_mb)
  return (!isNew || d.code.trim() !== '') && d.title.trim() !== '' && d.extensions.length > 0 && Number.isInteger(size) && size >= 1 && size <= 500 && Number.isInteger(Number(d.sort_order)) && Number(d.sort_order) >= 0
}

export function ChecklistPage() {
  const list = useAsync(listTemplates, 'templates')
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<Template | null>(null)
  const [draft, setDraft] = useState<Draft>(EMPTY)
  const [note, setNote] = useState<string | null>(null)
  const save = useAction()
  const toggle = useAction()

  function openNew() {
    setDraft({ ...EMPTY, sort_order: String((list.data?.length ?? 0) + 1) })
    setCreating(true)
    save.setError(null)
  }

  function openEdit(t: Template) {
    setDraft({ code: t.code, title: t.title, description: t.description, applies_to: t.applies_to, extensions: t.allowed_extensions, max_size_mb: String(t.max_size_mb), sort_order: String(t.sort_order) })
    setEditing(t)
    save.setError(null)
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    const common = { title: draft.title.trim(), description: draft.description.trim(), allowed_extensions: draft.extensions, max_size_mb: Number(draft.max_size_mb), sort_order: Number(draft.sort_order) }
    const done = await save.run(() => (editing
      ? updateTemplate(editing.id, common)
      : createTemplate({ ...common, code: draft.code.trim(), applies_to: draft.applies_to })))
    if (done) {
      setNote(editing ? 'Saved.' : `Item added to ${done.submission_rows_added} existing course files.`)
      setCreating(false)
      setEditing(null)
      list.reload()
    }
  }

  async function flip(t: Template) {
    const done = await toggle.run(() => updateTemplate(t.id, { is_active: !t.is_active }))
    if (done) {
      setNote(t.is_active
        ? `${t.code} switched off. Its missing and incomplete flags clear.`
        : `${t.code} switched on again. It was added to ${done.submission_rows_added} course files.`)
      list.reload()
    }
  }

  const close = () => { setCreating(false); setEditing(null) }

  return (
    <>
      <p className="muted">
        The items every course file must have. The list here is yours to set; the demo items are placeholders until the real list is known.
        Switching an item off keeps all history.
      </p>
      <div className="toolbar"><button className="btn btn-primary" onClick={openNew}>Add item</button></div>
      {note && <div className="alert alert-good" role="status">{note}</div>}
      {toggle.error && <ErrorBox message={toggle.error} />}
      {list.error && <ErrorBox message={list.error} onRetry={list.reload} />}
      {list.loading && !list.data && <Loading />}
      {list.data && list.data.length === 0 && <EmptyState>No checklist items yet. Add the first one.</EmptyState>}
      {list.data && list.data.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Code</th><th>Title</th><th>Applies to</th><th>File types</th><th>Max MB</th><th>Status</th><th /></tr></thead>
            <tbody>
              {list.data.map((t) => (
                <tr key={t.id}>
                  <td>{t.code}</td>
                  <td>{t.title}</td>
                  <td>{APPLIES_LABEL[t.applies_to]}</td>
                  <td>{t.allowed_extensions.join(', ')}</td>
                  <td>{t.max_size_mb}</td>
                  <td>{t.is_active ? <Badge tone="good">Active</Badge> : <Badge tone="muted">Off</Badge>}</td>
                  <td className="actions">
                    <button className="btn btn-small" onClick={() => openEdit(t)}>Edit</button>
                    <button className="btn btn-small" onClick={() => void flip(t)} disabled={toggle.busy}>{t.is_active ? 'Switch off' : 'Switch on'}</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {(creating || editing) && (
        <Modal title={editing ? `Edit ${editing.code}` : 'Add checklist item'} onClose={close}>
          <form className="form" onSubmit={(e) => void submit(e)}>
            <Form draft={draft} setDraft={setDraft} isNew={!editing} busy={save.busy} />
            {save.error && <ErrorBox message={save.error} />}
            <div className="modal-actions">
              <button type="button" className="btn" onClick={close}>Cancel</button>
              <button type="submit" className="btn btn-primary" disabled={save.busy || !valid(draft, !editing)}>Save</button>
            </div>
          </form>
        </Modal>
      )}
    </>
  )
}
