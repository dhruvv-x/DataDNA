import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import * as api from '../api/client'
import type { Session } from '../api/types'
import { AuthContext } from './context'
import type { AuthApi, AuthState } from './context'

const ANON: AuthState = { status: 'anon', user: null, mustChange: false }

function authed(s: Session): AuthState {
  return { status: 'authed', user: s.user, mustChange: s.must_change_password }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: 'loading', user: null, mustChange: false })

  useEffect(() => {
    let alive = true
    api.onSessionLost(() => setState(ANON))
    // After a page reload the token is gone, the cookie is not. One shared refresh call (see client.ts).
    api.refreshSession().then(
      (s) => alive && setState(s ? authed(s) : ANON),
      () => alive && setState(ANON),
    )
    return () => {
      alive = false
      api.onSessionLost(null)
    }
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    setState(authed(await api.login(email, password)))
  }, [])

  const logout = useCallback(async () => {
    try {
      await api.logout()
    } catch {
      /* the cookie may already be gone; we leave anyway */
    }
    setState(ANON)
  }, [])

  const changePassword = useCallback(async (current: string, next: string) => {
    setState(authed(await api.changePassword(current, next)))
  }, [])

  const value = useMemo<AuthApi>(() => ({ ...state, login, logout, changePassword }), [state, login, logout, changePassword])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
