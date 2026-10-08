import { describe, expect, it } from 'vitest'
import { canUpload, checkFileBeforeUpload, uploadNeedsReason } from './permissions'

describe('canUpload', () => {
  it('faculty: only in the current semester', () => {
    expect(canUpload('FACULTY', true, true)).toBe(true)
    expect(canUpload('FACULTY', false, true)).toBe(false)
  })
  it('dean: anywhere', () => {
    expect(canUpload('DEAN', true, true)).toBe(true)
    expect(canUpload('DEAN', false, true)).toBe(true)
  })
  it('HOD: never', () => {
    expect(canUpload('HOD', true, true)).toBe(false)
    expect(canUpload('HOD', false, true)).toBe(false)
  })
  it('nobody uploads to a switched-off item', () => {
    expect(canUpload('FACULTY', true, false)).toBe(false)
    expect(canUpload('DEAN', true, false)).toBe(false)
  })
})

describe('uploadNeedsReason', () => {
  it('only the Dean must give a reason', () => {
    expect(uploadNeedsReason('DEAN')).toBe(true)
    expect(uploadNeedsReason('FACULTY')).toBe(false)
  })
})

describe('checkFileBeforeUpload', () => {
  const file = (name: string, size: number) => new File([new Uint8Array(size)], name)
  it('accepts a good file', () => {
    expect(checkFileBeforeUpload(file('a.PDF', 10), ['pdf'], 1)).toBeNull()
  })
  it('refuses empty, wrong type, no extension and too big', () => {
    expect(checkFileBeforeUpload(file('a.pdf', 0), ['pdf'], 1)).toContain('empty')
    expect(checkFileBeforeUpload(file('a.exe', 5), ['pdf'], 1)).toContain('only: pdf')
    expect(checkFileBeforeUpload(file('noext', 5), ['pdf'], 1)).toContain('only: pdf')
    expect(checkFileBeforeUpload(file('a.pdf', 1024 * 1024 + 1), ['pdf'], 1)).toContain('larger than 1 MB')
  })
  it('exactly the limit is fine', () => {
    expect(checkFileBeforeUpload(file('a.pdf', 1024 * 1024), ['pdf'], 1)).toBeNull()
  })
})
