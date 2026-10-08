import { describe, expect, it } from 'vitest'
import { formatBytes, formatPoints, semesterLabel, stateTone, trustGaugeColor } from './format'

describe('trustGaugeColor', () => {
  it('green from 85, amber from 70, red below', () => {
    expect(trustGaugeColor(100)).toBe('#16a34a')
    expect(trustGaugeColor(85)).toBe('#16a34a')
    expect(trustGaugeColor(84.99)).toBe('#d97706')
    expect(trustGaugeColor(70)).toBe('#d97706')
    expect(trustGaugeColor(69.99)).toBe('#dc2626')
    expect(trustGaugeColor(0)).toBe('#dc2626')
  })
})

describe('formatPoints', () => {
  it('shows at most two decimals and a dash for none', () => {
    expect(formatPoints(88.89)).toBe('88.89')
    expect(formatPoints(100)).toBe('100')
    expect(formatPoints(19.4444)).toBe('19.44')
    expect(formatPoints(null)).toBe('-')
  })
})

describe('other helpers', () => {
  it('formatBytes', () => {
    expect(formatBytes(500)).toBe('500 B')
    expect(formatBytes(2048)).toBe('2.0 KB')
    expect(formatBytes(5 * 1024 * 1024)).toBe('5.0 MB')
  })
  it('stateTone', () => {
    expect(stateTone('OK')).toBe('good')
    expect(stateTone('PENDING')).toBe('muted')
    expect(stateTone('LATE')).toBe('warn')
    expect(stateTone('MISSING')).toBe('bad')
  })
  it('semesterLabel', () => {
    expect(semesterLabel('2026-27', 'ODD')).toBe('2026-27 Odd')
  })
})
