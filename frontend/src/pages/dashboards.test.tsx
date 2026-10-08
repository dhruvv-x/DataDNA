import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { API_BASE, resetClientForTests, setAccessToken } from '../api/client'
import type { Role } from '../api/types'
import App from '../App'
import { AuthContext } from '../auth/context'
import type { AuthApi } from '../auth/context'
import { canGrantException, canOpenFlagsPage, canWaiveLate } from '../lib/permissions'
import { jsonResponse, mockFetch } from '../test/helpers'
import type { Call } from '../test/helpers'
import { CourseFilePage } from './CourseFilePage'

beforeEach(() => resetClientForTests())
afterEach(() => vi.unstubAllGlobals())

const pathOf = (url: string) => url.slice(url.startsWith(API_BASE) ? API_BASE.length : 0).split('?')[0]
const queryOf = (url: string) => new URLSearchParams(url.split('?')[1] ?? '')
const bodyOf = (c: Call) => JSON.parse(String(c.init.body))
const sent = (calls: Call[], method: string, path: string) => calls.filter((c) => (c.init.method ?? 'GET') === method && pathOf(c.url) === path)

type Route_ = unknown | ((body: unknown, call: Call) => Response)

/** A fake backend. Keys look like "GET /scores". Anything not listed answers 404. */
function server(role: Role, routes: Record<string, Route_>, deptId: string | null = 'd-it') {
  return mockFetch((url, init, all) => {
    const path = pathOf(url)
    if (path === '/auth/refresh') {
      return jsonResponse(200, { access_token: 'tok', must_change_password: false, user: { id: `me-${role}`, email: 'me@x.in', full_name: 'Me Myself', role, department_id: deptId } })
    }
    const hit = routes[`${init.method ?? 'GET'} ${path}`]
    if (hit === undefined) return jsonResponse(404, { detail: 'Not found.' })
    if (typeof hit === 'function') return (hit as (b: unknown, c: Call) => Response)(init.body ? JSON.parse(String(init.body)) : null, all[all.length - 1])
    return jsonResponse(200, hit)
  })
}

function open(path: string) {
  render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>)
}

const DEPTS = [{ id: 'd-it', code: 'IT', name: 'Information Technology' }, { id: 'd-cs', code: 'CS', name: 'Computer Science' }]
const SEMS = [
  { id: 's-cur', academic_year: '2026-27', term: 'ODD', start_date: '2026-07-01', end_date: '2027-01-15', is_current: true },
  { id: 's-old', academic_year: '2025-26', term: 'EVEN', start_date: '2026-02-01', end_date: '2026-06-30', is_current: false },
]
const SUBJECTS = [
  { id: 'sub-it', code: 'IT101', name: 'Data Structures', department_id: 'd-it', subject_type: 'THEORY', is_active: true },
  { id: 'sub-cs', code: 'CS101', name: 'Operating Systems', department_id: 'd-cs', subject_type: 'THEORY', is_active: true },
]
const scoreRow = (id: string, code: string, total: number | null, problems: number, dept = 'IT') => ({
  course_file_id: id, subject_code: code, subject_name: `Name ${code}`, faculty_id: 'f', faculty_name: `Teacher ${code}`, department_id: 'd-it', department_code: dept,
  division: null, source: 'live', is_final: false, status: total === null ? 'NO_DEADLINES' : 'SCORED', total,
  parts: { completeness: total, timeliness: total, format: total, content: null }, items_total: 17, items_pending: 14, open_problems: problems,
})
const scores = (rows: ReturnType<typeof scoreRow>[]) => ({ semester_id: 's-cur', total: rows.length, scores: rows })
const flag = (id: string, kind = 'MISSING', status = 'OPEN', extra = {}) => ({
  id, course_file_id: 'cf1', submission_id: 'sub1', kind, status, reason: `${kind} reason`, raised_at: '2026-10-01T10:00:00Z', cleared_at: null,
  template_code: 'D01', template_title: 'Course syllabus', subject_code: 'IT101', subject_name: 'Data Structures', faculty_name: 'Asha Shah',
  department_id: 'd-it', department_code: 'IT', semester_id: 's-cur', division: null, exceptions: [], ...extra,
})

describe('who may act on flags', () => {
  it('Faculty never, HOD only in the current semester, Dean always', () => {
    expect(canGrantException('FACULTY', true)).toBe(false)
    expect(canGrantException('HOD', true)).toBe(true)
    expect(canGrantException('HOD', false)).toBe(false)
    expect(canGrantException('DEAN', false)).toBe(true)
  })
  it('only the Dean waives a whole item, only HOD and Dean open the flags page', () => {
    expect(canWaiveLate('DEAN')).toBe(true)
    expect(canWaiveLate('HOD')).toBe(false)
    expect(canOpenFlagsPage('FACULTY')).toBe(false)
    expect(canOpenFlagsPage('HOD')).toBe(true)
  })
})

describe('dashboard filters', () => {
  it('the Dean can filter by semester, department and subject', async () => {
    const calls = server('DEAN', {
      'GET /scores': scores([scoreRow('cf1', 'IT101', 90, 0)]), 'GET /flags': { total: 0, flags: [] },
      'GET /departments': DEPTS, 'GET /semesters': SEMS, 'GET /subjects': SUBJECTS,
    }, null)
    const u = userEvent.setup()
    open('/')
    await screen.findByRole('heading', { name: 'All courses' })
    const filters = await screen.findByRole('group', { name: 'Filters' })
    await waitFor(() => expect(within(filters).getByLabelText('Department')).toHaveTextContent('IT Information Technology'))
    await u.selectOptions(within(filters).getByLabelText('Department'), 'd-cs')
    await waitFor(() => expect(calls.some((c) => pathOf(c.url) === '/scores' && queryOf(c.url).get('department_id') === 'd-cs')).toBe(true))
    // after choosing CS, only CS subjects are offered
    const subjectBox = within(filters).getByLabelText('Subject')
    expect(within(subjectBox).queryByText('IT101 Data Structures')).not.toBeInTheDocument()
    await u.selectOptions(subjectBox, 'sub-cs')
    await waitFor(() => expect(calls.some((c) => pathOf(c.url) === '/scores' && queryOf(c.url).get('subject_id') === 'sub-cs')).toBe(true))
    await u.selectOptions(within(filters).getByLabelText('Semester'), 's-old')
    await waitFor(() => expect(calls.some((c) => pathOf(c.url) === '/scores' && queryOf(c.url).get('semester_id') === 's-old')).toBe(true))
  })

  it('a HOD gets only the subject filter', async () => {
    server('HOD', { 'GET /scores': scores([scoreRow('cf1', 'IT101', 90, 2)]), 'GET /flags': { total: 5, flags: [] }, 'GET /subjects': [SUBJECTS[0]] })
    open('/')
    const filters = await screen.findByRole('group', { name: 'Filters' })
    expect(within(filters).getByLabelText('Subject')).toBeInTheDocument()
    expect(within(filters).queryByLabelText('Department')).not.toBeInTheDocument()
    expect(within(filters).queryByLabelText('Semester')).not.toBeInTheDocument()
    expect(await screen.findByText('Open flags')).toBeInTheDocument()
  })

  it('with a subject chosen, the card counts the problems of the rows shown', async () => {
    server('HOD', { 'GET /scores': scores([scoreRow('cf1', 'IT101', 90, 3)]), 'GET /flags': { total: 9, flags: [] }, 'GET /subjects': [SUBJECTS[0]] })
    const u = userEvent.setup()
    open('/')
    const subjectBox = await screen.findByLabelText('Subject')
    await waitFor(() => expect(subjectBox).toHaveTextContent('IT101 Data Structures'))
    await u.selectOptions(subjectBox, 'sub-it')
    expect(await screen.findByText('Open problems', { selector: '.muted' })).toBeInTheDocument()
    expect(screen.queryByText('Open flags')).not.toBeInTheDocument()
  })

  it('a faculty member gets no filters and no flags link', async () => {
    server('FACULTY', { 'GET /scores': scores([scoreRow('cf1', 'IT101', 90, 0)]), 'GET /flags': { total: 0, flags: [] } })
    open('/')
    await screen.findByRole('heading', { name: 'My courses' })
    await screen.findByText('IT101 - Name IT101')
    expect(screen.queryByRole('group', { name: 'Filters' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /flags/i })).not.toBeInTheDocument()
  })

  it('the lowest score can be shown first', async () => {
    server('HOD', { 'GET /scores': scores([scoreRow('a', 'AAA', 95, 0), scoreRow('b', 'BBB', 40, 5), scoreRow('c', 'CCC', null, 0)]), 'GET /flags': { total: 0, flags: [] }, 'GET /subjects': [] })
    const u = userEvent.setup()
    open('/')
    await screen.findByText('AAA - Name AAA')
    const order = () => screen.getAllByRole('link').map((l) => l.textContent).filter((t) => t?.includes(' - Name'))
    expect(order()).toEqual(['AAA - Name AAA', 'BBB - Name BBB', 'CCC - Name CCC'])
    await u.click(screen.getByRole('button', { name: 'Lowest score first' }))
    expect(order()).toEqual(['BBB - Name BBB', 'AAA - Name AAA', 'CCC - Name CCC'])
  })

  it('an empty fresh database points the Dean to Setup, and a filter with no match says so', async () => {
    server('DEAN', { 'GET /scores': scores([]), 'GET /flags': { total: 0, flags: [] }, 'GET /departments': DEPTS, 'GET /semesters': SEMS, 'GET /subjects': SUBJECTS }, null)
    const u = userEvent.setup()
    open('/')
    expect(await screen.findByText(/No course files in the current semester yet/)).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: 'Setup' }).length).toBeGreaterThan(0)
    const filters = screen.getByRole('group', { name: 'Filters' })
    await waitFor(() => expect(within(filters).getByLabelText('Department')).toHaveTextContent('CS Computer Science'))
    await u.selectOptions(within(filters).getByLabelText('Department'), 'd-cs')
    expect(await screen.findByText('No course files match these filters.')).toBeInTheDocument()
  })
})

describe('flags page', () => {
  const list = (flags: ReturnType<typeof flag>[]) => ({ semester_id: 's-cur', total: flags.length, limit: 200, offset: 0, flags })

  it('a faculty member is sent home', async () => {
    server('FACULTY', { 'GET /scores': scores([]), 'GET /flags': list([]) })
    open('/flags')
    expect(await screen.findByRole('heading', { name: 'My courses' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Flags' })).not.toBeInTheDocument()
  })

  it('a HOD sees open flags of the department and can waive one only with a reason', async () => {
    let waived = false
    const calls = server('HOD', {
      'GET /flags': () => jsonResponse(200, list(waived ? [] : [flag('f1')])),
      'POST /flags/f1/waive': (b: unknown) => {
        waived = true
        expect((b as { reason: string }).reason).toBe('Leave approved by the HOD')
        return jsonResponse(200, { flag_id: 'f1', status: 'WAIVED' })
      },
    })
    const u = userEvent.setup()
    open('/flags')
    await screen.findByRole('heading', { name: 'Flags' })
    expect(await screen.findByText('IT101 - Data Structures')).toBeInTheDocument()
    expect(screen.queryByLabelText('Department')).not.toBeInTheDocument() // a HOD has one department only
    expect(queryOf(calls.filter((c) => pathOf(c.url) === '/flags').at(-1)!.url).get('status')).toBe('OPEN')

    await u.click(screen.getByRole('button', { name: 'Waive' }))
    const dialog = await screen.findByRole('dialog')
    await u.type(within(dialog).getByLabelText(/Reason/), 'short')
    await u.click(within(dialog).getByRole('button', { name: 'Waive flag' }))
    expect(await within(dialog).findByText(/at least 10 characters/)).toBeInTheDocument()
    expect(sent(calls, 'POST', '/flags/f1/waive')).toHaveLength(0)

    await u.clear(within(dialog).getByLabelText(/Reason/))
    await u.type(within(dialog).getByLabelText(/Reason/), 'Leave approved by the HOD')
    await u.click(within(dialog).getByRole('button', { name: 'Waive flag' }))
    expect(await within(dialog).findByText('The flag is waived.')).toBeInTheDocument()
    await u.click(within(dialog).getAllByRole('button', { name: 'Close' }).at(-1)!)
    expect(await screen.findByText('No open flags. Nothing needs attention.')).toBeInTheDocument()
  })

  it('shows the real reason when the server refuses', async () => {
    server('HOD', {
      'GET /flags': list([flag('f1')]),
      'POST /flags/f1/waive': () => jsonResponse(409, { detail: 'This flag is already WAIVED.' }),
    })
    const u = userEvent.setup()
    open('/flags')
    await u.click(await screen.findByRole('button', { name: 'Waive' }))
    const dialog = await screen.findByRole('dialog')
    await u.type(within(dialog).getByLabelText(/Reason/), 'A long enough reason')
    await u.click(within(dialog).getByRole('button', { name: 'Waive flag' }))
    expect(await within(dialog).findByText('This flag is already WAIVED.')).toBeInTheDocument()
  })

  it('filters go to the server: status, kind and (Dean) department', async () => {
    const calls = server('DEAN', { 'GET /flags': list([flag('f1')]), 'GET /departments': DEPTS, 'GET /checklist-templates': [], 'GET /scores': scores([]) }, null)
    const u = userEvent.setup()
    open('/flags')
    await screen.findByText('IT101 - Data Structures')
    await u.selectOptions(screen.getByLabelText('Kind'), 'LATE')
    await waitFor(() => expect(calls.some((c) => pathOf(c.url) === '/flags' && queryOf(c.url).get('kind') === 'LATE')).toBe(true))
    await waitFor(() => expect(screen.getByLabelText('Department')).toHaveTextContent('CS Computer Science'))
    await u.selectOptions(screen.getByLabelText('Department'), 'd-cs')
    await waitFor(() => expect(calls.some((c) => pathOf(c.url) === '/flags' && queryOf(c.url).get('department_id') === 'd-cs')).toBe(true))
    await u.selectOptions(screen.getByLabelText('Status'), '')
    await waitFor(() => expect(calls.filter((c) => pathOf(c.url) === '/flags').at(-1)!.url).not.toContain('status='))
  })

  it('only the Dean can waive every late flag of one item', async () => {
    const tmpl = [{ id: 't1', code: 'D01', title: 'Course syllabus', description: '', applies_to: 'BOTH', allowed_extensions: ['pdf'], max_size_mb: 10, sort_order: 1, is_active: true }]
    const calls = server('DEAN', {
      'GET /flags': list([flag('f1', 'LATE')]), 'GET /departments': DEPTS, 'GET /checklist-templates': tmpl, 'GET /scores': scores([]),
      'POST /semesters/s-cur/waive-late': () => jsonResponse(200, { waived: 2 }),
    }, null)
    const u = userEvent.setup()
    open('/flags')
    await u.click(await screen.findByRole('button', { name: 'Waive late flags of one item' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByRole('button', { name: 'Waive late flags' })).toBeDisabled() // no item chosen yet
    await waitFor(() => expect(within(dialog).getByLabelText('Checklist item')).toHaveTextContent('D01 Course syllabus'))
    await u.selectOptions(within(dialog).getByLabelText('Checklist item'), 't1')
    await u.type(within(dialog).getByLabelText(/Reason/), 'Server was down on the deadline')
    await u.click(within(dialog).getByRole('button', { name: 'Waive late flags' }))
    expect(await within(dialog).findByText('2 late flags waived.')).toBeInTheDocument()
    expect(bodyOf(sent(calls, 'POST', '/semesters/s-cur/waive-late')[0])).toEqual({ template_id: 't1', reason: 'Server was down on the deadline' })
  })

  it('the Waive button is only on open flags', async () => {
    server('HOD', { 'GET /flags': list([flag('f1', 'MISSING', 'OPEN'), flag('f2', 'LATE', 'WAIVED'), flag('f3', 'FORMAT', 'CLEARED')]) })
    open('/flags')
    await screen.findByText(/MISSING reason/)
    expect(screen.getAllByRole('button', { name: 'Waive' })).toHaveLength(1)
  })

  it('a HOD does not get the whole-item button', async () => {
    server('HOD', { 'GET /flags': list([flag('f1', 'LATE')]) })
    open('/flags')
    await screen.findByText('IT101 - Data Structures')
    expect(screen.queryByRole('button', { name: /Waive late flags of one item/ })).not.toBeInTheDocument()
  })
})

describe('course file page actions', () => {
  const part = (w: number) => ({ weight: w, effective_weight: w, points: w, lost: 0 })
  const body = (current: boolean) => ({
    course_file_id: 'cf1', semester_id: 's-cur', academic_year: '2026-27', term: 'ODD', subject_code: 'IT101', subject_name: 'Data Structures', faculty_id: 'f',
    faculty_name: 'Asha Shah', department_code: 'IT', division: null, semester_is_current: current, source: current ? 'live' : 'snapshot', is_final: !current,
    as_of: '2026-10-01T10:00:00Z', status: 'SCORED', total: 80, parts: { completeness: part(38.89), timeliness: part(38.89), format: part(22.22), content: part(0) },
    content_active: false, items_total: 1, items_pending: 0, notes: [],
    items: [{ submission_id: 'sub1', code: 'D01', title: 'Course syllabus', state: 'MISSING', due_at: '2026-09-30T11:30:00Z', lost: { completeness: 4, timeliness: 4, format: 0, content: 0 }, reasons: ['Nothing uploaded.'], flags: [] }],
  })
  const row = {
    submission_id: 'sub1', code: 'D01', title: 'Course syllabus', template_active: true, allowed_extensions: ['pdf'], max_size_mb: 5, due_at: '2026-09-30T11:30:00Z',
    extended_to: null, effective_due_at: '2026-09-30T11:30:00Z', current_version_id: null, version_no: null, validation_status: null, uploaded_at: null,
    uploaded_by_name: null, uploaded_by_role: null, original_filename: null, version_count: 0, open_flags: ['MISSING'],
  }

  function page(role: Role, current: boolean, extra: Record<string, Route_> = {}) {
    setAccessToken('tok')
    const calls = mockFetch((url, init) => {
      const key = `${init.method ?? 'GET'} ${pathOf(url)}`
      const hit = ({
        'GET /course-files/cf1/score': body(current), 'GET /course-files/cf1/submissions': [row],
        'GET /course-files/cf1/flags': [flag('f1')], 'GET /course-files/cf1/score/history': { snapshots: [] }, ...extra,
      } as Record<string, Route_>)[key]
      if (hit === undefined) return jsonResponse(404, { detail: 'Not found.' })
      return typeof hit === 'function' ? (hit as (b: unknown, c: Call) => Response)(init.body ? JSON.parse(String(init.body)) : null, { url, init }) : jsonResponse(200, hit)
    })
    const auth: AuthApi = {
      status: 'authed', mustChange: false, login: async () => {}, logout: async () => {}, changePassword: async () => {},
      user: { id: 'u', email: 'a@b.c', full_name: 'Test User', role, department_id: 'd' },
    }
    render(
      <AuthContext.Provider value={auth}>
        <MemoryRouter initialEntries={['/course-files/cf1']}><Routes><Route path="/course-files/:id" element={<CourseFilePage />} /></Routes></MemoryRouter>
      </AuthContext.Provider>,
    )
    return calls
  }

  it.each([
    ['HOD', true, true],
    ['DEAN', true, true],
    ['DEAN', false, true],
    ['HOD', false, false],
    ['FACULTY', true, false],
  ] as [Role, boolean, boolean][])('%s, semester current=%s: buttons shown = %s', async (role, current, shown) => {
    page(role, current)
    await screen.findByText(/MISSING reason/)
    const waive = screen.queryByRole('button', { name: 'Waive' })
    const extend = screen.queryByRole('button', { name: 'Extend deadline' })
    expect(Boolean(waive)).toBe(shown)
    expect(Boolean(extend)).toBe(shown)
  })

  it('extends a deadline: refuses an earlier date, then sends India time with the reason', async () => {
    const calls = page('HOD', true, { 'POST /submissions/sub1/extensions': () => jsonResponse(201, { exception: {}, late_flag_waived: null, changes: [] }) })
    const u = userEvent.setup()
    await u.click(await screen.findByRole('button', { name: 'Extend deadline' }))
    const dialog = await screen.findByRole('dialog')
    const date = within(dialog).getByLabelText(/New deadline/)
    expect(within(dialog).getByRole('button', { name: 'Extend deadline' })).toBeDisabled() // no date yet
    await u.type(date, '2026-09-01T10:00')
    expect(await within(dialog).findByText('The new date must be after the current deadline.')).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Extend deadline' })).toBeDisabled()
    await u.clear(date)
    await u.type(date, '2026-10-15T17:00')
    await u.type(within(dialog).getByLabelText(/Reason/), 'University holiday on that week')
    await u.click(within(dialog).getByRole('button', { name: 'Extend deadline' }))
    expect(await within(dialog).findByText('Deadline extended.')).toBeInTheDocument()
    expect(bodyOf(sent(calls, 'POST', '/submissions/sub1/extensions')[0])).toEqual({ new_due_at: '2026-10-15T17:00:00+05:30', reason: 'University holiday on that week' })
  })

  it('tells the person when an extension also waived the late flag', async () => {
    page('DEAN', true, { 'POST /submissions/sub1/extensions': () => jsonResponse(201, { exception: {}, late_flag_waived: 'f9', changes: [] }) })
    const u = userEvent.setup()
    await u.click(await screen.findByRole('button', { name: 'Extend deadline' }))
    const dialog = await screen.findByRole('dialog')
    await u.type(within(dialog).getByLabelText(/New deadline/), '2026-10-15T17:00')
    await u.type(within(dialog).getByLabelText(/Reason/), 'Exam schedule changed')
    await u.click(within(dialog).getByRole('button', { name: 'Extend deadline' }))
    expect(await within(dialog).findByText('Deadline extended. The late flag was waived too.')).toBeInTheDocument()
  })

  it('reloads the page data after a waiver', async () => {
    const calls = page('HOD', true, { 'POST /flags/f1/waive': () => jsonResponse(200, { flag_id: 'f1', status: 'WAIVED' }) })
    const u = userEvent.setup()
    await u.click(await screen.findByRole('button', { name: 'Waive' }))
    const dialog = await screen.findByRole('dialog')
    await u.type(within(dialog).getByLabelText(/Reason/), 'Faculty was on approved leave')
    const before = sent(calls, 'GET', '/course-files/cf1/score').length
    await u.click(within(dialog).getByRole('button', { name: 'Waive flag' }))
    await within(dialog).findByText('The flag is waived.')
    await waitFor(() => expect(sent(calls, 'GET', '/course-files/cf1/score').length).toBeGreaterThan(before))
  })
})
