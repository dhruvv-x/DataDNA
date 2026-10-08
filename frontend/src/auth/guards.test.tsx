import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { AuthContext } from './context'
import type { AuthApi } from './context'
import { RequireAuth } from './guards'

const USER = { id: 'u', email: 'a@b.c', full_name: 'Asha', role: 'FACULTY' as const, department_id: 'd' }
const noop = async () => {}

function renderAt(path: string, auth: Partial<AuthApi>) {
  const value: AuthApi = { status: 'authed', user: USER, mustChange: false, login: noop, logout: noop, changePassword: noop, ...auth }
  return render(
    <AuthContext.Provider value={value}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/login" element={<div>LOGIN PAGE</div>} />
          <Route element={<RequireAuth />}>
            <Route path="/" element={<div>HOME PAGE</div>} />
            <Route path="/change-password" element={<div>CHANGE PAGE</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>,
  )
}

describe('RequireAuth', () => {
  it('logged in: shows the page', () => {
    renderAt('/', {})
    expect(screen.getByText('HOME PAGE')).toBeInTheDocument()
  })
  it('not logged in: goes to login', () => {
    renderAt('/', { status: 'anon', user: null })
    expect(screen.getByText('LOGIN PAGE')).toBeInTheDocument()
    expect(screen.queryByText('HOME PAGE')).not.toBeInTheDocument()
  })
  it('still checking: shows a loading note, not the page and not the login', () => {
    renderAt('/', { status: 'loading', user: null })
    expect(screen.getByRole('status')).toHaveTextContent('Loading')
    expect(screen.queryByText('HOME PAGE')).not.toBeInTheDocument()
    expect(screen.queryByText('LOGIN PAGE')).not.toBeInTheDocument()
  })
  it('temporary password: every page except change-password is blocked', () => {
    renderAt('/', { mustChange: true })
    expect(screen.getByText('CHANGE PAGE')).toBeInTheDocument()
    expect(screen.queryByText('HOME PAGE')).not.toBeInTheDocument()
  })
  it('temporary password: change-password itself opens', () => {
    renderAt('/change-password', { mustChange: true })
    expect(screen.getByText('CHANGE PAGE')).toBeInTheDocument()
  })
})
