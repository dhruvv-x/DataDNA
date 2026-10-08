import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { authHeader, jsonResponse, mockFetch } from '../test/helpers'
import {
  ApiError, errorMessage, filenameFromDisposition, getAccessToken, login, onSessionLost, request,
  resetClientForTests, setAccessToken,
} from './client'

const SESSION = { access_token: 'new', must_change_password: false, user: { id: 'u1' } }

beforeEach(() => resetClientForTests())
afterEach(() => vi.unstubAllGlobals())

/** A server where only the token "new" is accepted, and refresh hands out "new". */
function server() {
  return mockFetch(async (url, init) => {
    if (url.endsWith('/auth/refresh')) {
      await new Promise((r) => setTimeout(r, 10)) // slow enough for requests to overlap
      return jsonResponse(200, SESSION)
    }
    return authHeader(init) === 'Bearer new' ? jsonResponse(200, { ok: true }) : jsonResponse(401, { detail: 'Not authenticated.' })
  })
}

describe('one refresh at a time', () => {
  it('three parallel 401s cause exactly one refresh, and all three are retried with the new token', async () => {
    setAccessToken('old')
    const calls = server()
    const results = await Promise.all([request('/a'), request('/b'), request('/c')])
    expect(results).toEqual([{ ok: true }, { ok: true }, { ok: true }])
    expect(calls.filter((c) => c.url.endsWith('/auth/refresh'))).toHaveLength(1)
    expect(getAccessToken()).toBe('new')
    const retried = calls.filter((c) => !c.url.endsWith('/auth/refresh') && authHeader(c.init) === 'Bearer new')
    expect(retried).toHaveLength(3)
  })

  it('does not refresh again when another request already renewed the token', async () => {
    setAccessToken('old')
    let release!: () => void
    const gate = new Promise<void>((r) => (release = r))
    const calls = mockFetch(async (url, init) => {
      if (url.endsWith('/auth/refresh')) return jsonResponse(200, SESSION)
      if (authHeader(init) === 'Bearer old') {
        await gate
        return jsonResponse(401, { detail: 'x' })
      }
      return jsonResponse(200, { ok: true })
    })
    const pending = request('/slow')
    setAccessToken('new') // someone else refreshed while this call was in flight
    release()
    await expect(pending).resolves.toEqual({ ok: true })
    expect(calls.filter((c) => c.url.endsWith('/auth/refresh'))).toHaveLength(0)
  })

  it('a later 401 starts a new refresh (the shared promise is cleared)', async () => {
    setAccessToken('old')
    const calls = server()
    await request('/a')
    setAccessToken('old')
    await request('/b')
    expect(calls.filter((c) => c.url.endsWith('/auth/refresh'))).toHaveLength(2)
  })
})

describe('session loss', () => {
  it('a failed refresh tells the app, clears the token, and does not retry', async () => {
    setAccessToken('old')
    const lost = vi.fn()
    onSessionLost(lost)
    const calls = mockFetch((url) =>
      url.endsWith('/auth/refresh') ? jsonResponse(401, { detail: 'Session expired.' }) : jsonResponse(401, { detail: 'no' }))
    await expect(request('/a')).rejects.toMatchObject({ status: 401 })
    expect(lost).toHaveBeenCalledTimes(1)
    expect(getAccessToken()).toBeNull()
    expect(calls).toHaveLength(2) // the call and one refresh, no loop
  })

  it('a 401 that repeats after a good refresh gives up instead of looping', async () => {
    setAccessToken('old')
    const lost = vi.fn()
    onSessionLost(lost)
    const calls = mockFetch((url) => (url.endsWith('/auth/refresh') ? jsonResponse(200, SESSION) : jsonResponse(401, { detail: 'no' })))
    await expect(request('/a')).rejects.toBeInstanceOf(ApiError)
    expect(lost).toHaveBeenCalledTimes(1)
    expect(calls).toHaveLength(3) // call, refresh, one retry
  })
})

describe('login', () => {
  it('sends the email as "username" in a form body and keeps the token in memory', async () => {
    const calls = mockFetch(() => jsonResponse(200, SESSION))
    await login('  Dean@Uni.edu ', 'secret-pass')
    const { init, url } = calls[0]
    expect(url).toBe('/api/auth/login')
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/x-www-form-urlencoded')
    expect(String(init.body)).toBe('username=Dean%40Uni.edu&password=secret-pass')
    expect(init.credentials).toBe('include')
    expect(getAccessToken()).toBe('new')
  })

  it('a wrong password shows the server message and never triggers a refresh', async () => {
    const calls = mockFetch(() => jsonResponse(401, { detail: 'Invalid email or password.' }))
    await expect(login('a@b.c', 'x')).rejects.toThrow('Invalid email or password.')
    expect(calls).toHaveLength(1)
    expect(getAccessToken()).toBeNull()
  })
})

describe('requests', () => {
  it('attaches the bearer token and sends cookies', async () => {
    setAccessToken('tok')
    const calls = mockFetch(() => jsonResponse(200, {}))
    await request('/scores')
    expect(authHeader(calls[0].init)).toBe('Bearer tok')
    expect(calls[0].init.credentials).toBe('include')
    expect(calls[0].url).toBe('/api/scores')
  })

  it('does not set a Content-Type for file uploads (the browser adds the boundary)', async () => {
    setAccessToken('tok')
    const calls = mockFetch(() => jsonResponse(201, {}))
    const form = new FormData()
    form.append('file', new File(['x'], 'a.csv'))
    await request('/submissions/1/versions', { method: 'POST', form })
    expect((calls[0].init.headers as Record<string, string>)['Content-Type']).toBeUndefined()
    expect(calls[0].init.body).toBe(form)
  })

  it('a network failure becomes a readable error with status 0', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch') }))
    await expect(request('/x')).rejects.toMatchObject({ status: 0, message: expect.stringContaining('Cannot reach the server') })
  })

  it('server errors keep the server text', async () => {
    setAccessToken('tok')
    mockFetch(() => jsonResponse(409, { detail: 'This semester is closed. Only the Dean can upload to it.' }))
    await expect(request('/x')).rejects.toMatchObject({ status: 409, message: 'This semester is closed. Only the Dean can upload to it.' })
  })
})

describe('errorMessage', () => {
  it('formats FastAPI validation lists', () => {
    const body = { detail: [{ loc: ['body', 'reason'], msg: 'Value error, a reason of at least 10 characters is required' }] }
    expect(errorMessage(body, 422)).toBe('reason: a reason of at least 10 characters is required')
  })
  it('has plain fallbacks', () => {
    expect(errorMessage(null, 403)).toBe('You are not allowed to do this.')
    expect(errorMessage(null, 404)).toBe('Not found.')
    expect(errorMessage(null, 500)).toContain('server had a problem')
  })
})

describe('filenameFromDisposition', () => {
  it('reads plain, quoted and UTF-8 names, and falls back', () => {
    expect(filenameFromDisposition('attachment; filename="plan.pdf"', 'x')).toBe('plan.pdf')
    expect(filenameFromDisposition("attachment; filename*=UTF-8''my%20plan.pdf", 'x')).toBe('my plan.pdf')
    expect(filenameFromDisposition(null, 'fallback.bin')).toBe('fallback.bin')
  })
})
