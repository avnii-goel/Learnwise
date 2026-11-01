import { Link } from 'react-router-dom'

export function NotFoundPage() {
  return (
    <div className="page-container text-center">
      <h1>404 - Page Not Found</h1>
      <p>The page you requested does not exist.</p>
      <div style={{ marginTop: '1rem' }}>
        <Link to="/" className="btn btn-primary">
          Back to Home
        </Link>
      </div>
    </div>
  )
}

