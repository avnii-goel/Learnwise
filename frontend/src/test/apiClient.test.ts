import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { apiFetch, TOKEN_STORAGE_KEY, ApiError } from '../api/client'

describe('apiFetch client', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('attaches the Authorization header when a token exists in localStorage', async () => {
    localStorage.setItem(TOKEN_STORAGE_KEY, 'my-secret-jwt')

    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ message: 'success' }),
    })
    vi.stubGlobal('fetch', mockFetch)

    const data = await apiFetch<{ message: string }>('/api/test-auth')

    expect(data).toEqual({ message: 'success' })
    expect(mockFetch).toHaveBeenCalledTimes(1)
    const callArgs = mockFetch.mock.calls[0]
    const headers = callArgs[1]?.headers as Headers
    expect(headers.get('Authorization')).toBe('Bearer my-secret-jwt')
  })

  it('clears the stored token and throws ApiError on 401 response', async () => {
    localStorage.setItem(TOKEN_STORAGE_KEY, 'expired-token')

    const mockFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      statusText: 'Unauthorized',
      json: async () => ({ detail: 'Invalid or expired token' }),
    })
    vi.stubGlobal('fetch', mockFetch)

    await expect(apiFetch('/api/protected')).rejects.toThrow(ApiError)
    expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull()
  })
})

