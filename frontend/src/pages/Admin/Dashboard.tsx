import React from 'react'
import { NavLink, Navigate, useParams } from 'react-router'

import AdminActivity from './Activity'
import AdminAgents from './Agents'
import AdminHealthChecks from './HealthChecks'
import AdminOverview from './Overview'
import AdminReports from './Reports'
import AdminSettings from './Settings'
import AdminTargets from './Targets'
import AdminUsers from './Users'

const sections = [
  { key: 'overview', title: 'Overview', render: () => <AdminOverview /> },
  { key: 'targets', title: 'Targets', render: () => <AdminTargets /> },
  { key: 'agents', title: 'Agents', render: () => <AdminAgents /> },
  { key: 'health', title: 'Health checks', render: () => <AdminHealthChecks /> },
  { key: 'reports', title: 'Reports', render: () => <AdminReports /> },
  { key: 'users', title: 'Users', render: () => <AdminUsers /> },
  { key: 'settings', title: 'Settings', render: () => <AdminSettings /> },
  { key: 'activity', title: 'Activity log', render: () => <AdminActivity /> },
]

export default function AdminDashboard() {
  const { section } = useParams()
  const current = sections.find((item) => item.key === section)
  if (!current) return <Navigate to="/admin/overview" replace />

  return (
    <div>
      <div className="page-head">
        <div>
          <h2 className="page-title">Administration</h2>
          <p className="muted">Targets and capabilities, agents, health checks, usage reports, users, lab policy, notifications and the activity log.</p>
        </div>
      </div>
      <div className="admin-layout">
        <aside className="admin-sidebar card">
          <nav className="admin-nav" aria-label="admin sections">
            {sections.map((item) => (
              <NavLink key={item.key} to={`/admin/${item.key}`}
                className={({ isActive }) => `admin-nav-btn ${isActive ? 'active' : ''}`}>
                {item.title}
              </NavLink>
            ))}
          </nav>
        </aside>
        <section key={current.key}>{current.render()}</section>
      </div>
    </div>
  )
}
