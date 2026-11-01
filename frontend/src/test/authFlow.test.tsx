import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { AuthProvider } from '../auth/AuthContext'
import { AppRoutes } from '../App'
import { TOKEN_STORAGE_KEY } from '../api/client'

function renderAppWithRoute(initialRoute: string) {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={[initialRoute]}>
        <AppRoutes />
      </MemoryRouter>
    </AuthProvider>
  )
}

describe('Authentication & Route Protection', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('login success stores learnwise_token and redirects learner to /dashboard', async () => {
    const user = userEvent.setup()

    const mockFetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/api/auth/login')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ access_token: 'jwt-learner-123', token_type: 'bearer' }),
        })
      }
      if (url.includes('/api/auth/me')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            id: 1,
            name: 'Synthetic Learner 01',
            email: 'learner@example.com',
            role: 'learner',
            created_at: '2026-10-31T12:00:00Z',
          }),
        })
      }
      return Promise.reject(new Error(`Unhandled url ${url}`))
    })
    vi.stubGlobal('fetch', mockFetch)

    renderAppWithRoute('/login')

    const emailInput = screen.getByLabelText(/email address/i)
    const passwordInput = screen.getByLabelText(/password/i)
    const submitBtn = screen.getByRole('button', { name: /sign in/i })

    await user.type(emailInput, 'learner@example.com')
    await user.type(passwordInput, 'password123')
    await user.click(submitBtn)

    await waitFor(() => {
      expect(screen.getByRole('heading', { level: 1, name: /learner dashboard/i })).toBeInTheDocument()
    })

    expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBe('jwt-learner-123')
    expect(screen.getByText(/Synthetic Learner 01/i)).toBeInTheDocument()
  })

  it('login success stores learnwise_token and redirects instructor to /instructor', async () => {
    const user = userEvent.setup()

    const mockFetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/api/auth/login')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ access_token: 'jwt-instructor-456', token_type: 'bearer' }),
        })
      }
      if (url.includes('/api/auth/me')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            id: 2,
            name: 'Dr. Instructor',
            email: 'instructor@example.com',
            role: 'instructor',
            created_at: '2026-10-31T12:00:00Z',
          }),
        })
      }
      return Promise.reject(new Error(`Unhandled url ${url}`))
    })
    vi.stubGlobal('fetch', mockFetch)

    renderAppWithRoute('/login')

    const emailInput = screen.getByLabelText(/email address/i)
    const passwordInput = screen.getByLabelText(/password/i)
    const submitBtn = screen.getByRole('button', { name: /sign in/i })

    await user.type(emailInput, 'instructor@example.com')
    await user.type(passwordInput, 'password123')
    await user.click(submitBtn)

    await waitFor(() => {
      expect(screen.getByRole('heading', { level: 1, name: /instructor dashboard/i })).toBeInTheDocument()
    })

    expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBe('jwt-instructor-456')
    expect(screen.getByText(/Dr\. Instructor/i)).toBeInTheDocument()
  })

  it('login failure shows the API error message and stores no token', async () => {
    const user = userEvent.setup()

    const mockFetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/api/auth/login')) {
        return Promise.resolve({
          ok: false,
          status: 401,
          statusText: 'Unauthorized',
          json: async () => ({ detail: 'Invalid credentials provided' }),
        })
      }
      return Promise.reject(new Error(`Unhandled url ${url}`))
    })
    vi.stubGlobal('fetch', mockFetch)

    renderAppWithRoute('/login')

    const emailInput = screen.getByLabelText(/email address/i)
    const passwordInput = screen.getByLabelText(/password/i)
    const submitBtn = screen.getByRole('button', { name: /sign in/i })

    await user.type(emailInput, 'wrong@example.com')
    await user.type(passwordInput, 'wrongpass')
    await user.click(submitBtn)

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/invalid credentials provided/i)
    })

    expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull()
  })

  it('RequireRole: a learner opening /instructor is redirected to /dashboard', async () => {
    localStorage.setItem(TOKEN_STORAGE_KEY, 'existing-learner-token')

    const mockFetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/api/auth/me')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            id: 1,
            name: 'Learner One',
            email: 'learner1@example.com',
            role: 'learner',
            created_at: '2026-10-31T12:00:00Z',
          }),
        })
      }
      return Promise.reject(new Error(`Unhandled url ${url}`))
    })
    vi.stubGlobal('fetch', mockFetch)

    renderAppWithRoute('/instructor')

    await waitFor(() => {
      expect(screen.getByRole('heading', { level: 1, name: /learner dashboard/i })).toBeInTheDocument()
    })
  })

  it('RequireRole: an unauthenticated user opening /quiz is redirected to /login', async () => {
    localStorage.clear()

    renderAppWithRoute('/quiz')

    await waitFor(() => {
      expect(screen.getByRole('heading', { level: 2, name: /sign in to learnwise/i })).toBeInTheDocument()
    })
  })

  it('register success: creates new learner account, logs in, and redirects to /dashboard', async () => {
    const user = userEvent.setup()

    const mockFetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      if (url.includes('/api/auth/register')) {
        const body = JSON.parse(init?.body as string)
        expect(body.role).toBe('learner')
        expect(body.name).toBe('New Learner')
        return Promise.resolve({
          ok: true,
          status: 201,
          json: async () => ({
            id: 99,
            name: 'New Learner',
            email: 'newlearner@example.com',
            role: 'learner',
            created_at: '2026-11-01T23:00:00Z',
          }),
        })
      }
      if (url.includes('/api/auth/login')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ access_token: 'jwt-new-learner-token', token_type: 'bearer' }),
        })
      }
      if (url.includes('/api/auth/me')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            id: 99,
            name: 'New Learner',
            email: 'newlearner@example.com',
            role: 'learner',
            created_at: '2026-11-01T23:00:00Z',
          }),
        })
      }
      return Promise.reject(new Error(`Unhandled url ${url}`))
    })
    vi.stubGlobal('fetch', mockFetch)

    renderAppWithRoute('/register')

    expect(screen.getByRole('heading', { level: 2, name: /create learner account/i })).toBeInTheDocument()

    await user.type(screen.getByLabelText(/full name/i), 'New Learner')
    await user.type(screen.getByLabelText(/email address/i), 'newlearner@example.com')
    await user.type(screen.getByLabelText(/^password$/i), 'password123')
    await user.type(screen.getByLabelText(/confirm password/i), 'password123')
    await user.click(screen.getByRole('button', { name: /create account/i }))

    await waitFor(() => {
      expect(screen.getByRole('heading', { level: 1, name: /learner dashboard/i })).toBeInTheDocument()
    })

    expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBe('jwt-new-learner-token')
  })

  it('register validation: shows error when passwords do not match', async () => {
    const user = userEvent.setup()

    renderAppWithRoute('/register')

    await user.type(screen.getByLabelText(/full name/i), 'New Learner')
    await user.type(screen.getByLabelText(/email address/i), 'newlearner@example.com')
    await user.type(screen.getByLabelText(/^password$/i), 'password123')
    await user.type(screen.getByLabelText(/confirm password/i), 'differentpassword')
    await user.click(screen.getByRole('button', { name: /create account/i }))

    expect(screen.getByRole('alert')).toHaveTextContent(/passwords do not match/i)
  })
})
