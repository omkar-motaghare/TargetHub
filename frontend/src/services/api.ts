const API_BASE = (import.meta.env.VITE_API_URL as string) || '/api/v1'

function authHeaders(){
  const token = localStorage.getItem('th_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export async function login(username:string, password:string){
  const body = new URLSearchParams()
  body.set('username', username)
  body.set('password', password)
  body.set('grant_type', '')
  const res = await fetch(`${API_BASE}/auth/token`, { method: 'POST', body })
  if(!res.ok) throw new Error('Login failed')
  const data = await res.json()
  return data.access_token
}

export async function me(){
  const res = await fetch(`${API_BASE}/auth/me`, { headers: { ...authHeaders(), 'Content-Type':'application/json' } })
  if(!res.ok) throw new Error('Not authenticated')
  return res.json()
}

export async function listTargets(){
  const res = await fetch(`${API_BASE}/targets`, { headers: { ...authHeaders(), 'Content-Type':'application/json' } })
  if(!res.ok) throw new Error('Failed to list targets')
  return res.json()
}

export async function listReservations(params: { target_id?:string; user_id?:string } = {}){
  const qs = new URLSearchParams()
  if(params.target_id) qs.set('target_id', params.target_id)
  if(params.user_id) qs.set('user_id', params.user_id)
  const res = await fetch(`${API_BASE}/reservations?${qs.toString()}`, { headers: authHeaders() })
  if(!res.ok) throw new Error('Failed to list reservations')
  return res.json()
}

export async function createReservation(target_id:string, user_id:string, starts_at: string, ends_at: string){
  const body = { target_id, user_id, starts_at, ends_at }
  const res = await fetch(`${API_BASE}/reservations`, { method:'POST', headers: { ...authHeaders(), 'Content-Type':'application/json' }, body: JSON.stringify(body) })
  if(!res.ok){ const txt = await res.text(); throw new Error(txt||'Failed to create reservation') }
  return res.json()
}

export async function releaseReservation(reservation_id:string, user_id:string){
  const res = await fetch(`${API_BASE}/reservations/${reservation_id}/release?user_id=${encodeURIComponent(user_id)}`, { method:'POST', headers: authHeaders() })
  if(!res.ok) throw new Error('Failed to release')
  return res.json()
}

export async function listAgents(){
  const res = await fetch(`${API_BASE}/agents`, { headers: authHeaders() })
  if(!res.ok) throw new Error('Failed to list agents')
  return res.json()
}

export async function createAgentEnrollment(agent_name:string){
  const res = await fetch(`${API_BASE}/agents/enrollments`, { method:'POST', headers: { ...authHeaders(), 'Content-Type':'application/json' }, body: JSON.stringify({ agent_name }) })
  if(!res.ok) throw new Error('Failed to create enrollment')
  return res.json()
}

export async function forceReleaseReservation(reservation_id:string){
  const res = await fetch(`${API_BASE}/reservations/${reservation_id}/force-release`, { method:'POST', headers: authHeaders() })
  if(!res.ok) throw new Error('Failed to force release')
  return res.json()
}

export default { login, listTargets, listReservations, createReservation, releaseReservation, listAgents, createAgentEnrollment }
