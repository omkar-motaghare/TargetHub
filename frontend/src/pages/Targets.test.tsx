import React from 'react'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '../services/api'
import type { Target } from '../services/types'
import Targets from './Targets'

vi.mock('../services/api')
const auth = vi.hoisted(() => ({ value: { user: { username: 'alice' }, canOperate: true, isAdmin: false } }))
vi.mock('../services/auth', () => ({ useAuth: () => auth.value }))

function target(name: string, availability: Partial<NonNullable<Target['availability']>>, extra: Partial<Target> = {}): Target {
  return {
    id: name, name, description: null, vendor: 'ST', board_model: 'Nucleo', serial_number: null, lab_name: 'Lab A',
    location: null, status: 'available', status_reason: null, tags: ['nucleo'], enabled: true, created_at: '', updated_at: '',
    capabilities: [{ id: `${name}-c`, target_id: name, name: 'Console', capability_type: 'serial', enabled: true, hosting: 'agent', mode: 'simulated', created_at: '', updated_at: '' }],
    availability: { state: 'available', reason: null, reserved_by: null, reserved_until: null, next_reservation_at: null, next_reserved_by: null, ...availability },
    ...extra,
  }
}

describe('Targets page', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    auth.value = { user: { username: 'alice' }, canOperate: true, isAdmin: false }
    vi.mocked(api.listTargets).mockResolvedValue([
      target('FREE-1', {}),
      target('BUSY-2', { state: 'reserved', reserved_by: 'bob', reserved_until: '2030-01-01T10:00:00Z' }),
      target('FIX-3', { state: 'maintenance', reason: 'cable broken' }, { status: 'maintenance', status_reason: 'cable broken' }),
    ])
    vi.mocked(api.listReservations).mockResolvedValue([])
    vi.mocked(api.getPolicy).mockResolvedValue({
      max_duration_minutes: 240, max_advance_days: 30, max_active_reservations_per_user: 0, default_duration_minutes: 60,
      expiry_warning_minutes: 10, allow_extend_when_waitlisted: false, waitlist_entry_ttl_hours: 24,
      transcript_retention_days: 30, audit_retention_days: 365,
    })
  })
  afterEach(cleanup)

  it('shows who holds each board, maintenance reasons and simulated capabilities', async () => {
    render(<MemoryRouter><Targets /></MemoryRouter>)
    expect(await screen.findByText(/Reserved by bob/)).toBeInTheDocument()
    expect(screen.getByText(/In maintenance: cable broken/)).toBeInTheDocument()
    expect(screen.getAllByText(/Console · simulated/).length).toBe(3)
    expect(screen.getByRole('button', { name: 'Join waitlist' })).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Reserve' })).toHaveLength(1)
  })

  it('reserves with a preset duration, limited by policy', async () => {
    vi.mocked(api.createReservation).mockResolvedValue({
      id: 'r1', target_id: 'FREE-1', user_id: 'alice', starts_at: '', ends_at: '2030-01-01T11:00:00Z', status: 'active',
      released_at: null, created_at: '', updated_at: '',
    })
    render(<MemoryRouter><Targets /></MemoryRouter>)
    fireEvent.click(await screen.findByRole('button', { name: 'Reserve' }))
    expect(screen.queryByRole('button', { name: '8 h' })).toBeNull() // above the 240-minute policy limit
    fireEvent.click(screen.getByRole('button', { name: '2 h' }))
    fireEvent.click(screen.getAllByRole('button', { name: 'Reserve' }).at(-1)!)
    await waitFor(() => expect(api.createReservation).toHaveBeenCalled())
    const input = vi.mocked(api.createReservation).mock.calls[0][0]
    expect(new Date(input.ends_at).getTime() - new Date(input.starts_at).getTime()).toBe(120 * 60_000)
  })

  it('viewers see availability but no reserve actions', async () => {
    auth.value = { user: { username: 'vic' }, canOperate: false, isAdmin: false }
    render(<MemoryRouter><Targets /></MemoryRouter>)
    expect(await screen.findByText(/Reserved by bob/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reserve' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Join waitlist' })).toBeNull()
  })
})
