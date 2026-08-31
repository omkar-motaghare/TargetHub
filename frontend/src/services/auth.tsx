import React, { createContext, useContext, useState } from 'react'
import * as api from './api'

type User = { username: string; role: 'admin' | 'user' }

const AuthContext = createContext<any>(null)

export function AuthProvider({ children }: { children: React.ReactNode }){
  const [user, setUser] = useState<User | null>(()=>{
    const raw = localStorage.getItem('th_user')
    return raw ? JSON.parse(raw) : null
  })

  const login = async (username: string, password: string) =>{
    const token = await api.login(username, password)
    localStorage.setItem('th_token', token)
    // fetch /auth/me to get roles and canonical username
    const me = await api.me()
    const role = (me.roles || []).includes('admin') ? 'admin' : 'user'
    const u:User = { username: me.username || username, role }
    setUser(u)
    localStorage.setItem('th_user', JSON.stringify(u))
  }

  // If we already have a token, try to fetch the current user on mount
  React.useEffect(()=>{
    (async()=>{
      const token = localStorage.getItem('th_token')
      if(token && !user){
        try{ const me = await api.me(); const role = (me.roles||[]).includes('admin') ? 'admin' : 'user'; const u:User = { username: me.username, role }; setUser(u); localStorage.setItem('th_user', JSON.stringify(u)) }catch{ /* ignore */ }
      }
    })()
  }, [])

  const logout = ()=>{ setUser(null); localStorage.removeItem('th_user'); localStorage.removeItem('th_token') }
  return <AuthContext.Provider value={{ user, login, logout }}>{children}</AuthContext.Provider>
}

export function useAuth(){ return useContext(AuthContext) }
