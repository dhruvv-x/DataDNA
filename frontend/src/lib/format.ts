import type { FlagKind, ItemState, Part, QueryAction, QueryDetail, QueryLevel, QueryRow, QueryStatus, Role } from '../api/types'

const TZ = 'Asia/Kolkata'

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '-'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '-'
  return d.toLocaleString('en-IN', { timeZone: TZ, day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '-'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '-'
  return d.toLocaleDateString('en-IN', { timeZone: TZ, day: '2-digit', month: 'short', year: 'numeric' })
}

/** 88.89 -> "88.89", 100 -> "100", null -> "-" */
export function formatPoints(n: number | null | undefined): string {
  if (n === null || n === undefined) return '-'
  return String(Math.round(n * 100) / 100)
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

/** Ring and number colour for a 0-100 score. */
export function trustGaugeColor(score: number): string {
  if (score >= 85) return '#16a34a'
  if (score >= 70) return '#d97706'
  return '#dc2626'
}

export const PART_LABEL: Record<Part, string> = {
  completeness: 'Completeness',
  timeliness: 'Timeliness',
  format: 'Format',
  content: 'Content',
}

export const ROLE_LABEL: Record<Role, string> = { FACULTY: 'Faculty', HOD: 'HOD', DEAN: 'Dean' }

export const STATE_LABEL: Record<ItemState, string> = {
  OK: 'OK',
  PENDING: 'Pending',
  WAIVED: 'Waived',
  LATE: 'Late',
  MISSING: 'Missing',
  INCOMPLETE: 'Incomplete',
  FORMAT: 'Format problem',
  CONTENT: 'Content problem',
  MISMATCH: 'Mismatch',
}

export const KIND_LABEL: Record<FlagKind, string> = {
  LATE: 'Late',
  MISSING: 'Missing',
  INCOMPLETE: 'Incomplete',
  FORMAT: 'Format problem',
  CONTENT: 'Content problem',
  MISMATCH: 'Mismatch',
  ANOMALY: 'Anomaly (review only)',
}

/** Tone used for badge colours. */
export function stateTone(state: string): 'good' | 'warn' | 'bad' | 'muted' {
  if (state === 'OK') return 'good'
  if (state === 'PENDING' || state === 'WAIVED') return 'muted'
  if (state === 'LATE' || state === 'INCOMPLETE' || state === 'ANOMALY') return 'warn'
  return 'bad'
}

export function semesterLabel(year: string, term: string): string {
  return `${year} ${term === 'ODD' ? 'Odd' : term === 'EVEN' ? 'Even' : term}`
}

// ------------------------------------------------------------------ India time for deadline inputs
const IST_MS = 5.5 * 60 * 60 * 1000

/** "2026-09-30T17:00" typed in a datetime-local box (India time) -> "2026-09-30T17:00:00+05:30" (the server needs a time zone). */
export function istInputToIso(local: string): string {
  return `${local}:00+05:30`
}

/** An ISO moment -> "2026-09-30T17:00" in India time, for a datetime-local box. */
export function isoToIstInput(iso: string | null | undefined): string {
  if (!iso) return ''
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return ''
  return new Date(t + IST_MS).toISOString().slice(0, 16)
}

export const SUBJECT_TYPE_LABEL = { THEORY: 'Theory', LAB: 'Lab', THEORY_LAB: 'Theory + Lab' } as const
export const APPLIES_LABEL = { THEORY: 'Theory only', LAB: 'Lab only', BOTH: 'Theory and lab' } as const
export const SUPPORTED_EXTENSIONS = ['pdf', 'docx', 'doc', 'xlsx', 'xls', 'pptx', 'csv', 'txt', 'png', 'jpg', 'jpeg']

// ------------------------------------------------------------------ queries (S8)
export const QUERY_STATUS_LABEL: Record<QueryStatus, string> = {
  OPEN: 'Open',
  RESOLVED_UPHELD: 'Decided: flag stays',
  RESOLVED_OVERTURNED: 'Decided: flag overturned',
}

export const QUERY_LEVEL_LABEL: Record<QueryLevel, string> = { HOD: 'With the HOD', DEAN: 'With the Dean' }

export const QUERY_ACTION_LABEL: Record<QueryAction, string> = {
  RAISE: 'raised the query',
  REPLY: 'replied',
  ESCALATE: 'passed it to the Dean',
  APPEAL: 'appealed to the Dean',
  RESOLVE: 'decided',
}

export function queryTone(q: Pick<QueryRow | QueryDetail, 'status'>): 'warn' | 'good' | 'muted' {
  if (q.status === 'OPEN') return 'warn'
  return q.status === 'RESOLVED_OVERTURNED' ? 'good' : 'muted'
}

/** "With the HOD" while open, the decision once closed. */
export function queryStatusText(q: Pick<QueryRow | QueryDetail, 'status' | 'current_level'>): string {
  return q.status === 'OPEN' ? `Open, ${QUERY_LEVEL_LABEL[q.current_level].toLowerCase()}` : QUERY_STATUS_LABEL[q.status]
}
