import React from 'react'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '../../services/api'
import type { Target, Team, UserAdmin } from '../../services/types'
import AdminTeams from './Teams'

vi.mock('../../services/api')

const target = (id: string, name: string) =>
  ({ id, name, status: 'available', tags: [], capabilities: [], enabled: true }) as unknown as Target
const user = (username: string) => ({ id: 1, username, roles: ['user'], created_at: null }) as UserAdmin
const firmware: Team = { id: 'tm1', name: 'firmware', description: 'FW team', members: ['alice'], target_ids: ['t1'] }

describe('Admin teams', () => {
  beforeEach(() => {
    vi.mocked(api.listTeams).mockResolvedValue([firmware])
    vi.mocked(api.listUsers).mockResolvedValue([user('alice'), user('bob')])
    vi.mocked(api.listTargets).mockResolvedValue([target('t1', 'B1'), target('t2', 'B2')])
  })
  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('lists teams with their members and boards', async () => {
    render(<AdminTeams />)
    const table = within(await screen.findByRole('table', { name: 'teams' }))
    expect(await table.findByText('firmware')).toBeInTheDocument()
    expect(table.getByText('alice')).toBeInTheDocument()
    expect(table.getByText('B1')).toBeInTheDocument()
  })

  it('creates a team with chosen members and boards', async () => {
    vi.mocked(api.createTeam).mockResolvedValue({ ...firmware, id: 'tm2', name: 'qa' })
    render(<AdminTeams />)
    await screen.findByText('firmware')
    fireEvent.click(screen.getByRole('button', { name: 'New team' }))
    const form = within(await screen.findByRole('form', { name: 'team editor' }))
    fireEvent.change(form.getByLabelText('Name'), { target: { value: 'qa' } })
    fireEvent.click(form.getByLabelText('bob'))
    fireEvent.click(form.getByLabelText('B2'))
    fireEvent.click(form.getByRole('button', { name: 'Create team' }))
    await waitFor(() =>
      expect(api.createTeam).toHaveBeenCalledWith({ name: 'qa', description: null, members: ['bob'], target_ids: ['t2'] }),
    )
  })

  it('edits and deletes after confirmation', async () => {
    vi.mocked(api.updateTeam).mockResolvedValue(firmware)
    vi.mocked(api.deleteTeam).mockResolvedValue(undefined)
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<AdminTeams />)
    await screen.findByText('firmware')
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }))
    const form = within(await screen.findByRole('form', { name: 'team editor' }))
    fireEvent.click(form.getByLabelText('bob'))
    fireEvent.click(form.getByRole('button', { name: 'Save team' }))
    await waitFor(() =>
      expect(api.updateTeam).toHaveBeenCalledWith('tm1', {
        name: 'firmware', description: 'FW team', members: ['alice', 'bob'], target_ids: ['t1'],
      }),
    )
    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(api.deleteTeam).toHaveBeenCalledWith('tm1'))
  })

  it('shows errors from the server', async () => {
    vi.mocked(api.createTeam).mockRejectedValue(new Error("A team named 'qa' already exists"))
    render(<AdminTeams />)
    await screen.findByText('firmware')
    fireEvent.click(screen.getByRole('button', { name: 'New team' }))
    const form = within(await screen.findByRole('form', { name: 'team editor' }))
    fireEvent.change(form.getByLabelText('Name'), { target: { value: 'qa' } })
    fireEvent.click(form.getByRole('button', { name: 'Create team' }))
    expect(await screen.findByText(/already exists/)).toBeInTheDocument()
  })
})
