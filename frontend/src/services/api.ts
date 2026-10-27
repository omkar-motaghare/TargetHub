import type {
  Agent,
  AgentEnrollment,
  ApiToken,
  AppNotification,
  AuditEntry,
  OperationStatus,
  ProviderResult,
  Reservation,
  ReservationPolicy,
  Session,
  SessionOperationList,
  Target,
  TargetCapability,
  TargetCapabilityCreateInput,
  TargetCapabilityUpdateInput,
  TargetCreateInput,
  TargetUpdateInput,
  TokenPair,
  UserAdmin,
  UserProfile,
  WaitlistEntry,
  Webhook,
} from './types'

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }

  kind(): 'unauthorized' | 'forbidden' | 'conflict' | 'offline' | 'validation' | 'rate_limited' | 'generic' {
    if (this.status === 401) return 'unauthorized'
    if (this.status === 403) return 'forbidden'
    if (this.status === 409) return 'conflict'
    if (this.status === 422) return 'validation'
    if (this.status === 429) return 'rate_limited'
    if (this.status <= 0) return 'offline'
    return 'generic'
  }
}

export const API_BASE = (import.meta.env.VITE_API_URL as string) || '/api/v1'

const ACCESS_KEY = 'th_token'
const REFRESH_KEY = 'th_refresh'

function storageGet(key: string): string {
  try {
    return localStorage.getItem(key) || ''
  } catch {
    return ''
  }
}

function storageSet(key: string, value: string): void {
  try {
    if (value) localStorage.setItem(key, value)
    else localStorage.removeItem(key)
  } catch {
    // Storage may be unavailable (private mode); tokens then live in memory only.
  }
}

let authToken = storageGet(ACCESS_KEY)
let refreshToken = storageGet(REFRESH_KEY)
let unauthorizedHandler: (() => void) | null = null
let refreshing: Promise<boolean> | null = null

// Keep tabs in sync: another tab may rotate the tokens or log out.
if (typeof window !== 'undefined') {
  window.addEventListener('storage', (event) => {
    if (event.key === ACCESS_KEY) authToken = event.newValue || ''
    if (event.key === REFRESH_KEY) refreshToken = event.newValue || ''
  })
}

function getAuthHeaders(): Record<string, string> {
  return authToken ? { Authorization: `Bearer ${authToken}` } : {}
}

function withQuery(path: string, params?: Record<string, string | number | boolean | undefined | null>): string {
  if (!params) return path
  const qs = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') qs.set(key, String(value))
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

export function setTokens(pair: { access_token: string; refresh_token?: string | null }): void {
  authToken = pair.access_token
  storageSet(ACCESS_KEY, authToken)
  if (pair.refresh_token !== undefined) {
    refreshToken = pair.refresh_token || ''
    storageSet(REFRESH_KEY, refreshToken)
  }
}

/** Backwards-compatible single-token setter (e.g. a pasted API token). */
export function setAuthToken(token: string): void {
  setTokens({ access_token: token })
}

export function clearAuthToken(): void {
  authToken = ''
  refreshToken = ''
  storageSet(ACCESS_KEY, '')
  storageSet(REFRESH_KEY, '')
}

export function getAuthToken(): string {
  return authToken
}

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler
}

async function doRefresh(): Promise<boolean> {
  const presented = storageGet(REFRESH_KEY) || refreshToken
  if (!presented) return false
  try {
    const response = await fetch(`${API_BASE}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: presented }),
    })
    if (!response.ok) return false
    setTokens((await response.json()) as TokenPair)
    return true
  } catch {
    return false
  }
}

/**
 * Renew the access token once, even if many requests (or several tabs) hit a 401
 * at the same time: refresh tokens rotate, and presenting a used one revokes them all.
 */
export async function refreshAccessToken(): Promise<boolean> {
  if (refreshing) return refreshing
  const before = storageGet(REFRESH_KEY) || refreshToken
  const run = async (): Promise<boolean> => {
    const current = storageGet(REFRESH_KEY)
    if (current && current !== before) {
      // Another tab refreshed while we waited for the lock.
      refreshToken = current
      authToken = storageGet(ACCESS_KEY)
      return true
    }
    return doRefresh()
  }
  const locks = typeof navigator !== 'undefined' ? (navigator as Navigator & { locks?: LockManager }).locks : undefined
  const pending: Promise<boolean> = (
    locks ? (locks.request('targethub-token-refresh', run) as unknown as Promise<boolean>) : run()
  ).finally(() => {
    refreshing = null
  })
  refreshing = pending
  return pending
}

async function request<T>(path: string, options: RequestInit = {}, fallback = 'Request failed', retry = true): Promise<T> {
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

  if (response.status === 401 && retry && !path.startsWith('/auth/token') && !path.startsWith('/auth/refresh')) {
    if (await refreshAccessToken()) return request<T>(path, options, fallback, false)
  }

  if (!response.ok) {
    const message = await parseError(response, fallback)
    if (response.status === 401 && unauthorizedHandler && !path.startsWith('/auth/token')) unauthorizedHandler()
    throw new ApiError(response.status, message)
  }

  if (response.status === 204) return undefined as T
  const contentType = response.headers.get('content-type') || ''
  const body = await response.text()
  if (!body) return undefined as T
  return (contentType.includes('application/json') ? JSON.parse(body) : body) as T
}

const json = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body) })
const put = (body: unknown): RequestInit => ({ method: 'PUT', body: JSON.stringify(body) })

// ---------------------------------------------------------------- auth

export async function login(username: string, password: string): Promise<TokenPair> {
  const form = new URLSearchParams()
  form.set('username', username)
  form.set('password', password)
  form.set('grant_type', '')
  return request<TokenPair>('/auth/token', { method: 'POST', body: form }, 'Login failed')
}

export async function logout(): Promise<void> {
  const presented = refreshToken
  clearAuthToken()
  if (presented) {
    await fetch(`${API_BASE}/auth/logout`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: presented }),
    }).catch(() => undefined)
  }
}

export const logoutEverywhere = () => request<void>('/auth/logout-all', { method: 'POST' }, 'Failed to sign out other devices')

export const getSetupStatus = () =>
  request<{ setup_required: boolean; bootstrap_enabled: boolean }>('/auth/setup-status', {}, 'Failed to check setup status')

export const bootstrapAdmin = (input: { username: string; password: string; bootstrap_token: string }) =>
  request<void>('/auth/bootstrap', json(input), 'Failed to create the admin account')

export const changePassword = (input: { username: string; current_password: string; new_password: string }) =>
  request<void>('/auth/change-password', json(input), 'Failed to change password')

export const me = () => request<UserProfile>('/auth/me', {}, 'Not authenticated')
export const listUsers = () => request<UserAdmin[]>('/auth/users', {}, 'Failed to list users')
export const createUser = (input: {
  username: string
  password: string
  roles: string[]
  display_name?: string | null
  email?: string | null
}) => request<UserAdmin>('/auth/users', json(input), 'Failed to create user')
export const updateUser = (
  userId: number,
  input: { roles?: string[]; password?: string; is_active?: boolean; display_name?: string; email?: string },
) => request<UserAdmin>(`/auth/users/${userId}`, put(input), 'Failed to update user')
export const deleteUser = (userId: number) =>
  request<void>(`/auth/users/${userId}`, { method: 'DELETE' }, 'Failed to delete user')

export const listApiTokens = () => request<ApiToken[]>('/auth/api-tokens', {}, 'Failed to list API tokens')
export const createApiToken = (name: string, expires_days?: number | null) =>
  request<ApiToken>('/auth/api-tokens', json({ name, expires_days: expires_days || null }), 'Failed to create API token')
export const revokeApiToken = (tokenId: string) =>
  request<void>(`/auth/api-tokens/${tokenId}`, { method: 'DELETE' }, 'Failed to revoke API token')

// ---------------------------------------------------------------- targets

export const listTargets = (params: { tag?: string; lab?: string } = {}) =>
  request<Target[]>(withQuery('/targets', params), {}, 'Failed to list targets')
export const listTags = () => request<string[]>('/targets/tags', {}, 'Failed to list tags')
export const getTarget = (targetId: string) => request<Target>(`/targets/${targetId}`, {}, 'Failed to load target details')
export const createTarget = (input: TargetCreateInput) => request<Target>('/targets', json(input), 'Failed to create target')
export const updateTarget = (targetId: string, input: TargetUpdateInput) =>
  request<Target>(`/targets/${targetId}`, put(input), 'Failed to update target')
export const deleteTarget = (targetId: string) =>
  request<void>(`/targets/${targetId}`, { method: 'DELETE' }, 'Failed to delete target')

export const listCapabilities = (targetId: string) =>
  request<TargetCapability[]>(`/targets/${targetId}/capabilities`, {}, 'Failed to list target capabilities')
export const createCapability = (targetId: string, input: TargetCapabilityCreateInput) =>
  request<TargetCapability>(`/targets/${targetId}/capabilities`, json(input), 'Failed to create target capability')
export const updateCapability = (targetId: string, capabilityId: string, input: TargetCapabilityUpdateInput) =>
  request<TargetCapability>(`/targets/${targetId}/capabilities/${capabilityId}`, put(input), 'Failed to update target capability')
export const deleteCapability = (targetId: string, capabilityId: string) =>
  request<void>(`/targets/${targetId}/capabilities/${capabilityId}`, { method: 'DELETE' }, 'Failed to delete target capability')

export const listLabs = () => request<string[]>('/labs', {}, 'Failed to list labs')

// ---------------------------------------------------------------- reservations

export const listReservations = (params: { target_id?: string; user_id?: string; status?: string } = {}) =>
  request<Reservation[]>(withQuery('/reservations', params), {}, 'Failed to list reservations')

export const reservationCalendar = (params: { from?: string; to?: string; target_id?: string } = {}) =>
  request<Reservation[]>(withQuery('/reservations/calendar', params), {}, 'Failed to load the calendar')

export const createReservation = (input: { target_id: string; starts_at: string; ends_at: string; note?: string | null }) =>
  request<Reservation>('/reservations', json(input), 'Failed to create reservation')

export const reserveAny = (input: { tag: string; duration_minutes: number; starts_at?: string; note?: string | null }) =>
  request<Reservation>('/reservations/any', json(input), 'Failed to reserve a target')

export const extendReservation = (reservationId: string, extend_minutes: number) =>
  request<Reservation>(`/reservations/${reservationId}/extend`, json({ extend_minutes }), 'Failed to extend reservation')

export const releaseReservation = (reservationId: string) =>
  request<Reservation>(`/reservations/${reservationId}/release`, { method: 'POST' }, 'Failed to release reservation')

export const forceReleaseReservation = (reservationId: string) =>
  request<Reservation>(`/reservations/${reservationId}/force-release`, { method: 'POST' }, 'Failed to force release reservation')

export const listWaitlist = (params: { target_id?: string } = {}) =>
  request<WaitlistEntry[]>(withQuery('/waitlist', params), {}, 'Failed to load the waitlist')
export const joinWaitlist = (input: { target_id?: string; tag?: string; duration_minutes: number; note?: string | null }) =>
  request<WaitlistEntry>('/waitlist', json(input), 'Failed to join the waitlist')
export const leaveWaitlist = (entryId: string) =>
  request<WaitlistEntry>(`/waitlist/${entryId}`, { method: 'DELETE' }, 'Failed to leave the waitlist')

export const listNotifications = (unread = false) =>
  request<AppNotification[]>(withQuery('/notifications', { unread: unread || undefined }), {}, 'Failed to load notifications')
export const markNotificationsRead = (id?: string) =>
  request<{ updated: number }>(withQuery('/notifications/read', { id }), { method: 'POST' }, 'Failed to update notifications')

export const getPolicy = () => request<ReservationPolicy>('/settings/policy', {}, 'Failed to load the reservation policy')
export const updatePolicy = (policy: ReservationPolicy) =>
  request<ReservationPolicy>('/settings/policy', put(policy), 'Failed to save the reservation policy')
export const getWebhooks = () =>
  request<{ webhooks: Webhook[]; events: string[] }>('/settings/webhooks', {}, 'Failed to load webhooks')
export const saveWebhooks = (webhooks: Webhook[]) =>
  request<{ webhooks: Webhook[]; events: string[] }>('/settings/webhooks', put({ webhooks }), 'Failed to save webhooks')
export const testWebhook = (id: string) =>
  request<{ delivered: boolean }>(`/settings/webhooks/${id}/test`, { method: 'POST' }, 'Webhook test failed')

// ---------------------------------------------------------------- sessions

export const listSessions = (params: { user_id?: string; target_id?: string } = {}) =>
  request<Session[]>(withQuery('/sessions', params), {}, 'Failed to list sessions')

export const createSession = (reservation_id: string, capability_type: string, capability_id?: string) =>
  request<Session>('/sessions', json({ reservation_id, capability_type, capability_id }), 'Failed to create session')

export const getSession = (sessionId: string) => request<Session>(`/sessions/${sessionId}`, {}, 'Failed to load session')

export const closeSession = (sessionId: string) =>
  request<Session>(`/sessions/${sessionId}/close`, { method: 'POST' }, 'Failed to close session')

export const listSessionOperations = (sessionId: string) =>
  request<SessionOperationList>(`/sessions/${sessionId}/operations`, {}, 'Failed to load session operations')

export const executeSessionOperation = (sessionId: string, operation: string, params: Record<string, unknown> = {}) =>
  request<ProviderResult>(`/sessions/${sessionId}/execute`, json({ operation, params }), `Failed to execute '${operation}'`)

/** Queue a long-running Agent operation (deploy) and return immediately with its id. */
export const submitSessionOperation = (sessionId: string, operation: string, params: Record<string, unknown> = {}) =>
  request<ProviderResult>(`/sessions/${sessionId}/execute?wait=false`, json({ operation, params }), `Failed to queue '${operation}'`)

export const getOperationStatus = (sessionId: string, operationId: string) =>
  request<OperationStatus>(`/sessions/${sessionId}/operations/${operationId}`, {}, 'Failed to load operation status')

export const serialRead = (sessionId: string, size = 4096) =>
  request<ProviderResult>(`/sessions/${sessionId}/serial/read?size=${size}`, {}, 'Failed to read from serial session')

export const serialWrite = (sessionId: string, text: string) =>
  request<ProviderResult>(`/sessions/${sessionId}/serial/write`, json({ text }), 'Failed to write to serial session')

export const serialLog = (sessionId: string, includeInput = false) =>
  request<string>(withQuery(`/sessions/${sessionId}/serial/log`, { include_input: includeInput || undefined }), {}, 'Failed to download the console log')

/** WebSocket URL for the interactive serial console (token is sent as the first frame). */
export function serialSocketUrl(sessionId: string): string {
  const base = API_BASE.startsWith('http') ? API_BASE : `${window.location.origin}${API_BASE}`
  return `${base.replace(/^http/, 'ws')}/sessions/${sessionId}/serial/ws`
}

// ---------------------------------------------------------------- agents

export const listAgents = () => request<Agent[]>('/agents', {}, 'Failed to list agents')
export const listAgentEnrollments = () => request<AgentEnrollment[]>('/agents/enrollments', {}, 'Failed to list enrollments')
export const createAgentEnrollment = (agent_name: string) =>
  request<AgentEnrollment>('/agents/enrollments', json({ agent_name }), 'Failed to create enrollment')
export const disableAgent = (agentId: string) => request<Agent>(`/agents/${agentId}/disable`, { method: 'POST' }, 'Failed to disable agent')
export const enableAgent = (agentId: string) => request<Agent>(`/agents/${agentId}/enable`, { method: 'POST' }, 'Failed to enable agent')
export const revokeAgentCredential = (agentId: string) =>
  request<Agent>(`/agents/${agentId}/revoke-credential`, { method: 'POST' }, 'Failed to revoke agent credential')

export const listAuditEntries = (
  params: { user_id?: string; target_id?: string; session_id?: string; action?: string; limit?: number } = {},
) => request<AuditEntry[]>(withQuery('/audit', params), {}, 'Failed to list audit entries')
