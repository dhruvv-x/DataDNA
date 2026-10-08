import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/context'

const MIN_LENGTH = 10

export function ChangePasswordPage() {
  const { mustChange, changePassword, logout } = useAuth()
  const navigate = useNavigate()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [again, setAgain] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    if (next.length < MIN_LENGTH) return setError(`The new password must be at least ${MIN_LENGTH} characters.`)
    if (next !== again) return setError('The two new passwords are not the same.')
    setBusy(true)
    try {
      await changePassword(current, next)
      setDone(true)
      if (mustChange) navigate('/', { replace: true })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not change the password.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="center-card">
      <h1>{mustChange ? 'Choose a new password' : 'Change password'}</h1>
      {mustChange && <p className="muted">You are using a temporary password. Set your own before you continue.</p>}
      <form onSubmit={(e) => void submit(e)} className="card form">
        <label className="field">
          <span>{mustChange ? 'Temporary password' : 'Current password'}</span>
          <input type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
        </label>
        <label className="field">
          <span>New password (at least {MIN_LENGTH} characters)</span>
          <input type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} required />
        </label>
        <label className="field">
          <span>New password again</span>
          <input type="password" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} required />
        </label>
        {error && <div className="alert alert-bad" role="alert">{error}</div>}
        {done && <div className="alert alert-good" role="status">Password changed. Other devices were logged out.</div>}
        <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? 'Saving...' : 'Save new password'}</button>
        {mustChange ? (
          <button type="button" className="btn" onClick={() => void logout()}>Log out</button>
        ) : (
          <Link to="/" className="linklike">Back to dashboard</Link>
        )}
      </form>
    </div>
  )
}
