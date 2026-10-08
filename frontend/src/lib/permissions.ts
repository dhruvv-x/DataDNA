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
