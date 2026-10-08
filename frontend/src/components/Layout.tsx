import { Link, Outlet } from 'react-router-dom'
import { useAuth } from '../auth/context'
import { ROLE_LABEL } from '../lib/format'

export function Layout() {
  const { user, logout } = useAuth()
  return (
    <>
      <header className="topbar">
        <Link to="/" className="brand">Faculty Compliance &amp; Trust Engine</Link>
        <nav className="topnav" aria-label="Main">
          <Link to="/">Dashboard</Link>
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
