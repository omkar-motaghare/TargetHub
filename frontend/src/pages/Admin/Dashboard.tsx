import React, { useState } from 'react'

import AdminTargets from './Targets'
import AdminAgents from './Agents'
import AdminActivity from './Activity'
import AdminConfig from './Config'
import AdminUsers from './Users'

const tabs = [
  { key: 'targets', title: 'Targets', comp: <AdminTargets /> },
  { key: 'agents', title: 'Agents', comp: <AdminAgents /> },
  { key: 'activity', title: 'Activity', comp: <AdminActivity /> },
  { key: 'config', title: 'Config', comp: <AdminConfig /> },
  { key: 'users', title: 'Users', comp: <AdminUsers /> },
]

export default function AdminDashboard() {
  const [active, setActive] = useState('targets')
  const t = tabs.find((x) => x.key === active)!
  return (
    <div>
      <div className="page-head">
        <div>
          <h2 className="page-title">Admin Control Plane</h2>
          <p className="muted">Manage targets, map resources, operate agents, and inspect activity.</p>
        </div>
      </div>
      <div className="admin-layout">
        <aside className="admin-sidebar card">
          <div className="muted" style={{ marginBottom: '0.7rem' }}>
            Sections
          </div>
          <div className="admin-nav">
            {tabs.map((tb) => (
              <button
                type="button"
                key={tb.key}
                className={`admin-nav-btn ${tb.key === active ? 'active' : ''}`}
                onClick={() => setActive(tb.key)}
              >
                {tb.title}
              </button>
            ))}
          </div>
        </aside>
        <section>{t.comp}</section>
      </div>
    </div>
  )
}
