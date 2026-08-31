// Simple in-memory mock API for targets, agents and reservations

export type Target = { id:string; name:string; tags?:string[]; enabled?:boolean }
export type Reservation = { id:string; targetId:string; user:string; startedAt:string }

const targetsKey = 'th_targets_v1'
const reservationsKey = 'th_reservations_v1'

function getTargets(): Target[]{
  const raw = localStorage.getItem(targetsKey)
  if(raw) return JSON.parse(raw)
  const sample = [
    {id:'t1', name:'Raspberry Pi 5', tags:['linux','arm'], enabled:true},
    {id:'t2', name:'Intel NUC', tags:['linux','x86'], enabled:true},
    {id:'t3', name:'Disabled Target', tags:[], enabled:false}
  ]
  localStorage.setItem(targetsKey, JSON.stringify(sample))
  return sample
}

function saveTargets(ts:Target[]){ localStorage.setItem(targetsKey, JSON.stringify(ts)) }

export function listTargets(): Promise<Target[]>{
  return Promise.resolve(getTargets())
}

export function reserveTarget(targetId:string, user:string): Promise<Reservation>{
  const reservations:Reservation[] = JSON.parse(localStorage.getItem(reservationsKey)||'[]')
  if(reservations.find(r=>r.targetId===targetId)) return Promise.reject(new Error('Already reserved'))
  const r:Reservation = {id:Date.now().toString(), targetId, user, startedAt:new Date().toISOString()}
  reservations.push(r)
  localStorage.setItem(reservationsKey, JSON.stringify(reservations))
  return Promise.resolve(r)
}

export function releaseTarget(targetId:string, user:string): Promise<void>{
  let reservations:Reservation[] = JSON.parse(localStorage.getItem(reservationsKey)||'[]')
  const idx = reservations.findIndex(r=>r.targetId===targetId && r.user===user)
  if(idx===-1) return Promise.reject(new Error('No active reservation by you'))
  reservations.splice(idx,1)
  localStorage.setItem(reservationsKey, JSON.stringify(reservations))
  return Promise.resolve()
}

export function listReservations(): Promise<Reservation[]>{
  return Promise.resolve(JSON.parse(localStorage.getItem(reservationsKey)||'[]'))
}

export function forceRelease(targetId:string): Promise<void>{
  let reservations:Reservation[] = JSON.parse(localStorage.getItem(reservationsKey)||'[]')
  reservations = reservations.filter(r=>r.targetId!==targetId)
  localStorage.setItem(reservationsKey, JSON.stringify(reservations))
  return Promise.resolve()
}
