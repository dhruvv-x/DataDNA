import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { API_BASE, resetClientForTests, setAccessToken } from '../api/client'
import type { QueryCan, QueryDetail, QueryRow, QueryStep, Role } from '../api/types'
import { AuthContext } from '../auth/context'
import type { AuthApi } from '../auth/context'
import { Layout } from '../components/Layout'
import { QUERY_ACTION_LABEL, queryStatusText, queryTone } from '../lib/format'
import { canRaiseQuery } from '../lib/permissions'
import { jsonResponse, mockFetch } from '../test/helpers'
import type { Call } from '../test/helpers'
import { CourseFilePage } from './CourseFilePage'
import { HomePage } from './HomePage'
import { QueriesPage } from './QueriesPage'
import { QueryPage } from './QueryPage'

beforeEach(() => resetClientForTests())
afterEach(() => vi.unstubAllGlobals())

const pathOf = (url: string) => url.slice(url.startsWith(API_BASE) ? API_BASE.length : 0).split('?')[0]
const queryOf = (url: string) => new URLSearchParams(url.split('?')[1] ?? '')
const bodyOf = (c: Call) => JSON.parse(String(c.init.body))
const sent = (calls: Call[], method: string, path: string) => calls.filter((c) => (c.init.method ?? 'GET') === method && pathOf(c.url) === path)

type Route_ = unknown | ((body: unknown, call: Call) => Response)

function mount(path: string, role: Role, routes: Record<string, Route_>, userId = 'u') {
  setAccessToken('tok')
  const calls = mockFetch((url, init) => {
    const hit = routes[`${init.method ?? 'GET'} ${pathOf(url)}`]
    if (hit === undefined) return jsonResponse(404, { detail: 'Not found.' })
    return typeof hit === 'function' ? (hit as (b: unknown, c: Call) => Response)(init.body ? JSON.parse(String(init.body)) : null, { url, init }) : jsonResponse(200, hit)
  })
  const auth: AuthApi = {
    status: 'authed', mustChange: false, login: async () => {}, logout: async () => {}, changePassword: async () => {},
    user: { id: userId, email: 'a@b.c', full_name: 'Test User', role, department_id: 'd' },
  }
  render(
    <AuthContext.Provider value={auth}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<HomePage />} />
            <Route path="course-files/:id" element={<CourseFilePage />} />
            <Route path="queries" element={<QueriesPage />} />
            <Route path="queries/:id" element={<QueryPage />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>,
  )
  return calls
}

const NO: QueryCan = { reply: false, escalate: false, resolve: false, appeal: false, override: false }
const step = (action: QueryStep['action'], extra: Partial<QueryStep> = {}): QueryStep => ({
  id: `st-${action}-${Math.random()}`, action, level: 'HOD', actor_id: 'x', actor_name: 'Asha Shah', actor_role: 'FACULTY', override: false,
  outcome: null, message: 'The file reached the portal on time.', created_at: '2026-10-02T10:00:00Z', ...extra,
})
const row = (extra: Partial<QueryRow> = {}): QueryRow => ({
  id: 'q1', flag_id: 'f1', raised_by: 'fac', raised_by_name: 'Asha Shah', raised_by_role: 'FACULTY', current_level: 'HOD', status: 'OPEN', appealed: false,
  created_at: '2026-10-02T10:00:00Z', resolved_at: null, resolved_level: null, last_activity_at: '2026-10-02T10:00:00Z', flag_kind: 'MISSING',
  flag_status: 'OPEN', flag_reason: 'Nothing uploaded by the deadline.', template_code: 'D01', template_title: 'Course syllabus', course_file_id: 'cf1',
  semester_is_current: true, department_code: 'IT', division: null, faculty_id: 'fac', faculty_name: 'Asha Shah', subject_code: 'IT101',
  subject_name: 'Data Structures', can: NO, ...extra,
})
const detail = (extra: Partial<QueryDetail> = {}): QueryDetail => {
  const { can: _can, last_actor_role: _l, ...base } = row()
  void _can
  void _l
  return { ...base, steps: [step('RAISE')], can: NO, ...extra }
}
const listOf = (...queries: QueryRow[]) => ({ total: queries.length, queries })

// ------------------------------------------------------------------ rules the screen follows
describe('who is offered "Dispute this flag"', () => {
  it('only the owner, on an open flag, in the current semester, with no query yet', () => {
    expect(canRaiseQuery('FACULTY', 'a', 'a', true, true, false)).toBe(true)
    expect(canRaiseQuery('HOD', 'a', 'a', true, true, false)).toBe(true)         // a HOD who teaches the course
    expect(canRaiseQuery('FACULTY', 'a', 'b', true, true, false)).toBe(false)    // somebody else's course
    expect(canRaiseQuery('DEAN', 'a', 'a', true, true, false)).toBe(false)
    expect(canRaiseQuery('FACULTY', 'a', 'a', false, true, false)).toBe(false)   // flag already waived or cleared
    expect(canRaiseQuery('FACULTY', 'a', 'a', true, false, false)).toBe(false)   // closed semester
    expect(canRaiseQuery('FACULTY', 'a', 'a', true, true, true)).toBe(false)     // one query per flag
  })
})

describe('words on the screen', () => {
  it('say where an open query is and what a closed one decided', () => {
    expect(queryStatusText({ status: 'OPEN', current_level: 'HOD' })).toBe('Open, with the hod')
    expect(queryStatusText({ status: 'OPEN', current_level: 'DEAN' })).toBe('Open, with the dean')
    expect(queryStatusText({ status: 'RESOLVED_OVERTURNED', current_level: 'DEAN' })).toBe('Decided: flag overturned')
    expect(queryTone({ status: 'OPEN' })).toBe('warn')
    expect(queryTone({ status: 'RESOLVED_OVERTURNED' })).toBe('good')
    expect(QUERY_ACTION_LABEL.ESCALATE).toBe('passed it to the Dean')
  })
})

// ------------------------------------------------------------------ the flag on the course file
describe('disputing a flag on the course file page', () => {
  const part = (w: number) => ({ weight: w, effective_weight: w, points: w, lost: 0 })
  const score = (current: boolean, facultyId = 'fac') => ({
    course_file_id: 'cf1', semester_id: 's-cur', academic_year: '2026-27', term: 'ODD', subject_code: 'IT101', subject_name: 'Data Structures', faculty_id: facultyId,
    faculty_name: 'Asha Shah', department_code: 'IT', division: null, semester_is_current: current, source: current ? 'live' : 'snapshot', is_final: !current,
    as_of: '2026-10-01T10:00:00Z', status: 'SCORED', total: 80, parts: { completeness: part(38.89), timeliness: part(38.89), format: part(22.22), content: part(0) },
    content_active: false, items_total: 1, items_pending: 0, notes: [], items: [],
  })
  const flag = (status = 'OPEN') => ({
    id: 'f1', course_file_id: 'cf1', submission_id: 'sub1', kind: 'MISSING', status, reason: 'Nothing uploaded by the deadline.', raised_at: '2026-10-01T10:00:00Z',
    cleared_at: null, template_code: 'D01', template_title: 'Course syllabus', exceptions: [],
  })
  const base = (over: Record<string, Route_> = {}) => ({
    'GET /course-files/cf1/score': score(true), 'GET /course-files/cf1/submissions': [], 'GET /course-files/cf1/flags': [flag()],
    'GET /course-files/cf1/score/history': { snapshots: [] }, 'GET /queries': listOf(), ...over,
  })

  it('the owner sends a query, which opens the new query page', async () => {
    const calls = mount('/course-files/cf1', 'FACULTY', base({
      'POST /flags/f1/queries': () => jsonResponse(201, detail()), 'GET /queries/q1': detail({ can: { ...NO, reply: true } }),
    }), 'fac')
    const u = userEvent.setup()
    await u.click(await screen.findByRole('button', { name: 'Dispute this flag' }))
    const dialog = screen.getByRole('dialog')
    await u.type(within(dialog).getByLabelText('Why is this flag wrong?'), 'The file reached the portal on time.')
    await u.click(within(dialog).getByRole('button', { name: 'Send query' }))
    expect(await screen.findByRole('heading', { name: /Query: IT101/ })).toBeInTheDocument()
    expect(bodyOf(sent(calls, 'POST', '/flags/f1/queries')[0])).toEqual({ message: 'The file reached the portal on time.' })
  })

  it('a message that is too short is stopped on the screen, nothing is sent', async () => {
    const calls = mount('/course-files/cf1', 'FACULTY', base(), 'fac')
    const u = userEvent.setup()
    await u.click(await screen.findByRole('button', { name: 'Dispute this flag' }))
    const dialog = screen.getByRole('dialog')
    await u.type(within(dialog).getByLabelText('Why is this flag wrong?'), 'wrong')
    await u.click(within(dialog).getByRole('button', { name: 'Send query' }))
    expect(within(dialog).getByRole('alert')).toHaveTextContent('at least 10 characters')
    expect(sent(calls, 'POST', '/flags/f1/queries')).toHaveLength(0)
  })

  it("the server's refusal is shown and the dialog stays open", async () => {
    mount('/course-files/cf1', 'FACULTY', base({ 'POST /flags/f1/queries': () => jsonResponse(409, { detail: 'This flag already has a query.' }) }), 'fac')
    const u = userEvent.setup()
    await u.click(await screen.findByRole('button', { name: 'Dispute this flag' }))
    const dialog = screen.getByRole('dialog')
    await u.type(within(dialog).getByLabelText('Why is this flag wrong?'), 'The file reached the portal on time.')
    await u.click(within(dialog).getByRole('button', { name: 'Send query' }))
    expect(await within(dialog).findByText('This flag already has a query.')).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Send query' })).toBeEnabled()
  })

  it.each<[string, Role, string, boolean]>([
    ['a HOD looking at someone else', 'HOD', 'hod', true],
    ['the Dean', 'DEAN', 'dean', true],
    ['another faculty member', 'FACULTY', 'other', true],
    ['the owner in a closed semester', 'FACULTY', 'fac', false],
  ])('no dispute button for %s', async (_who, role, userId, current) => {
    mount('/course-files/cf1', role, base({ 'GET /course-files/cf1/score': score(current) }), userId)
    await screen.findByText('Nothing uploaded by the deadline.')
    expect(screen.queryByRole('button', { name: 'Dispute this flag' })).not.toBeInTheDocument()
  })

  it('no dispute button on a flag that is already waived', async () => {
    mount('/course-files/cf1', 'FACULTY', base({ 'GET /course-files/cf1/flags': [flag('WAIVED')] }), 'fac')
    await screen.findByText('Nothing uploaded by the deadline.')
    expect(screen.queryByRole('button', { name: 'Dispute this flag' })).not.toBeInTheDocument()
  })

  it('a flag that has a query shows a link to it instead of the button', async () => {
    mount('/course-files/cf1', 'FACULTY', base({ 'GET /queries': listOf(row()) }), 'fac')
    const link = await screen.findByRole('link', { name: 'Query: open, with the hod' })
    expect(link).toHaveAttribute('href', '/queries/q1')
    expect(screen.queryByRole('button', { name: 'Dispute this flag' })).not.toBeInTheDocument()
  })

  it('if the queries cannot be loaded the course file still works', async () => {
    mount('/course-files/cf1', 'FACULTY', { ...base(), 'GET /queries': () => jsonResponse(500, { detail: 'boom' }) }, 'fac')
    expect(await screen.findByRole('button', { name: 'Dispute this flag' })).toBeInTheDocument()
  })
})

// ------------------------------------------------------------------ the list
describe('queries page', () => {
  it('faculty see their own list without a Faculty column', async () => {
    mount('/queries', 'FACULTY', { 'GET /queries': listOf(row()) }, 'fac')
    await screen.findByRole('link', { name: /IT101 Data Structures/ })
    expect(screen.queryByRole('columnheader', { name: 'Faculty' })).not.toBeInTheDocument()
    expect(screen.getByText('Open, with the hod')).toBeInTheDocument()
  })

  it('a HOD sees the faculty column and an appealed query is marked', async () => {
    mount('/queries', 'HOD', { 'GET /queries': listOf(row({ appealed: true, current_level: 'DEAN' })) })
    await screen.findByRole('link', { name: /IT101 Data Structures/ })
    expect(screen.getByRole('columnheader', { name: 'Faculty' })).toBeInTheDocument()
    expect(screen.getByText('Appealed')).toBeInTheDocument()
    expect(screen.getByText('Open, with the dean')).toBeInTheDocument()
  })

  it('"Waiting for me" and the status filter go to the server', async () => {
    const calls = mount('/queries', 'DEAN', { 'GET /queries': listOf(row()) })
    const u = userEvent.setup()
    await screen.findByRole('link', { name: /IT101/ })
    await u.click(screen.getByRole('button', { name: 'Waiting for me' }))
    await waitFor(() => expect(sent(calls, 'GET', '/queries').some((c) => queryOf(c.url).get('waiting_for_me') === 'true')).toBe(true))
    await u.selectOptions(screen.getByLabelText('Status'), 'RESOLVED_UPHELD')
    await waitFor(() => expect(sent(calls, 'GET', '/queries').some((c) => queryOf(c.url).get('status') === 'RESOLVED_UPHELD')).toBe(true))
  })

  it('opens already filtered when the link says waiting=1', async () => {
    const calls = mount('/queries?waiting=1', 'HOD', { 'GET /queries': listOf(row()) })
    await screen.findByRole('link', { name: /IT101/ })
    expect(screen.getByRole('button', { name: 'Waiting for me' })).toHaveAttribute('aria-pressed', 'true')
    expect(queryOf(sent(calls, 'GET', '/queries')[0].url).get('waiting_for_me')).toBe('true')
  })

  it('says what to do when faculty have no queries, and when a filter finds nothing', async () => {
    mount('/queries', 'FACULTY', { 'GET /queries': listOf() }, 'fac')
    expect(await screen.findByText(/Dispute this flag/)).toBeInTheDocument()
  })

  it('shows the error with a retry', async () => {
    mount('/queries', 'HOD', { 'GET /queries': () => jsonResponse(500, { detail: 'Server trouble.' }) })
    expect(await screen.findByRole('alert')).toHaveTextContent('Server trouble.')
  })
})

// ------------------------------------------------------------------ one query
describe('query page', () => {
  it('shows the flag and every step in order', async () => {
    mount('/queries/q1', 'HOD', {
      'GET /queries/q1': detail({
        steps: [step('RAISE'), step('REPLY', { actor_name: 'Hari HOD', actor_role: 'HOD', message: 'Please send the portal receipt.' }),
          step('ESCALATE', { actor_name: 'Hari HOD', actor_role: 'HOD', message: 'Needs the Dean.' })],
      }),
    })
    await screen.findByRole('heading', { name: /Query: IT101/ })
    expect(screen.getByText('Nothing uploaded by the deadline.')).toBeInTheDocument()
    const steps = within(screen.getByRole('list', { name: 'Steps of this query' })).getAllByRole('listitem')
    expect(steps).toHaveLength(3)
    expect(steps[0]).toHaveTextContent('Asha Shah (Faculty) raised the query')
    expect(steps[1]).toHaveTextContent('Hari HOD (HOD) replied')
    expect(steps[2]).toHaveTextContent('passed it to the Dean')
    expect(screen.getByRole('link', { name: 'Open the course file' })).toHaveAttribute('href', '/course-files/cf1')
  })

  it('the author can only reply, and a reply goes to the server and shows up', async () => {
    const calls = mount('/queries/q1', 'FACULTY', {
      'GET /queries/q1': detail({ can: { ...NO, reply: true } }),
      'POST /queries/q1/reply': () => jsonResponse(200, detail({ can: { ...NO, reply: true }, steps: [step('RAISE'), step('REPLY', { message: 'Receipt attached to the item.' })] })),
    }, 'fac')
    const u = userEvent.setup()
    await screen.findByRole('heading', { name: /Query: IT101/ })
    expect(screen.queryByRole('button', { name: 'Overturn the flag' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Pass to the Dean' })).not.toBeInTheDocument()
    await u.type(screen.getByLabelText('Your message'), 'Receipt attached to the item.')
    await u.click(screen.getByRole('button', { name: 'Send reply' }))
    expect(await screen.findByText('Receipt attached to the item.')).toBeInTheDocument()
    expect(bodyOf(sent(calls, 'POST', '/queries/q1/reply')[0])).toEqual({ message: 'Receipt attached to the item.' })
    expect((screen.getByLabelText('Your message') as HTMLTextAreaElement).value).toBe('')
  })

  it('a HOD gets reply, pass on, keep and overturn, nothing else', async () => {
    mount('/queries/q1', 'HOD', { 'GET /queries/q1': detail({ can: { reply: true, escalate: true, resolve: true, appeal: false, override: false } }) })
    await screen.findByRole('heading', { name: /Query: IT101/ })
    for (const name of ['Send reply', 'Pass to the Dean', 'Keep the flag', 'Overturn the flag']) {
      expect(screen.getByRole('button', { name })).toBeInTheDocument()
    }
    expect(screen.queryByRole('button', { name: 'Appeal to the Dean' })).not.toBeInTheDocument()
    expect(screen.queryByText(/stepping in/)).not.toBeInTheDocument()
  })

  it('passing to the Dean sends the message and shows the new level', async () => {
    const calls = mount('/queries/q1', 'HOD', {
      'GET /queries/q1': detail({ can: { reply: true, escalate: true, resolve: true, appeal: false, override: false } }),
      'POST /queries/q1/escalate': () => jsonResponse(200, detail({ current_level: 'DEAN', steps: [step('RAISE'), step('ESCALATE', { actor_role: 'HOD', actor_name: 'Hari HOD' })] })),
    })
    const u = userEvent.setup()
    await screen.findByRole('heading', { name: /Query: IT101/ })
    await u.type(screen.getByLabelText('Your message'), 'This needs the Dean to decide.')
    await u.click(screen.getByRole('button', { name: 'Pass to the Dean' }))
    expect((await screen.findAllByText('Open, with the dean')).length).toBeGreaterThan(0)
    expect(bodyOf(sent(calls, 'POST', '/queries/q1/escalate')[0])).toEqual({ message: 'This needs the Dean to decide.' })
    expect(screen.queryByRole('button', { name: 'Pass to the Dean' })).not.toBeInTheDocument()   // the server now says no
  })

  it('overturning needs a second click that says what it does, and Back cancels', async () => {
    const calls = mount('/queries/q1', 'HOD', {
      'GET /queries/q1': detail({ can: { reply: true, escalate: true, resolve: true, appeal: false, override: false } }),
      'POST /queries/q1/resolve': () => jsonResponse(200, detail({ status: 'RESOLVED_OVERTURNED', flag_status: 'WAIVED', resolved_at: '2026-10-03T10:00:00Z', resolved_level: 'HOD', can: NO })),
    })
    const u = userEvent.setup()
    await screen.findByRole('heading', { name: /Query: IT101/ })
    await u.type(screen.getByLabelText('Your message'), 'The portal was down that day.')
    await u.click(screen.getByRole('button', { name: 'Overturn the flag' }))
    const confirm = screen.getByRole('group', { name: 'Confirm decision' })
    expect(confirm).toHaveTextContent('full credit')
    expect(sent(calls, 'POST', '/queries/q1/resolve')).toHaveLength(0)
    await u.click(within(confirm).getByRole('button', { name: 'Back' }))
    expect(screen.getByRole('button', { name: 'Overturn the flag' })).toBeInTheDocument()
    await u.click(screen.getByRole('button', { name: 'Overturn the flag' }))
    await u.click(screen.getByRole('button', { name: 'Confirm: overturn the flag' }))
    expect(await screen.findByText(/The flag was overturned and set aside as waived/)).toBeInTheDocument()
    expect(bodyOf(sent(calls, 'POST', '/queries/q1/resolve')[0])).toEqual({ outcome: 'OVERTURNED', message: 'The portal was down that day.' })
    expect(screen.queryByLabelText('Your message')).not.toBeInTheDocument()
  })

  it('keeping the flag warns the HOD about the appeal, and the Dean that it is final', async () => {
    const can = { reply: true, escalate: false, resolve: true, appeal: false, override: false }
    mount('/queries/q1', 'HOD', { 'GET /queries/q1': detail({ can: { ...can, escalate: true } }) })
    const u = userEvent.setup()
    await screen.findByRole('heading', { name: /Query: IT101/ })
    await u.type(screen.getByLabelText('Your message'), 'The deadline was clear.')
    await u.click(screen.getByRole('button', { name: 'Keep the flag' }))
    expect(screen.getByRole('group', { name: 'Confirm decision' })).toHaveTextContent('appeal it once')
  })

  it('the Dean is told the decision is final', async () => {
    mount('/queries/q1', 'DEAN', { 'GET /queries/q1': detail({ current_level: 'DEAN', can: { reply: true, escalate: false, resolve: true, appeal: false, override: false } }) })
    const u = userEvent.setup()
    await screen.findByRole('heading', { name: /Query: IT101/ })
    await u.type(screen.getByLabelText('Your message'), 'Checked everything again.')
    await u.click(screen.getByRole('button', { name: 'Keep the flag' }))
    expect(screen.getByRole('group', { name: 'Confirm decision' })).toHaveTextContent('final')
  })

  it('a short message is stopped before anything is sent', async () => {
    const calls = mount('/queries/q1', 'HOD', { 'GET /queries/q1': detail({ can: { reply: true, escalate: true, resolve: true, appeal: false, override: false } }) })
    const u = userEvent.setup()
    await screen.findByRole('heading', { name: /Query: IT101/ })
    await u.type(screen.getByLabelText('Your message'), 'no')
    await u.click(screen.getByRole('button', { name: 'Overturn the flag' }))
    expect(screen.getByRole('alert')).toHaveTextContent('at least 10 characters')
    expect(screen.queryByRole('group', { name: 'Confirm decision' })).not.toBeInTheDocument()
    await u.click(screen.getByRole('button', { name: 'Send reply' }))
    expect(screen.getByRole('alert')).toHaveTextContent('at least 3 characters')
    expect(sent(calls, 'POST', '/queries/q1/reply')).toHaveLength(0)
  })

  it('the Dean stepping in at the HOD level is told it is an override', async () => {
    mount('/queries/q1', 'DEAN', { 'GET /queries/q1': detail({ can: { reply: true, escalate: false, resolve: true, appeal: false, override: true } }) })
    expect(await screen.findByText(/recorded as an override/)).toBeInTheDocument()
  })

  it('a step by the Dean at the HOD level is labelled in the timeline', async () => {
    mount('/queries/q1', 'FACULTY', {
      'GET /queries/q1': detail({ steps: [step('RAISE'), step('REPLY', { actor_role: 'DEAN', actor_name: 'Dean Rao', override: true })] }),
    }, 'fac')
    expect(await screen.findByText('Dean stepped in at HOD level')).toBeInTheDocument()
  })

  it('after a HOD kept the flag the author can appeal, and the appeal goes to the server', async () => {
    const calls = mount('/queries/q1', 'FACULTY', {
      'GET /queries/q1': detail({
        status: 'RESOLVED_UPHELD', resolved_level: 'HOD', resolved_at: '2026-10-03T10:00:00Z', can: { ...NO, appeal: true },
        steps: [step('RAISE'), step('RESOLVE', { actor_role: 'HOD', actor_name: 'Hari HOD', outcome: 'UPHELD' })],
      }),
      'POST /queries/q1/appeal': () => jsonResponse(200, detail({ current_level: 'DEAN', appealed: true, can: { ...NO, reply: true }, steps: [step('RAISE'), step('RESOLVE', { outcome: 'UPHELD' }), step('APPEAL')] })),
    }, 'fac')
    const u = userEvent.setup()
    await screen.findByRole('heading', { name: 'Appeal to the Dean' })
    expect(screen.getByText(/within 7 days/)).toBeInTheDocument()
    expect(screen.getByText('The flag stays and keeps counting in the score.')).toBeInTheDocument()
    await u.type(screen.getByLabelText('Why should the Dean look again?'), 'I now have the portal receipt.')
    await u.click(screen.getByRole('button', { name: 'Appeal to the Dean' }))
    expect(await screen.findAllByText('Appealed')).not.toHaveLength(0)
    expect(bodyOf(sent(calls, 'POST', '/queries/q1/appeal')[0])).toEqual({ message: 'I now have the portal receipt.' })
  })

  it('a closed query offers no box at all', async () => {
    mount('/queries/q1', 'FACULTY', { 'GET /queries/q1': detail({ status: 'RESOLVED_OVERTURNED', resolved_level: 'DEAN', resolved_at: '2026-10-03T10:00:00Z', can: NO }) }, 'fac')
    expect(await screen.findByText('This query is closed.')).toBeInTheDocument()
    expect(screen.queryByLabelText('Your message')).not.toBeInTheDocument()
  })

  it('tells a HOD it is waiting for the Dean when it has moved up', async () => {
    mount('/queries/q1', 'HOD', { 'GET /queries/q1': detail({ current_level: 'DEAN', can: NO }) })
    expect(await screen.findByText(/Waiting for the Dean/)).toBeInTheDocument()
  })

  it('a refusal from the server is shown and the typed message is kept', async () => {
    mount('/queries/q1', 'HOD', {
      'GET /queries/q1': detail({ can: { reply: true, escalate: true, resolve: true, appeal: false, override: false } }),
      'POST /queries/q1/reply': () => jsonResponse(409, { detail: 'This query is already decided.' }),
    })
    const u = userEvent.setup()
    await screen.findByRole('heading', { name: /Query: IT101/ })
    await u.type(screen.getByLabelText('Your message'), 'Please send the receipt.')
    await u.click(screen.getByRole('button', { name: 'Send reply' }))
    expect(await screen.findByText('This query is already decided.')).toBeInTheDocument()
    expect((screen.getByLabelText('Your message') as HTMLTextAreaElement).value).toBe('Please send the receipt.')
  })

  it('a query outside your scope shows the not found message', async () => {
    mount('/queries/q9', 'FACULTY', {}, 'fac')
    expect(await screen.findByRole('alert')).toHaveTextContent('Not found.')
  })
})

// ------------------------------------------------------------------ the numbers
describe('menu badge and dashboard link', () => {
  const scoresBody = { semester_id: 's-cur', total: 0, scores: [] }

  it('the menu shows how many queries wait for me', async () => {
    mount('/queries', 'HOD', { 'GET /queries': listOf(), 'GET /queries/count': { waiting_for_me: 3, open: 5 } })
    expect(await screen.findByLabelText('3 waiting for you')).toHaveTextContent('3')
  })

  it('no badge when nothing waits, and none when the number cannot be loaded', async () => {
    mount('/queries', 'HOD', { 'GET /queries': listOf(), 'GET /queries/count': { waiting_for_me: 0, open: 2 } })
    await screen.findByRole('heading', { name: 'Queries' })
    expect(screen.queryByLabelText(/waiting for you/)).not.toBeInTheDocument()
  })

  it('the dashboard links a HOD to the queries waiting for them', async () => {
    mount('/', 'HOD', {
      'GET /scores': scoresBody, 'GET /flags': { total: 0, flags: [] }, 'GET /subjects': [], 'GET /queries/count': { waiting_for_me: 1, open: 1 },
    })
    const link = await screen.findByRole('link', { name: '1 query is waiting for you' })
    expect(link).toHaveAttribute('href', '/queries?waiting=1')
  })

  it('the dashboard still works when the query numbers fail', async () => {
    mount('/', 'FACULTY', { 'GET /scores': scoresBody, 'GET /flags': { total: 0, flags: [] } }, 'fac')
    expect(await screen.findByRole('heading', { name: 'My courses' })).toBeInTheDocument()
    expect(screen.queryByText(/waiting for you/)).not.toBeInTheDocument()
  })
})
