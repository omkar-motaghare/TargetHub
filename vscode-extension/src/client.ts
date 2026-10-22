export class HubError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message)
  }
}

export type Target = { id: string; name: string; enabled: boolean }
export type Reservation = { id: string; target_id: string; user_id: string; status: string }
export type Session = { id: string; target_id: string; capability_type: string; status: string }
export type Fetch = typeof fetch

async function detail(response: Response): Promise<string> {
  const text = await response.text()
  try {
    const body = JSON.parse(text) as { detail?: unknown }
    return typeof body.detail === 'string' ? body.detail : text
  } catch {
    return text || response.statusText
  }
}

export class HubClient {
  constructor(
    private readonly baseUrl: string,
    private token: string | undefined,
    private readonly doFetch: Fetch = fetch,
  ) {}

  private async request<T>(method: string, path: string, body?: unknown, form?: URLSearchParams): Promise<T> {
    const headers: Record<string, string> = {}
    if (this.token) headers.Authorization = `Bearer ${this.token}`
    if (body !== undefined) headers['Content-Type'] = 'application/json'
    let response: Response
    try {
      response = await this.doFetch(`${this.baseUrl.replace(/\/$/, '')}/api/v1${path}`, {
        method,
        headers,
        body: form ?? (body === undefined ? undefined : JSON.stringify(body)),
      })
    } catch (error) {
      throw new HubError(0, `Cannot reach TargetHub: ${error instanceof Error ? error.message : String(error)}`)
    }
    if (!response.ok) throw new HubError(response.status, await detail(response))
    const text = await response.text()
    return (text ? JSON.parse(text) : undefined) as T
  }

  async login(username: string, password: string): Promise<string> {
    const form = new URLSearchParams({ username, password, grant_type: '' })
    const result = await this.request<{ access_token: string }>('POST', '/auth/token', undefined, form)
    this.token = result.access_token
    return result.access_token
  }

  async username(): Promise<string> {
    return (await this.request<{ username: string }>('GET', '/auth/me')).username
  }

  listTargets(): Promise<Target[]> {
    return this.request('GET', '/targets')
  }

  async reserve(targetId: string, minutes: number): Promise<Reservation> {
    const start = new Date()
    return this.request('POST', '/reservations', {
      target_id: targetId,
      user_id: await this.username(),
      starts_at: start.toISOString(),
      ends_at: new Date(start.getTime() + minutes * 60_000).toISOString(),
    })
  }

  async release(reservationId: string): Promise<Reservation> {
    const user = encodeURIComponent(await this.username())
    return this.request('POST', `/reservations/${reservationId}/release?user_id=${user}`)
  }

  async myReservations(): Promise<Reservation[]> {
    const user = await this.username()
    const all = await this.request<Reservation[]>('GET', '/reservations')
    return all.filter((reservation) => reservation.user_id === user && reservation.status === 'active')
  }

  async openSession(reservationId: string, capabilityType: string): Promise<Session> {
    return this.request('POST', '/sessions', {
      reservation_id: reservationId,
      user_id: await this.username(),
      capability_type: capabilityType,
    })
  }

  async activeSessions(capabilityType: string): Promise<Session[]> {
    const sessions = await this.request<Session[]>('GET', '/sessions')
    return sessions.filter((s) => s.status === 'active' && s.capability_type === capabilityType)
  }

  async execute(sessionId: string, operation: string, params: Record<string, unknown> = {}) {
    return this.request<{ message: string; data: Record<string, unknown> }>(
      'POST',
      `/sessions/${sessionId}/execute`,
      { operation, params },
    )
  }

  serialWrite(sessionId: string, text: string) {
    return this.request('POST', `/sessions/${sessionId}/serial/write`, { text })
  }

  async serialRead(sessionId: string): Promise<string> {
    const result = await this.request<{ data: { data_text?: string } }>('GET', `/sessions/${sessionId}/serial/read?size=4096`)
    return result.data.data_text ?? ''
  }
}
