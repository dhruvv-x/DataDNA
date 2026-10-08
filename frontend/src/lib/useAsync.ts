import { useEffect, useState } from 'react'
import { ApiError } from '../api/client'

interface Result<T> {
  key: string
  id: string
  data?: T
  error?: string
}

/**
 * Loads data when `key` changes (put every input of the call into the key) and again on reload().
 * While reloading, the old data stays on screen. Data from a different key is never shown.
 */
export function useAsync<T>(load: () => Promise<T>, key: string) {
  const [tick, setTick] = useState(0)
  const [result, setResult] = useState<Result<T> | null>(null)
  const id = `${key}#${tick}`

  useEffect(() => {
    let alive = true
    load().then(
      (data) => alive && setResult({ key, id, data }),
      (err) => alive && setResult({ key, id, error: err instanceof ApiError ? err.message : 'Something went wrong.' }),
    )
    return () => {
      alive = false
    }
    // `load` is rebuilt on every render; `id` already holds everything it depends on.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  const sameKey = result !== null && result.key === key
  return {
    data: sameKey ? result.data : undefined,
    error: sameKey && result.id === id ? result.error : undefined,
    loading: result === null || result.id !== id,
    reload: () => setTick((t) => t + 1),
  }
}
