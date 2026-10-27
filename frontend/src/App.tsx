import React from 'react'
import { Link, NavLink, Navigate, Route, Routes } from 'react-router-dom'

import ChangePassword from './pages/ChangePassword'
import Login from './pages/Login'
import MyReservations from './pages/MyReservations'
import SessionWorkspace from './pages/SessionWorkspace'
import Sessions from './pages/Sessions'
import Setup from './pages/Setup'
import AdminDashboard from './pages/Admin/Dashboard'
import Targets from './pages/Targets'
import { AuthProvider, useAuth } from './services/auth'

function RequireAuth({ children, role }: { children: JSX.Element; role?: 'admin' | 'user' }) {
  const auth = useAuth()
  if (auth.restoring) return <div className="card">Restoring session...</div>
  if (!auth.user) return <Navigate to="/login" replace />
  if (role && auth.user.role !== role) return <div className="card error">403 Forbidden</div>
  return children
}

function AppFrame() {
  const auth = useAuth()

  return (
    <div className="app-shell">
      <header className="header">
        <div className="container topbar">
          <div className="topbar-left">
            <div>
              <Link to="/" className="brand-link">
                TargetHub
              </Link>
              <p className="brand-subtitle">Embedded lab orchestration</p>
            </div>
            {auth.user && <div className="topbar-divider" aria-hidden="true" />}
            {auth.user && (
              <nav className="nav">
                <NavLink to="/targets" className={({ isActive }) => (isActive ? 'active' : undefined)}>
                  Targets
                </NavLink>
                <NavLink to="/my" className={({ isActive }) => (isActive ? 'active' : undefined)}>
                  Reservations
                </NavLink>
                <NavLink to="/sessions" className={({ isActive }) => (isActive ? 'active' : undefined)}>
                  Sessions
                </NavLink>
                {auth.isAdmin && (
                  <NavLink to="/admin" className={({ isActive }) => (isActive ? 'active' : undefined)}>
                    Admin
                  </NavLink>
                )}
              </nav>
            )}
          </div>
          {auth.user ? (
            <div className="identity">
              <div className="identity-meta">
                <div>
                  <span className="identity-label">user :</span> <span>{auth.user.username}</span>
                </div>
                <div>
                  <span className="identity-label">role :</span>{' '}
                  <span className={`role-badge ${auth.isAdmin ? 'admin' : 'user'}`}>{auth.user.role}</span>
                </div>
              </div>
              <button className="button secondary" onClick={auth.logout} type="button">
                Logout
              </button>
              <Link to="/change-password" className="button secondary">
                Change Password
              </Link>
            </div>
          ) : (
            <nav className="nav">
              <Link to="/login">Login</Link>
            </nav>
          )}
        </div>
      </header>

      <main className="container page-space">
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/setup" element={<Setup />} />
          <Route
            path="/change-password"
            element={
              <RequireAuth>
                <ChangePassword />
              </RequireAuth>
            }
          />
          <Route path="/" element={<Navigate to="/targets" replace />} />
          <Route
            path="/targets"
            element={
              <RequireAuth>
                <Targets />
              </RequireAuth>
            }
          />
          <Route
            path="/my"
            element={
              <RequireAuth>
                <MyReservations />
              </RequireAuth>
            }
          />
          <Route
            path="/sessions"
            element={
              <RequireAuth>
                <Sessions />
              </RequireAuth>
            }
          />
          <Route
            path="/sessions/:sessionId"
            element={
              <RequireAuth>
                <SessionWorkspace />
              </RequireAuth>
            }
          />
          <Route
            path="/admin/*"
            element={
              <RequireAuth role="admin">
                <AdminDashboard />
              </RequireAuth>
            }
          />
          <Route path="*" element={<div className="card">Not Found</div>} />
        </Routes>
      </main>
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
