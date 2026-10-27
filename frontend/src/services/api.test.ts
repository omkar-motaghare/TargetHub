import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { clearAuthToken, getAuthToken, listTargets, login, setTokens, setUnauthorizedHandler } from './api'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
}

describe('login', () => {
  afterEach(() => vi.restoreAllMocks())

  it('sends credentials as form data for FastAPI OAuth login', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      jsonResponse({ access_token: 'test-token', refresh_token: 'thr_x', token_type: 'bearer' }),
    )

    await expect(login('admin', 'admin')).resolves.toMatchObject({ access_token: 'test-token', refresh_token: 'thr_x' })

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/auth/token',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ 'Content-Type': 'application/x-www-form-urlencoded' }),
      }),
    )
    const request = fetchMock.mock.calls[0][1] as RequestInit
    expect((request.body as URLSearchParams).get('username')).toBe('admin')
  })
})

describe('token refresh', () => {
  beforeEach(() => {
    clearAuthToken()
    localStorage.clear()
  })
  afterEach(() => {
    vi.restoreAllMocks()
    setUnauthorizedHandler(null)
  })

  it('refreshes once on 401 and retries the request with the new token', async () => {
    setTokens({ access_token: 'old', refresh_token: 'thr_old' })
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      const auth = (init?.headers as Record<string, string> | undefined)?.Authorization
      if (url.endsWith('/auth/refresh')) {
        expect(JSON.parse(String(init?.body))).toEqual({ refresh_token: 'thr_old' })
        return jsonResponse({ access_token: 'new', refresh_token: 'thr_new', token_type: 'bearer' })
      }
      return auth === 'Bearer new' ? jsonResponse([]) : jsonResponse({ detail: 'Invalid or expired token' }, 401)
    })

    await expect(listTargets()).resolves.toEqual([])
    expect(getAuthToken()).toBe('new')
    expect(localStorage.getItem('th_refresh')).toBe('thr_new')
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/auth/refresh'))).toHaveLength(1)
  })

  it('concurrent 401s share a single refresh (rotating tokens must not be reused)', async () => {
    setTokens({ access_token: 'old', refresh_token: 'thr_old' })
    let refreshes = 0
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      if (String(input).endsWith('/auth/refresh')) {
        refreshes += 1
        await new Promise((resolve) => setTimeout(resolve, 20))
        return jsonResponse({ access_token: 'new', refresh_token: 'thr_new', token_type: 'bearer' })
      }
      const auth = (init?.headers as Record<string, string>).Authorization
      return auth === 'Bearer new' ? jsonResponse([]) : jsonResponse({ detail: 'expired' }, 401)
    })
    await Promise.all([listTargets(), listTargets(), listTargets()])
    expect(refreshes).toBe(1)
  })

  it('signs the user out when the refresh token is rejected', async () => {
    setTokens({ access_token: 'old', refresh_token: 'thr_dead' })
    const onUnauthorized = vi.fn()
    setUnauthorizedHandler(onUnauthorized)
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) =>
      String(input).endsWith('/auth/refresh')
        ? jsonResponse({ detail: 'refresh token expired' }, 401)
        : jsonResponse({ detail: 'expired' }, 401),
    )
    await expect(listTargets()).rejects.toMatchObject({ status: 401 })
    expect(onUnauthorized).toHaveBeenCalled()
  })
})
