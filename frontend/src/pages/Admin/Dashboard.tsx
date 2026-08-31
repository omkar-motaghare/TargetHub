import React, {useState} from 'react'
import AdminTargets from './Targets'
import AdminAgents from './Agents'
import AdminActivity from './Activity'
import AdminConfig from './Config'

const tabs = [
  {key:'targets', title:'Targets', comp: <AdminTargets/>},
  {key:'agents', title:'Agents', comp: <AdminAgents/>},
  {key:'activity', title:'Activity', comp:<AdminActivity/>},
  {key:'config', title:'Config', comp:<AdminConfig/>}
]

export default function AdminDashboard(){
  const [active,setActive] = useState('targets')
  const t = tabs.find(x=>x.key===active)!
  return (
    <div>
      <h2>Admin Dashboard</h2>
      <div style={{display:'flex',gap:8,marginBottom:12}}>
        {tabs.map(tb=> (
          <div key={tb.key} className={`tab ${tb.key===active? 'active':''}`} onClick={()=>setActive(tb.key)}>{tb.title}</div>
        ))}
      </div>
      <div>{t.comp}</div>
    </div>
  )
}
