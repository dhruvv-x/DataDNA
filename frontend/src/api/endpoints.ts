import { downloadFile, request } from './client'
import type {
  ChecklistRow, Flag, FlagList, FlagStatus, ScoreList, ScoreView, SnapshotRow, UploadResult, Version,
} from './types'

export const getScores = (params: { semester_id?: string; department_id?: string } = {}) =>
  request<ScoreList>(`/scores${qs(params)}`)

export const getScore = (courseFileId: string) => request<ScoreView>(`/course-files/${courseFileId}/score`)

export const getScoreHistory = (courseFileId: string) =>
  request<{ snapshots: SnapshotRow[] }>(`/course-files/${courseFileId}/score/history`)

export const getChecklist = (courseFileId: string) => request<ChecklistRow[]>(`/course-files/${courseFileId}/submissions`)

/** Flags of the current semester across everything the caller may see (dashboards). */
export const getFlags = (params: { status?: FlagStatus; department_id?: string; limit?: number } = {}) =>
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

function qs(params: Record<string, string | number | undefined>): string {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== '') q.set(k, String(v))
  const s = q.toString()
  return s ? `?${s}` : ''
}
