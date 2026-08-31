const API_BASE = (import.meta.env.VITE_API_URL as string) || '/api/v1'

function authHeaders(){
  const token = localStorage.getItem('th_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function readError(res: Response, fallback: string){
  const text = await res.text()
  try{
    const parsed = JSON.parse(text)
    if(parsed?.detail) return String(parsed.detail)
  }catch{
    // Keep fallback when response is not JSON.
  }
  return text || fallback
}

export async function login(username:string, password:string){
  const body = new URLSearchParams()
  body.set('username', username)
  body.set('password', password)
  body.set('grant_type', '')
  const res = await fetch(`${API_BASE}/auth/token`, { method: 'POST', body })
  if(!res.ok) throw new Error(await readError(res, 'Login failed'))
  const data = await res.json()
  return data.access_token
}

export async function me(){
  const res = await fetch(`${API_BASE}/auth/me`, { headers: { ...authHeaders(), 'Content-Type':'application/json' } })
  if(!res.ok) throw new Error(await readError(res, 'Not authenticated'))
  return res.json()
}

export async function listTargets(){
  const res = await fetch(`${API_BASE}/targets`, { headers: { ...authHeaders(), 'Content-Type':'application/json' } })
  if(!res.ok) throw new Error(await readError(res, 'Failed to list targets'))
  return res.json()
}

export async function listReservations(params: { target_id?:string; user_id?:string } = {}){
  const qs = new URLSearchParams()
  if(params.target_id) qs.set('target_id', params.target_id)
  if(params.user_id) qs.set('user_id', params.user_id)
  const res = await fetch(`${API_BASE}/reservations?${qs.toString()}`, { headers: authHeaders() })
  if(!res.ok) throw new Error(await readError(res, 'Failed to list reservations'))
  return res.json()
}

export async function createReservation(target_id:string, user_id:string, starts_at: string, ends_at: string){
  const body = { target_id, user_id, starts_at, ends_at }
  const res = await fetch(`${API_BASE}/reservations`, { method:'POST', headers: { ...authHeaders(), 'Content-Type':'application/json' }, body: JSON.stringify(body) })
  if(!res.ok) throw new Error(await readError(res, 'Failed to create reservation'))
  return res.json()
}

export async function releaseReservation(reservation_id:string, user_id:string){
  const res = await fetch(`${API_BASE}/reservations/${reservation_id}/release?user_id=${encodeURIComponent(user_id)}`, { method:'POST', headers: authHeaders() })
  if(!res.ok) throw new Error(await readError(res, 'Failed to release'))
  return res.json()
}

export async function listAgents(){
  const res = await fetch(`${API_BASE}/agents`, { headers: authHeaders() })
  if(!res.ok) throw new Error(await readError(res, 'Failed to list agents'))
  return res.json()
}

export async function createAgentEnrollment(agent_name:string){
  const res = await fetch(`${API_BASE}/agents/enrollments`, { method:'POST', headers: { ...authHeaders(), 'Content-Type':'application/json' }, body: JSON.stringify({ agent_name }) })
  if(!res.ok) throw new Error(await readError(res, 'Failed to create enrollment'))
  return res.json()
}

export async function disableAgent(agent_id:string){
  const res = await fetch(`${API_BASE}/agents/${agent_id}/disable`, { method:'POST', headers: authHeaders() })
  if(!res.ok) throw new Error(await readError(res, 'Failed to disable agent'))
  return res.json()
}

export async function enableAgent(agent_id:string){
  const res = await fetch(`${API_BASE}/agents/${agent_id}/enable`, { method:'POST', headers: authHeaders() })
  if(!res.ok) throw new Error(await readError(res, 'Failed to enable agent'))
  return res.json()
}

export async function revokeAgentCredential(agent_id:string){
  const res = await fetch(`${API_BASE}/agents/${agent_id}/revoke-credential`, { method:'POST', headers: authHeaders() })
  if(!res.ok) throw new Error(await readError(res, 'Failed to revoke credential'))
  return res.json()
}

export async function forceReleaseReservation(reservation_id:string){
  const res = await fetch(`${API_BASE}/reservations/${reservation_id}/force-release`, { method:'POST', headers: authHeaders() })
  if(!res.ok) throw new Error(await readError(res, 'Failed to force release'))
  return res.json()
}

export async function listSessions(params: { user_id?:string; target_id?:string } = {}){
  const qs = new URLSearchParams()
  if(params.user_id) qs.set('user_id', params.user_id)
  if(params.target_id) qs.set('target_id', params.target_id)
  const res = await fetch(`${API_BASE}/sessions?${qs.toString()}`, { headers: authHeaders() })
  if(!res.ok) throw new Error(await readError(res, 'Failed to list sessions'))
  return res.json()
}

export async function createSession(reservation_id:string, user_id:string, capability_type:string){
  const body = { reservation_id, user_id, capability_type }
  const res = await fetch(`${API_BASE}/sessions`, {
    method:'POST',
    headers: { ...authHeaders(), 'Content-Type':'application/json' },
    body: JSON.stringify(body),
  })
  if(!res.ok) throw new Error(await readError(res, 'Failed to create session'))
  return res.json()
}

export async function closeSession(session_id:string, user_id:string){
  const res = await fetch(`${API_BASE}/sessions/${session_id}/close?user_id=${encodeURIComponent(user_id)}`, {
    method:'POST',
    headers: authHeaders(),
  })
  if(!res.ok) throw new Error(await readError(res, 'Failed to close session'))
  return res.json()
}

export default {
  login,
  me,
  listTargets,
  listReservations,
  createReservation,
  releaseReservation,
  forceReleaseReservation,
  listSessions,
  createSession,
  closeSession,
  listAgents,
  createAgentEnrollment,
  disableAgent,
  enableAgent,
  revokeAgentCredential,
}
