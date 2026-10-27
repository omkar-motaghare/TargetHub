import React from 'react'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'

const authState = vi.hoisted(() => ({
  value: { user: null as null | { username: string; role: string; roles: string[] }, restoring: false, isAdmin: false },
}))

vi.mock('./services/auth', () => ({
  AuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useAuth: () => ({ ...authState.value, logout: vi.fn(), login: vi.fn() }),
}))
vi.mock('./services/api', () => ({
  getSetupStatus: vi.fn().mockResolvedValue({ setup_required: false, bootstrap_enabled: false }),
}))

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  )
}

describe('route guards', () => {
  afterEach(cleanup)

  it('sends anonymous users to login', () => {
    authState.value = { user: null, restoring: false, isAdmin: false }
    renderAt('/sessions')
    expect(screen.getByRole('button', { name: /sign in|login/i })).toBeInTheDocument()
  })

  it('forbids non-admins from the admin area and hides the nav link', () => {
    authState.value = { user: { username: 'bob', role: 'user', roles: ['user'] }, restoring: false, isAdmin: false }
    renderAt('/admin')
    expect(screen.getByText('403 Forbidden')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Admin' })).toBeNull()
  })
})
