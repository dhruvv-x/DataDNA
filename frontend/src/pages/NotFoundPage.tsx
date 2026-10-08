import { Link } from 'react-router-dom'

export function NotFoundPage() {
  return (
    <div className="center-card">
      <h1>Page not found</h1>
      <p><Link to="/">Go to the dashboard</Link></p>
    </div>
  )
}
