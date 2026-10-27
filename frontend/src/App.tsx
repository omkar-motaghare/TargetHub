import React, { Suspense, lazy } from 'react'
import { Link, NavLink, Navigate, Route, Routes } from 'react-router'

import NotificationBell from './components/NotificationBell'
import Account from './pages/Account'
import Calendar from './pages/Calendar'
import ChangePassword from './pages/ChangePassword'
import Login from './pages/Login'
import MyReservations from './pages/MyReservations'
import Sessions from './pages/Sessions'
import Setup from './pages/Setup'
import Targets from './pages/Targets'
import { AuthProvider, useAuth } from './services/auth'

// Heavy screens (terminal emulator, admin tools) load on demand.
const SessionWorkspace = lazy(() => import('./pages/SessionWorkspace'))
const AdminDashboard = lazy(() => import('./pages/Admin/Dashboard'))

function RequireAuth({ children, role }: { children: JSX.Element; role?: 'admin' }) {
  const auth = useAuth()
  if (auth.restoring) return <div className="card">Restoring session…</div>
  if (!auth.user) return <Navigate to="/login" replace />
  if (role === 'admin' && !auth.isAdmin) return <div className="card error">403 Forbidden — this area is for administrators.</div>
  return children
}

const navClass = ({ isActive }: { isActive: boolean }) => (isActive ? 'active' : undefined)

function AppFrame() {
  const auth = useAuth()

  return (
    <div className="app-shell">
      <header className="header">
        <div className="container topbar">
          <div className="topbar-left">
            <div>
              <Link to="/" className="brand-link">TargetHub</Link>
              <p className="brand-subtitle">Embedded lab orchestration</p>
            </div>
            {auth.user && <div className="topbar-divider" aria-hidden="true" />}
            {auth.user && (
              <nav className="nav" aria-label="main">
                <NavLink to="/targets" className={navClass}>Targets</NavLink>
                <NavLink to="/calendar" className={navClass}>Calendar</NavLink>
                {auth.canOperate && <NavLink to="/my" className={navClass}>Reservations</NavLink>}
                {auth.canOperate && <NavLink to="/sessions" className={navClass}>Sessions</NavLink>}
                {auth.isAdmin && <NavLink to="/admin" className={navClass}>Admin</NavLink>}
              </nav>
            )}
          </div>
          {auth.user ? (
            <div className="identity">
              <NotificationBell />
              <Link to="/account" className="identity-meta" title="Account, API tokens and password">
                <div>{auth.user.displayName}</div>
                <span className={`role-badge ${auth.user.role}`}>{auth.user.role}</span>
              </Link>
              <button className="button secondary" onClick={auth.logout} type="button">Sign out</button>
            </div>
          ) : (
            <nav className="nav"><Link to="/login">Sign in</Link></nav>
          )}
        </div>
      </header>

      <main className="container page-space">
        <Suspense fallback={<div className="card">Loading…</div>}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/setup" element={<Setup />} />
          <Route path="/change-password" element={<RequireAuth><ChangePassword /></RequireAuth>} />
          <Route path="/account" element={<RequireAuth><Account /></RequireAuth>} />
          <Route path="/" element={<Navigate to="/targets" replace />} />
          <Route path="/targets" element={<RequireAuth><Targets /></RequireAuth>} />
          <Route path="/calendar" element={<RequireAuth><Calendar /></RequireAuth>} />
          <Route path="/my" element={<RequireAuth><MyReservations /></RequireAuth>} />
          <Route path="/sessions" element={<RequireAuth><Sessions /></RequireAuth>} />
          <Route path="/sessions/:sessionId" element={<RequireAuth><SessionWorkspace /></RequireAuth>} />
          <Route path="/admin" element={<Navigate to="/admin/overview" replace />} />
          <Route path="/admin/:section" element={<RequireAuth role="admin"><AdminDashboard /></RequireAuth>} />
          <Route path="*" element={<div className="card">Page not found. <Link to="/targets">Go to targets</Link></div>} />
        </Routes>
        </Suspense>
      </main>
      <footer className="container footer muted small">
        TargetHub {import.meta.env.VITE_APP_VERSION || ''} · <a href="/docs" target="_blank" rel="noreferrer">API docs</a>
      </footer>
    </div>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <AppFrame />
    </AuthProvider>
  )
}
