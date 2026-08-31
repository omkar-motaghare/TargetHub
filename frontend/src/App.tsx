import React from 'react'
import { Routes, Route, Navigate, Link } from 'react-router-dom'
import Login from './pages/Login'
import Targets from './pages/Targets'
import MyReservations from './pages/MyReservations'
import Sessions from './pages/Sessions'
import AdminDashboard from './pages/Admin/Dashboard'
import { AuthProvider, useAuth } from './services/auth'

function RequireAuth({ children, role }:{children:JSX.Element, role?: 'admin'|'user'}){
  const auth = useAuth()
  if(!auth.user) return <Navigate to="/login" replace />
  if(role && auth.user.role !== role) return <Navigate to="/" replace />
  return children
}

export default function App(){
  return (
    <AuthProvider>
      <div>
        <header className="header">
          <div className="container">
            <div style={{display:'flex',justifyContent:'space-between',alignItems:'center'}}>
              <div><Link to="/" style={{color:'white',textDecoration:'none'}}>TargetHub</Link></div>
              <nav className="nav">
                <Link to="/targets" style={{color:'white'}}>Targets</Link>
                <Link to="/my" style={{color:'white'}}>My Reservations</Link>
                <Link to="/sessions" style={{color:'white'}}>Sessions</Link>
                <Link to="/admin" style={{color:'white'}}>Admin</Link>
              </nav>
            </div>
          </div>
        </header>
        <main className="container">
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/" element={<Navigate to="/targets" replace />} />
            <Route path="/targets" element={<RequireAuth><Targets /></RequireAuth>} />
            <Route path="/my" element={<RequireAuth><MyReservations /></RequireAuth>} />
            <Route path="/sessions" element={<RequireAuth><Sessions /></RequireAuth>} />
            <Route path="/admin/*" element={<RequireAuth role="admin"><AdminDashboard /></RequireAuth>} />
            <Route path="*" element={<div className="card">Not Found</div>} />
          </Routes>
        </main>
      </div>
    </AuthProvider>
  )
}
