import React, {useEffect, useState} from 'react'
import { listTargets, listReservations, forceReleaseReservation } from '../../services/api'

export default function AdminTargets(){
  const [targets,setTargets] = useState<any[]>([])
  const [reservations,setReservations] = useState<any[]>([])
  useEffect(()=>{ refresh() },[])
  async function refresh(){ setTargets(await listTargets()); setReservations(await listReservations()) }
  async function handleForceRelease(targetId:string){
    if(!confirm('Force release?')) return
    // find reservation id for the target
    const r = reservations.find((x:any)=>x.target_id===targetId)
    if(!r){ alert('No active reservation'); return }
    try{ await forceReleaseReservation(r.id); await refresh() }catch(err:any){ alert(err.message) }
  }
  return (
    <div>
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center'}}>
        <h3>Targets</h3>
        <button className="button" onClick={()=>refresh()}>Refresh</button>
      </div>
      <div className="list">
        {targets.map(t=>{
          const r = reservations.find((rr:any)=>rr.target_id===t.id || rr.targetId===t.id)
          const status = !t.enabled ? 'disabled' : r ? 'reserved' : 'available'
          return (
            <div key={t.id} className="list-item">
              <div>
                <div style={{fontWeight:600}}>{t.name}</div>
                <div style={{fontSize:12,color:'#6b7280'}}>{t.tags?.join(', ')}</div>
              </div>
              <div style={{display:'flex',gap:8,alignItems:'center'}}>
                <div className={`badge ${status}`}>{status}</div>
                {r && <div style={{fontSize:12}}>Reserved by {r.user_id || r.user}</div>}
                {r && <button className="button secondary" onClick={()=>handleForceRelease(t.id)}>Force Release</button>}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
