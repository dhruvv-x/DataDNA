import { useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError } from '../api/client'
import { raiseQuery } from '../api/endpoints'
import { MIN_QUERY_MESSAGE } from '../lib/permissions'
import { Modal } from './Modal'

/** Faculty disputes one flag. The HOD sees it first, the Dean only if the HOD passes it on. */
export function RaiseQueryDialog({ flagId, label, onClose, onRaised }: {
  flagId: string
  label: string
  onClose: () => void
  onRaised: (queryId: string) => void
}) {
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (busy) return
    setError(null)
    if (message.trim().length < MIN_QUERY_MESSAGE) return setError(`Explain why the flag is wrong, in at least ${MIN_QUERY_MESSAGE} characters.`)
    setBusy(true)
    try {
      const q = await raiseQuery(flagId, message.trim())
      onRaised(q.id)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong. Try again.')
      setBusy(false)
    }
  }

  return (
    <Modal title={`Dispute: ${label}`} onClose={onClose}>
      <form onSubmit={(e) => void submit(e)}>
        <p className="muted small">
          Your HOD looks at this first. If the HOD cannot settle it, the Dean decides. Every step is recorded. The flag keeps
          counting until someone decides. If it is overturned, you get full credit for it.
        </p>
        <label className="field">
          <span>Why is this flag wrong?</span>
          <textarea value={message} onChange={(e) => setMessage(e.target.value)} rows={4} maxLength={2000} disabled={busy} />
        </label>
        {error && <div className="alert alert-bad" role="alert">{error}</div>}
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={busy}>{busy ? 'Sending...' : 'Send query'}</button>
        </div>
      </form>
    </Modal>
  )
}
