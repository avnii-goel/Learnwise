export const TOKEN_STORAGE_KEY = 'learnwise_token'

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export interface ApiResponse<T> {
  data: T
  status: number
}

type UnauthorizedCallback = () => void
const unauthorizedCallbacks = new Set<UnauthorizedCallback>()

export function onUnauthorized(callback: UnauthorizedCallback): () => void {
  unauthorizedCallbacks.add(callback)
  return () => {
    unauthorizedCallbacks.delete(callback)
  }
}

function notifyUnauthorized() {
  localStorage.removeItem(TOKEN_STORAGE_KEY)
  for (const cb of unauthorizedCallbacks) {
    try {
      cb()
    } catch (e) {
      console.error('Error in onUnauthorized callback', e)
    }
  }
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('learnwise:unauthorized'))
  }
}

export function formatFastApiError(detail: unknown, statusText: string): string {
  if (typeof detail === 'string') {
    return detail
  }
  if (Array.isArray(detail)) {
    const messages = detail.map((err) => {
      if (typeof err === 'object' && err !== null && 'msg' in err) {
        return String(err.msg)
      }
      return typeof err === 'string' ? err : JSON.stringify(err)
    })
    return messages.filter(Boolean).join('; ') || statusText
  }
  if (typeof detail === 'object' && detail !== null) {
    return JSON.stringify(detail)
  }
  return statusText || 'Request failed'
}

export async function apiFetchWithStatus<T>(
  path: string,
  options: RequestInit = {}
): Promise<ApiResponse<T>> {
  const baseUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined) || 'http://localhost:8000'
  const url = `${baseUrl.replace(/\/+$/, '')}/${path.replace(/^\/+/, '')}`

  const headers = new Headers(options.headers || {})

  if (!headers.has('Content-Type') && options.body && typeof options.body === 'string') {
    headers.set('Content-Type', 'application/json')
  }
  if (!headers.has('Accept')) {
    headers.set('Accept', 'application/json')
  }

  const token = localStorage.getItem(TOKEN_STORAGE_KEY)
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  const response = await fetch(url, {
    ...options,
    headers,
  })

  if (!response.ok) {
    let errorMessage = response.statusText || `Request failed with status ${response.status}`
    try {
      const errorBody = await response.json()
      if (errorBody && 'detail' in errorBody) {
        errorMessage = formatFastApiError(errorBody.detail, response.statusText)
      } else if (errorBody && 'message' in errorBody) {
        errorMessage = String(errorBody.message)
      }
    } catch {
      // Body wasn't JSON; use statusText
    }

    if (response.status === 401) {
      notifyUnauthorized()
    }

    throw new ApiError(response.status, errorMessage)
  }

  // 204 No Content
  if (response.status === 204) {
    return { data: undefined as unknown as T, status: response.status }
  }

  const data = (await response.json()) as T
  return { data, status: response.status }
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const result = await apiFetchWithStatus<T>(path, options)
  return result.data
}

