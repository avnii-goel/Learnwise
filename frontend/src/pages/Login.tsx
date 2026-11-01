import { useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { ApiError } from '../api/client'

export function LoginPage() {
  const { user, login } = useAuth()
  const navigate = useNavigate()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Redirect if already authenticated
  if (user) {
    return user.role === 'instructor' ? (
      <Navigate to="/instructor" replace />
    ) : (
      <Navigate to="/dashboard" replace />
    )
  }

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setError(null)
    setSubmitting(true)

    try {
      const loggedInUser = await login(email, password)
      if (loggedInUser.role === 'instructor') {
        navigate('/instructor')
      } else {
        navigate('/dashboard')
      }
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message)
      } else if (err instanceof Error) {
        setError(err.message)
      } else {
        setError('Login failed. Please try again.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="login-card-container">
      <div className="card login-card">
        <h2>Sign in to LearnWise</h2>
        <p className="card-subtitle">
          Enter your email and password to access your dashboard.
        </p>

        {error && (
          <div className="alert alert-error" role="alert">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="form">
          <div className="form-group">
            <label htmlFor="email">Email address</label>
            <input
              id="email"
              name="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="e.g. learner@example.com"
              disabled={submitting}
            />
          </div>

          <div className="form-group">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter your password"
              disabled={submitting}
            />
          </div>

          <button
            type="submit"
            className="btn btn-primary btn-block"
            disabled={submitting}
          >
            {submitting ? 'Signing in...' : 'Sign in'}
          </button>
        </form>

        <div
          className="auth-footer"
          style={{
            marginTop: '1.25rem',
            textAlign: 'center',
            fontSize: '0.875rem',
            color: 'var(--text-muted)',
          }}
        >
          Don't have an account?{' '}
          <Link
            to="/register"
            style={{ color: 'var(--primary)', fontWeight: 600, textDecoration: 'none' }}
          >
            Register as a learner
          </Link>
        </div>
      </div>
    </div>
  )
}

