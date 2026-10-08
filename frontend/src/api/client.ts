/**
 * The only place that talks to the backend.
 *
 * - The access token lives in memory only (never localStorage). After a page reload the login cookie
 *   (HttpOnly, set by the backend) is swapped for a new token through /auth/refresh.
 * - The backend rotates the refresh cookie on every refresh and logs the user out everywhere if an
 *   old one comes back. So only ONE refresh may run at a time: every request that gets a 401 waits
 *   for the same shared promise (refreshSession).
 */
import type { Session } from './types'

export const API_BASE: string = (import.meta.env.VITE_API_BASE || '/api').replace(/\/+$/, '')

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

let accessToken: string | null = null
let refreshPromise: Promise<Session | null> | null = null
let sessionLostHandler: (() => void) | null = null

export function getAccessToken(): string | null {
  return accessToken
}

export function setAccessToken(token: string | null): void {
  accessToken = token
}

/** The app registers one function here; it is called when the session cannot be renewed. */
export function onSessionLost(handler: (() => void) | null): void {
  sessionLostHandler = handler
}

/** Test helper: forget everything. */
export function resetClientForTests(): void {
  accessToken = null
  refreshPromise = null
  sessionLostHandler = null
}

/** FastAPI sends "detail" as text, or as a list of {msg, loc} for validation errors. */
export function errorMessage(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail) && detail.length > 0) {
    const parts = detail.map((d) => {
      const msg = typeof d?.msg === 'string' ? d.msg.replace(/^Value error, /, '') : 'invalid value'
      const loc = Array.isArray(d?.loc) ? d.loc.filter((x: unknown) => x !== 'body' && x !== 'query').join('.') : ''
      return loc ? `${loc}: ${msg}` : msg
    })
    return parts.join('; ')
  }
  if (status === 403) return 'You are not allowed to do this.'
  if (status === 404) return 'Not found.'
  if (status >= 500) return 'The server had a problem. Please try again, and tell the administrator if it continues.'
  return `Request failed (${status}).`
}

async function readBody(res: Response): Promise<unknown> {
  const text = await res.text()
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return null
  }
}

function networkError(): ApiError {
  return new ApiError(0, 'Cannot reach the server. Check your connection and try again.')
}

async function doRefresh(): Promise<Session | null> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}/auth/refresh`, { method: 'POST', credentials: 'include' })
  } catch {
    throw networkError()
  }
  if (res.status === 401) return null
  if (!res.ok) throw new ApiError(res.status, errorMessage(await readBody(res), res.status))
  const session = (await res.json()) as Session
  accessToken = session.access_token
  return session
}

/** Swap the cookie for a new access token. Calls made while one is running share its result. */
export function refreshSession(): Promise<Session | null> {
  if (refreshPromise === null) {
    refreshPromise = doRefresh().finally(() => {
      refreshPromise = null
    })
  }
  return refreshPromise
}

interface Options {
  method?: string
  json?: unknown
  form?: FormData
  urlEncoded?: Record<string, string>
  /** Do not try to renew the session on 401 (used by login). */
  noRefresh?: boolean
  signal?: AbortSignal
}

async function send(path: string, opts: Options, token: string | null): Promise<Response> {
  const headers: Record<string, string> = {}
  let body: BodyInit | undefined
  if (opts.json !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(opts.json)
  } else if (opts.urlEncoded) {
    headers['Content-Type'] = 'application/x-www-form-urlencoded'
    body = new URLSearchParams(opts.urlEncoded).toString()
  } else if (opts.form) {
    body = opts.form // the browser sets the multipart boundary itself
  }
  if (token) headers['Authorization'] = `Bearer ${token}`
  try {
    return await fetch(`${API_BASE}${path}`, {
      method: opts.method ?? 'GET',
      headers,
      body,
      credentials: 'include',
      signal: opts.signal,
    })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    throw networkError()
  }
}

async function requestRaw(path: string, opts: Options = {}): Promise<Response> {
  const usedToken = accessToken
  let res = await send(path, opts, usedToken)
  if (res.status === 401 && !opts.noRefresh) {
    // Another request may already have renewed the token while this one was in flight.
    let token = accessToken !== usedToken ? accessToken : null
    if (token === null) {
      const session = await refreshSession()
      if (session === null) {
        accessToken = null
        sessionLostHandler?.()
        throw new ApiError(401, 'Session expired. Please log in again.')
      }
      token = session.access_token
    }
    res = await send(path, opts, token)
    if (res.status === 401) {
      accessToken = null
      sessionLostHandler?.()
      throw new ApiError(401, 'Session expired. Please log in again.')
    }
  }
  if (!res.ok) throw new ApiError(res.status, errorMessage(await readBody(res), res.status))
  return res
}

export async function request<T>(path: string, opts: Options = {}): Promise<T> {
  const res = await requestRaw(path, opts)
  return (await readBody(res)) as T
}

export function filenameFromDisposition(header: string | null, fallback: string): string {
  if (!header) return fallback
  const star = /filename\*=UTF-8''([^;]+)/i.exec(header)
  if (star) {
    try {
      return decodeURIComponent(star[1])
    } catch {
      /* fall through */
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(header)
  return plain ? plain[1] : fallback
}

/** Download a protected file (needs the token, so a plain link cannot be used). */
export async function downloadFile(path: string, fallbackName: string): Promise<string> {
  const res = await requestRaw(path)
  const name = filenameFromDisposition(res.headers.get('Content-Disposition'), fallbackName)
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
  return res.headers.get('X-File-SHA256') ?? ''
}

// ------------------------------------------------------------------ session calls
export async function login(email: string, password: string): Promise<Session> {
  const session = await request<Session>('/auth/login', {
    method: 'POST',
    urlEncoded: { username: email.trim(), password },
    noRefresh: true,
  })
  accessToken = session.access_token
  return session
}

export async function logout(): Promise<void> {
  try {
    await request('/auth/logout', { method: 'POST', noRefresh: true })
  } finally {
    accessToken = null
  }
}

export async function changePassword(current_password: string, new_password: string): Promise<Session> {
  const session = await request<Session>('/auth/change-password', {
    method: 'POST',
    json: { current_password, new_password },
  })
  accessToken = session.access_token
  return session
}
