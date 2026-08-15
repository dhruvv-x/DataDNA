import './App.css'
import { useState, useEffect, useRef } from 'react'

interface DatasetSummary {
  dataset_id: string
  name: string
  created_at: string
  version_count: number
  latest_version_id: string | null
  latest_version_number: number | null
  latest_integrity_status: string | null
  latest_has_audit: boolean
}

function App() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [datasetName, setDatasetName] = useState('')
  const [status, setStatus] = useState<string>('')
  const [trustScore, setTrustScore] = useState<any>(null)
  const [datasetId, setDatasetId] = useState<string>('')
  const [versionId, setVersionId] = useState<string>('')
  const [impact, setImpact] = useState<any>(null)

  const [newVersionFile, setNewVersionFile] = useState<File | null>(null)
  const [lineage, setLineage] = useState<any>(null)

  const [fabricResult, setFabricResult] = useState<any>(null)
  const [verifyResult, setVerifyResult] = useState<any>(null)

  const [datasetHistory, setDatasetHistory] = useState<DatasetSummary[]>([])
  const [historyError, setHistoryError] = useState('')

  // Refs let us clear the native file input's displayed filename after we've
  // consumed the file — React state alone can't do this since file inputs
  // are uncontrolled.
  const uploadFileInputRef = useRef<HTMLInputElement>(null)
  const newVersionFileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    fetchDatasetHistory()
  }, [])

  async function fetchDatasetHistory() {
    try {
      const response = await fetch('http://localhost:8000/datasets')
      const data = await response.json()
      setDatasetHistory(data.datasets || [])
      setHistoryError('')
    } catch (error) {
      setHistoryError('Could not load dataset history. Is the backend running?')
    }
  }

  function resetAllResults() {
    setTrustScore(null)
    setImpact(null)
    setLineage(null)
    setFabricResult(null)
    setVerifyResult(null)
  }

  // Turns a failed-response JSON body into a short, readable line instead of
  // dumping raw JSON in front of the user (and any judges watching).
  function describeError(data: any, fallback: string): string {
    if (data && typeof data.detail === 'string') {
      return data.detail
    }
    if (data && typeof data.message === 'string') {
      return data.message
    }
    return fallback
  }

  // Looks up a parent version's number from the currently loaded lineage
  // array, so the UI can show "Version 2" instead of a raw UUID. Falls back
  // to "an earlier version" if the parent isn't in the current lineage list
  // for some reason (shouldn't normally happen).
  function getParentVersionLabel(parentVersionId: string | null): string {
    if (!parentVersionId) {
      return 'none (root)'
    }
    const parent = lineage?.versions?.find((v: any) => v.version_id === parentVersionId)
    return parent ? `Version ${parent.version_number}` : 'an earlier version'
  }

  // Fabric CLI output comes back with raw ANSI color escape codes
  // (e.g. "\u001b[34m...\u001b[0m") which render as ugly literal characters
  // in HTML. This strips them so the log line is readable in the UI.
  function stripAnsiCodes(text: string): string {
    return text.replace(/\u001b\[[0-9;]*m/g, '')
  }

  function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (file) {
      setSelectedFile(file)
      setStatus('')
      resetAllResults()
      // Auto-fill the dataset name from the filename every time a new file
      // is chosen — this always reflects the currently selected file,
      // rather than only filling an empty field.
      const nameWithoutExt = file.name.replace(/\.(csv|json)$/i, '')
      const cleanedName = nameWithoutExt.replace(/[_-]+/g, ' ').trim()
      setDatasetName(cleanedName)
    }
  }


  // Lets the user clear an accidentally-chosen file before uploading,
  // instead of being forced to pick a replacement file or refresh the page.
  function handleRemoveSelectedFile() {
    setSelectedFile(null)
    setDatasetName('')
    if (uploadFileInputRef.current) {
      uploadFileInputRef.current.value = ''
    }
  }

  function handleRemoveNewVersionFile() {
    setNewVersionFile(null)
    if (newVersionFileInputRef.current) {
      newVersionFileInputRef.current.value = ''
    }
  }

  async function handleUpload() {
    if (!selectedFile) {
      setStatus('Please choose a file first.')
      return
    }
    if (!datasetName) {
      setStatus('Please enter a dataset name first.')
      return
    }

    setStatus('Uploading...')
    resetAllResults()

    const formData = new FormData()
    formData.append('file', selectedFile)
    formData.append('name', datasetName)

    try {
      const uploadResponse = await fetch('http://localhost:8000/datasets', {
        method: 'POST',
        body: formData,
      })
      const uploadData = await uploadResponse.json()

      if (!uploadResponse.ok) {
        setStatus('Upload failed: ' + describeError(uploadData, 'please check the file and try again.'))
        return
      }

      setStatus('Upload successful. Fetching trust score...')
      setDatasetId(uploadData.dataset_id)
      setVersionId(uploadData.version_id)

      const trustResponse = await fetch(
        `http://localhost:8000/datasets/versions/${uploadData.version_id}/trust`
      )
      const trustData = await trustResponse.json()

      setStatus('')
      setTrustScore(trustData)
      setDatasetName('')
      setSelectedFile(null)
      if (uploadFileInputRef.current) {
        uploadFileInputRef.current.value = ''
      }
      fetchDatasetHistory()
    } catch (error) {
      setStatus('Error: could not reach backend. Is it running?')
    }
  }

  async function loadVersion(targetDatasetId: string, targetVersionId: string) {
    setStatus('Loading version...')
    resetAllResults()

    try {
      const trustResponse = await fetch(
        `http://localhost:8000/datasets/versions/${targetVersionId}/trust`
      )
      const trustData = await trustResponse.json()

      if (!trustResponse.ok) {
        setStatus('Could not load version: ' + describeError(trustData, 'that version could not be found.'))
        return
      }

      setDatasetId(targetDatasetId)
      setVersionId(targetVersionId)
      setTrustScore(trustData)
      setStatus('')
    } catch (error) {
      setStatus('Error: could not reach backend.')
    }
  }

  async function handleLoadFromHistory(item: DatasetSummary) {
    if (!item.latest_version_id) {
      setStatus('This dataset has no versions yet.')
      return
    }
    if (!item.latest_has_audit) {
      setStatus(
        `"${item.name}" has no audit data on its latest version (likely leftover from early testing) — it can't be loaded. Use the cleanup script to remove it, or re-upload it as a fresh dataset.`
      )
      return
    }
    await loadVersion(item.dataset_id, item.latest_version_id)
  }

  async function handleAnalyzeImpact() {
    if (!versionId) {
      setStatus('Load a dataset version first.')
      return
    }

    setStatus('Analyzing impact...')
    setImpact(null)

    try {
      const impactResponse = await fetch(
        `http://localhost:8000/datasets/versions/${versionId}/impact`
      )
      const impactData = await impactResponse.json()

      if (!impactResponse.ok) {
        setStatus('Could not analyze impact: ' + describeError(impactData, 'please try again.'))
        return
      }

      setStatus('')
      setImpact(impactData)
    } catch (error) {
      setStatus('Error: could not reach backend.')
    }
  }

  async function handleMarkInvalidAndAnalyze() {
    if (!versionId) {
      setStatus('Load a dataset version first.')
      return
    }

    // This permanently flags the currently loaded version as invalid in the
    // database — it's not something to trigger by accident, especially on a
    // dataset being used for the live demo.
    const confirmed = window.confirm(
      'This will permanently mark the currently loaded version as INVALID. ' +
        'This cannot be undone from the UI. Continue?'
    )
    if (!confirmed) {
      return
    }

    setStatus('Marking as invalid and analyzing impact...')
    setImpact(null)

    try {
      const invalidateResponse = await fetch(
        `http://localhost:8000/datasets/versions/${versionId}/invalidate`,
        { method: 'POST' }
      )
      if (!invalidateResponse.ok) {
        const invalidateData = await invalidateResponse.json()
        setStatus('Could not mark invalid: ' + describeError(invalidateData, 'please try again.'))
        return
      }

      const impactResponse = await fetch(
        `http://localhost:8000/datasets/versions/${versionId}/impact`
      )
      const impactData = await impactResponse.json()

      if (!impactResponse.ok) {
        setStatus('Marked invalid, but impact analysis failed: ' + describeError(impactData, 'please try again.'))
        fetchDatasetHistory()
        return
      }

      setStatus('')
      setImpact(impactData)
      fetchDatasetHistory()
    } catch (error) {
      setStatus('Error: could not reach backend.')
    }
  }

  function handleNewVersionFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (file) {
      setNewVersionFile(file)
    }
  }

  async function handleAddVersion() {
    if (!datasetId) {
      setStatus('Load a dataset from history first.')
      return
    }
    if (!newVersionFile) {
      setStatus('Choose a file for the new version first.')
      return
    }

    setStatus('Adding new version...')

    const formData = new FormData()
    formData.append('file', newVersionFile)

    try {
      const response = await fetch(
        `http://localhost:8000/datasets/${datasetId}/versions`,
        {
          method: 'POST',
          body: formData,
        }
      )
      const data = await response.json()

      if (!response.ok) {
        setStatus('Add version failed: ' + describeError(data, 'please check the file and try again.'))
        return
      }

      setStatus('New version added successfully.')
      setNewVersionFile(null)
      if (newVersionFileInputRef.current) {
        newVersionFileInputRef.current.value = ''
      }
      handleViewLineage()
      fetchDatasetHistory()
    } catch (error) {
      setStatus('Error: could not reach backend.')
    }
  }

  async function handleViewLineage() {
    if (!datasetId) {
      setStatus('Load a dataset first.')
      return
    }

    try {
      const response = await fetch(
        `http://localhost:8000/datasets/${datasetId}/lineage`
      )
      const data = await response.json()

      if (!response.ok) {
        setStatus('Could not load lineage: ' + describeError(data, 'please try again.'))
        return
      }

      setLineage(data)
    } catch (error) {
      setStatus('Error: could not reach backend.')
    }
  }

  async function handleRegisterOnChain() {
    if (!versionId) {
      setStatus('Load a dataset version first.')
      return
    }

    setStatus('Registering on-chain (this may take a few seconds)...')
    setFabricResult(null)
    setVerifyResult(null)

    try {
      const response = await fetch(
        `http://localhost:8000/datasets/versions/${versionId}/register-onchain`,
        { method: 'POST' }
      )
      const data = await response.json()

      if (!response.ok) {
        setStatus('Register on-chain failed: ' + describeError(data, 'please check the Fabric network and try again.'))
        return
      }

      setStatus('')
      setFabricResult(data)
    } catch (error) {
      setStatus('Error: could not reach backend.')
    }
  }

  async function handleVerifyOnChain() {
    if (!versionId) {
      setStatus('Load a dataset version first.')
      return
    }

    setStatus('Verifying on-chain...')
    setVerifyResult(null)

    try {
      const response = await fetch(
        `http://localhost:8000/datasets/versions/${versionId}/verify-onchain`
      )
      const data = await response.json()

      if (!response.ok) {
        setStatus('Verify on-chain failed: ' + describeError(data, 'please check the Fabric network and try again.'))
        return
      }

      setStatus('')
      setVerifyResult(data)
    } catch (error) {
      setStatus('Error: could not reach backend.')
    }
  }

  function formatDate(iso: string) {
    try {
      return new Date(iso).toLocaleString()
    } catch {
      return iso
    }
  }

  return (
    <div>
      <h1>DataDNA Dashboard</h1>
      <p className="subtitle">
        AI training-data provenance, trust scoring, and downstream impact tracking
      </p>

      {datasetHistory.length > 0 && (
        <div className="stats-bar">
          <div className="stat-card">
            <span className="stat-number">{datasetHistory.length}</span>
            <span className="stat-label">Total Datasets</span>
          </div>
          <div className="stat-card">
            <span className="stat-number stat-good">
              {datasetHistory.filter((d) => d.latest_integrity_status === 'VERIFIED').length}
            </span>
            <span className="stat-label">Active</span>
          </div>
          <div className="stat-card">
            <span className="stat-number stat-bad">
              {datasetHistory.filter((d) => d.latest_integrity_status !== 'VERIFIED').length}
            </span>
            <span className="stat-label">Flagged Invalid</span>
          </div>
          <div className="stat-card">
            <span className="stat-number">
              {datasetHistory.reduce((sum, d) => sum + d.version_count, 0)}
            </span>
            <span className="stat-label">Total Versions</span>
          </div>
        </div>
      )}

      <div className="section">
        <h2>Your Datasets</h2>

        {historyError && <p className="error-text">{historyError}</p>}

        {!historyError && datasetHistory.length === 0 && (
          <p>No datasets yet — upload your first one below to get started.</p>
        )}

        {datasetHistory.length > 0 && (
          <div className="history-list">
            {datasetHistory.map((item) => (
              <div
                key={item.dataset_id}
                className={
                  'history-row' +
                  (item.dataset_id === datasetId ? ' history-row-active' : '') +
                  (!item.latest_has_audit ? ' history-row-broken' : '')
                }
              >
                <div className="history-row-main">
                  <span className="history-name">{item.name}</span>
                  <span className="history-meta">
                    {item.version_count} version{item.version_count === 1 ? '' : 's'} · uploaded{' '}
                    {formatDate(item.created_at)}
                    {!item.latest_has_audit && ' · no audit data (broken)'}
                  </span>
                </div>
                <div className="history-row-side">
                  {item.latest_integrity_status && (
                    <span
                      className={
                        'status-badge ' +
                        (item.latest_integrity_status === 'VERIFIED'
                          ? 'status-verified'
                          : 'status-invalid')
                      }
                      title={
                        item.latest_integrity_status === 'VERIFIED'
                          ? 'No invalidation has been recorded for this version (this is not a blockchain check — see Verify On-Chain for that)'
                          : 'This version was manually marked invalid for impact analysis'
                      }
                    >
                      {item.latest_integrity_status === 'VERIFIED' ? (
                        <>
                          <svg width="10" height="10" viewBox="0 0 24 24" fill="none">
                            <path
                              d="M20 6L9 17l-5-5"
                              stroke="currentColor"
                              strokeWidth="3"
                              strokeLinecap="round"
                              strokeLinejoin="round"
                            />
                          </svg>
                          ACTIVE
                        </>
                      ) : (
                        <>
                          <svg width="10" height="10" viewBox="0 0 24 24" fill="none">
                            <path
                              d="M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"
                              stroke="currentColor"
                              strokeWidth="2.5"
                              strokeLinecap="round"
                              strokeLinejoin="round"
                            />
                          </svg>
                          FLAGGED INVALID
                        </>
                      )}
                    </span>
                  )}
                  <button
                    className="primary"
                    disabled={!item.latest_has_audit}
                    onClick={() => handleLoadFromHistory(item)}
                  >
                    Load
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="section">
        <h2>Upload a New Dataset</h2>
        <p>Give it a name — this starts a brand new dataset at Version 1.</p>

        <input
          type="text"
          placeholder="Dataset name"
          value={datasetName}
          onChange={(e) => setDatasetName(e.target.value)}
        />
        <input
          type="file"
          accept=".csv,.json"
          onChange={handleFileChange}
          ref={uploadFileInputRef}
        />
        <button className="primary" onClick={handleUpload}>
          Upload
        </button>

        {selectedFile && (
          <p className="selected-file-row">
            Selected file: {selectedFile.name}
            <button className="remove-file-button" onClick={handleRemoveSelectedFile}>
              ✕ Remove
            </button>
          </p>
        )}
      </div>

      {status && <p className="status-text">{status}</p>}

      {trustScore && (
        <div className="section">
          <h2 className="trust-score-heading">Trust Score: {trustScore.overall_score}/100</h2>
          <ul>
            <li>
              Integrity: {trustScore.breakdown.integrity.score} —{' '}
              {trustScore.breakdown.integrity.explanation}
            </li>
            <li>
              Quality: {trustScore.breakdown.quality.score} —{' '}
              {trustScore.breakdown.quality.explanation}
            </li>
            <li>
              Provenance: {trustScore.breakdown.provenance.score} —{' '}
              {trustScore.breakdown.provenance.explanation}
            </li>
            <li>
              Anomaly Risk: {trustScore.breakdown.anomaly_risk.score} —{' '}
              {trustScore.breakdown.anomaly_risk.explanation}
            </li>
            {trustScore.breakdown.drift && (
              <li>
                Drift: {trustScore.breakdown.drift.score} —{' '}
                {trustScore.breakdown.drift.explanation}
              </li>
            )}
          </ul>

          <button onClick={handleAnalyzeImpact}>Analyze Impact (as-is)</button>
          <button onClick={handleMarkInvalidAndAnalyze}>
            Mark as Invalid & Analyze Impact
          </button>
        </div>
      )}

      {versionId && (
        <div className="section">
          <h2>Blockchain Provenance (Hyperledger Fabric)</h2>
          <button className="primary" onClick={handleRegisterOnChain}>
            Register On-Chain
          </button>
          <button onClick={handleVerifyOnChain}>Verify On-Chain</button>

          {fabricResult && (
            <div className="blockchain-result">
              <p className="blockchain-status-ok">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                  <path
                    d="M20 6L9 17l-5-5"
                    stroke="currentColor"
                    strokeWidth="3"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
                Registered on blockchain
              </p>
              <p className="blockchain-detail">Version ID: {fabricResult.version_id}</p>
              {fabricResult.fabric_output && (
                <p className="blockchain-detail blockchain-log">
                  {stripAnsiCodes(String(fabricResult.fabric_output))}
                </p>
              )}
            </div>
          )}

          {verifyResult && (
            <div className="blockchain-result">
              {verifyResult.verified === 'true' || verifyResult.verified === true ? (
                <p className="blockchain-status-ok">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                    <path
                      d="M20 6L9 17l-5-5"
                      stroke="currentColor"
                      strokeWidth="3"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                  Verified — matches blockchain record
                </p>
              ) : (
                <p className="blockchain-status-fail">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                    <path
                      d="M18 6L6 18M6 6l12 12"
                      stroke="currentColor"
                      strokeWidth="3"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                  Not verified — mismatch with blockchain record
                </p>
              )}
              <p className="blockchain-detail">Version ID: {verifyResult.version_id}</p>
            </div>
          )}
        </div>
      )}

      {impact && (
        <div className="section">
          <h2>Impact Analysis</h2>
          <p>Severity: {impact.severity}</p>
          <p>Confidence: {impact.confidence}</p>
          <p>Recommendation: {impact.recommendation}</p>
          <p>Affected models: {impact.affected_model_ids?.length ?? 0}</p>
          <p>Affected training runs: {impact.affected_training_runs?.length ?? 0}</p>
          <p>Affected child versions: {impact.affected_child_versions?.length ?? 0}</p>
        </div>
      )}

      {datasetId && (
        <div className="section">
          <h2>Add a New Version</h2>
          <p>Upload a modified/transformed version of the currently loaded dataset.</p>
          <input
            type="file"
            accept=".csv,.json"
            onChange={handleNewVersionFileChange}
            ref={newVersionFileInputRef}
          />
          <button className="primary" onClick={handleAddVersion}>
            Add New Version
          </button>
          <button onClick={handleViewLineage}>View Lineage</button>

          {newVersionFile && (
            <p className="selected-file-row">
              Selected file: {newVersionFile.name}
              <button className="remove-file-button" onClick={handleRemoveNewVersionFile}>
                ✕ Remove
              </button>
            </p>
          )}
        </div>
      )}

      {lineage && (
        <div className="section">
          <h2>Lineage — {lineage.versions?.length ?? 0} version(s)</h2>
          <ul className="lineage-list">
            {lineage.versions?.map((v: any) => (
              <li key={v.version_id} className="lineage-item">
                <span>
                  Version {v.version_number} — parent:{' '}
                  {getParentVersionLabel(v.parent_version_id)} — created:{' '}
                  {formatDate(v.created_at)}
                  {v.version_id === versionId && ' (currently loaded)'}
                </span>
                <button
                  className="primary"
                  disabled={v.version_id === versionId}
                  onClick={() => loadVersion(datasetId, v.version_id)}
                >
                  {v.version_id === versionId ? 'Loaded' : 'Load'}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

export default App