import { describe, expect, it, vi } from 'vitest'

import { HubClient, HubError } from './client'

function respond(body: unknown, status = 200): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), { status })
}

function clientWith(handler: (url: string, init: RequestInit) => Response, token = 'tok') {
  const fetchMock = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => handler(String(url), init ?? {}))
  return { hub: new HubClient('http://hub.test/', token, fetchMock as unknown as typeof fetch), fetchMock }
}

describe('HubClient', () => {
  it('logs in with a form post and keeps the token for later calls', async () => {
    const { hub, fetchMock } = clientWith(
      (url) => (url.endsWith('/auth/token') ? respond({ access_token: 'jwt' }) : respond([])),
      '',
    )
    expect(await hub.login('alice', 'pw')).toBe('jwt')
    await hub.listTargets()

    const [, loginInit] = fetchMock.mock.calls[0]
    expect(String(loginInit?.body)).toBe('username=alice&password=pw&grant_type=')
    const [listUrl, listInit] = fetchMock.mock.calls[1]
    expect(listUrl).toBe('http://hub.test/api/v1/targets')
    expect((listInit?.headers as Record<string, string>).Authorization).toBe('Bearer jwt')
  })

  it('reserves using the authenticated username and a bounded window', async () => {
    const { hub, fetchMock } = clientWith((url) =>
      url.endsWith('/auth/me') ? respond({ username: 'alice' }) : respond({ id: 'r1' }),
    )
    await hub.reserve('t1', 30)

    const body = JSON.parse(String(fetchMock.mock.calls[1][1]?.body))
    expect(body.user_id).toBe('alice')
    expect(body.target_id).toBe('t1')
    expect(new Date(body.ends_at).getTime() - new Date(body.starts_at).getTime()).toBe(30 * 60_000)
  })

  it('lists only my active reservations', async () => {
    const { hub } = clientWith((url) =>
      url.endsWith('/auth/me')
        ? respond({ username: 'alice' })
        : respond([
            { id: 'a', target_id: 't', user_id: 'alice', status: 'active' },
            { id: 'b', target_id: 't', user_id: 'bob', status: 'active' },
            { id: 'c', target_id: 't', user_id: 'alice', status: 'released' },
          ]),
    )
    expect((await hub.myReservations()).map((r) => r.id)).toEqual(['a'])
  })

  it('reads serial text from the nested data payload', async () => {
    const { hub } = clientWith(() => respond({ data: { data_text: 'boot\r\n' } }))
    expect(await hub.serialRead('s1')).toBe('boot\r\n')
  })

  it('surfaces API errors with status and detail', async () => {
    const { hub } = clientWith(() => respond({ detail: 'Target already reserved' }, 409))
    await expect(hub.listTargets()).rejects.toMatchObject({ status: 409, message: 'Target already reserved' })
  })

  it('reports unreachable hubs with status 0', async () => {
    const hub = new HubClient('http://hub.test', 't', (async () => {
      throw new Error('ECONNREFUSED')
    }) as unknown as typeof fetch)
    const error = await hub.listTargets().catch((e: unknown) => e)
    expect(error).toBeInstanceOf(HubError)
    expect((error as HubError).status).toBe(0)
    expect((error as HubError).message).toContain('ECONNREFUSED')
  })
})
