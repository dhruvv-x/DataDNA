// Shapes of the backend answers the UI uses. Kept small on purpose: only fields the screens read.

export type Role = 'FACULTY' | 'HOD' | 'DEAN'

export interface User {
  id: string
  email: string
  full_name: string
  role: Role
  department_id: string | null
}

export interface Session {
  access_token: string
  must_change_password: boolean
  user: User
}

export type Part = 'completeness' | 'timeliness' | 'format' | 'content'
export const PARTS: Part[] = ['completeness', 'timeliness', 'format', 'content']

export type ScoreStatus = 'SCORED' | 'NO_DEADLINES' | 'NO_ITEMS'
export type ItemState = 'OK' | 'PENDING' | 'WAIVED' | 'LATE' | 'MISSING' | 'INCOMPLETE' | 'FORMAT' | 'CONTENT' | 'MISMATCH'
export type FlagKind = 'LATE' | 'MISSING' | 'INCOMPLETE' | 'FORMAT' | 'CONTENT' | 'MISMATCH' | 'ANOMALY'
export type FlagStatus = 'OPEN' | 'CLEARED' | 'WAIVED'

export interface PartScore {
  weight: number
  effective_weight: number
  points: number | null
  lost: number | null
}

export interface ScoreItem {
  submission_id: string
  code: string
  title: string
  state: ItemState
  due_at: string | null
  lost: Record<Part, number>
  reasons: string[]
  flags: { id: string; kind: FlagKind; status: FlagStatus }[]
}

export interface ScoreView {
  course_file_id: string
  semester_id: string
  academic_year: string
  term: string
  subject_code: string
  subject_name: string
  faculty_id: string
  faculty_name: string
  department_code: string
  division: string | null
  semester_is_current: boolean
  source: 'live' | 'snapshot' | 'live_unfrozen'
  is_final: boolean
  as_of: string
  status: ScoreStatus
  total: number | null
  parts: Record<Part, PartScore>
  content_active: boolean
  items_total: number
  items_pending: number
  items: ScoreItem[]
  notes: string[]
}

export interface ScoreRow {
  course_file_id: string
  subject_code: string
  subject_name: string
  faculty_id: string
  faculty_name: string
  department_id: string
  department_code: string
  division: string | null
  source: 'live' | 'snapshot' | 'live_unfrozen'
  is_final: boolean
  status: ScoreStatus
  total: number | null
  parts: Record<Part, number | null>
  items_total: number
  items_pending: number
  open_problems: number
}

export interface ScoreList {
  semester_id: string | null
  total: number
  scores: ScoreRow[]
}

export interface SnapshotRow {
  id: number
  created_at: string
  trigger: string
  is_final: boolean
  status: ScoreStatus
  total: number | null
}

export interface ChecklistRow {
  submission_id: string
  code: string
  title: string
  template_active: boolean
  allowed_extensions: string[]
  max_size_mb: number
  due_at: string | null
  extended_to: string | null
  effective_due_at: string | null
  current_version_id: string | null
  version_no: number | null
  validation_status: string | null
  uploaded_at: string | null
  uploaded_by_name: string | null
  uploaded_by_role: Role | null
  original_filename: string | null
  version_count: number
  open_flags: FlagKind[]
}

export interface Flag {
  id: string
  course_file_id: string
  submission_id: string | null
  kind: FlagKind
  status: FlagStatus
  reason: string
  raised_at: string
  cleared_at: string | null
  template_code: string | null
  template_title: string | null
  subject_code?: string
  faculty_name?: string
  exceptions: { id: string; kind: string; reason: string; granted_at: string; granted_by_name: string }[]
}

export interface FlagList {
  total: number
  flags: Flag[]
}

export interface Version {
  id: string
  version_no: number
  original_filename: string
  size_bytes: number
  sha256: string
  validation_status: string
  validation_detail: string | null
  uploaded_at: string
  uploaded_by_name: string
  uploaded_by_role: Role
  on_behalf_reason: string | null
  is_current: boolean
}

export interface UploadResult {
  message: string
  validation_status: string
  late: boolean
}
