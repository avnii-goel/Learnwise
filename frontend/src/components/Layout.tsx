import { Link, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

export function Layout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  return (
    <div className="app-container">
      <header className="top-nav">
        <div className="nav-brand">
          <Link to="/" className="brand-logo">
            LearnWise
          </Link>
        </div>

        {user && (
          <nav className="nav-links">
            {user.role === 'learner' && (
              <>
                <Link to="/dashboard" className="nav-link">
                  Dashboard
                </Link>
                <Link to="/quiz" className="nav-link">
                  Take a quiz
                </Link>
              </>
            )}

            {user.role === 'instructor' && (
              <Link to="/instructor" className="nav-link">
                Dashboard
              </Link>
            )}
          </nav>
        )}

        {!user && (
          <nav className="nav-links">
            <Link to="/login" className="nav-link">
              Sign In
            </Link>
            <Link to="/register" className="btn btn-primary btn-sm">
              Register as Learner
            </Link>
          </nav>
        )}

        {user && (
          <div className="nav-user">
            <span className="user-greeting">
              Signed in as <strong>{user.name}</strong>
            </span>
            <button
              type="button"
              onClick={handleLogout}
              className="btn btn-secondary btn-sm"
            >
              Logout
            </button>
          </div>
        )}
      </header>

      <main className="main-content">
        <Outlet />
      </main>
    </div>
  )
}

