import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

import {
  clearAuthToken,
  getAuthToken,
  login as apiLogin,
  logout as apiLogout,
  me,
  setTokens,
  setUnauthorizedHandler,
} from './api'
import type { UserProfile, UserRole } from './types'

export type AuthUser = {
  username: string
  displayName: string
  /** Highest role: admin > user > viewer */
  role: UserRole
  roles: string[]
}

type AuthContextValue = {
  user: AuthUser | null
  restoring: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
  isAdmin: boolean
  /** May reserve targets and operate hardware (admin or user, not viewer). */
  canOperate: boolean
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function profileToAuthUser(profile: UserProfile): AuthUser {
  const roles = profile.roles || []
  const role: UserRole = roles.includes('admin') ? 'admin' : roles.includes('user') ? 'user' : 'viewer'
  return { username: profile.username, displayName: profile.display_name || profile.username, role, roles }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [restoring, setRestoring] = useState<boolean>(true)

  const logout = useCallback(() => {
    setUser(null)
    void apiLogout()
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setUser(null)
      clearAuthToken()
    })
    return () => setUnauthorizedHandler(null)
  }, [])

  useEffect(() => {
    if (!getAuthToken()) {
      setRestoring(false)
      return
    }
    ;(async () => {
      try {
        setUser(profileToAuthUser(await me()))
      } catch {
        setUser(null)
      } finally {
        setRestoring(false)
      }
    })()
  }, [])

  const login = useCallback(async (username: string, password: string) => {
    setTokens(await apiLogin(username, password))
    setUser(profileToAuthUser(await me()))
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      restoring,
      login,
      logout,
      isAdmin: user?.role === 'admin',
      canOperate: user?.role === 'admin' || user?.role === 'user',
    }),
    [user, restoring, login, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used within AuthProvider')
  return context
}
