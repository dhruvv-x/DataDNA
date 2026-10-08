import { useState } from 'react'
import { downloadVersion, getVersions } from '../api/endpoints'
import { ApiError } from '../api/client'
import type { ChecklistRow } from '../api/types'
import { formatBytes, formatDateTime } from '../lib/format'
import { useAsync } from '../lib/useAsync'
import { Badge, ErrorBox, Loading } from './Feedback'
import { Modal } from './Modal'

export function VersionsDialog({ row, onClose }: { row: ChecklistRow; onClose: () => void }) {
  const versions = useAsync(() => getVersions(row.submission_id), row.submission_id)
  const [error, setError] = useState<string | null>(null)

  async function download(id: string, name: string) {
    setError(null)
    try {
      await downloadVersion(id, name)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Download failed.')
    }
  }

  return (
    <Modal title={`Versions: ${row.title}`} onClose={onClose}>
      {versions.loading && !versions.data && <Loading />}
      {versions.error && <ErrorBox message={versions.error} onRetry={versions.reload} />}
      {error && <ErrorBox message={error} />}
      {versions.data && (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Version</th><th>File</th><th>Uploaded</th><th>Check</th><th>SHA-256</th><th /></tr></thead>
            <tbody>
              {versions.data.map((v) => (
                <tr key={v.id}>
                  <td>v{v.version_no}{v.is_current && <> <Badge tone="info">current</Badge></>}</td>
                  <td>{v.original_filename}<div className="muted small">{formatBytes(v.size_bytes)}</div></td>
                  <td>
                    {formatDateTime(v.uploaded_at)}
                    <div className="muted small">
                      {v.uploaded_by_name}{v.uploaded_by_role === 'DEAN' && ' (Dean, on behalf)'}
                    </div>
                    {v.on_behalf_reason && <div className="muted small">Reason: {v.on_behalf_reason}</div>}
                  </td>
                  <td>
                    <Badge tone={v.validation_status === 'FORMAT_FAILED' ? 'bad' : 'good'}>
                      {v.validation_status === 'FORMAT_FAILED' ? 'Problem' : 'Passed'}
                    </Badge>
                    {v.validation_detail && <div className="muted small">{v.validation_detail}</div>}
                  </td>
                  <td><code title={v.sha256}>{v.sha256.slice(0, 12)}</code></td>
                  <td><button className="btn btn-small" onClick={() => void download(v.id, v.original_filename)}>Download</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Modal>
  )
}
