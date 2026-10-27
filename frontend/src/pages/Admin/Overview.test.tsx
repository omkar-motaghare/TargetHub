import React from 'react'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import * as api from '../../services/api'
import type { SystemOverview } from '../../services/types'
import AdminOverview from './Overview'

vi.mock('../../services/api')

const base: SystemOverview = {
  version: '0.2.0', environment: 'production', database: 'postgresql', public_url: 'https://hub.lab',
  simulation_enabled: false, scheduler_enabled: true, targets: { total: 3, available: 2, maintenance: 1 },
  reservations_active: 1, sessions_active: 2, waitlist_waiting: 4, users: { total: 5, active: 4 },
  agents: { total: 2, online: 1, disabled: 0 }, issues: [],
}

describe('Admin overview', () => {
  afterEach(cleanup)

  it('lists configuration problems, errors first', async () => {
    vi.mocked(api.getSystemOverview).mockResolvedValue({
      ...base,
      issues: [
        { severity: 'warning', message: 'B2 · Console: Agent \'pi\' is offline', target_id: 'b2', target_name: 'B2' },
        { severity: 'error', message: 'B1 · Power: environment variable DD_KEY (api_key_env) is not set on the server', target_id: 'b1', target_name: 'B1' },
      ],
    })
    render(<MemoryRouter><AdminOverview /></MemoryRouter>)
    const items = await screen.findAllByRole('listitem')
    expect(items[0]).toHaveTextContent('DD_KEY')
    expect(items[1]).toHaveTextContent('offline')
    expect(screen.getByText('1 / 2')).toBeInTheDocument()
    expect(screen.getByText('4 waiting in queues')).toBeInTheDocument()
  })

  it('confirms a clean configuration and warns about a localhost public URL', async () => {
    vi.mocked(api.getSystemOverview).mockResolvedValue({ ...base, public_url: 'http://localhost:8000' })
    render(<MemoryRouter><AdminOverview /></MemoryRouter>)
    expect(await screen.findByText(/No problems found/)).toBeInTheDocument()
    expect(screen.getByText(/points at localhost/)).toBeInTheDocument()
  })
})
