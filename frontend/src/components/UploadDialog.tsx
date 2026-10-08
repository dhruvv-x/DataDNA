import { useState } from 'react'
import type { FormEvent } from 'react'
import { uploadVersion } from '../api/endpoints'
import { ApiError } from '../api/client'
import type { ChecklistRow, Role, UploadResult } from '../api/types'
import { MIN_REASON, checkFileBeforeUpload, uploadNeedsReason } from '../lib/permissions'
import { Modal } from './Modal'

export function UploadDialog({ row, role, onClose, onUploaded }: {
  row: ChecklistRow
  role: Role
  onClose: () => void
  onUploaded: () => void
}) {
  const [file, setFile] = useState<File | null>(null)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<UploadResult | null>(null)
  const needsReason = uploadNeedsReason(role)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    if (!file) return setError('Choose a file first.')
    const problem = checkFileBeforeUpload(file, row.allowed_extensions, row.max_size_mb)
    if (problem) return setError(problem)
    if (needsReason && reason.trim().length < MIN_REASON) return setError(`Write a reason of at least ${MIN_REASON} characters.`)
    setBusy(true)
    try {
      const res = await uploadVersion(row.submission_id, file, needsReason ? reason.trim() : null)
      setResult(res)
      onUploaded()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Upload failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title={`Upload: ${row.title}`} onClose={onClose}>
      {result ? (
        <>
          <div className={`alert ${result.validation_status === 'FORMAT_FAILED' ? 'alert-warn' : 'alert-good'}`} role="status">{result.message}</div>
          <div className="modal-actions"><button className="btn" onClick={onClose}>Close</button></div>
        </>
      ) : (
        <form onSubmit={(e) => void submit(e)}>
          <p className="muted small">
            Allowed: {row.allowed_extensions.join(', ')}. Largest file: {row.max_size_mb} MB. Every upload is kept as a new version.
          </p>
          <label className="field">
            <span>File</span>
            <input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} disabled={busy} />
          </label>
          {needsReason && (
            <label className="field">
              <span>Reason for uploading on behalf of the faculty (kept forever)</span>
              <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} disabled={busy} />
            </label>
          )}
          {error && <div className="alert alert-bad" role="alert">{error}</div>}
          <div className="modal-actions">
            <button type="button" className="btn" onClick={onClose} disabled={busy}>Cancel</button>
            <button type="submit" className="btn btn-primary" disabled={busy}>{busy ? 'Uploading...' : 'Upload'}</button>
          </div>
        </form>
      )}
    </Modal>
  )
}
