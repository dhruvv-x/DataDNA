import { useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { grantExtension, waiveAllLate, waiveFlag } from '../api/endpoints'
import { ApiError } from '../api/client'
import type { Template } from '../api/types'
import { formatDateTime, istInputToIso } from '../lib/format'
import { MIN_REASON } from '../lib/permissions'
import { SelectField } from './Fields'
import { Modal } from './Modal'

/** Shared shell: a reason box (at least 10 characters, kept in the log forever), the server's error, Cancel and Submit. */
function ReasonForm({ intro, children, submitLabel, onClose, onSubmit, canSubmit = true }: {
  intro: ReactNode
  children?: ReactNode
  submitLabel: string
  onClose: () => void
  onSubmit: (reason: string) => Promise<string | null>
  canSubmit?: boolean
}) {
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (busy) return
    setError(null)
    if (reason.trim().length < MIN_REASON) return setError(`Write a reason of at least ${MIN_REASON} characters.`)
    setBusy(true)
    try {
      setDone(await onSubmit(reason.trim()))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong. Try again.')
    } finally {
      setBusy(false)
    }
  }

  if (done !== null) {
    return (
      <>
        <div className="alert alert-good" role="status">{done}</div>
        <div className="modal-actions"><button className="btn" onClick={onClose}>Close</button></div>
      </>
    )
  }
  return (
    <form onSubmit={(e) => void submit(e)}>
      <p className="muted small">{intro}</p>
      {children}
      <label className="field">
        <span>Reason (kept in the record forever)</span>
        <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} disabled={busy} />
      </label>
      {error && <div className="alert alert-bad" role="alert">{error}</div>}
      <div className="modal-actions">
        <button type="button" className="btn" onClick={onClose} disabled={busy}>Cancel</button>
        <button type="submit" className="btn btn-primary" disabled={busy || !canSubmit}>{busy ? 'Saving...' : submitLabel}</button>
      </div>
    </form>
  )
}

export function WaiveDialog({ flagId, label, onClose, onDone }: { flagId: string; label: string; onClose: () => void; onDone: () => void }) {
  return (
    <Modal title={`Waive: ${label}`} onClose={onClose}>
      <ReasonForm
        intro="The flag stays in the record as waived. It stops costing points, and your name and reason are logged."
        submitLabel="Waive flag"
        onClose={onClose}
        onSubmit={async (reason) => {
          await waiveFlag(flagId, reason)
          onDone()
          return 'The flag is waived.'
        }}
      />
    </Modal>
  )
}

export function ExtendDialog({ submissionId, label, effectiveDueAt, onClose, onDone }: {
  submissionId: string
  label: string
  effectiveDueAt: string | null
  onClose: () => void
  onDone: () => void
}) {
  const [local, setLocal] = useState('')
  const iso = local ? istInputToIso(local) : ''
  const tooEarly = iso !== '' && effectiveDueAt !== null && new Date(iso).getTime() <= new Date(effectiveDueAt).getTime()
  return (
    <Modal title={`Extend deadline: ${label}`} onClose={onClose}>
      <ReasonForm
        intro={`Current deadline: ${formatDateTime(effectiveDueAt)}. The new date must be later. An open late flag that the new date covers is waived with it.`}
        submitLabel="Extend deadline"
        canSubmit={iso !== '' && !tooEarly}
        onClose={onClose}
        onSubmit={async (reason) => {
          const res = await grantExtension(submissionId, iso, reason)
          onDone()
          return res.late_flag_waived ? 'Deadline extended. The late flag was waived too.' : 'Deadline extended.'
        }}
      >
        <label className="field">
          <span>New deadline (India time)</span>
          <input type="datetime-local" value={local} onChange={(e) => setLocal(e.target.value)} />
        </label>
        {tooEarly && <div className="alert alert-bad" role="alert">The new date must be after the current deadline.</div>}
      </ReasonForm>
    </Modal>
  )
}

export function WaiveLateDialog({ semesterId, templates, onClose, onDone }: {
  semesterId: string
  templates: Template[]
  onClose: () => void
  onDone: () => void
}) {
  const [templateId, setTemplateId] = useState('')
  return (
    <Modal title="Waive all late flags of one item" onClose={onClose}>
      <ReasonForm
        intro="Dean only. Every open late flag of the chosen checklist item in this semester is waived, with one reason. Each flag keeps its own record."
        submitLabel="Waive late flags"
        canSubmit={templateId !== ''}
        onClose={onClose}
        onSubmit={async (reason) => {
          const res = await waiveAllLate(semesterId, templateId, reason)
          onDone()
          return res.waived === 0 ? 'No open late flags for this item.' : `${res.waived} late flag${res.waived === 1 ? '' : 's'} waived.`
        }}
      >
        <SelectField
          label="Checklist item"
          value={templateId}
          onChange={setTemplateId}
          placeholder="Choose an item"
          options={templates.map((t) => ({ value: t.id, label: `${t.code} ${t.title}` }))}
        />
      </ReasonForm>
    </Modal>
  )
}
