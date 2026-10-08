import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { API_BASE, resetClientForTests } from '../api/client'
import type { Role } from '../api/types'
import App from '../App'
import { isoToIstInput, istInputToIso } from '../lib/format'
import { setupTabs } from '../lib/permissions'
import { jsonResponse, mockFetch } from '../test/helpers'
import type { Call } from '../test/helpers'

beforeEach(() => resetClientForTests())
afterEach(() => vi.unstubAllGlobals())

/** "/api/departments?x=1" (or a full address from .env.local) -> "/departments" */
const pathOf = (url: string) => url.slice(url.startsWith(API_BASE) ? API_BASE.length : 0).split('?')[0]

type Route = unknown | ((body: unknown, call: Call) => Response)

/** A fake backend. Keys look like "GET /departments". Anything not listed answers 404 and is recorded. */
function server(role: Role, routes: Record<string, Route>, deptId: string | null = 'd-it') {
  const calls = mockFetch((url, init, all) => {
    const path = pathOf(url)
    if (path === '/auth/refresh') {
      return jsonResponse(200, { access_token: 'tok', must_change_password: false, user: { id: `me-${role}`, email: 'me@x.in', full_name: 'Me Myself', role, department_id: deptId } })
    }
    const hit = routes[`${init.method ?? 'GET'} ${path}`]
    if (hit === undefined) return jsonResponse(404, { detail: 'Not found.' })
    if (typeof hit === 'function') return (hit as (b: unknown, c: Call) => Response)(init.body ? JSON.parse(String(init.body)) : null, all[all.length - 1])
    return jsonResponse(200, hit)
  })
  return calls
}

const sent = (calls: Call[], method: string, path: string) =>
  calls.filter((c) => (c.init.method ?? 'GET') === method && pathOf(c.url) === path)
const bodyOf = (c: Call) => JSON.parse(String(c.init.body))

function open(path: string) {
  render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>)
}

const DEPTS = [{ id: 'd-it', code: 'IT', name: 'Information Technology' }, { id: 'd-cs', code: 'CS', name: 'Computer Science' }]
const SEMS = [
  { id: 's-new', academic_year: '2026-27', term: 'ODD', start_date: '2026-07-01', end_date: '2027-01-15', is_current: false },
  { id: 's-cur', academic_year: '2026-27', term: 'EVEN', start_date: '2026-02-01', end_date: '2026-06-30', is_current: true },
]
const TEMPLATES = [
  { id: 't1', code: 'D01', title: 'Syllabus', description: '', applies_to: 'BOTH', allowed_extensions: ['pdf'], max_size_mb: 10, sort_order: 1, is_active: true },
  { id: 't2', code: 'D02', title: 'Time table', description: '', applies_to: 'BOTH', allowed_extensions: ['xlsx'], max_size_mb: 5, sort_order: 2, is_active: true },
]
const user = (id: string, name: string, role: Role, dept: string | null, extra = {}) => ({
  id, email: `${id}@x.in`, full_name: name, role, department_id: dept, department_code: dept ? dept.slice(2).toUpperCase() : null,
  employee_code: null, is_active: true, must_change_password: false, last_login_at: null, ...extra,
})

describe('who gets the setup screens', () => {
  it('lists the tabs per role', () => {
    expect(setupTabs('DEAN')).toHaveLength(7)
    expect(setupTabs('HOD')).toEqual(['users'])
    expect(setupTabs('FACULTY')).toEqual([])
  })

  it('a Dean sees the Setup link and all seven tabs', async () => {
    server('DEAN', { 'GET /departments': [], 'GET /scores': { semester_id: null, total: 0, scores: [] }, 'GET /flags': { total: 0, flags: [] } })
    open('/setup')
    expect(await screen.findByRole('heading', { name: 'Setup' })).toBeInTheDocument()
    const tabs = within(screen.getByRole('navigation', { name: 'Setup' })).getAllByRole('link')
    expect(tabs.map((t) => t.textContent)).toEqual(['Departments', 'Semesters', 'Subjects', 'Checklist items', 'Users', 'Course files', 'Score weights'])
    expect(await screen.findByText(/No departments yet/)).toBeInTheDocument()
  })

  it('a faculty member is sent home and never loads a setup page', async () => {
    const calls = server('FACULTY', { 'GET /scores': { semester_id: 's', total: 0, scores: [] }, 'GET /flags': { total: 0, flags: [] }, 'GET /departments': DEPTS })
    open('/setup/departments')
    expect(await screen.findByRole('heading', { name: 'My courses' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /^(Setup|People)$/ })).not.toBeInTheDocument()
    expect(sent(calls, 'GET', '/departments')).toHaveLength(0)
  })

  it('a HOD only gets the Users tab, whatever address is typed', async () => {
    server('HOD', { 'GET /users': [user('f1', 'Asha Shah', 'FACULTY', 'd-it')], 'GET /departments': [DEPTS[0]] })
    open('/setup/departments')
    expect(await screen.findByRole('heading', { name: 'People' })).toBeInTheDocument()
    const tabs = within(screen.getByRole('navigation', { name: 'Setup' })).getAllByRole('link')
    expect(tabs.map((t) => t.textContent)).toEqual(['Users'])
    expect(await screen.findByText('Asha Shah')).toBeInTheDocument()
    expect(screen.queryByLabelText('Role')).not.toBeInTheDocument()
  })
})

describe('India time helpers', () => {
  it('adds the +05:30 zone the server demands', () => {
    expect(istInputToIso('2026-09-30T17:00')).toBe('2026-09-30T17:00:00+05:30')
  })
  it('shows a stored moment in India time', () => {
    expect(isoToIstInput('2026-09-30T11:30:00Z')).toBe('2026-09-30T17:00')
    expect(isoToIstInput('2026-12-31T20:00:00Z')).toBe('2027-01-01T01:30')
    expect(isoToIstInput(null)).toBe('')
  })
})

describe('departments', () => {
  it('creates one and shows the server message when it already exists', async () => {
    const calls = server('DEAN', {
      'GET /departments': [],
      'POST /departments': () => jsonResponse(409, { detail: 'This already exists.' }),
    })
    const u = userEvent.setup()
    open('/setup/departments')
    await screen.findByText(/No departments yet/)
    await u.type(screen.getByLabelText(/Code/), ' it ')
    await u.type(screen.getByLabelText('Name'), 'Information Technology')
    await u.click(screen.getByRole('button', { name: 'Add department' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('This already exists.')
    expect(bodyOf(sent(calls, 'POST', '/departments')[0])).toEqual({ code: 'it', name: 'Information Technology' })
  })

  it('renames with PATCH', async () => {
    const calls = server('DEAN', { 'GET /departments': DEPTS, 'PATCH /departments/d-it': () => jsonResponse(200, DEPTS[0]) })
    const u = userEvent.setup()
    open('/setup/departments')
    await u.click((await screen.findAllByRole('button', { name: 'Rename' }))[0])
    const dialog = within(screen.getByRole('dialog'))
    const field = dialog.getByLabelText('Name')
    await u.clear(field)
    await u.type(field, 'IT Dept')
    await u.click(dialog.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(sent(calls, 'PATCH', '/departments/d-it')).toHaveLength(1))
    expect(bodyOf(sent(calls, 'PATCH', '/departments/d-it')[0])).toEqual({ name: 'IT Dept' })
  })
})

describe('semesters', () => {
  it('asks before making a semester current, and only then calls the server', async () => {
    const calls = server('DEAN', { 'GET /semesters': SEMS, 'POST /semesters/s-new/make-current': () => jsonResponse(200, { ...SEMS[0], is_current: true }) })
    const u = userEvent.setup()
    open('/setup/semesters')
    await u.click(await screen.findByRole('button', { name: 'Make current' }))
    expect(sent(calls, 'POST', '/semesters/s-new/make-current')).toHaveLength(0)
    expect(screen.getByRole('dialog')).toHaveTextContent(/final scores are frozen/)
    await u.click(screen.getByRole('button', { name: 'Yes, make it current' }))
    await waitFor(() => expect(sent(calls, 'POST', '/semesters/s-new/make-current')).toHaveLength(1))
  })

  it('the current semester has no Make current button', async () => {
    server('DEAN', { 'GET /semesters': [SEMS[1]] })
    open('/setup/semesters')
    expect(await screen.findByText('Current')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Make current' })).not.toBeInTheDocument()
  })

  it('creates a semester with the typed values', async () => {
    const calls = server('DEAN', { 'GET /semesters': [], 'POST /semesters': () => jsonResponse(201, SEMS[0]) })
    const u = userEvent.setup()
    open('/setup/semesters')
    await screen.findByText(/No semesters yet/)
    await u.type(screen.getByLabelText(/Academic year/), '2026-27')
    await u.type(screen.getByLabelText('Start date'), '2026-07-01')
    await u.type(screen.getByLabelText('End date'), '2027-01-15')
    await u.click(screen.getByRole('button', { name: 'Add semester' }))
    await waitFor(() => expect(sent(calls, 'POST', '/semesters')).toHaveLength(1))
    expect(bodyOf(sent(calls, 'POST', '/semesters')[0])).toEqual({ academic_year: '2026-27', term: 'ODD', start_date: '2026-07-01', end_date: '2027-01-15' })
  })
})

describe('deadlines', () => {
  const base = {
    'GET /semesters': SEMS, 'GET /checklist-templates': TEMPLATES,
    'GET /semesters/s-new/deadlines': [{ semester_id: 's-new', template_id: 't1', template_code: 'D01', title: 'Syllabus', due_at: '2099-09-30T11:30:00Z' }],
  }

  it('sends only the rows that changed, in India time', async () => {
    const calls = server('DEAN', { ...base, 'PUT /semesters/s-new/deadlines': () => jsonResponse(200, []) })
    const u = userEvent.setup()
    open('/setup/semesters/s-new/deadlines')
    const first = await screen.findByLabelText('Deadline for D01')
    expect(first).toHaveValue('2099-09-30T17:00') // shown in India time
    await u.type(screen.getByLabelText('Deadline for D02'), '2099-10-15T17:00')
    await u.click(screen.getByRole('button', { name: 'Save 1 change' }))
    await waitFor(() => expect(sent(calls, 'PUT', '/semesters/s-new/deadlines')).toHaveLength(1))
    expect(bodyOf(sent(calls, 'PUT', '/semesters/s-new/deadlines')[0])).toEqual({
      items: [{ template_id: 't2', due_at: '2099-10-15T17:00:00+05:30' }], allow_past: false,
    })
  })

  it('a row typed back to its stored value is not sent', async () => {
    const calls = server('DEAN', { ...base, 'PUT /semesters/s-new/deadlines': () => jsonResponse(200, []) })
    const u = userEvent.setup()
    open('/setup/semesters/s-new/deadlines')
    const first = await screen.findByLabelText('Deadline for D01')
    await u.clear(first)
    await u.type(first, '2099-09-30T17:00') // same as stored (India time)
    expect(screen.getByRole('button', { name: 'Save 0 changes' })).toBeDisabled()
    await u.type(screen.getByLabelText('Deadline for D02'), '2099-10-15T17:00')
    await u.click(screen.getByRole('button', { name: 'Save 1 change' }))
    await waitFor(() => expect(sent(calls, 'PUT', '/semesters/s-new/deadlines')).toHaveLength(1))
    expect(bodyOf(sent(calls, 'PUT', '/semesters/s-new/deadlines')[0]).items).toHaveLength(1)
  })

  it('a deadline in the past needs a tick before it can be saved', async () => {
    const calls = server('DEAN', { ...base, 'PUT /semesters/s-new/deadlines': () => jsonResponse(200, []) })
    const u = userEvent.setup()
    open('/setup/semesters/s-new/deadlines')
    await screen.findByLabelText('Deadline for D01')
    await u.type(screen.getByLabelText('Deadline for D02'), '2020-01-01T10:00')
    const save = screen.getByRole('button', { name: 'Save 1 change' })
    expect(save).toBeDisabled()
    expect(screen.getByText(/flagged MISSING at once/)).toBeInTheDocument()
    await u.click(screen.getByRole('checkbox'))
    expect(save).toBeEnabled()
    await u.click(save)
    await waitFor(() => expect(sent(calls, 'PUT', '/semesters/s-new/deadlines')).toHaveLength(1))
    expect(bodyOf(sent(calls, 'PUT', '/semesters/s-new/deadlines')[0]).allow_past).toBe(true)
  })

  it('shows the server refusal', async () => {
    server('DEAN', { ...base, 'PUT /semesters/s-new/deadlines': () => jsonResponse(422, { detail: 'A deadline is in the past.' }) })
    const u = userEvent.setup()
    open('/setup/semesters/s-new/deadlines')
    await u.type(await screen.findByLabelText('Deadline for D02'), '2099-10-15T17:00')
    await u.click(screen.getByRole('button', { name: 'Save 1 change' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('A deadline is in the past.')
  })
})

describe('subjects and checklist', () => {
  it('creates a subject in the chosen department', async () => {
    const calls = server('DEAN', { 'GET /subjects': [], 'GET /departments': DEPTS, 'POST /subjects': () => jsonResponse(201, {}) })
    const u = userEvent.setup()
    open('/setup/subjects')
    await screen.findByText(/No subjects yet/)
    await u.type(screen.getByLabelText(/Code/), 'IT101')
    await u.type(screen.getByLabelText('Name'), 'Data Structures')
    await u.selectOptions(screen.getByLabelText('Department'), 'd-cs')
    await u.selectOptions(screen.getByLabelText('Type'), 'LAB')
    await u.click(screen.getByRole('button', { name: 'Add subject' }))
    await waitFor(() => expect(sent(calls, 'POST', '/subjects')).toHaveLength(1))
    expect(bodyOf(sent(calls, 'POST', '/subjects')[0])).toEqual({ code: 'IT101', name: 'Data Structures', department_id: 'd-cs', subject_type: 'LAB' })
  })

  it('switches a subject off', async () => {
    const subject = { id: 'sub1', code: 'IT101', name: 'DS', department_id: 'd-it', subject_type: 'THEORY', is_active: true }
    const calls = server('DEAN', { 'GET /subjects': [subject], 'GET /departments': DEPTS, 'PATCH /subjects/sub1': () => jsonResponse(200, subject) })
    const u = userEvent.setup()
    open('/setup/subjects')
    await u.click(await screen.findByRole('button', { name: 'Switch off' }))
    await waitFor(() => expect(sent(calls, 'PATCH', '/subjects/sub1')).toHaveLength(1))
    expect(bodyOf(sent(calls, 'PATCH', '/subjects/sub1')[0])).toEqual({ is_active: false })
  })

  it('creates a checklist item and refuses to save without a file type', async () => {
    const calls = server('DEAN', { 'GET /checklist-templates': [], 'POST /checklist-templates': () => jsonResponse(201, { submission_rows_added: 3 }) })
    const u = userEvent.setup()
    open('/setup/checklist')
    await screen.findByText(/No checklist items yet/)
    await u.click(screen.getByRole('button', { name: 'Add item' }))
    const dialog = within(screen.getByRole('dialog'))
    await u.type(dialog.getByLabelText(/Code/), 'D01')
    await u.type(dialog.getByLabelText('Title'), 'Syllabus')
    await u.click(dialog.getByLabelText('pdf')) // untick the default
    expect(dialog.getByRole('button', { name: 'Save' })).toBeDisabled()
    await u.click(dialog.getByLabelText('docx'))
    await u.click(dialog.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(sent(calls, 'POST', '/checklist-templates')).toHaveLength(1))
    expect(bodyOf(sent(calls, 'POST', '/checklist-templates')[0])).toMatchObject({ code: 'D01', title: 'Syllabus', allowed_extensions: ['docx'], max_size_mb: 10, applies_to: 'BOTH' })
    expect(await screen.findByText(/added to 3 existing course files/)).toBeInTheDocument()
  })
})

describe('users', () => {
  const people = [
    user('dean1', 'Me Myself', 'DEAN', null),
    user('hod1', 'Dr Joshi', 'HOD', 'd-it'),
    user('fac1', 'Asha Shah', 'FACULTY', 'd-it'),
  ]

  it('shows the temporary password once, then it is gone', async () => {
    const calls = server('DEAN', {
      'GET /users': people, 'GET /departments': DEPTS,
      'POST /users': () => jsonResponse(201, { ...user('new1', 'Ravi', 'FACULTY', 'd-cs'), temporary_password: 'Abc123Xyz789Qw' }),
    })
    const u = userEvent.setup()
    open('/setup/users')
    await screen.findByText('Asha Shah')
    await u.type(screen.getByLabelText('Email'), ' Ravi@X.in ')
    await u.type(screen.getByLabelText('Full name'), 'Ravi')
    await u.selectOptions(screen.getByLabelText('Department'), 'd-cs')
    await u.click(screen.getByRole('button', { name: 'Create user' }))
    expect(await screen.findByText('Abc123Xyz789Qw')).toBeInTheDocument()
    expect(bodyOf(sent(calls, 'POST', '/users')[0])).toEqual({ email: 'Ravi@X.in', full_name: 'Ravi', role: 'FACULTY', department_id: 'd-cs', employee_code: null })
    await u.click(screen.getByRole('button', { name: 'I have noted it' }))
    expect(screen.queryByText('Abc123Xyz789Qw')).not.toBeInTheDocument()
  })

  it('closing the password box with Escape also removes it', async () => {
    server('DEAN', { 'GET /users': people, 'GET /departments': DEPTS, 'POST /users/fac1/reset-password': () => jsonResponse(200, { user_id: 'fac1', temporary_password: 'EscapeMe12345' }) })
    const u = userEvent.setup()
    open('/setup/users')
    await screen.findByText('Asha Shah')
    const row = screen.getByText('Asha Shah').closest('tr') as HTMLElement
    await u.click(within(row).getByRole('button', { name: 'Reset password' }))
    await screen.findByText('EscapeMe12345')
    await u.keyboard('{Escape}')
    expect(screen.queryByText('EscapeMe12345')).not.toBeInTheDocument()
  })

  it('shows the server message for a duplicate email', async () => {
    server('DEAN', { 'GET /users': people, 'GET /departments': DEPTS, 'POST /users': () => jsonResponse(409, { detail: 'A user with this email already exists.' }) })
    const u = userEvent.setup()
    open('/setup/users')
    await screen.findByText('Asha Shah')
    await u.type(screen.getByLabelText('Email'), 'a@b.in')
    await u.type(screen.getByLabelText('Full name'), 'A B')
    await u.selectOptions(screen.getByLabelText('Department'), 'd-it')
    await u.click(screen.getByRole('button', { name: 'Create user' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('A user with this email already exists.')
  })

  it('never offers actions on the Dean row or on yourself, and reset shows a new password', async () => {
    server('DEAN', { 'GET /users': people, 'GET /departments': DEPTS, 'POST /users/fac1/reset-password': () => jsonResponse(200, { user_id: 'fac1', temporary_password: 'NewPassw0rdXyz' }) })
    const u = userEvent.setup()
    open('/setup/users')
    await screen.findByText('Asha Shah')
    expect(screen.getAllByRole('button', { name: 'Reset password' })).toHaveLength(2) // HOD and faculty, not the Dean
    const row = screen.getByText('Asha Shah').closest('tr') as HTMLElement
    await u.click(within(row).getByRole('button', { name: 'Reset password' }))
    expect(await screen.findByText('NewPassw0rdXyz')).toBeInTheDocument()
  })

  it('a HOD creates faculty in their own department without choosing role or department', async () => {
    const calls = server('HOD', {
      'GET /users': [user('hod-me', 'Me Myself', 'HOD', 'd-it'), user('fac1', 'Asha Shah', 'FACULTY', 'd-it')], 'GET /departments': [DEPTS[0]],
      'POST /users': () => jsonResponse(201, { ...user('new1', 'Ravi', 'FACULTY', 'd-it'), temporary_password: 'Pw12345678abcd' }),
    })
    const u = userEvent.setup()
    open('/setup/users')
    await screen.findByText('Asha Shah')
    await u.type(screen.getByLabelText('Email'), 'ravi@x.in')
    await u.type(screen.getByLabelText('Full name'), 'Ravi')
    await u.click(screen.getByRole('button', { name: 'Create user' }))
    await screen.findByText('Pw12345678abcd')
    expect(bodyOf(sent(calls, 'POST', '/users')[0])).toMatchObject({ role: 'FACULTY', department_id: 'd-it' })
    expect(screen.getAllByRole('button', { name: 'Reset password' })).toHaveLength(1) // only the faculty row
  })
})

describe('course files', () => {
  const server1 = () => server('DEAN', {
    'GET /semesters': SEMS, 'GET /course-files': [],
    'GET /subjects': [
      { id: 'sub-it', code: 'IT101', name: 'DS', department_id: 'd-it', subject_type: 'THEORY', is_active: true },
      { id: 'sub-cs', code: 'CS101', name: 'OS', department_id: 'd-cs', subject_type: 'THEORY', is_active: false },
    ],
    'GET /users': [user('f-it', 'Asha IT', 'FACULTY', 'd-it'), user('f-cs', 'Nisha CS', 'FACULTY', 'd-cs')],
    'POST /course-files/bulk': () => jsonResponse(201, { created: 1 }),
  })

  it('offers only faculty of the subject department and creates in one request for the current semester', async () => {
    const calls = server1()
    const u = userEvent.setup()
    open('/setup/course-files')
    await screen.findByText(/No course files in this semester yet/)
    await u.selectOptions(screen.getByLabelText('Subject'), 'sub-it')
    const options = within(screen.getByLabelText(/Faculty/)).getAllByRole('option').map((o) => o.textContent)
    expect(options).toEqual(['Choose...', 'Asha IT'])
    await u.selectOptions(screen.getByLabelText(/Faculty/), 'f-it')
    await u.click(screen.getByRole('button', { name: 'Add to list' }))
    await u.click(screen.getByRole('button', { name: 'Create 1 course file' }))
    await waitFor(() => expect(sent(calls, 'POST', '/course-files/bulk')).toHaveLength(1))
    expect(bodyOf(sent(calls, 'POST', '/course-files/bulk')[0])).toEqual({ items: [{ subject_id: 'sub-it', faculty_id: 'f-it', division: null, semester_id: 's-cur' }] })
    expect(await screen.findByText(/Created 1 course file/)).toBeInTheDocument()
  })

  it('does not stage the same course file twice', async () => {
    server1()
    const u = userEvent.setup()
    open('/setup/course-files')
    await screen.findByText(/No course files in this semester yet/)
    for (let i = 0; i < 2; i++) {
      await u.selectOptions(screen.getByLabelText('Subject'), 'sub-it')
      await u.selectOptions(screen.getByLabelText(/Faculty/), 'f-it')
      await u.click(screen.getByRole('button', { name: 'Add to list' }))
    }
    expect(await screen.findByRole('alert')).toHaveTextContent(/already has a course file/)
    expect(screen.getByRole('button', { name: 'Create 1 course file' })).toBeInTheDocument()
  })
})

describe('score weights', () => {
  const W = (id: number, c: number, t: number, f: number, k: number, reason: string | null) => ({ id, completeness: c, timeliness: t, format: f, content: k, reason, set_by_name: null, created_at: '2026-07-01T00:00:00Z' })
  const routes = {
    'GET /score-weights': { latest: W(1, 35, 35, 20, 10, 'Start'), current_semester: { semester_id: 's-cur', weights: W(1, 35, 35, 20, 10, 'Start') }, content_scoring_enabled: false, effective_for_current_semester: { completeness: 38.89, timeliness: 38.89, format: 22.22, content: 0 } },
    'GET /score-weights/history': { weights: [W(1, 35, 35, 20, 10, 'Start')], semester_assignments: [] },
    'POST /score-weights': () => jsonResponse(201, { message: 'Saved. The current semester keeps its weights.', latest: W(2, 40, 30, 20, 10, 'x'), current_semester: null, content_scoring_enabled: false, applied_to_current_semester: false }),
  }

  it('blocks a total that is not 100 and shows the running total', async () => {
    server('DEAN', routes)
    const u = userEvent.setup()
    open('/setup/weights')
    const completeness = await screen.findByLabelText('Completeness', { selector: 'input' })
    await u.clear(completeness)
    await u.type(completeness, '50')
    expect(screen.getByText('Total: 115 of 100')).toHaveClass('sum-bad')
    await u.type(screen.getByLabelText(/Reason/), 'Audit feedback from IQAC')
    expect(screen.getByRole('button', { name: 'Save weights' })).toBeDisabled()
  })

  it('needs a change and a reason, then sends the new weights', async () => {
    const calls = server('DEAN', routes)
    const u = userEvent.setup()
    open('/setup/weights')
    const completeness = await screen.findByLabelText('Completeness', { selector: 'input' })
    const save = screen.getByRole('button', { name: 'Save weights' })
    expect(save).toBeDisabled() // nothing changed
    await u.type(screen.getByLabelText(/Reason/), 'Audit feedback from IQAC')
    expect(save).toBeDisabled() // a reason alone is not a change
    await u.clear(completeness)
    await u.type(completeness, '40')
    await u.clear(screen.getByLabelText('Timeliness', { selector: 'input' }))
    await u.type(screen.getByLabelText('Timeliness', { selector: 'input' }), '30')
    expect(save).toBeEnabled()
    await u.clear(screen.getByLabelText(/Reason/))
    await u.type(screen.getByLabelText(/Reason/), 'too short') // 9 characters
    expect(save).toBeDisabled()
    await u.clear(screen.getByLabelText(/Reason/))
    await u.type(screen.getByLabelText(/Reason/), 'Audit feedback from IQAC')
    await u.click(save)
    await waitFor(() => expect(sent(calls, 'POST', '/score-weights')).toHaveLength(1))
    expect(bodyOf(sent(calls, 'POST', '/score-weights')[0])).toEqual({ completeness: 40, timeliness: 30, format: 20, content: 10, reason: 'Audit feedback from IQAC', apply_now: false })
    expect(await screen.findByText(/current semester keeps its weights/)).toBeInTheDocument()
  })

  it('says when content weight is shared', async () => {
    server('DEAN', routes)
    open('/setup/weights')
    expect(await screen.findByText(/Content checks are not live yet/)).toBeInTheDocument()
    expect(screen.getAllByText(/counts as 38.89/)).toHaveLength(2) // Completeness and Timeliness
    expect(screen.getByText(/counts as 22.22/)).toBeInTheDocument()
  })
})
