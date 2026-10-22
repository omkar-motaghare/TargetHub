import React from 'react'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '../services/api'
import type { Session } from '../services/types'
import SessionWorkspace from './SessionWorkspace'

vi.mock('../services/api')
vi.mock('../services/auth', () => ({
  useAuth: () => ({ user: { username: 'alice', role: 'user', roles: ['user'] }, isAdmin: false }),
}))

function makeSession(capability_type: Session['capability_type'], status = 'active'): Session {
  return {
    id: 's1',
    reservation_id: 'r1',
    target_id: 't1',
    user_id: 'alice',
    capability_type,
    capability_id: 'c1',
    status,
    expires_at: '2030-01-01T00:00:00Z',
    ended_at: null,
    created_at: '2030-01-01T00:00:00Z',
    updated_at: '2030-01-01T00:00:00Z',
  }
}

function result(operation: string, data: Record<string, unknown> = {}) {
  return { session_id: 's1', capability_type: 'serial' as const, operation, message: `${operation} ok`, data }
}

function renderWorkspace() {
  return render(
    <MemoryRouter initialEntries={['/sessions/s1']}>
      <Routes>
        <Route path="/sessions/:sessionId" element={<SessionWorkspace />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('SessionWorkspace', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })
  afterEach(cleanup)

  it('opens the serial port, shows polled output and sends input', async () => {
    vi.mocked(api.getSession).mockResolvedValue(makeSession('serial'))
    vi.mocked(api.listSessionOperations).mockResolvedValue({
      session_id: 's1',
      capability_type: 'serial',
      operations: ['open', 'read', 'write'],
    })
    vi.mocked(api.executeSessionOperation).mockResolvedValue(result('open'))
    vi.mocked(api.serialRead).mockResolvedValue(result('read', { data_text: 'boot ok\n' }))
    vi.mocked(api.serialWrite).mockResolvedValue(result('write'))

    renderWorkspace()

    await waitFor(() => expect(api.executeSessionOperation).toHaveBeenCalledWith('s1', 'open', {}))
    await waitFor(() => expect(screen.getByLabelText('serial output')).toHaveTextContent('boot ok'), { timeout: 3000 })

    fireEvent.change(screen.getByLabelText('serial input'), { target: { value: 'help' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(api.serialWrite).toHaveBeenCalledWith('s1', 'help\n'))
  })

  it('renders only the power operations the session offers and logs results', async () => {
    vi.mocked(api.getSession).mockResolvedValue(makeSession('power'))
    vi.mocked(api.listSessionOperations).mockResolvedValue({
      session_id: 's1',
      capability_type: 'power',
      operations: ['on', 'off', 'status'],
    })
    vi.mocked(api.executeSessionOperation).mockResolvedValue(result('off', { state: 'off' }))

    renderWorkspace()

    const off = await screen.findByRole('button', { name: 'off' })
    expect(screen.queryByRole('button', { name: 'cycle' })).toBeNull()
    fireEvent.click(off)
    await waitFor(() => expect(screen.getByText(/off: off ok/)).toBeInTheDocument())
    expect(api.executeSessionOperation).toHaveBeenCalledWith('s1', 'off', {})
  })

  it('submits deploy with url and sha256', async () => {
    vi.mocked(api.getSession).mockResolvedValue(makeSession('deploy'))
    vi.mocked(api.listSessionOperations).mockResolvedValue({
      session_id: 's1',
      capability_type: 'deploy',
      operations: ['deploy'],
    })
    vi.mocked(api.executeSessionOperation).mockResolvedValue(result('deploy', { status: 'ok' }))

    renderWorkspace()

    const sha = 'a'.repeat(64)
    fireEvent.change(await screen.findByLabelText('artifact url'), { target: { value: 'https://x/fw.bin' } })
    fireEvent.change(screen.getByLabelText('artifact sha256'), { target: { value: sha } })
    fireEvent.click(screen.getByRole('button', { name: 'Deploy' }))
    await waitFor(() =>
      expect(api.executeSessionOperation).toHaveBeenCalledWith('s1', 'deploy', { url: 'https://x/fw.bin', sha256: sha }),
    )
  })

  it('shows closed sessions as read-only', async () => {
    vi.mocked(api.getSession).mockResolvedValue(makeSession('serial', 'closed'))

    renderWorkspace()

    expect(await screen.findByText(/operations are unavailable/)).toBeInTheDocument()
    expect(api.listSessionOperations).not.toHaveBeenCalled()
    expect(api.executeSessionOperation).not.toHaveBeenCalled()
  })
})
