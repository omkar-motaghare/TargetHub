import React from 'react'

export default function AdminActivity(){
  const logs = JSON.parse(localStorage.getItem('th_activity_v1')||'[]')
  return (
    <div>
      <h3>Activity Log</h3>
      <div className="list">
        {logs.length===0 && <div className="card">No activity yet (mock)</div>}
        {logs.map((l:any,i:number)=> (
          <div key={i} className="list-item"><div>{l}</div></div>
        ))}
      </div>
    </div>
  )
}
