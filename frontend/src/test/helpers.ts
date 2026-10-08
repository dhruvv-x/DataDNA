import { vi } from 'vitest'

export function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(body === null ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  })
}

export interface Call {
  url: string
  init: RequestInit
}

/** Replace fetch with a function you control. Returns the list of calls made. */
export function mockFetch(handler: (url: string, init: RequestInit, calls: Call[]) => Response | Promise<Response>): Call[] {
  const calls: Call[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input)
    calls.push({ url, init })
    return handler(url, init, calls)
  }))
  return calls
}

export function authHeader(init: RequestInit): string | undefined {
  return (init.headers as Record<string, string> | undefined)?.['Authorization']
}
