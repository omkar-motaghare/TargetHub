import React from 'react'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import * as api from '../../services/api'
import type { UsageReport } from '../../services/types'
import AdminReports from './Reports'

vi.mock('../../services/api')

const report: UsageReport = {
  period: { from: '', to: '', hours: 720 },
  totals: { targets: 2, reservations: 3, users: 2, booked_hours: 16, idle_reservations: 1, idle_hours: 2, idle_share_percent: 12.5 },
  targets: [
    { target_id: 't1', name: 'B1', tags: ['stm32'], reservations: 2, users: 2, booked_hours: 12, utilisation_percent: 5, idle_reservations: 1, idle_hours: 2 },
    { target_id: 't2', name: 'B2', tags: [], reservations: 0, users: 0, booked_hours: 0, utilisation_percent: 0, idle_reservations: 0, idle_hours: 0 },
  ],
  tags: [{ tag: 'stm32', targets: 1, reservations: 2, booked_hours: 12, utilisation_percent: 5 }],
  users: [{ user_id: 'alice', reservations: 2, targets: 1, booked_hours: 14, idle_reservations: 0, idle_hours: 0 }],
  idle: [{ reservation_id: 'r1', target: 'B1', user_id: 'bob', starts_at: '2026-11-01T10:00:00Z', hours_held: 2, note: 'flash test' }],
  waitlist: { entries: 3, fulfilled: 2, waiting: 0, cancelled: 0, expired: 1, average_wait_minutes: 60, longest_wait_minutes: 90 },
}

describe('Admin reports', () => {
  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('shows totals, per-target utilisation and idle reservations', async () => {
    vi.mocked(api.usageReport).mockResolvedValue(report)
    render(<AdminReports />)
    expect(await screen.findByText('16 h')).toBeInTheDocument()
    expect(screen.getByText(/12.5% of booked time/)).toBeInTheDocument()
    expect(screen.getByText('60 min')).toBeInTheDocument()
    const targets = within(screen.getByRole('table', { name: 'utilisation per target' }))
    expect(targets.getByText('B1')).toBeInTheDocument()
    expect(targets.getByText('5%')).toBeInTheDocument()
    expect(within(screen.getByRole('table', { name: 'idle reservations' })).getByText('flash test')).toBeInTheDocument()
    expect(api.usageReport).toHaveBeenCalledWith(30)
  })

  it('reloads for another period', async () => {
    vi.mocked(api.usageReport).mockResolvedValue(report)
    render(<AdminReports />)
    await screen.findByText('16 h')
    fireEvent.change(screen.getByLabelText('report period'), { target: { value: '90' } })
    await waitFor(() => expect(api.usageReport).toHaveBeenLastCalledWith(90))
  })

  it('downloads a CSV and reports errors', async () => {
    vi.mocked(api.usageReport).mockResolvedValue(report)
    vi.mocked(api.usageReportCsv).mockResolvedValue('name\nB1\n')
    const createObjectURL = vi.fn(() => 'blob:csv')
    Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    render(<AdminReports />)
    await screen.findByText('16 h')
    fireEvent.click(screen.getByLabelText('download idle csv'))
    await waitFor(() => expect(api.usageReportCsv).toHaveBeenCalledWith('idle', 30))
    await waitFor(() => expect(click).toHaveBeenCalled())

    vi.mocked(api.usageReportCsv).mockRejectedValue(new Error('boom'))
    fireEvent.click(screen.getByLabelText('download users csv'))
    expect(await screen.findByRole('alert')).toHaveTextContent('boom')
    click.mockRestore()
  })

  it('shows the error when the report cannot be loaded', async () => {
    vi.mocked(api.usageReport).mockRejectedValue(new Error('server down'))
    render(<AdminReports />)
    expect(await screen.findByRole('alert')).toHaveTextContent('server down')
  })
})
