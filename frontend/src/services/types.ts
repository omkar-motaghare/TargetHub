export type UserRole = 'admin' | 'user'

export type UserProfile = {
  id: number
  username: string
  roles: string[]
  created_at: string
}

export type UserAdmin = {
  id: number
  username: string
  roles: string[]
  created_at: string
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

export type TargetCapability = {
  id: string
  target_id: string
  name: string
  capability_type: CapabilityType
  agent_id: string | null
  resource_id: string | null
  provider_key: string | null
  provider_config: Record<string, unknown>
  enabled: boolean
  created_at: string
  updated_at: string
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
  status: string
  enabled: boolean
  capabilities: TargetCapability[]
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
  released_at: string | null
  created_at: string
  updated_at: string
}

export type Session = {
  id: string
  reservation_id: string
  target_id: string
  user_id: string
  capability_type: CapabilityType
  provider_key: string | null
  capability_id: string | null
  agent_id: string | null
  resource_id: string | null
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

export type SessionOperationList = string[]

export type ProviderResult = {
  success: boolean
  message: string
  data?: Record<string, unknown>
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
  status?: string
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