import { createContext, useContext } from 'react'
import type { User } from '../api/types'

export interface AuthState {
  status: 'loading' | 'anon' | 'authed'
  user: User | null
  mustChange: boolean
}

export interface AuthApi extends AuthState {
  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
  changePassword: (current: string, next: string) => Promise<void>
}

export const AuthContext = createContext<AuthApi | null>(null)

export function useAuth(): AuthApi {
  const ctx = useContext(AuthContext)
  if (ctx === null) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
