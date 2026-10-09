import { useState } from 'react'
import { appealQuery, escalateQuery, replyToQuery, resolveQuery } from '../api/endpoints'
import type { QueryDetail } from '../api/types'
import { MIN_QUERY_MESSAGE } from '../lib/permissions'
import { useAction } from '../lib/useAction'

const MIN_REPLY = 3
type Pending = 'UPHELD' | 'OVERTURNED' | null

/**
 * One box, and the buttons the SERVER says this person may press (query.can). Deciding is permanent,
 * so a decision asks for a second click that says what it will do.
 */
export function QueryActionPanel({ query, isDean, onChanged }: { query: QueryDetail; isDean: boolean; onChanged: (q: QueryDetail) => void }) {
  const { can } = query
  const [message, setMessage] = useState('')
  const [pending, setPending] = useState<Pending>(null)
  const { busy, error, setError, run } = useAction()

  if (!can.reply && !can.escalate && !can.resolve && !can.appeal) return null

  const text = message.trim()
  function tooShort(min: number): boolean {
    if (text.length >= min) return false
    setError(`Write at least ${min} characters.`)
    return true
  }

  async function send(min: number, call: () => Promise<QueryDetail>) {
    if (tooShort(min)) return
    const updated = await run(call)
    if (updated) {
      setMessage('')
      setPending(null)
      onChanged(updated)
    }
  }

  const label = can.appeal && !can.reply ? 'Why should the Dean look again?' : 'Your message'

  return (
    <section className="card" aria-label="Your answer">
      <h2>{can.appeal && !can.reply ? 'Appeal to the Dean' : 'Your answer'}</h2>
      {can.override && (
        <p className="muted small">You are the Dean stepping in at the HOD level. This is recorded as an override.</p>
      )}
      {can.appeal && <p className="muted small">The HOD kept the flag. You can take it to the Dean once, within 7 days of that decision. The Dean's decision is final.</p>}
      <label className="field">
        <span>{label}</span>
        <textarea value={message} onChange={(e) => { setMessage(e.target.value); setError(null) }} rows={3} maxLength={2000} disabled={busy} />
      </label>
      {error && <div className="alert alert-bad" role="alert">{error}</div>}

      {pending === null ? (
        <div className="modal-actions">
          {can.reply && <button className="btn" disabled={busy} onClick={() => void send(MIN_REPLY, () => replyToQuery(query.id, text))}>Send reply</button>}
          {can.escalate && <button className="btn" disabled={busy} onClick={() => void send(MIN_QUERY_MESSAGE, () => escalateQuery(query.id, text))}>Pass to the Dean</button>}
          {can.resolve && <button className="btn" disabled={busy} onClick={() => { if (!tooShort(MIN_QUERY_MESSAGE)) setPending('UPHELD') }}>Keep the flag</button>}
          {can.resolve && <button className="btn btn-primary" disabled={busy} onClick={() => { if (!tooShort(MIN_QUERY_MESSAGE)) setPending('OVERTURNED') }}>Overturn the flag</button>}
          {can.appeal && <button className="btn btn-primary" disabled={busy} onClick={() => void send(MIN_QUERY_MESSAGE, () => appealQuery(query.id, text))}>Appeal to the Dean</button>}
        </div>
      ) : (
        <div role="group" aria-label="Confirm decision">
          <p className="alert alert-warn">
            {pending === 'OVERTURNED'
              ? 'Overturning waives the flag and gives the faculty full credit for it. This is recorded and cannot be undone.'
              : isDean
                ? 'Keeping the flag as the Dean is final. The faculty cannot appeal a Dean decision.'
                : 'Keeping the flag is recorded. The faculty can appeal it once to the Dean within 7 days.'}
          </p>
          <div className="modal-actions">
            <button className="btn" disabled={busy} onClick={() => setPending(null)}>Back</button>
            <button className="btn btn-primary" disabled={busy} onClick={() => void send(MIN_QUERY_MESSAGE, () => resolveQuery(query.id, pending, text))}>
              {busy ? 'Saving...' : pending === 'OVERTURNED' ? 'Confirm: overturn the flag' : 'Confirm: keep the flag'}
            </button>
          </div>
        </div>
      )}
    </section>
  )
}
