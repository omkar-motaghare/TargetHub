export type UserRole = 'admin' | 'user' | 'viewer'
export const ROLES: UserRole[] = ['admin', 'user', 'viewer']

export type UserProfile = {
  id: number
  username: string
  roles: string[]
  display_name?: string | null
  email?: string | null
  is_active?: boolean
  last_login_at?: string | null
  created_at: string | null
}

export type UserAdmin = UserProfile

export type TokenPair = {
  access_token: string
  refresh_token?: string | null
  token_type: string
  expires_in?: number | null
}

export type ApiToken = {
  id: string
  name: string
  prefix: string
  created_at: string
  expires_at: string | null
  last_used_at: string | null
  revoked_at: string | null
  token?: string
}

export type CapabilityType =
  | 'serial'
  | 'network'
  | 'ssh'
  | 'telnet'
  | 'ftp'
  | 'jlink'
  | 'power'
  | 'reset'
  | 'deploy'

export type CapabilityHosting = 'agent' | 'server'

export type TargetCapability = {
  id: string
  target_id: string
  name: string
  capability_type: CapabilityType
  enabled: boolean
  hosting: CapabilityHosting
  /** agent | dd | http | simulated | serial | unconfigured | invalid */
  mode: string
  // Admin-only fields
  agent_id?: string | null
  resource_id?: string | null
  provider_key?: string | null
  provider_config?: Record<string, unknown>
  created_at: string
  updated_at: string
}

export type TargetState = 'available' | 'reserved' | 'maintenance' | 'retired' | 'disabled'

export type Availability = {
  state: TargetState
  reason: string | null
  reserved_by: string | null
  reserved_until: string | null
  next_reservation_at: string | null
  next_reserved_by: string | null
}

export type Target = {
  id: string
  name: string
  description: string | null
  vendor: string | null
  board_model: string | null
  serial_number: string | null
  lab_name: string | null
  location: string | null
  status: 'available' | 'maintenance' | 'retired'
  status_reason: string | null
  tags: string[]
  enabled: boolean
  capabilities: TargetCapability[]
  availability?: Availability | null
  created_at: string
  updated_at: string
}

export type Reservation = {
  id: string
  target_id: string
  user_id: string
  starts_at: string
  ends_at: string
  status: string
  note?: string | null
  released_at: string | null
  released_by?: string | null
  created_at: string
  updated_at: string
}

export type WaitlistEntry = {
  id: string
  user_id: string
  target_id: string | null
  tag: string | null
  duration_minutes: number
  note: string | null
  status: string
  reservation_id: string | null
  created_at: string
  expires_at: string | null
  fulfilled_at: string | null
  position: number
}

export type AppNotification = {
  id: string
  kind: string
  message: string
  target_id: string | null
  reservation_id: string | null
  created_at: string
  read_at: string | null
}

export type ReservationPolicy = {
  max_duration_minutes: number
  max_advance_days: number
  max_active_reservations_per_user: number
  default_duration_minutes: number
  expiry_warning_minutes: number
  allow_extend_when_waitlisted: boolean
  waitlist_entry_ttl_hours: number
  transcript_retention_days: number
  audit_retention_days: number
}

export type Webhook = {
  id?: string
  name: string
  url: string
  format: 'slack' | 'teams' | 'generic'
  events: string[]
  enabled: boolean
  secret?: string | null
}

export type Session = {
  id: string
  reservation_id: string
  target_id: string
  user_id: string
  capability_type: CapabilityType
  provider_key?: string | null
  capability_id: string | null
  agent_id?: string | null
  resource_id?: string | null
  status: string
  expires_at: string
  ended_at: string | null
  created_at: string
  updated_at: string
}

export type AgentResource = {
  id: string
  agent_id: string
  resource_key: string
  resource_type: string
  display_name: string
  metadata: Record<string, unknown>
  available: boolean
  created_at: string
  updated_at: string
}

export type Agent = {
  id: string
  name: string
  hostname: string | null
  status: string
  enabled: boolean
  last_seen_at: string | null
  agent_version?: string | null
  platform?: string | null
  credential_prefix: string | null
  credential_created_at: string | null
  credential_revoked_at: string | null
  resources: AgentResource[]
}

export type AgentEnrollment = {
  id: string
  agent_name: string
  expires_at: string
  used_at: string | null
  agent_id: string | null
  created_at: string
  token: string | null
  targethub_url: string | null
  install_command: string | null
  install_command_windows?: string | null
}

export type AuditEntry = {
  id: string
  user_id: string | null
  action: string
  target_id: string | null
  session_id: string | null
  provider_key: string | null
  capability_type: string | null
  operation: string | null
  success: boolean
  detail: string | null
  created_at: string
}

export type SessionOperationList = {
  session_id: string
  capability_type: CapabilityType
  operations: string[]
}

export type ProviderResult = {
  session_id: string
  capability_type: CapabilityType
  operation: string
  message: string
  data: Record<string, unknown> | null
  operation_id?: string
  status?: string
}

export type OperationStatus = {
  operation_id: string
  operation: string
  status: 'pending' | 'in_progress' | 'completed' | 'failed' | 'cancelled' | 'timed_out'
  message: string | null
  data: Record<string, unknown> | null
  requested_at: string
  completed_at: string | null
}

export type TargetCreateInput = {
  name: string
  description?: string | null
  vendor?: string | null
  board_model?: string | null
  serial_number?: string | null
  lab_name?: string | null
  location?: string | null
  enabled?: boolean
  status?: Target['status']
  status_reason?: string | null
  tags?: string[]
  capabilities?: TargetCapabilityCreateInput[]
}

export type TargetUpdateInput = Partial<TargetCreateInput>

export type TargetCapabilityCreateInput = {
  name: string
  capability_type: CapabilityType
  agent_id?: string | null
  resource_id?: string | null
  provider_key?: string | null
  provider_config?: Record<string, unknown>
  enabled?: boolean
}

export type TargetCapabilityUpdateInput = Partial<TargetCapabilityCreateInput>

export type SystemIssue = {
  severity: 'error' | 'warning'
  message: string
  target_id: string | null
  target_name: string | null
}

export type SystemOverview = {
  version: string
  environment: string
  database: string
  public_url: string
  simulation_enabled: boolean
  scheduler_enabled: boolean
  targets: { total: number } & Record<string, number>
  reservations_active: number
  sessions_active: number
  waitlist_waiting: number
  users: { total: number; active: number }
  agents: { total: number; online: number; disabled: number }
  issues: SystemIssue[]
}

export type PowerCheckResult = {
  success: boolean
  message: string
  data: Record<string, unknown> | null
}
