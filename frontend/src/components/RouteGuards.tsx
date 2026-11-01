import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

export function RequireAuth() {
  const { user, loading } = useAuth()

  if (loading) {
    return <div className="loading-state">Loading session...</div>
  }

  if (!user) {
    return <Navigate to="/login" replace />
  }

  return <Outlet />
}

interface RequireRoleProps {
  allowedRole: 'learner' | 'instructor'
}

export function RequireRole({ allowedRole }: RequireRoleProps) {
  const { user, loading } = useAuth()

  if (loading) {
    return <div className="loading-state">Loading session...</div>
  }

  if (!user) {
    return <Navigate to="/login" replace />
  }

  if (user.role !== allowedRole) {
    // Redirect to the user's own home dashboard
    return user.role === 'instructor' ? (
      <Navigate to="/instructor" replace />
    ) : (
      <Navigate to="/dashboard" replace />
    )
  }

  return <Outlet />
}

export function RootRedirect() {
  const { user, loading } = useAuth()

  if (loading) {
    return <div className="loading-state">Loading session...</div>
  }

  if (!user) {
    return <Navigate to="/login" replace />
  }

  return user.role === 'instructor' ? (
    <Navigate to="/instructor" replace />
  ) : (
    <Navigate to="/dashboard" replace />
  )
}

