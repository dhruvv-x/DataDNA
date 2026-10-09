import { downloadFile, request } from './client'
import type {
  AppliesTo, BulkWaiveResult, QueryCount, QueryDetail, QueryList, QueryStatus, QueryLevel, ExtensionResult, FlagKind, WaiveResult, ChecklistRow, CourseFileRow, DeadlineRow, Department, Flag, FlagList, FlagStatus, ManagedUser, Role,
  ScoreList, ScoreView, Semester, SnapshotRow, Subject, SubjectType, Template, Term, UploadResult, Version,
  WeightsHistory, WeightsSaved, WeightsView,
} from './types'

export const getScores = (params: { semester_id?: string; department_id?: string; subject_id?: string } = {}) =>
  request<ScoreList>(`/scores${qs(params)}`)

export const getScore = (courseFileId: string) => request<ScoreView>(`/course-files/${courseFileId}/score`)

export const getScoreHistory = (courseFileId: string) =>
  request<{ snapshots: SnapshotRow[] }>(`/course-files/${courseFileId}/score/history`)

export const getChecklist = (courseFileId: string) => request<ChecklistRow[]>(`/course-files/${courseFileId}/submissions`)

/** Flags of the current semester across everything the caller may see (dashboards). */
export const getFlags = (params: { status?: FlagStatus; kind?: FlagKind; semester_id?: string; department_id?: string; limit?: number } = {}) =>
  request<FlagList>(`/flags${qs(params)}`)

/** Every flag of one course file, any semester. */
export const getCourseFileFlags = (courseFileId: string) => request<Flag[]>(`/course-files/${courseFileId}/flags`)

export const getVersions = (submissionId: string) => request<Version[]>(`/submissions/${submissionId}/versions`)

export function uploadVersion(submissionId: string, file: File, reason: string | null) {
  const form = new FormData()
  form.append('file', file)
  if (reason) form.append('reason', reason)
  return request<UploadResult>(`/submissions/${submissionId}/versions`, { method: 'POST', form })
}

export const downloadVersion = (versionId: string, fallbackName: string) =>
  downloadFile(`/submission-versions/${versionId}/download`, fallbackName)

// ------------------------------------------------------------------ flag actions (S7b-2). HOD: own department, current semester. Dean: anywhere.
export const waiveFlag = (flagId: string, reason: string) => request<WaiveResult>(`/flags/${flagId}/waive`, { method: 'POST', json: { reason } })
export const grantExtension = (submissionId: string, newDueAt: string, reason: string) =>
  request<ExtensionResult>(`/submissions/${submissionId}/extensions`, { method: 'POST', json: { new_due_at: newDueAt, reason } })
export const waiveAllLate = (semesterId: string, templateId: string, reason: string) =>
  request<BulkWaiveResult>(`/semesters/${semesterId}/waive-late`, { method: 'POST', json: { template_id: templateId, reason } })

// ------------------------------------------------------------------ queries / disputes (S8). The server decides who may do what.
export const listQueries = (params: { status?: QueryStatus; level?: QueryLevel; course_file_id?: string; waiting_for_me?: boolean; limit?: number } = {}) =>
  request<QueryList>(`/queries${qs({ ...params, waiting_for_me: params.waiting_for_me ? 'true' : undefined })}`)
export const getQuery = (id: string) => request<QueryDetail>(`/queries/${id}`)
export const getQueryCount = () => request<QueryCount>('/queries/count')
export const raiseQuery = (flagId: string, message: string) => request<QueryDetail>(`/flags/${flagId}/queries`, { method: 'POST', json: { message } })
export const replyToQuery = (id: string, message: string) => request<QueryDetail>(`/queries/${id}/reply`, { method: 'POST', json: { message } })
export const escalateQuery = (id: string, message: string) => request<QueryDetail>(`/queries/${id}/escalate`, { method: 'POST', json: { message } })
export const resolveQuery = (id: string, outcome: 'UPHELD' | 'OVERTURNED', message: string) =>
  request<QueryDetail>(`/queries/${id}/resolve`, { method: 'POST', json: { outcome, message } })
export const appealQuery = (id: string, message: string) => request<QueryDetail>(`/queries/${id}/appeal`, { method: 'POST', json: { message } })

// ------------------------------------------------------------------ setup (S7b-1). The server decides who may do what.
const post = <T>(path: string, json: unknown) => request<T>(path, { method: 'POST', json })
const patch = <T>(path: string, json: unknown) => request<T>(path, { method: 'PATCH', json })

export const listDepartments = () => request<Department[]>('/departments')
export const createDepartment = (code: string, name: string) => post<Department>('/departments', { code, name })
export const renameDepartment = (id: string, name: string) => patch<Department>(`/departments/${id}`, { name })

export const listSemesters = () => request<Semester[]>('/semesters')
export const createSemester = (b: { academic_year: string; term: Term; start_date: string; end_date: string }) =>
  post<Semester>('/semesters', b)
export const changeSemesterDates = (id: string, start_date: string, end_date: string) =>
  patch<Semester>(`/semesters/${id}`, { start_date, end_date })
export const makeSemesterCurrent = (id: string) => post<Semester>(`/semesters/${id}/make-current`, undefined)

export const listSubjects = () => request<Subject[]>('/subjects')
export const createSubject = (b: { code: string; name: string; department_id: string; subject_type: SubjectType }) =>
  post<Subject>('/subjects', b)
export const updateSubject = (id: string, b: { name?: string; subject_type?: SubjectType; is_active?: boolean }) =>
  patch<Subject>(`/subjects/${id}`, b)

export const listTemplates = () => request<Template[]>('/checklist-templates')
export interface TemplateInput {
  code: string
  title: string
  description: string
  applies_to: AppliesTo
  allowed_extensions: string[]
  max_size_mb: number
  sort_order: number
}
export const createTemplate = (b: TemplateInput) => post<Template & { submission_rows_added: number }>('/checklist-templates', b)
export const updateTemplate = (id: string, b: Partial<Omit<TemplateInput, 'code' | 'applies_to'>> & { is_active?: boolean }) =>
  patch<Template & { submission_rows_added: number }>(`/checklist-templates/${id}`, b)

export const getDeadlines = (semesterId: string) => request<DeadlineRow[]>(`/semesters/${semesterId}/deadlines`)
export const putDeadlines = (semesterId: string, items: { template_id: string; due_at: string }[], allowPast: boolean) =>
  request<DeadlineRow[]>(`/semesters/${semesterId}/deadlines`, { method: 'PUT', json: { items, allow_past: allowPast } })

export const listUsers = () => request<ManagedUser[]>('/users?limit=1000')
export const createUser = (b: { email: string; full_name: string; role: Exclude<Role, 'DEAN'>; department_id: string; employee_code: string | null }) =>
  post<ManagedUser & { temporary_password: string }>('/users', b)
export const setUserActive = (id: string, is_active: boolean) => patch<ManagedUser>(`/users/${id}/active`, { is_active })
export const resetUserPassword = (id: string) => post<{ user_id: string; temporary_password: string }>(`/users/${id}/reset-password`, undefined)

export const listCourseFiles = (semesterId: string) => request<CourseFileRow[]>(`/course-files${qs({ semester_id: semesterId, limit: 1000 })}`)
export const createCourseFiles = (items: { subject_id: string; semester_id: string; faculty_id: string; division: string | null }[]) =>
  post<{ created: number }>('/course-files/bulk', { items })

export const getWeights = () => request<WeightsView>('/score-weights')
export const getWeightsHistory = () => request<WeightsHistory>('/score-weights/history')
export const setWeights = (b: { completeness: number; timeliness: number; format: number; content: number; reason: string; apply_now: boolean }) =>
  post<WeightsSaved>('/score-weights', b)

function qs(params: Record<string, string | number | undefined>): string {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== '') q.set(k, String(v))
  const s = q.toString()
  return s ? `?${s}` : ''
}
