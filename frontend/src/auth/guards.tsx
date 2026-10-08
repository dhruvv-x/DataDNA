import { Navigate, Outlet, useLocation } from 'react-router-dom'
import type { Role } from '../api/types'
import { useAuth } from './context'

/** Everything inside needs a login. A user with a temporary password can only reach /change-password. */
export function RequireAuth() {
  const auth = useAuth()
  const location = useLocation()

  if (auth.status === 'loading') return <div className="splash" role="status">Loading...</div>
  if (auth.status === 'anon') return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  if (auth.mustChange && location.pathname !== '/change-password') return <Navigate to="/change-password" replace />
  return <Outlet />
}

/** Inside RequireAuth. A role that is not listed is sent home. The server refuses it anyway; this only avoids an empty page. */
export function RequireRole({ roles }: { roles: Role[] }) {
  const { user } = useAuth()
  if (!user || !roles.includes(user.role)) return <Navigate to="/" replace />
  return <Outlet />
}
