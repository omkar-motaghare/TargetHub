import React, {useEffect, useState} from 'react'
import { closeSession, listSessions } from '../services/api'
import { useAuth } from '../services/auth'

export default function Sessions(){
  const auth = useAuth()
  const [sessions, setSessions] = useState<any[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(()=>{ refresh() },[])

  async function refresh(){
    setLoading(true)
    try{
      setSessions(await listSessions())
    }catch(err:any){
      alert(err.message)
    }finally{
      setLoading(false)
    }
  }

  async function handleClose(sessionId:string){
    try{
      await closeSession(sessionId, auth.user.username)
      await refresh()
    }catch(err:any){
      alert(err.message)
    }
  }

  const mine = sessions.filter((s:any)=>s.user_id===auth.user.username)

  return (
    <div>
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center'}}>
        <h2>My Sessions</h2>
        <button className="button" onClick={()=>refresh()} disabled={loading}>{loading ? 'Refreshing...' : 'Refresh'}</button>
      </div>
      <div className="list">
        {mine.length===0 && <div className="card">No sessions yet. Open one from My Reservations.</div>}
        {mine.map((s:any)=> (
          <div key={s.id} className="list-item">
            <div>
              <div style={{fontWeight:600}}>{s.capability_type} on target {s.target_id}</div>
              <div style={{fontSize:12,color:'#6b7280'}}>Status: {s.status} | Expires: {new Date(s.expires_at).toLocaleString()}</div>
              {s.provider_key && <div style={{fontSize:12,color:'#6b7280'}}>Provider: {s.provider_key}</div>}
            </div>
            <div>
              {s.status === 'active' && <button className="button secondary" onClick={()=>handleClose(s.id)}>Close Session</button>}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
