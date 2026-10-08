import { Navigate, Outlet, useLocation } from 'react-router-dom'
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
