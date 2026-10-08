import type { ReactNode } from 'react'

interface Option {
  value: string
  label: string
}

export function TextField({ label, value, onChange, type = 'text', disabled, placeholder, maxLength }: {
  label: string
  value: string
  onChange: (v: string) => void
  type?: string
  disabled?: boolean
  placeholder?: string
  maxLength?: number
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <input type={type} value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled} placeholder={placeholder} maxLength={maxLength} />
    </label>
  )
}

export function SelectField({ label, value, onChange, options, disabled, placeholder }: {
  label: string
  value: string
  onChange: (v: string) => void
  options: Option[]
  disabled?: boolean
  placeholder?: string
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled}>
        {placeholder !== undefined && <option value="">{placeholder}</option>}
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </label>
  )
}

/** Shown when a list is empty: says what to do first. */
export function EmptyState({ children }: { children: ReactNode }) {
  return <div className="card"><p>{children}</p></div>
}

/** A temporary password is shown once. After closing it, it can only be replaced, never read again. */
export function SecretBox({ email, password }: { email?: string; password: string }) {
  return (
    <div className="secret" role="status">
      {email && <p className="small muted">Login: {email}</p>}
      <p className="small muted">Temporary password (shown only now, the person must change it at first login):</p>
      <code className="secret-code">{password}</code>
    </div>
  )
}
