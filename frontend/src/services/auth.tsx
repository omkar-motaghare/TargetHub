import React, { createContext, useContext, useEffect, useMemo, useState } from 'react'

import {
  clearAuthToken,
  getAuthToken,
  login as apiLogin,
  me,
  setAuthToken,
  setUnauthorizedHandler,
} from './api'
import type { UserProfile, UserRole } from './types'

export type AuthUser = {
  username: string
  role: UserRole
  roles: string[]
}

type AuthContextValue = {
  user: AuthUser | null
  restoring: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
  isAdmin: boolean
}

const AuthContext = createContext<AuthContextValue | null>(null)

function profileToAuthUser(profile: UserProfile): AuthUser {
  const roles = profile.roles || []
  return {
    username: profile.username,
    role: roles.includes('admin') ? 'admin' : 'user',
    roles,
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [restoring, setRestoring] = useState<boolean>(true)

  const logout = () => {
    setUser(null)
    localStorage.removeItem('th_user')
    clearAuthToken()
  }

  useEffect(() => {
    setUnauthorizedHandler(() => {
      logout()
    })
    return () => setUnauthorizedHandler(null)
  }, [])

  useEffect(() => {
    const raw = localStorage.getItem('th_user')
    if (raw) {
      try {
        setUser(JSON.parse(raw) as AuthUser)
      } catch {
        localStorage.removeItem('th_user')
      }
    }

    const token = getAuthToken()
    if (!token) {
      setRestoring(false)
      return
    }

    ;(async () => {
      try {
        const profile = await me()
        const authUser = profileToAuthUser(profile)
        setUser(authUser)
        localStorage.setItem('th_user', JSON.stringify(authUser))
      } catch {
        logout()
      } finally {
        setRestoring(false)
      }
    })()
  }, [])

  const login = async (username: string, password: string) => {
    const token = await apiLogin(username, password)
    setAuthToken(token)
    const profile = await me()
    const authUser = profileToAuthUser(profile)
    setUser(authUser)
    localStorage.setItem('th_user', JSON.stringify(authUser))
  }

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      restoring,
      login,
      logout,
      isAdmin: user?.role === 'admin',
    }),
    [user, restoring],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used within AuthProvider')
  return context
}
