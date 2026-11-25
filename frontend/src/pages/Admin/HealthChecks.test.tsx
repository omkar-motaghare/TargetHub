import React from 'react'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '../../services/api'
import type { HealthCheck, Target } from '../../services/types'
import AdminHealthChecks from './HealthChecks'

vi.mock('../../services/api')

function target(id: string, name: string, status = 'available'): Target {
  return {
    id, name, description: null, vendor: null, board_model: null, serial_number: null, lab_name: null, location: null,
    status, status_reason: null, tags: [], enabled: true, created_at: '', updated_at: '', capabilities: [],
  } as Target
}

const configured: HealthCheck = {
  target_id: 't1', enabled: true, boot_pattern: 'login:', interval_minutes: 1440, boot_timeout_seconds: 60,
  power_operation: 'cycle', failure_threshold: 2, auto_maintenance: true, next_run_at: null, last_run_at: '2026-11-01T10:00:00Z',
  last_status: 'failed', last_message: 'Boot text not seen', consecutive_failures: 1, maintenance_by_check: false,
}

describe('Admin health checks', () => {
  beforeEach(() => {
    vi.mocked(api.listTargets).mockResolvedValue([target('t1', 'B1'), target('t2', 'B2'), target('t3', 'OLD', 'retired')])
    vi.mocked(api.getHealthCheck).mockImplementation(async (id: string) => (id === 't1' ? configured : null))
    vi.mocked(api.healthCheckResults).mockResolvedValue([])
  })
  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
    vi.restoreAllMocks()
  })

  it('lists targets with their check state and skips retired boards', async () => {
    render(<AdminHealthChecks />)
    const table = within(await screen.findByRole('table', { name: 'health check status' }))
    expect(await table.findByText('Failing (1)')).toBeInTheDocument()
    expect(table.getByText('Not configured')).toBeInTheDocument()
    expect(table.queryByText('OLD')).not.toBeInTheDocument()
  })

  it('sets up a check for a new target', async () => {
    vi.mocked(api.saveHealthCheck).mockResolvedValue({ ...configured, target_id: 't2', last_status: null, consecutive_failures: 0 })
    render(<AdminHealthChecks />)
    fireEvent.click(await screen.findByLabelText('configure B2'))
    fireEvent.change(await screen.findByLabelText('boot text'), { target: { value: 'U-Boot' } })
    fireEvent.change(screen.getByLabelText('failure threshold'), { target: { value: '3' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(api.saveHealthCheck).toHaveBeenCalledWith('t2', expect.objectContaining({
      boot_pattern: 'U-Boot', failure_threshold: 3, power_operation: 'cycle', enabled: true, auto_maintenance: true,
    })))
    expect(await screen.findByText('Health check saved.')).toBeInTheDocument()
  })

  it('runs a check now and shows the outcome', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.mocked(api.runHealthCheck).mockResolvedValue({ status: 'failed', message: 'Boot text not seen within 60s' })
    render(<AdminHealthChecks />)
    fireEvent.click(await screen.findByLabelText('configure B1'))
    fireEvent.click(await screen.findByRole('button', { name: 'Run now' }))
    await waitFor(() => expect(api.runHealthCheck).toHaveBeenCalledWith('t1'))
    expect(await screen.findByText('failed: Boot text not seen within 60s')).toBeInTheDocument()
  })

  it('does not run or remove anything without confirmation, and removes when confirmed', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    vi.mocked(api.deleteHealthCheck).mockResolvedValue(undefined)
    render(<AdminHealthChecks />)
    fireEvent.click(await screen.findByLabelText('configure B1'))
    fireEvent.click(await screen.findByRole('button', { name: 'Run now' }))
    fireEvent.click(screen.getByRole('button', { name: 'Remove' }))
    expect(api.runHealthCheck).not.toHaveBeenCalled()
    expect(api.deleteHealthCheck).not.toHaveBeenCalled()
    confirm.mockReturnValue(true)
    fireEvent.click(screen.getByRole('button', { name: 'Remove' }))
    await waitFor(() => expect(api.deleteHealthCheck).toHaveBeenCalledWith('t1'))
  })

  it('shows a load error', async () => {
    vi.mocked(api.listTargets).mockRejectedValue(new Error('server down'))
    render(<AdminHealthChecks />)
    expect(await screen.findByRole('alert')).toHaveTextContent('server down')
  })
})
