import React from 'react'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '../services/api'
import type { Session, Target } from '../services/types'
import SessionWorkspace from './SessionWorkspace'

vi.mock('../services/api')
vi.mock('../components/SerialConsole', () => ({
  default: ({ sessionId }: { sessionId: string }) => <div>console for {sessionId}</div>,
}))

function makeSession(capability_type: Session['capability_type'], status = 'active'): Session {
  return {
    id: 's1', reservation_id: 'r1', target_id: 't1', user_id: 'alice', capability_type, capability_id: 'c1', status,
    expires_at: '2030-01-01T00:00:00Z', ended_at: null, created_at: '2030-01-01T00:00:00Z', updated_at: '2030-01-01T00:00:00Z',
  }
}

const target: Target = {
  id: 't1', name: 'BOARD-7', description: null, vendor: null, board_model: null, serial_number: null, lab_name: null,
  location: null, status: 'available', status_reason: null, tags: [], enabled: true, created_at: '', updated_at: '',
  capabilities: [{ id: 'c1', target_id: 't1', name: 'Relay', capability_type: 'power', enabled: true, hosting: 'server', mode: 'dd', created_at: '', updated_at: '' }],
}

function result(operation: string, data: Record<string, unknown> = {}) {
  return { session_id: 's1', capability_type: 'power' as const, operation, message: `${operation} ok`, data }
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
    vi.mocked(api.getTarget).mockResolvedValue(target)
    vi.spyOn(window, 'confirm').mockReturnValue(true)
  })
  afterEach(cleanup)

  it('mounts the WebSocket console for serial sessions', async () => {
    vi.mocked(api.getSession).mockResolvedValue(makeSession('serial'))
    vi.mocked(api.listSessionOperations).mockResolvedValue({ session_id: 's1', capability_type: 'serial', operations: ['open'] })
    renderWorkspace()
    expect(await screen.findByText('console for s1')).toBeInTheDocument()
  })

  it('shows power state, offers only supported operations and confirms destructive ones', async () => {
    vi.mocked(api.getSession).mockResolvedValue(makeSession('power'))
    vi.mocked(api.listSessionOperations).mockResolvedValue({ session_id: 's1', capability_type: 'power', operations: ['on', 'off', 'status'] })
    vi.mocked(api.executeSessionOperation).mockImplementation(async (_id, op) =>
      result(op, { power: op === 'off' ? 'off' : 'on', confirmed: true }))

    renderWorkspace()

    await waitFor(() => expect(api.executeSessionOperation).toHaveBeenCalledWith('s1', 'status'))
    expect(await screen.findByLabelText('power state')).toHaveTextContent('ON')
    expect(screen.queryByRole('button', { name: 'Power cycle' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Power off' }))
    await waitFor(() => expect(screen.getByLabelText('power state')).toHaveTextContent('OFF'))
    expect(window.confirm).toHaveBeenCalled()
    expect(screen.getByText(/BOARD-7/)).toBeInTheDocument()
  })

  it('queues deploy asynchronously and polls until it completes', async () => {
    vi.mocked(api.getSession).mockResolvedValue(makeSession('deploy'))
    vi.mocked(api.listSessionOperations).mockResolvedValue({ session_id: 's1', capability_type: 'deploy', operations: ['deploy'] })
    vi.mocked(api.submitSessionOperation).mockResolvedValue({ ...result('deploy'), operation_id: 'op1', status: 'pending' })
    vi.mocked(api.getOperationStatus).mockResolvedValue({
      operation_id: 'op1', operation: 'deploy', status: 'completed', message: 'Deployment complete',
      data: { output: 'flashed' }, requested_at: '', completed_at: '',
    })

    renderWorkspace()

    const sha = 'a'.repeat(64)
    fireEvent.change(await screen.findByLabelText('artifact url'), { target: { value: 'https://x/fw.bin' } })
    fireEvent.change(screen.getByLabelText('artifact sha256'), { target: { value: sha } })
    fireEvent.click(screen.getByRole('button', { name: 'Deploy' }))
    await waitFor(() => expect(api.submitSessionOperation).toHaveBeenCalledWith('s1', 'deploy', { url: 'https://x/fw.bin', sha256: sha }))
    await waitFor(() => expect(screen.getByLabelText('operation log')).toHaveTextContent('deploy completed'), { timeout: 4000 })
  })

  it('shows ended sessions as read-only', async () => {
    vi.mocked(api.getSession).mockResolvedValue(makeSession('serial', 'closed'))
    renderWorkspace()
    expect(await screen.findByText(/This session is closed/)).toBeInTheDocument()
    expect(api.listSessionOperations).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Download console log' })).toBeInTheDocument()
  })
})
