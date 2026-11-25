import React, { useCallback, useEffect, useState } from 'react'

import { createTeam, deleteTeam, listTargets, listTeams, listUsers, updateTeam } from '../../services/api'
import type { Target, Team, UserAdmin } from '../../services/types'
import { errorMessage } from '../../utils/ui'

function toggle(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((item) => item !== value) : [...list, value]
}

function TeamEditor({ team, users, targets, onSaved, onCancel }: {
  team: Team | null
  users: UserAdmin[]
  targets: Target[]
  onSaved: () => void
  onCancel: () => void
}) {
  const [name, setName] = useState(team?.name ?? '')
  const [description, setDescription] = useState(team?.description ?? '')
  const [members, setMembers] = useState<string[]>(team?.members ?? [])
  const [targetIds, setTargetIds] = useState<string[]>(team?.target_ids ?? [])
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  async function save(event: React.FormEvent): Promise<void> {
    event.preventDefault()
    if (!name.trim()) return setMessage('Give the team a name.')
    setBusy(true)
    try {
      const input = { name: name.trim(), description: description.trim() || null, members, target_ids: targetIds }
      if (team) await updateTeam(team.id, input)
      else await createTeam(input)
      onSaved()
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card" onSubmit={(event) => void save(event)} aria-label="team editor">
      <h3 style={{ marginTop: 0 }}>{team ? `Edit ${team.name}` : 'New team'}</h3>
      {message && <div className="feedback error">{message}</div>}
      <label className="field">
        <span>Name</span>
        <input className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={100} />
      </label>
      <label className="field">
        <span>Description</span>
        <input className="input" value={description} onChange={(e) => setDescription(e.target.value)} maxLength={500} />
      </label>
      <fieldset className="field">
        <legend>Members</legend>
        {users.map((user) => (
          <label key={user.username} style={{ display: 'block' }}>
            <input type="checkbox" checked={members.includes(user.username)} onChange={() => setMembers(toggle(members, user.username))} />{' '}
            {user.username}
          </label>
        ))}
      </fieldset>
      <fieldset className="field">
        <legend>Boards reserved for this team</legend>
        <p className="muted small">A board with no team is open to everyone. Admins can always reserve any board.</p>
        {targets.map((target) => (
          <label key={target.id} style={{ display: 'block' }}>
            <input type="checkbox" checked={targetIds.includes(target.id)} onChange={() => setTargetIds(toggle(targetIds, target.id))} />{' '}
            {target.name}
          </label>
        ))}
      </fieldset>
      <div className="toolbar">
        <button className="button" type="submit" disabled={busy}>{team ? 'Save team' : 'Create team'}</button>
        <button className="button ghost" type="button" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  )
}

export default function AdminTeams() {
  const [teams, setTeams] = useState<Team[]>([])
  const [users, setUsers] = useState<UserAdmin[]>([])
  const [targets, setTargets] = useState<Target[]>([])
  const [editing, setEditing] = useState<Team | 'new' | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const [teamList, userList, targetList] = await Promise.all([listTeams(), listUsers(), listTargets()])
      setTeams(teamList)
      setUsers(userList)
      setTargets(targetList.filter((target) => target.status !== 'retired'))
      setMessage(null)
    } catch (error) {
      setMessage(errorMessage(error))
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const nameOf = (id: string) => targets.find((target) => target.id === id)?.name ?? id

  async function remove(team: Team): Promise<void> {
    if (!window.confirm(`Delete team "${team.name}"? Its boards become open to everyone.`)) return
    try {
      await deleteTeam(team.id)
      await load()
    } catch (error) {
      setMessage(errorMessage(error))
    }
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <h3 style={{ margin: 0 }}>Teams</h3>
          <p className="muted">Group users and reserve boards for a team. Boards without a team stay open to everyone.</p>
        </div>
        <button className="button" type="button" onClick={() => setEditing('new')}>New team</button>
      </div>
      {message && <div className="feedback error">{message}</div>}
      {editing && (
        <TeamEditor
          key={editing === 'new' ? 'new' : editing.id}
          team={editing === 'new' ? null : editing}
          users={users}
          targets={targets}
          onCancel={() => setEditing(null)}
          onSaved={() => {
            setEditing(null)
            void load()
          }}
        />
      )}
      <div className="table-wrap">
        <table className="table" aria-label="teams">
          <thead><tr><th>Team</th><th>Members</th><th>Boards</th><th /></tr></thead>
          <tbody>
            {teams.map((team) => (
              <tr key={team.id}>
                <td><strong>{team.name}</strong>{team.description && <div className="muted small">{team.description}</div>}</td>
                <td>{team.members.join(', ') || '-'}</td>
                <td>{team.target_ids.map(nameOf).join(', ') || 'none (members only share a group)'}</td>
                <td>
                  <div className="toolbar">
                    <button className="button ghost" type="button" onClick={() => setEditing(team)}>Edit</button>
                    <button className="button ghost" type="button" onClick={() => void remove(team)}>Delete</button>
                  </div>
                </td>
              </tr>
            ))}
            {teams.length === 0 && <tr><td colSpan={4} className="muted">No teams yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  )
}
