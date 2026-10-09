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
  subject_name?: string
  faculty_name?: string
  department_id?: string
  department_code?: string
  semester_id?: string
  division?: string | null
  exceptions: { id: string; kind: string; reason: string; granted_at: string; granted_by_name: string }[]
}

export interface FlagList {
  semester_id?: string | null
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

// ------------------------------------------------------------------ setup screens (S7b-1)
export type Term = 'ODD' | 'EVEN'
export type SubjectType = 'THEORY' | 'LAB' | 'THEORY_LAB'
export type AppliesTo = 'THEORY' | 'LAB' | 'BOTH'

export interface Department {
  id: string
  code: string
  name: string
}

export interface Semester {
  id: string
  academic_year: string
  term: Term
  start_date: string
  end_date: string
  is_current: boolean
}

export interface Subject {
  id: string
  code: string
  name: string
  department_id: string
  subject_type: SubjectType
  is_active: boolean
}

export interface Template {
  id: string
  code: string
  title: string
  description: string
  applies_to: AppliesTo
  allowed_extensions: string[]
  max_size_mb: number
  sort_order: number
  is_active: boolean
}

export interface DeadlineRow {
  semester_id: string
  template_id: string
  template_code: string
  title: string
  due_at: string
}

export interface ManagedUser {
  id: string
  email: string
  full_name: string
  role: Role
  department_id: string | null
  department_code: string | null
  employee_code: string | null
  is_active: boolean
  must_change_password: boolean
  last_login_at: string | null
}

export interface CourseFileRow {
  id: string
  subject_id: string
  subject_code: string
  subject_name: string
  semester_id: string
  faculty_id: string
  faculty_name: string
  department_code: string
  division: string | null
}

export interface WeightSet {
  id: number
  completeness: number
  timeliness: number
  format: number
  content: number
  reason: string | null
  set_by_name: string | null
  created_at: string
}

export interface WeightsView {
  latest: WeightSet
  current_semester: { semester_id: string; weights: WeightSet } | null
  content_scoring_enabled: boolean
  effective_for_current_semester?: Record<Part, number>
}

export interface WeightsSaved extends WeightsView {
  applied_to_current_semester: boolean
  message: string
}

export interface WeightsHistory {
  weights: WeightSet[]
  semester_assignments: { id: number; semester_id: string; academic_year: string; term: Term; weights_id: number; reason: string | null; created_at: string }[]
}

export interface WaiveResult {
  flag_id: string
  status: 'WAIVED'
}

export interface ExtensionResult {
  late_flag_waived: string | null
}

export interface BulkWaiveResult {
  waived: number
}

// ------------------------------------------------------------------ queries / disputes (S8)
export type QueryLevel = 'HOD' | 'DEAN'
export type QueryStatus = 'OPEN' | 'RESOLVED_UPHELD' | 'RESOLVED_OVERTURNED'
export type QueryAction = 'RAISE' | 'REPLY' | 'ESCALATE' | 'APPEAL' | 'RESOLVE'

/** What the server says the caller may do with a query right now. The screen never guesses. */
export interface QueryCan {
  reply: boolean
  escalate: boolean
  resolve: boolean
  appeal: boolean
  override: boolean
}

export interface QueryStep {
  id: string
  action: QueryAction
  level: QueryLevel
  actor_id: string
  actor_name: string
  actor_role: Role
  override: boolean
  outcome: 'UPHELD' | 'OVERTURNED' | null
  message: string
  created_at: string
}

export interface QueryRow {
  id: string
  flag_id: string
  raised_by: string
  raised_by_name: string
  raised_by_role: Role
  current_level: QueryLevel
  status: QueryStatus
  appealed: boolean
  created_at: string
  resolved_at: string | null
  resolved_level: QueryLevel | null
  last_activity_at: string
  flag_kind: FlagKind
  flag_status: FlagStatus
  flag_reason: string
  template_code: string | null
  template_title: string | null
  course_file_id: string
  semester_is_current: boolean
  department_code: string
  division: string | null
  faculty_id: string
  faculty_name: string
  subject_code: string
  subject_name: string
  last_actor_role?: Role | null
  can: QueryCan
}

export interface QueryDetail extends Omit<QueryRow, 'can' | 'last_actor_role'> {
  steps: QueryStep[]
  can: QueryCan
  flag_change?: string
}

export interface QueryList {
  total: number
  queries: QueryRow[]
}

export interface QueryCount {
  waiting_for_me: number
  open: number
}
