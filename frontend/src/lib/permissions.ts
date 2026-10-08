import type { Role } from '../api/types'

/**
 * What the buttons show. The server decides for real (app/core/scope.py); this only avoids offering
 * buttons that would be refused.
 * FACULTY: upload to own course file, current semester only. DEAN: upload anywhere, reason required.
 * HOD: never uploads.
 */
export function canUpload(role: Role, semesterIsCurrent: boolean, templateActive: boolean): boolean {
  if (!templateActive) return false
  if (role === 'DEAN') return true
  if (role === 'FACULTY') return semesterIsCurrent
  return false
}

export function uploadNeedsReason(role: Role): boolean {
  return role === 'DEAN'
}

export const MIN_REASON = 10

/** A quick check before sending a big file. The server repeats every check. */
export function checkFileBeforeUpload(file: File, allowedExtensions: string[], maxMb: number): string | null {
  if (file.size === 0) return 'The file is empty.'
  const dot = file.name.lastIndexOf('.')
  const ext = dot >= 0 ? file.name.slice(dot + 1).toLowerCase() : ''
  if (!allowedExtensions.map((e) => e.toLowerCase()).includes(ext)) {
    return `This item accepts only: ${allowedExtensions.join(', ')}.`
  }
  if (file.size > maxMb * 1024 * 1024) return `The file is larger than ${maxMb} MB.`
  return null
}

/** Which setup tabs a role sees. The server still decides for real. DEAN: everything. HOD: people of the own department. */
export type SetupTab = 'departments' | 'semesters' | 'subjects' | 'checklist' | 'users' | 'course-files' | 'weights'

export function setupTabs(role: Role): SetupTab[] {
  if (role === 'DEAN') return ['departments', 'semesters', 'subjects', 'checklist', 'users', 'course-files', 'weights']
  if (role === 'HOD') return ['users']
  return []
}

export function canOpenSetup(role: Role): boolean {
  return setupTabs(role).length > 0
}

/** Waive a flag or extend a deadline. FACULTY never. HOD only in the current semester. DEAN anywhere. The server repeats the check. */
export function canGrantException(role: Role, semesterIsCurrent: boolean): boolean {
  if (role === 'DEAN') return true
  if (role === 'HOD') return semesterIsCurrent
  return false
}

/** Set aside every late flag of one checklist item at once. Dean only. */
export function canWaiveLate(role: Role): boolean {
  return role === 'DEAN'
}

/** The flags list page. Faculty see their flags on their own course files only. */
export function canOpenFlagsPage(role: Role): boolean {
  return role === 'HOD' || role === 'DEAN'
}
