import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react'
import {
  apiFetch,
  onUnauthorized,
  TOKEN_STORAGE_KEY,
} from '../api/client'
import type {
  LoginResponse,
  UserLoginRequest,
  UserResponse,
} from '../api/types'

export interface AuthContextType {
  user: UserResponse | null
  token: string | null
  loading: boolean
  login: (email: string, password: string) => Promise<UserResponse>
  register: (name: string, email: string, password: string) => Promise<UserResponse>
  logout: () => void
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserResponse | null>(null)
  const [token, setToken] = useState<string | null>(() => {
    return typeof window !== 'undefined' ? localStorage.getItem(TOKEN_STORAGE_KEY) : null
  })
  const [loading, setLoading] = useState(true)

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_STORAGE_KEY)
    setToken(null)
    setUser(null)
  }, [])

  // Listen for unauthorized events triggered from apiFetch
  useEffect(() => {
    const unsubscribe = onUnauthorized(() => {
      logout()
    })
    return unsubscribe
  }, [logout])

  // Restore user session on mount
  useEffect(() => {
    let isMounted = true
    const storedToken = localStorage.getItem(TOKEN_STORAGE_KEY)

    if (!storedToken) {
      setLoading(false)
      return
    }

    apiFetch<UserResponse>('/api/auth/me')
      .then((me) => {
        if (isMounted) {
          setUser(me)
          setToken(storedToken)
        }
      })
      .catch(() => {
        if (isMounted) {
          logout()
        }
      })
      .finally(() => {
        if (isMounted) {
          setLoading(false)
        }
      })

    return () => {
      isMounted = false
    }
  }, [logout])

  const login = useCallback(
    async (email: string, password: string): Promise<UserResponse> => {
      const loginPayload: UserLoginRequest = { email, password }
      const res = await apiFetch<LoginResponse>('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify(loginPayload),
      })

      localStorage.setItem(TOKEN_STORAGE_KEY, res.access_token)
      setToken(res.access_token)

      // Fetch user profile
      const me = await apiFetch<UserResponse>('/api/auth/me', {
        headers: {
          Authorization: `Bearer ${res.access_token}`,
        },
      })
      setUser(me)
      return me
    },
    []
  )

  const register = useCallback(
    async (name: string, email: string, password: string): Promise<UserResponse> => {
      await apiFetch<UserResponse>('/api/auth/register', {
        method: 'POST',
        body: JSON.stringify({ name, email, password, role: 'learner' }),
      })
      return login(email, password)
    },
    [login]
  )

  const value: AuthContextType = {
    user,
    token,
    loading,
    login,
    register,
    logout,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}

