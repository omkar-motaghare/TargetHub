import React, { useEffect, useState } from 'react'
import {
  createAgentEnrollment,
  disableAgent,
  enableAgent,
  listAgents,
  revokeAgentCredential,
} from '../../services/api'

export default function AdminAgents(){
  const [name,setName] = useState('')
  const [agents,setAgents] = useState<any[]>([])
  const [enrollment, setEnrollment] = useState<any | null>(null)

  useEffect(()=>{ load() },[])
  async function load(){ try{ setAgents(await listAgents()) }catch(e){ console.error(e) } }

  async function handleCreate(e:React.FormEvent){
    e.preventDefault()
    try{
      const res = await createAgentEnrollment(name)
      setEnrollment(res)
      setName('')
      await load()
    }catch(err:any){ alert(err.message) }
  }

  async function handleDisable(agentId: string){
    try{
      await disableAgent(agentId)
      await load()
    }catch(err:any){
      alert(err.message)
    }
  }

  async function handleEnable(agentId: string){
    try{
      await enableAgent(agentId)
      await load()
    }catch(err:any){
      alert(err.message)
    }
  }

  async function handleRevoke(agentId: string){
    if(!confirm('Revoke current agent credential?')) return
    try{
      await revokeAgentCredential(agentId)
      await load()
    }catch(err:any){
      alert(err.message)
    }
  }

  return (
    <div>
      <h3>Agents</h3>
      <div className="card" style={{marginBottom:12}}>
        <form onSubmit={handleCreate}>
          <div className="form-row">
            <input className="input" placeholder="Agent name" value={name} onChange={e=>setName(e.target.value)} />
          </div>
          <div>
            <button className="button" type="submit">Create Enrollment</button>
          </div>
        </form>
      </div>
      {enrollment && (
        <div className="card" style={{marginBottom:12}}>
          <div><strong>Enrollment token:</strong> {enrollment.token}</div>
          <div style={{marginTop:8}}><strong>Install command:</strong></div>
          <pre style={{whiteSpace:'pre-wrap'}}>{enrollment.install_command}</pre>
        </div>
      )}
      <div className="list">
        {agents.map((a:any)=> (
          <div key={a.id} className="list-item">
            <div>
              <div style={{fontWeight:600}}>{a.name}</div>
              <div style={{fontSize:12,color:'#6b7280'}}>
                {a.hostname || '—'} | Status: {a.status} | Enabled: {a.enabled ? 'yes' : 'no'}
              </div>
            </div>
            <div style={{display:'flex',gap:8}}>
              {a.enabled ? (
                <button className="button secondary" onClick={()=>handleDisable(a.id)}>Disable</button>
              ) : (
                <button className="button" onClick={()=>handleEnable(a.id)}>Enable</button>
              )}
              <button className="button secondary" onClick={()=>handleRevoke(a.id)}>Revoke Credential</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
