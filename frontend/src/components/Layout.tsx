import { Link, Outlet, useLocation } from 'react-router-dom'
import { getQueryCount } from '../api/endpoints'
import { useAuth } from '../auth/context'
import { ROLE_LABEL } from '../lib/format'
import { canOpenFlagsPage, canOpenSetup } from '../lib/permissions'
import { useAsync } from '../lib/useAsync'

export function Layout() {
  const { user, logout } = useAuth()
  const { pathname } = useLocation()
  // A small number for the menu. Reloaded when the person moves to another page. If it fails, no badge, nothing else breaks.
  const queries = useAsync(() => getQueryCount(), `qcount:${user?.id ?? ''}:${pathname}`)
  const waiting = queries.data?.waiting_for_me ?? 0
  return (
    <>
      <header className="topbar">
        <Link to="/" className="brand">Faculty Compliance &amp; Trust Engine</Link>
        <nav className="topnav" aria-label="Main">
          <Link to="/">Dashboard</Link>
          {user && canOpenFlagsPage(user.role) && <Link to="/flags">Flags</Link>}
          <Link to="/queries">Queries{waiting > 0 && <> <span className="badge badge-warn" aria-label={`${waiting} waiting for you`}>{waiting}</span></>}</Link>
          {user && canOpenSetup(user.role) && <Link to="/setup">{user.role === 'DEAN' ? 'Setup' : 'People'}</Link>}
        </nav>
        <div className="who">
          <span>{user?.full_name} <span className="badge badge-info">{user ? ROLE_LABEL[user.role] : ''}</span></span>
          <Link to="/change-password" className="linklike">Change password</Link>
          <button className="btn btn-small" onClick={() => void logout()}>Log out</button>
        </div>
      </header>
      <main className="page"><Outlet /></main>
    </>
  )
}
