import type {
  Agent,
  AgentEnrollment,
  AuditEntry,
  ProviderResult,
  Reservation,
  Session,
  SessionOperationList,
  Target,
  TargetCapability,
  TargetCapabilityCreateInput,
  TargetCapabilityUpdateInput,
  TargetCreateInput,
  TargetUpdateInput,
  UserAdmin,
  UserProfile,
} from './types'

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }

  kind(): 'unauthorized' | 'forbidden' | 'conflict' | 'offline' | 'validation' | 'generic' {
    if (this.status === 401) return 'unauthorized'
    if (this.status === 403) return 'forbidden'
    if (this.status === 409) return 'conflict'
    if (this.status === 422) return 'validation'
    if (this.status <= 0) return 'offline'
    return 'generic'
  }
}

const API_BASE = (import.meta.env.VITE_API_URL as string) || '/api/v1'

let authToken = localStorage.getItem('th_token') || ''
let unauthorizedHandler: (() => void) | null = null

function getAuthHeaders(): Record<string, string> {
  return authToken ? { Authorization: `Bearer ${authToken}` } : {}
}

function withQuery(path: string, params?: Record<string, string | undefined>): string {
  if (!params) return path
  const qs = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value) qs.set(key, value)
  })
  const suffix = qs.toString()
  return suffix ? `${path}?${suffix}` : path
}

export function formatApiErrorDetail(detail: unknown): string | null {
  if (typeof detail === 'string') return detail

  if (Array.isArray(detail)) {
    const messages = detail.map((item) => {
      if (typeof item === 'string') return item
      if (item && typeof item === 'object') {
        const validation = item as { loc?: unknown; msg?: unknown }
        const message = typeof validation.msg === 'string' ? validation.msg : JSON.stringify(item)
        const location = Array.isArray(validation.loc)
          ? validation.loc.filter((part): part is string => typeof part === 'string' && part !== 'body').join('.')
          : ''
        return location ? `${location}: ${message}` : message
      }
      return String(item)
    })
    return messages.join('; ')
  }

  if (detail && typeof detail === 'object') {
    const message = (detail as { msg?: unknown }).msg
    if (typeof message === 'string') return message
    return JSON.stringify(detail)
  }

  return detail == null ? null : String(detail)
}

async function parseError(response: Response, fallback: string): Promise<string> {
  const text = await response.text()
  try {
    const payload = JSON.parse(text)
    const detail = formatApiErrorDetail(payload?.detail)
    if (detail) return detail
  } catch {
    // Keep fallback if payload is not JSON.
  }
  return text || fallback
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  fallback = 'Request failed',
): Promise<T> {
  const headers: Record<string, string> = {
    ...getAuthHeaders(),
    ...(options.headers as Record<string, string> | undefined),
  }

  if (
    options.body &&
    !(options.body instanceof FormData) &&
    !(options.body instanceof URLSearchParams) &&
    !headers['Content-Type']
  ) {
    headers['Content-Type'] = 'application/json'
  }

  if (options.body instanceof URLSearchParams && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/x-www-form-urlencoded'
  }

  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, { ...options, headers })
  } catch (error) {
    throw new ApiError(0, error instanceof Error ? error.message : 'Network request failed')
  }

  if (!response.ok) {
    const message = await parseError(response, fallback)
    const apiError = new ApiError(response.status, message)
    if (response.status === 401 && unauthorizedHandler) unauthorizedHandler()
    throw apiError
  }

  if (response.status === 204) {
    return undefined as T
  }

  const body = await response.text()
  if (!body) return undefined as T
  return JSON.parse(body) as T
}

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler
}

export function setAuthToken(token: string): void {
  authToken = token
  if (token) {
    localStorage.setItem('th_token', token)
  } else {
    localStorage.removeItem('th_token')
  }
}

export function clearAuthToken(): void {
  setAuthToken('')
}

export function getAuthToken(): string {
  return authToken
}

export async function login(username: string, password: string): Promise<string> {
  const form = new URLSearchParams()
  form.set('username', username)
  form.set('password', password)
  form.set('grant_type', '')

  const payload = await request<{ access_token: string }>(
    '/auth/token',
    {
      method: 'POST',
      body: form,
    },
    'Login failed',
  )
  return payload.access_token
}

export async function getSetupStatus(): Promise<{ setup_required: boolean; bootstrap_enabled: boolean }> {
  return request('/auth/setup-status', { method: 'GET' }, 'Failed to check setup status')
}

export async function bootstrapAdmin(input: {
  username: string
  password: string
  bootstrap_token: string
}): Promise<void> {
  await request(
    '/auth/bootstrap',
    {
      method: 'POST',
      body: JSON.stringify(input),
    },
    'Failed to create the admin account',
  )
}

export async function changePassword(input: {
  username: string
  current_password: string
  new_password: string
}): Promise<void> {
  return request<void>(
    '/auth/change-password',
    {
      method: 'POST',
      body: JSON.stringify(input),
    },
    'Failed to change password',
  )
}

export async function me(): Promise<UserProfile> {
  return request<UserProfile>('/auth/me', { method: 'GET' }, 'Not authenticated')
}

export async function listUsers(): Promise<UserAdmin[]> {
  return request<UserAdmin[]>('/auth/users', { method: 'GET' }, 'Failed to list users')
}

export async function createUser(input: { username: string; password: string; roles: string[] }): Promise<UserAdmin> {
  return request<UserAdmin>(
    '/auth/users',
    {
      method: 'POST',
      body: JSON.stringify(input),
    },
    'Failed to create user',
  )
}

export async function updateUser(
  userId: number,
  input: { roles?: string[]; password?: string },
): Promise<UserAdmin> {
  return request<UserAdmin>(
    `/auth/users/${userId}`,
    {
      method: 'PUT',
      body: JSON.stringify(input),
    },
    'Failed to update user',
  )
}

export async function deleteUser(userId: number): Promise<void> {
  return request<void>(`/auth/users/${userId}`, { method: 'DELETE' }, 'Failed to delete user')
}

export async function listTargets(): Promise<Target[]> {
  return request<Target[]>('/targets', { method: 'GET' }, 'Failed to list targets')
}

export async function getTarget(targetId: string): Promise<Target> {
  return request<Target>(`/targets/${targetId}`, { method: 'GET' }, 'Failed to load target details')
}

export async function createTarget(input: TargetCreateInput): Promise<Target> {
  return request<Target>(
    '/targets',
    {
      method: 'POST',
      body: JSON.stringify(input),
    },
    'Failed to create target',
  )
}

export async function updateTarget(targetId: string, input: TargetUpdateInput): Promise<Target> {
  return request<Target>(
    `/targets/${targetId}`,
    {
      method: 'PUT',
      body: JSON.stringify(input),
    },
    'Failed to update target',
  )
}

export async function deleteTarget(targetId: string): Promise<void> {
  return request<void>(`/targets/${targetId}`, { method: 'DELETE' }, 'Failed to delete target')
}

export async function listCapabilities(targetId: string): Promise<TargetCapability[]> {
  return request<TargetCapability[]>(
    `/targets/${targetId}/capabilities`,
    { method: 'GET' },
    'Failed to list target capabilities',
  )
}

export async function createCapability(
  targetId: string,
  input: TargetCapabilityCreateInput,
): Promise<TargetCapability> {
  return request<TargetCapability>(
    `/targets/${targetId}/capabilities`,
    {
      method: 'POST',
      body: JSON.stringify(input),
    },
    'Failed to create target capability',
  )
}

export async function updateCapability(
  targetId: string,
  capabilityId: string,
  input: TargetCapabilityUpdateInput,
): Promise<TargetCapability> {
  return request<TargetCapability>(
    `/targets/${targetId}/capabilities/${capabilityId}`,
    {
      method: 'PUT',
      body: JSON.stringify(input),
    },
    'Failed to update target capability',
  )
}

export async function deleteCapability(targetId: string, capabilityId: string): Promise<void> {
  return request<void>(
    `/targets/${targetId}/capabilities/${capabilityId}`,
    { method: 'DELETE' },
    'Failed to delete target capability',
  )
}

export async function listReservations(params: { target_id?: string; user_id?: string } = {}): Promise<Reservation[]> {
  return request<Reservation[]>(
    withQuery('/reservations', params),
    { method: 'GET' },
    'Failed to list reservations',
  )
}

export async function createReservation(
  target_id: string,
  user_id: string,
  starts_at: string,
  ends_at: string,
): Promise<Reservation> {
  return request<Reservation>(
    '/reservations',
    {
      method: 'POST',
      body: JSON.stringify({ target_id, user_id, starts_at, ends_at }),
    },
    'Failed to create reservation',
  )
}

export async function releaseReservation(reservationId: string, userId: string): Promise<Reservation> {
  return request<Reservation>(
    `/reservations/${reservationId}/release?user_id=${encodeURIComponent(userId)}`,
    { method: 'POST' },
    'Failed to release reservation',
  )
}

export async function forceReleaseReservation(reservationId: string): Promise<Reservation> {
  return request<Reservation>(
    `/reservations/${reservationId}/force-release`,
    { method: 'POST' },
    'Failed to force release reservation',
  )
}

export async function listSessions(params: { user_id?: string; target_id?: string } = {}): Promise<Session[]> {
  return request<Session[]>(
    withQuery('/sessions', params),
    { method: 'GET' },
    'Failed to list sessions',
  )
}

export async function createSession(
  reservation_id: string,
  user_id: string,
  capability_type: string,
  capability_id?: string,
): Promise<Session> {
  return request<Session>(
    '/sessions',
    {
      method: 'POST',
      body: JSON.stringify({ reservation_id, user_id, capability_type, capability_id }),
    },
    'Failed to create session',
  )
}

export async function getSession(sessionId: string): Promise<Session> {
  return request<Session>(`/sessions/${sessionId}`, { method: 'GET' }, 'Failed to load session')
}

export async function closeSession(sessionId: string, userId: string): Promise<Session> {
  return request<Session>(
    `/sessions/${sessionId}/close?user_id=${encodeURIComponent(userId)}`,
    { method: 'POST' },
    'Failed to close session',
  )
}

export async function listSessionOperations(sessionId: string): Promise<SessionOperationList> {
  return request<SessionOperationList>(
    `/sessions/${sessionId}/operations`,
    { method: 'GET' },
    'Failed to load session operations',
  )
}

export async function executeSessionOperation(
  sessionId: string,
  operation: string,
  params: Record<string, unknown>,
): Promise<ProviderResult> {
  return request<ProviderResult>(
    `/sessions/${sessionId}/execute`,
    {
      method: 'POST',
      body: JSON.stringify({ operation, params }),
    },
    `Failed to execute operation '${operation}'`,
  )
}

export async function serialRead(sessionId: string, size = 4096): Promise<ProviderResult> {
  return request<ProviderResult>(
    `/sessions/${sessionId}/serial/read?size=${size}`,
    { method: 'GET' },
    'Failed to read from serial session',
  )
}

export async function serialWrite(sessionId: string, text: string): Promise<ProviderResult> {
  return request<ProviderResult>(
    `/sessions/${sessionId}/serial/write`,
    {
      method: 'POST',
      body: JSON.stringify({ text }),
    },
    'Failed to write to serial session',
  )
}

export async function listAgents(): Promise<Agent[]> {
  return request<Agent[]>('/agents', { method: 'GET' }, 'Failed to list agents')
}

export async function listAgentEnrollments(): Promise<AgentEnrollment[]> {
  return request<AgentEnrollment[]>('/agents/enrollments', { method: 'GET' }, 'Failed to list enrollments')
}

export async function createAgentEnrollment(agent_name: string): Promise<AgentEnrollment> {
  return request<AgentEnrollment>(
    '/agents/enrollments',
    {
      method: 'POST',
      body: JSON.stringify({ agent_name }),
    },
    'Failed to create enrollment',
  )
}

export async function disableAgent(agentId: string): Promise<Agent> {
  return request<Agent>(`/agents/${agentId}/disable`, { method: 'POST' }, 'Failed to disable agent')
}

export async function enableAgent(agentId: string): Promise<Agent> {
  return request<Agent>(`/agents/${agentId}/enable`, { method: 'POST' }, 'Failed to enable agent')
}

export async function revokeAgentCredential(agentId: string): Promise<Agent> {
  return request<Agent>(
    `/agents/${agentId}/revoke-credential`,
    { method: 'POST' },
    'Failed to revoke agent credential',
  )
}

export async function listAuditEntries(params: {
  user_id?: string
  target_id?: string
  session_id?: string
  action?: string
  limit?: number
} = {}): Promise<AuditEntry[]> {
  const normalized: Record<string, string | undefined> = {
    user_id: params.user_id,
    target_id: params.target_id,
    session_id: params.session_id,
    action: params.action,
    limit: params.limit ? String(params.limit) : undefined,
  }
  return request<AuditEntry[]>(withQuery('/audit', normalized), { method: 'GET' }, 'Failed to list audit entries')
}

export async function listLabs(): Promise<string[]> {
  return request<string[]>('/labs', { method: 'GET' }, 'Failed to list labs')
}
