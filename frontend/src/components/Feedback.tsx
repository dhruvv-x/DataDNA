import type { ReactNode } from 'react'
import { stateTone } from '../lib/format'

export function Loading({ what = 'Loading' }: { what?: string }) {
  return <p className="muted" role="status">{what}...</p>
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="alert alert-bad" role="alert">
      <span>{message}</span>
      {onRetry && <button className="btn btn-small" onClick={onRetry}>Try again</button>}
    </div>
  )
}

export function Badge({ tone, children }: { tone: 'good' | 'warn' | 'bad' | 'muted' | 'info'; children: ReactNode }) {
  return <span className={`badge badge-${tone}`}>{children}</span>
}

export function StateBadge({ state, label }: { state: string; label: string }) {
  return <Badge tone={stateTone(state)}>{label}</Badge>
}
