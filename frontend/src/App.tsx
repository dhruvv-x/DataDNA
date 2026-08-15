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

  // Theme — persisted to localStorage, applied via a data-theme attribute on
  // <html> so every color in App.css (which reads CSS variables only) flips
  // in one shot. Defaults to dark if nothing's saved yet.
  const [theme, setTheme] = useState<'dark' | 'light'>(() => {
    const saved = localStorage.getItem('datadna-theme')
    return saved === 'light' ? 'light' : 'dark'
  })

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('datadna-theme', theme)
  }, [theme])

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

  // Maps a severity/confidence label (HIGH/MEDIUM/LOW) to its badge class.
  // Falls back to the plain badge style for unexpected values.
  function severityClass(level: string): string {
    const normalized = (level || '').toUpperCase()
    if (normalized === 'HIGH') return 'severity-badge severity-high'
    if (normalized === 'MEDIUM') return 'severity-badge severity-medium'
    if (normalized === 'LOW') return 'severity-badge severity-low'
    return 'severity-badge'
  }

  // Maps a 0-100 sub-score to a bar-fill color tier.
  function scoreBarClass(score: number): string {
    if (score >= 70) return 'score-bar-fill'
    if (score >= 40) return 'score-bar-fill score-mid'
    return 'score-bar-fill score-low'
  }

  // Maps a 0-100 trust score to the gauge's ring/verdict color.
  function trustGaugeColor(score: number): string {
    if (score >= 70) return 'var(--color-success)'
    if (score >= 40) return 'var(--color-accent)'
    return 'var(--color-danger)'
  }

  function trustVerdictLabel(score: number): string {
    if (score >= 70) return 'Verified'
    if (score >= 40) return 'Moderate Trust'
    return 'High Risk'
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

  const trustComponents = trustScore
    ? [
        ['Integrity', trustScore.breakdown.integrity],
        ['Quality', trustScore.breakdown.quality],
        ['Provenance', trustScore.breakdown.provenance],
        ['Anomaly Risk', trustScore.breakdown.anomaly_risk],
        ...(trustScore.breakdown.drift ? [['Drift', trustScore.breakdown.drift]] : []),
      ]
    : []

  const hasInspectorContent = trustScore || impact || versionId
  const hasStatsBar = datasetHistory.length > 0

  return (
    <div>
      <header className={'topbar' + (hasStatsBar ? '' : ' topbar-solo')}>
        <div className="app-logo-frame">
          <svg
            className="app-logo"
            width="40"
            height="40"
            viewBox="0 0 60 60"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
          >
            <defs>
              <linearGradient id="logoGradient" x1="0" y1="0" x2="60" y2="60" gradientUnits="userSpaceOnUse">
                <stop offset="0" id="logo-stop-a" />
                <stop offset="1" id="logo-stop-b" />
              </linearGradient>
            </defs>
            {/* Strand A */}
            <path
              d="M30,4 Q44,10 30,18 Q16,26 30,34 Q44,42 30,50 Q16,56 30,54"
              stroke="url(#logoGradient)"
              strokeWidth="2.6"
              strokeLinecap="round"
              fill="none"
            />
            {/* Strand B */}
            <path
              d="M30,4 Q16,10 30,18 Q44,26 30,34 Q16,42 30,50 Q44,56 30,54"
              stroke="url(#logoGradient)"
              strokeWidth="2.6"
              strokeLinecap="round"
              fill="none"
              opacity="0.55"
            />
            {/* Base-pair rungs, echoing the record-fingerprint concept */}
            <line x1="18" y1="10" x2="42" y2="10" stroke="url(#logoGradient)" strokeWidth="1.6" opacity="0.7" />
            <line x1="18" y1="26" x2="42" y2="26" stroke="url(#logoGradient)" strokeWidth="1.6" opacity="0.7" />
            <line x1="18" y1="42" x2="42" y2="42" stroke="url(#logoGradient)" strokeWidth="1.6" opacity="0.7" />
            <circle cx="30" cy="4" r="2.4" fill="url(#logoGradient)" />
            {/* Pulsing node — reads as an active fingerprint scan */}
            <circle cx="30" cy="18" r="2.4" fill="url(#logoGradient)" className="logo-pulse-node" />
            <circle cx="30" cy="34" r="2.4" fill="url(#logoGradient)" />
            <circle cx="30" cy="50" r="2.4" fill="url(#logoGradient)" />
          </svg>
        </div>

        <div className="topbar-text">
          <h1>DataDNA</h1>
          <p className="subtitle">
            Cryptographic lineage for every dataset — fingerprinted on upload, versioned
            immutably, and traced through every model it trains, with tamper-evident
            proof on Hyperledger Fabric at each step.
          </p>
        </div>

        <button
          type="button"
          className="theme-toggle"
          onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
          aria-label="Toggle color theme"
        >
          <span className={'theme-toggle-option' + (theme === 'dark' ? ' theme-toggle-option-active' : '')}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z" />
            </svg>
            Dark
          </span>
          <span className={'theme-toggle-option' + (theme === 'light' ? ' theme-toggle-option-active' : '')}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="5" />
              <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" />
            </svg>
            Light
          </span>
        </button>
      </header>

      {hasStatsBar && (
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

      {status && <p className="status-text">{status}</p>}
      {historyError && <p className="error-text">{historyError}</p>}

      <div className="dashboard-grid">
        {/* ============ MAIN COLUMN ============ */}
        <div className="main-col">
          <div className="section">
            <h2>Your Datasets</h2>

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
                      (!item.latest_has_audit ? ' history-row-broken' : '') +
                      (item.latest_integrity_status === 'INVALID' ? ' history-row-flagged' : '')
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

        {/* ============ SIDE COLUMN — INSPECTOR ============ */}
        <aside className="side-col">
          {!hasInspectorContent && (
            <div className="section empty-state">
              <h2>Inspector</h2>
              <p>
                Load a dataset from the list, or upload a new one, to see its trust
                score, impact analysis, and blockchain record here.
              </p>
            </div>
          )}

          {trustScore && (
            <div className="section">
              <h2 className="trust-score-heading">Trust Score</h2>

              <div
                className="trust-gauge-row"
                style={
                  {
                    '--pct': trustScore.overall_score,
                    '--gauge-color': trustGaugeColor(trustScore.overall_score),
                  } as React.CSSProperties
                }
              >
                <div className="trust-gauge">
                  <div className="trust-gauge-value">
                    {trustScore.overall_score}
                    <span>/ 100</span>
                  </div>
                </div>
                <div className="trust-gauge-label">
                  <span className="trust-gauge-title">Overall Trust</span>
                  <span
                    className="trust-gauge-verdict"
                    style={{ color: trustGaugeColor(trustScore.overall_score) }}
                  >
                    {trustVerdictLabel(trustScore.overall_score)}
                  </span>
                </div>
              </div>

              {trustComponents.map(([label, comp]: any) => (
                <div className="score-row" key={label}>
                  <div className="score-row-label">
                    <span>{label}</span>
                    <span className="score-row-value">{comp.score}</span>
                  </div>
                  <div className="score-bar-track">
                    <div className={scoreBarClass(comp.score)} style={{ width: `${comp.score}%` }} />
                  </div>
                  <p className="score-row-explanation">{comp.explanation}</p>
                </div>
              ))}

              <button onClick={handleAnalyzeImpact}>Analyze Impact (as-is)</button>
              <button className="danger" onClick={handleMarkInvalidAndAnalyze}>
                Mark as Invalid &amp; Analyze Impact
              </button>
            </div>
          )}

          {impact && (
            <div className="section">
              <h2>Impact Analysis</h2>

              <div className="impact-badge-row">
                <div className="impact-badge-block">
                  <span className="impact-badge-label">Severity</span>
                  <span className={severityClass(impact.severity)}>{impact.severity}</span>
                </div>
                <div className="impact-badge-block">
                  <span className="impact-badge-label">Confidence</span>
                  <span className={severityClass(impact.confidence)}>{impact.confidence}</span>
                </div>
              </div>

              <div className={'impact-recommendation impact-recommendation-' + (impact.severity || '').toLowerCase()}>
                <span className="impact-recommendation-label">Recommended Action</span>
                <span className="impact-recommendation-value">{impact.recommendation}</span>
              </div>

              <div className="impact-stats-row">
                <div className="impact-stat-chip">
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <rect x="3" y="3" width="7" height="7" rx="1" />
                    <rect x="14" y="3" width="7" height="7" rx="1" />
                    <rect x="14" y="14" width="7" height="7" rx="1" />
                    <rect x="3" y="14" width="7" height="7" rx="1" />
                  </svg>
                  <span className="impact-stat-value">{impact.affected_model_ids?.length ?? 0}</span>
                  <span className="impact-stat-label">Models</span>
                </div>
                <div className="impact-stat-chip">
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <circle cx="12" cy="12" r="9" />
                    <path d="M12 7v5l3 3" />
                  </svg>
                  <span className="impact-stat-value">{impact.affected_training_runs?.length ?? 0}</span>
                  <span className="impact-stat-label">Training Runs</span>
                </div>
                <div className="impact-stat-chip">
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M9 3v18M9 3l6 4.5L9 12l6 4.5L9 21" />
                  </svg>
                  <span className="impact-stat-value">{impact.affected_child_versions?.length ?? 0}</span>
                  <span className="impact-stat-label">Child Versions</span>
                </div>
              </div>
            </div>
          )}

          {versionId && (
            <div className="section">
              <h2>Blockchain Provenance</h2>
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
        </aside>
      </div>
    </div>
  )
}

export default App