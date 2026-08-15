import { useState } from 'react'

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

  const [existingVersionId, setExistingVersionId] = useState('')

  function resetAllResults() {
    setTrustScore(null)
    setImpact(null)
    setLineage(null)
    setFabricResult(null)
    setVerifyResult(null)
  }

  function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (file) {
      setSelectedFile(file)
      setStatus('')
      resetAllResults()
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
        setStatus('Upload failed: ' + JSON.stringify(uploadData))
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
    } catch (error) {
      setStatus('Error: could not reach backend. Is it running?')
    }
  }

  async function handleLoadExistingVersion() {
    if (!existingVersionId) {
      setStatus('Paste a version ID first.')
      return
    }

    setStatus('Loading existing version...')
    resetAllResults()
    setDatasetId('')
    setVersionId('')

    try {
      const trustResponse = await fetch(
        `http://localhost:8000/datasets/versions/${existingVersionId}/trust`
      )
      const trustData = await trustResponse.json()

      if (!trustResponse.ok) {
        setStatus('Could not load version: ' + JSON.stringify(trustData))
        return
      }

      setVersionId(existingVersionId)
      setTrustScore(trustData)
      setStatus('Loaded. You can now analyze impact or check on-chain status.')
    } catch (error) {
      setStatus('Error: could not reach backend.')
    }
  }

  async function handleAnalyzeImpact() {
    if (!versionId) {
      setStatus('Upload or load a dataset version first.')
      return
    }

    setStatus('Analyzing impact...')
    setImpact(null)

    try {
      const impactResponse = await fetch(
        `http://localhost:8000/datasets/versions/${versionId}/impact`
      )
      const impactData = await impactResponse.json()

      setStatus('')
      setImpact(impactData)
    } catch (error) {
      setStatus('Error: could not reach backend.')
    }
  }

  async function handleMarkInvalidAndAnalyze() {
    if (!versionId) {
      setStatus('Upload or load a dataset version first.')
      return
    }

    setStatus('Marking as invalid and analyzing impact...')
    setImpact(null)

    try {
      await fetch(`http://localhost:8000/datasets/versions/${versionId}/invalidate`, {
        method: 'POST',
      })

      const impactResponse = await fetch(
        `http://localhost:8000/datasets/versions/${versionId}/impact`
      )
      const impactData = await impactResponse.json()

      setStatus('')
      setImpact(impactData)
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
      setStatus('Upload an initial dataset first.')
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
        setStatus('Add version failed: ' + JSON.stringify(data))
        return
      }

      setStatus('New version added successfully.')
      handleViewLineage()
    } catch (error) {
      setStatus('Error: could not reach backend.')
    }
  }

  async function handleViewLineage() {
    if (!datasetId) {
      setStatus('Upload a dataset first.')
      return
    }

    try {
      const response = await fetch(
        `http://localhost:8000/datasets/${datasetId}/lineage`
      )
      const data = await response.json()
      setLineage(data)
    } catch (error) {
      setStatus('Error: could not reach backend.')
    }
  }

  async function handleRegisterOnChain() {
    if (!versionId) {
      setStatus('Upload or load a dataset version first.')
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
        setStatus('Register on-chain failed: ' + JSON.stringify(data))
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
      setStatus('Upload or load a dataset version first.')
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
        setStatus('Verify on-chain failed: ' + JSON.stringify(data))
        return
      }

      setStatus('')
      setVerifyResult(data)
    } catch (error) {
      setStatus('Error: could not reach backend.')
    }
  }

  return (
    <div>
      <h1>DataDNA Dashboard</h1>

      <div>
        <h2>Load an Existing Version (for demo)</h2>
        <input
          type="text"
          placeholder="Paste an existing version_id"
          value={existingVersionId}
          onChange={(e) => setExistingVersionId(e.target.value)}
          style={{ width: '400px' }}
        />
        <button onClick={handleLoadExistingVersion}>Load</button>
      </div>

      <hr />

      <p>Or upload a new dataset to get started.</p>

      <input
        type="text"
        placeholder="Dataset name"
        value={datasetName}
        onChange={(e) => setDatasetName(e.target.value)}
      />
      <input type="file" onChange={handleFileChange} />
      <button onClick={handleUpload}>Upload</button>

      {selectedFile && <p>Selected file: {selectedFile.name}</p>}
      {status && <p>{status}</p>}

      {trustScore && (
        <div>
          <h2>Trust Score: {trustScore.overall_score}/100</h2>
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
          </ul>

          <button onClick={handleAnalyzeImpact}>Analyze Impact (as-is)</button>
          <button onClick={handleMarkInvalidAndAnalyze}>
            Mark as Invalid & Analyze Impact
          </button>
        </div>
      )}

      {versionId && (
        <div>
          <h2>Blockchain Provenance (Hyperledger Fabric)</h2>
          <button onClick={handleRegisterOnChain}>Register On-Chain</button>
          <button onClick={handleVerifyOnChain}>Verify On-Chain</button>

          {fabricResult && (
            <p>Register result: {JSON.stringify(fabricResult)}</p>
          )}
          {verifyResult && (
            <p>Verify result: {JSON.stringify(verifyResult)}</p>
          )}
        </div>
      )}

      {impact && (
        <div>
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
        <div>
          <h2>Add a New Version</h2>
          <p>Upload a modified/transformed version of the same dataset.</p>
          <input type="file" onChange={handleNewVersionFileChange} />
          <button onClick={handleAddVersion}>Add New Version</button>
          <button onClick={handleViewLineage}>View Lineage</button>
        </div>
      )}

      {lineage && (
        <div>
          <h2>Lineage — {lineage.versions?.length ?? 0} version(s)</h2>
          <ul>
            {lineage.versions?.map((v: any) => (
              <li key={v.version_id}>
                Version {v.version_number} — id: {v.version_id} — parent:{' '}
                {v.parent_version_id ?? 'none (root)'} — created: {v.created_at}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

export default App