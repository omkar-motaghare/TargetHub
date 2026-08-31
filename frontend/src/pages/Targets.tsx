import React, {useEffect, useState} from 'react'
import { listTargets, listReservations, createReservation } from '../services/api'
import { useAuth } from '../services/auth'

export default function Targets(){
  const [targets, setTargets] = useState<any[]>([])
  const [reservations, setReservations] = useState<any[]>([])
  const [reservingTarget, setReservingTarget] = useState<string | null>(null)
  const [startsAt, setStartsAt] = useState<string>('')
  const [endsAt, setEndsAt] = useState<string>('')
  const auth = useAuth()

  useEffect(()=>{ refresh() },[])
  async function refresh(){
    const t = await listTargets()
    const r = await listReservations()
    setTargets(t); setReservations(r)
  }

  function reservedBy(targetId:string){
    return reservations.find((r:any)=>r.target_id===targetId || r.targetId===targetId)
  }

  async function handleReserve(id:string){
    try{
      if(!startsAt || !endsAt){ alert('Please choose start and end time'); return }
      // convert local datetime-local to ISO with timezone
      const starts = new Date(startsAt).toISOString()
      const ends = new Date(endsAt).toISOString()
      await createReservation(id, auth.user.username, starts, ends)
      setReservingTarget(null)
      await refresh()
    }catch(err:any){ alert(err.message) }
  }
  async function handleRelease(id:string){
    try{
      // find reservation id for this target owned by user
      const r = reservations.find((x:any)=>x.target_id===id && x.user_id===auth.user.username)
      if(!r) throw new Error('No reservation found')
      await fetch(`/api/v1/reservations/${r.id}/release?user_id=${encodeURIComponent(auth.user.username)}`, { method:'POST', headers: { Authorization: `Bearer ${localStorage.getItem('th_token')}` } })
      await refresh()
    }catch(err:any){ alert(err.message) }
  }

  return (
    <div>
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center'}}>
        <h2>Targets</h2>
        <button className="button" onClick={()=>refresh()}>Refresh</button>
      </div>
      <div className="list">
        {targets.map(t=>{
          const r = reservedBy(t.id)
          const status = !t.enabled ? 'disabled' : r ? 'reserved' : 'available'
          return (
            <div key={t.id} className="list-item">
              <div>
                <div style={{fontWeight:600}}>{t.name}</div>
                <div style={{fontSize:12,color:'#6b7280'}}>{t.tags?.join(', ')}</div>
              </div>
              <div style={{display:'flex',gap:8,alignItems:'center'}}>
                <div className={`badge ${status}`}>{status}</div>
                {t.enabled && !r && <button className="button" onClick={()=>{ setReservingTarget(t.id); const now = new Date(); setStartsAt(new Date(now.getTime()).toISOString().slice(0,16)); setEndsAt(new Date(now.getTime()+30*60*1000).toISOString().slice(0,16)) }}>Reserve</button>}
                {r && (r.user_id===auth.user.username || r.user===auth.user.username) && <button className="button secondary" onClick={()=>handleRelease(t.id)}>Release</button>}
                {r && !(r.user_id===auth.user.username || r.user===auth.user.username) && <div style={{fontSize:12}}>Reserved by {r.user_id || r.user}</div>}
              </div>
            </div>
          )
        })}
      </div>
      {reservingTarget && (
        <div className="card" style={{marginTop:12}}>
          <h3>Reserve target</h3>
          <div style={{display:'flex',gap:8,alignItems:'center'}}>
            <input className="input" type="datetime-local" value={startsAt} onChange={e=>setStartsAt(e.target.value)} />
            <input className="input" type="datetime-local" value={endsAt} onChange={e=>setEndsAt(e.target.value)} />
            <button className="button" onClick={()=>handleReserve(reservingTarget)}>Confirm</button>
            <button className="button secondary" onClick={()=>setReservingTarget(null)}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  )
}
