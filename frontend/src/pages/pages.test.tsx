import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { resetClientForTests, setAccessToken } from '../api/client'
import type { Role } from '../api/types'
import App from '../App'
import { AuthContext } from '../auth/context'
import type { AuthApi } from '../auth/context'
import { jsonResponse, mockFetch } from '../test/helpers'
import { CourseFilePage } from './CourseFilePage'

beforeEach(() => {
  resetClientForTests()
  setAccessToken('tok')
})
afterEach(() => vi.unstubAllGlobals())

const noop = async () => {}
function asRole(role: Role): AuthApi {
  return {
    status: 'authed', mustChange: false, login: noop, logout: noop, changePassword: noop,
    user: { id: 'u', email: 'a@b.c', full_name: 'Test User', role, department_id: 'd' },
  }
}

function scoreBody(current: boolean) {
  const zero = { completeness: 0, timeliness: 0, format: 0, content: 0 }
  const part = (w: number, pts: number) => ({ weight: w, effective_weight: w, points: pts, lost: w - pts })
  return {
    course_file_id: 'cf1', semester_id: 's1', academic_year: '2026-27', term: 'ODD', subject_code: 'CS101',
    subject_name: 'Data Structures', faculty_id: 'f', faculty_name: 'Asha Shah', department_code: 'IT', division: null,
    semester_is_current: current, source: current ? 'live' : 'snapshot', is_final: !current, as_of: '2026-10-01T10:00:00Z',
    status: 'SCORED', total: 80.56,
    parts: { completeness: part(38.89, 38.89), timeliness: part(38.89, 19.45), format: part(22.22, 22.22), content: { weight: 10, effective_weight: 0, points: 0, lost: 0 } },
    content_active: false, items_total: 2, items_pending: 1, notes: ['Content checks are not live yet.'],
    items: [
      { submission_id: 'sub1', code: 'D01', title: 'Syllabus', state: 'LATE', due_at: '2026-09-30T11:30:00Z', lost: { ...zero, timeliness: 19.44 }, reasons: ['Late. Lateness never clears.'], flags: [] },
      { submission_id: 'sub2', code: 'D02', title: 'Time table', state: 'PENDING', due_at: null, lost: zero, reasons: ['Not due yet.'], flags: [] },
    ],
  }
}

function checklistRow(id: string, code: string, title: string, withFile: boolean) {
  return {
    submission_id: id, code, title, template_active: true, allowed_extensions: ['pdf'], max_size_mb: 5, due_at: '2026-09-30T11:30:00Z',
    extended_to: null, effective_due_at: '2026-09-30T11:30:00Z', current_version_id: withFile ? 'v1' : null, version_no: withFile ? 1 : null,
    validation_status: withFile ? 'OK' : null, uploaded_at: withFile ? '2026-10-01T10:00:00Z' : null, uploaded_by_name: 'Asha',
    uploaded_by_role: 'FACULTY', original_filename: withFile ? 'syllabus.pdf' : null, version_count: withFile ? 1 : 0, open_flags: [],
  }
}

function courseFileServer(current: boolean) {
  mockFetch((url) => {
    if (url.endsWith('/score')) return jsonResponse(200, scoreBody(current))
    if (url.endsWith('/submissions')) return jsonResponse(200, [checklistRow('sub1', 'D01', 'Syllabus', true), checklistRow('sub2', 'D02', 'Time table', false)])
    if (url.endsWith('/flags')) return jsonResponse(200, [])
    if (url.endsWith('/score/history')) return jsonResponse(200, { snapshots: [] })
    return jsonResponse(404, { detail: 'Not found.' })
  })
}

function renderCourseFile(role: Role) {
  return render(
    <AuthContext.Provider value={asRole(role)}>
      <MemoryRouter initialEntries={['/course-files/cf1']}>
        <Routes><Route path="/course-files/:id" element={<CourseFilePage />} /></Routes>
      </MemoryRouter>
    </AuthContext.Provider>,
  )
}

describe('CourseFilePage', () => {
  it('shows the score, the parts, the reasons and the checklist', async () => {
    courseFileServer(true)
    renderCourseFile('FACULTY')
    expect(await screen.findByText(/CS101 - Data Structures/)).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Score 80.56 out of 100' })).toBeInTheDocument()
    expect(screen.getByText('Late. Lateness never clears.')).toBeInTheDocument()
    expect(screen.getByText('Content checks are not live yet.')).toBeInTheDocument()
    expect(screen.getByText('Off (not scored yet)')).toBeInTheDocument()
    expect(await screen.findByText('syllabus.pdf')).toBeInTheDocument()
  })

  it('faculty in the current semester can upload and replace', async () => {
    courseFileServer(true)
    renderCourseFile('FACULTY')
    expect(await screen.findByRole('button', { name: 'Replace' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Upload' })).toBeInTheDocument()
  })

  it('HOD sees no upload button', async () => {
    courseFileServer(true)
    renderCourseFile('HOD')
    await screen.findByText('syllabus.pdf')
    expect(screen.queryByRole('button', { name: 'Upload' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Replace' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Download' })).toBeInTheDocument()
  })

  it('faculty cannot upload to a closed semester, the Dean can', async () => {
    courseFileServer(false)
    const first = renderCourseFile('FACULTY')
    await screen.findByText('syllabus.pdf')
    expect(screen.queryByRole('button', { name: 'Upload' })).not.toBeInTheDocument()
    expect(screen.getByText('Closed, score of record')).toBeInTheDocument()
    first.unmount()
    renderCourseFile('DEAN')
    expect(await screen.findByRole('button', { name: 'Upload' })).toBeInTheDocument()
  })

  it('the Dean must write a reason, faculty are not asked for one', async () => {
    courseFileServer(true)
    const user = userEvent.setup()
    const dean = renderCourseFile('DEAN')
    await user.click(await screen.findByRole('button', { name: 'Upload' }))
    expect(screen.getByText(/Reason for uploading on behalf/)).toBeInTheDocument()
    dean.unmount()
    renderCourseFile('FACULTY')
    await user.click(await screen.findByRole('button', { name: 'Upload' }))
    expect(screen.queryByText(/Reason for uploading on behalf/)).not.toBeInTheDocument()
  })

  it('shows the server message when the course file is out of scope', async () => {
    mockFetch(() => jsonResponse(404, { detail: 'Not found.' }))
    renderCourseFile('FACULTY')
    expect(await screen.findByRole('alert')).toHaveTextContent('Not found.')
  })
})

describe('upload dialog', () => {
  function uploadServer(post: () => Response) {
    return mockFetch((url, init) => {
      if (url.endsWith('/submissions/sub2/versions') && init.method === 'POST') return post()
      if (url.endsWith('/score')) return jsonResponse(200, scoreBody(true))
      if (url.endsWith('/submissions')) return jsonResponse(200, [checklistRow('sub1', 'D01', 'Syllabus', true), checklistRow('sub2', 'D02', 'Time table', false)])
      if (url.endsWith('/flags')) return jsonResponse(200, [])
      if (url.endsWith('/score/history')) return jsonResponse(200, { snapshots: [] })
      return jsonResponse(404, { detail: 'Not found.' })
    })
  }
  const sendButton = () => within(screen.getByRole('dialog')).getByRole('button', { name: 'Upload' })
  const uploads = (calls: { url: string; init: RequestInit }[]) => calls.filter((c) => c.init.method === 'POST')
  const pdf = () => new File(['%PDF-1.4'], 'plan.pdf', { type: 'application/pdf' })

  it('the Dean cannot send without a reason of 10 characters', async () => {
    const calls = uploadServer(() => jsonResponse(201, { message: 'Saved.', validation_status: 'OK', late: false }))
    const user = userEvent.setup()
    renderCourseFile('DEAN')
    await user.click(await screen.findByRole('button', { name: 'Upload' }))
    await user.upload(screen.getByLabelText('File'), pdf())
    await user.type(screen.getByLabelText(/Reason for uploading/), 'too short')
    await user.click(sendButton())
    expect(await screen.findByText(/at least 10 characters/)).toBeInTheDocument()
    expect(uploads(calls)).toHaveLength(0)
  })

  it('the Dean sends file and reason together', async () => {
    const calls = uploadServer(() => jsonResponse(201, { message: 'Saved. The file passed the format checks.', validation_status: 'OK', late: false }))
    const user = userEvent.setup()
    renderCourseFile('DEAN')
    await user.click(await screen.findByRole('button', { name: 'Upload' }))
    await user.upload(screen.getByLabelText('File'), pdf())
    await user.type(screen.getByLabelText(/Reason for uploading/), 'faculty is on leave this week')
    await user.click(sendButton())
    expect(await screen.findByText(/passed the format checks/)).toBeInTheDocument()
    const form = uploads(calls)[0].init.body as FormData
    expect((form.get('file') as File).name).toBe('plan.pdf')
    expect(form.get('reason')).toBe('faculty is on leave this week')
  })

  it('a file of the wrong type is stopped before it is sent', async () => {
    const calls = uploadServer(() => jsonResponse(201, {}))
    const user = userEvent.setup({ applyAccept: false })
    renderCourseFile('FACULTY')
    await user.click(await screen.findByRole('button', { name: 'Upload' }))
    await user.upload(screen.getByLabelText('File'), new File(['x'], 'run.exe'))
    await user.click(sendButton())
    expect(await screen.findByText(/accepts only: pdf/)).toBeInTheDocument()
    expect(uploads(calls)).toHaveLength(0)
  })

  it('a server refusal is shown, and faculty are not asked for a reason', async () => {
    const calls = uploadServer(() => jsonResponse(409, { detail: 'This exact file is already the current version.' }))
    const user = userEvent.setup()
    renderCourseFile('FACULTY')
    await user.click(await screen.findByRole('button', { name: 'Upload' }))
    await user.upload(screen.getByLabelText('File'), pdf())
    await user.click(sendButton())
    expect(await screen.findByText('This exact file is already the current version.')).toBeInTheDocument()
    expect((uploads(calls)[0].init.body as FormData).has('reason')).toBe(false)
  })

  it('a file that arrives with a format problem is shown as a warning', async () => {
    uploadServer(() => jsonResponse(201, { message: 'Saved, but the file has a problem: PDF is damaged.', validation_status: 'FORMAT_FAILED', late: false }))
    const user = userEvent.setup()
    renderCourseFile('FACULTY')
    await user.click(await screen.findByRole('button', { name: 'Upload' }))
    await user.upload(screen.getByLabelText('File'), pdf())
    await user.click(sendButton())
    const note = await screen.findByText(/PDF is damaged/)
    expect(note).toHaveClass('alert-warn')
  })
})

describe('login flow through the whole app', () => {
  function appServer(loginStatus: number) {
    return mockFetch((url) => {
      if (url.endsWith('/auth/refresh')) return jsonResponse(401, { detail: 'Session expired. Please log in again.' })
      if (url.endsWith('/auth/login')) {
        return loginStatus === 200
          ? jsonResponse(200, { access_token: 'tok', must_change_password: false, user: { id: 'u', email: 'a@b.c', full_name: 'Asha Shah', role: 'FACULTY', department_id: 'd' } })
          : jsonResponse(401, { detail: 'Invalid email or password.' })
      }
      if (url.includes('/scores')) return jsonResponse(200, { semester_id: 's1', total: 0, scores: [] })
      if (url.includes('/flags')) return jsonResponse(200, { total: 0, flags: [] })
      return jsonResponse(404, { detail: 'Not found.' })
    })
  }

  it('a visitor without a session lands on the login page and a good login opens the dashboard', async () => {
    appServer(200)
    const user = userEvent.setup()
    render(<MemoryRouter initialEntries={['/']}><App /></MemoryRouter>)
    await user.type(await screen.findByLabelText('Email'), 'a@b.c')
    await user.type(screen.getByLabelText('Password'), 'long-enough-pass')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('heading', { name: 'My courses' })).toBeInTheDocument()
    expect(screen.getByText('Asha Shah')).toBeInTheDocument()
  })

  it('a wrong password shows the message and stays on the login page', async () => {
    appServer(401)
    const user = userEvent.setup()
    render(<MemoryRouter initialEntries={['/']}><App /></MemoryRouter>)
    await user.type(await screen.findByLabelText('Email'), 'a@b.c')
    await user.type(screen.getByLabelText('Password'), 'wrong')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Invalid email or password.'))
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument()
  })
})
