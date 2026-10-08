import { NavLink, Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../../auth/context'
import type { SetupTab } from '../../lib/permissions'
import { setupTabs } from '../../lib/permissions'

const LABEL: Record<SetupTab, string> = {
  departments: 'Departments',
  semesters: 'Semesters',
  subjects: 'Subjects',
  checklist: 'Checklist items',
  users: 'Users',
  'course-files': 'Course files',
  weights: 'Score weights',
}

/** Frame of every setup page. A role only reaches the tabs it is offered; anything else goes to its first tab or home. */
export function SetupLayout() {
  const { user } = useAuth()
  const location = useLocation()
  const tabs = user ? setupTabs(user.role) : []
  if (!user || tabs.length === 0) return <Navigate to="/" replace />
  const current = location.pathname.split('/')[2] as SetupTab | undefined
  if (!current || !tabs.includes(current)) return <Navigate to={`/setup/${tabs[0]}`} replace />

  return (
    <>
      <h1>{user.role === 'DEAN' ? 'Setup' : 'People'}</h1>
      <nav className="tabs" aria-label="Setup">
        {tabs.map((t) => <NavLink key={t} to={`/setup/${t}`}>{LABEL[t]}</NavLink>)}
      </nav>
      <Outlet />
    </>
  )
}
