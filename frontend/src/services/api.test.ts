import { afterEach, describe, expect, it, vi } from 'vitest'

import { login } from './api'

describe('login', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('sends credentials as form data for FastAPI OAuth login', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response(JSON.stringify({ access_token: 'test-token' }), { status: 200 }))

    await expect(login('admin', 'admin')).resolves.toBe('test-token')

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/auth/token',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ 'Content-Type': 'application/x-www-form-urlencoded' }),
      }),
    )
    const request = fetchMock.mock.calls[0][1] as RequestInit
    expect(request.body).toBeInstanceOf(URLSearchParams)
    expect((request.body as URLSearchParams).get('username')).toBe('admin')
    expect((request.body as URLSearchParams).get('password')).toBe('admin')
  })
})