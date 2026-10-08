import { useState } from 'react'
import { ApiError } from '../api/client'

/** Runs one button action: blocks double clicks, keeps the server's message when it fails. */
export function useAction() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function run<T>(fn: () => Promise<T>): Promise<T | undefined> {
    if (busy) return undefined
    setBusy(true)
    setError(null)
    try {
      return await fn()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong. Try again.')
      return undefined
    } finally {
      setBusy(false)
    }
  }
  return { busy, error, setError, run }
}
