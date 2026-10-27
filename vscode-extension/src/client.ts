export class HubError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message)
  }
}

export type Availability = { state: string; reserved_by: string | null; reserved_until: string | null }
export type Target = { id: string; name: string; enabled: boolean; tags?: string[]; availability?: Availability | null }
export type Reservation = { id: string; target_id: string; user_id: string; status: string; starts_at?: string; ends_at?: string }
export type Session = { id: string; target_id: string; capability_type: string; status: string; reservation_id?: string }
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
  private user: string | undefined

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

  /**
   * Password sign-in that returns a long-lived personal API token (named after this machine),
   * so the extension keeps working after the 15-minute access token expires.
   */
  async login(username: string, password: string, tokenName = 'vscode'): Promise<string> {
    const form = new URLSearchParams({ username, password, grant_type: '' })
    const session = await this.request<{ access_token: string }>('POST', '/auth/token', undefined, form)
    this.token = session.access_token
    const created = await this.request<{ token: string }>('POST', '/auth/api-tokens', { name: tokenName, expires_days: 365 })
    this.token = created.token
    this.user = username
    return created.token
  }

  async username(): Promise<string> {
    if (!this.user) this.user = (await this.request<{ username: string }>('GET', '/auth/me')).username
    return this.user
  }

  listTargets(): Promise<Target[]> {
    return this.request('GET', '/targets')
  }

  reserve(targetId: string, minutes: number): Promise<Reservation> {
    const start = new Date()
    return this.request('POST', '/reservations', {
      target_id: targetId,
      starts_at: start.toISOString(),
      ends_at: new Date(start.getTime() + minutes * 60_000).toISOString(),
    })
  }

  reserveAny(tag: string, minutes: number): Promise<Reservation> {
    return this.request('POST', '/reservations/any', { tag, duration_minutes: minutes })
  }

  extend(reservationId: string, minutes: number): Promise<Reservation> {
    return this.request('POST', `/reservations/${reservationId}/extend`, { extend_minutes: minutes })
  }

  release(reservationId: string): Promise<Reservation> {
    return this.request('POST', `/reservations/${reservationId}/release`)
  }

  async myReservations(): Promise<Reservation[]> {
    const user = await this.username()
    const all = await this.request<Reservation[]>('GET', '/reservations?status=active')
    return all.filter((reservation) => reservation.user_id === user && reservation.status === 'active')
  }

  openSession(reservationId: string, capabilityType: string): Promise<Session> {
    return this.request('POST', '/sessions', { reservation_id: reservationId, capability_type: capabilityType })
  }

  async activeSessions(capabilityType: string): Promise<Session[]> {
    const sessions = await this.request<Session[]>('GET', '/sessions')
    return sessions.filter((s) => s.status === 'active' && s.capability_type === capabilityType)
  }

  execute(sessionId: string, operation: string, params: Record<string, unknown> = {}) {
    return this.request<{ message: string; data: Record<string, unknown> }>('POST', `/sessions/${sessionId}/execute`, {
      operation,
      params,
    })
  }

  serialWrite(sessionId: string, text: string) {
    return this.request('POST', `/sessions/${sessionId}/serial/write`, { text })
  }

  /** Long read: returns as soon as the device prints something, or after waitMs. */
  async serialRead(sessionId: string, waitMs = 2000): Promise<string> {
    const result = await this.request<{ data: { data_text?: string } | null }>(
      'GET',
      `/sessions/${sessionId}/serial/read?size=65536&wait_ms=${waitMs}`,
    )
    return result.data?.data_text ?? ''
  }
}
