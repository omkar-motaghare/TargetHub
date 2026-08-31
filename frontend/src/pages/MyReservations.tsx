import React, {useEffect, useState} from 'react'
import { listReservations, listTargets, releaseReservation } from '../services/api'
import { useAuth } from '../services/auth'

export default function MyReservations(){
  const [reservations,setReservations] = useState<any[]>([])
  const [targets,setTargets] = useState<any[]>([])
  const auth = useAuth()
  useEffect(()=>{ refresh() },[])
  async function refresh(){ setReservations(await listReservations()); setTargets(await listTargets()) }
  async function handleRelease(id:string){ try{ const r = reservations.find((x:any)=>x.target_id===id && x.user_id===auth.user.username); if(!r) throw new Error('No reservation'); await releaseReservation(r.id, auth.user.username); await refresh() }catch(err:any){ alert(err.message) } }

  return (
    <div>
      <h2>My Reservations</h2>
      <div className="list">
        {reservations.filter((r:any)=>r.user_id===auth.user.username).map((r:any)=>{
          const t = targets.find((tt:any)=>tt.id===r.target_id)
          return (
            <div key={r.id} className="list-item">
              <div>
                <div style={{fontWeight:600}}>{t?.name || r.target_id}</div>
                <div style={{fontSize:12,color:'#6b7280'}}>Started: {new Date(r.starts_at).toLocaleString()}</div>
              </div>
              <div>
                <button className="button secondary" onClick={()=>handleRelease(r.target_id)}>Release</button>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
