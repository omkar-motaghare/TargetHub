import React, { useEffect, useState } from 'react'

import { createUser, deleteUser, listUsers, updateUser } from '../../services/api'
import { useAuth } from '../../services/auth'
import { ROLES, type UserAdmin, type UserRole } from '../../services/types'
import { errorMessage, relativeTime } from '../../utils/ui'

const ROLE_HELP: Record<UserRole, string> = {
  admin: 'manages targets, agents, users and settings',
  user: 'reserves targets and operates hardware',
  viewer: 'read-only: sees targets and the calendar',
}

function primaryRole(user: UserAdmin): UserRole {
  if (user.roles.includes('admin')) return 'admin'
  if (user.roles.includes('user')) return 'user'
  return 'viewer'
}

export default function AdminUsers() {
  const auth = useAuth()
  const [users, setUsers] = useState<UserAdmin[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ kind: 'error' | 'info'; text: string } | null>(null)
  const [draft, setDraft] = useState({ username: '', display_name: '', email: '', password: '', role: 'user' as UserRole })
  const [resets, setResets] = useState<Record<number, string>>({})

  async function load(): Promise<void> {
    setLoading(true)
    try {
      setUsers(await listUsers())
    } catch (error) {
      setMessage({ kind: 'error', text: errorMessage(error) })
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  async function act(work: () => Promise<unknown>, success: string): Promise<void> {
    setBusy(true)
    setMessage(null)
    try {
      await work()
      setMessage({ kind: 'info', text: success })
      await load()
    } catch (error) {
      setMessage({ kind: 'error', text: errorMessage(error) })
    } finally {
      setBusy(false)
    }
  }

  async function create(event: React.FormEvent): Promise<void> {
    event.preventDefault()
    await act(
      () =>
        createUser({
          username: draft.username.trim(),
          password: draft.password,
          roles: [draft.role],
          display_name: draft.display_name.trim() || null,
          email: draft.email.trim() || null,
        }),
      `User ${draft.username.trim()} created.`,
    )
    setDraft({ username: '', display_name: '', email: '', password: '', role: 'user' })
  }

  return (
    <div className="grid" style={{ gap: '1rem' }}>
      {message && <div className={`feedback ${message.kind}`} role={message.kind === 'error' ? 'alert' : 'status'}>{message.text}</div>}

      <section className="card">
        <h3 style={{ marginTop: 0 }}>Add a user</h3>
        <form onSubmit={(event) => void create(event)} className="grid three">
          <label><span className="muted">Username *</span>
            <input className="input" value={draft.username} required minLength={3} maxLength={100}
              onChange={(e) => setDraft({ ...draft, username: e.target.value })} /></label>
          <label><span className="muted">Display name</span>
            <input className="input" value={draft.display_name} onChange={(e) => setDraft({ ...draft, display_name: e.target.value })} /></label>
          <label><span className="muted">Email</span>
            <input className="input" type="email" value={draft.email} onChange={(e) => setDraft({ ...draft, email: e.target.value })} /></label>
          <label><span className="muted">Initial password * (min. 8)</span>
            <input className="input" type="password" value={draft.password} required minLength={8} autoComplete="new-password"
              onChange={(e) => setDraft({ ...draft, password: e.target.value })} /></label>
          <label><span className="muted">Role</span>
            <select className="select" value={draft.role} onChange={(e) => setDraft({ ...draft, role: e.target.value as UserRole })}>
              {ROLES.map((role) => <option key={role} value={role}>{role} — {ROLE_HELP[role]}</option>)}
            </select></label>
          <div style={{ display: 'flex', alignItems: 'end' }}>
            <button className="button" type="submit" disabled={busy}>Create user</button>
          </div>
        </form>
      </section>

      <section className="card">
        <div className="page-head">
          <h3 style={{ margin: 0 }}>Users ({users.length})</h3>
          <button className="button ghost" onClick={() => void load()} disabled={loading || busy}>{loading ? 'Loading…' : 'Refresh'}</button>
        </div>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr><th>User</th><th>Role</th><th>Status</th><th>Last login</th><th>Reset password</th><th /></tr>
            </thead>
            <tbody>
              {users.map((user) => {
                const self = auth.user?.username === user.username
                return (
                  <tr key={user.id} className={user.is_active === false ? 'muted' : ''}>
                    <td>
                      <strong>{user.username}</strong>
                      {user.display_name && <div className="muted small">{user.display_name}</div>}
                      {user.email && <div className="muted small">{user.email}</div>}
                    </td>
                    <td>
                      <select className="select" aria-label={`role of ${user.username}`} value={primaryRole(user)} disabled={busy}
                        onChange={(e) => void act(() => updateUser(user.id, { roles: [e.target.value] }), `${user.username} is now ${e.target.value}.`)}>
                        {ROLES.map((role) => <option key={role} value={role}>{role}</option>)}
                      </select>
                    </td>
                    <td>
                      <button className="button ghost" type="button" disabled={busy || self}
                        title={self ? 'You cannot disable yourself' : undefined}
                        onClick={() => void act(() => updateUser(user.id, { is_active: user.is_active === false }),
                          `${user.username} ${user.is_active === false ? 'enabled' : 'disabled and signed out'}.`)}>
                        {user.is_active === false ? 'Disabled · enable' : 'Active · disable'}
                      </button>
                    </td>
                    <td>{user.last_login_at ? relativeTime(user.last_login_at) : 'never'}</td>
                    <td>
                      <div className="toolbar">
                        <input className="input narrow" type="password" placeholder="new password" autoComplete="new-password"
                          aria-label={`new password for ${user.username}`} value={resets[user.id] || ''}
                          onChange={(e) => setResets({ ...resets, [user.id]: e.target.value })} />
                        <button className="button ghost" type="button" disabled={busy || (resets[user.id] || '').length < 8}
                          onClick={() => void act(async () => {
                            await updateUser(user.id, { password: resets[user.id] })
                            setResets({ ...resets, [user.id]: '' })
                          }, `Password for ${user.username} reset; their sessions were signed out.`)}>
                          Set
                        </button>
                      </div>
                    </td>
                    <td>
                      {!self && (
                        <button className="button danger" type="button" disabled={busy}
                          onClick={() => window.confirm(`Delete ${user.username}? Their history stays in the audit log.`) &&
                            void act(() => deleteUser(user.id), `${user.username} deleted.`)}>
                          Delete
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
