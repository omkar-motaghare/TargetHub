import React, { useEffect, useMemo, useState } from 'react'

import { createUser, deleteUser, listUsers, updateUser } from '../../services/api'
import { useAuth } from '../../services/auth'
import type { UserAdmin } from '../../services/types'
import { errorMessage, prettyDate } from '../../utils/ui'

type UserDraft = {
  username: string
  password: string
  privilege: 'admin' | 'user'
}

export default function AdminUsers() {
  const auth = useAuth()
  const [users, setUsers] = useState<UserAdmin[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [privilegeEdits, setPrivilegeEdits] = useState<Record<number, 'admin' | 'user'>>({})
  const [draft, setDraft] = useState<UserDraft>({
    username: '',
    password: '',
    privilege: 'user',
  })
  const [passwordResets, setPasswordResets] = useState<Record<number, string>>({})
  const adminCount = useMemo(() => users.filter((user) => user.roles.includes('admin')).length, [users])

  useEffect(() => {
    void load()
  }, [])

  async function load(): Promise<void> {
    setLoading(true)
    setMessage(null)
    try {
      const rows = await listUsers()
      setUsers(rows)
      setPrivilegeEdits(
        Object.fromEntries(rows.map((user) => [user.id, user.roles.includes('admin') ? 'admin' : 'user'])),
      )
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }

  async function handleCreate(event: React.FormEvent): Promise<void> {
    event.preventDefault()
    if (!draft.username.trim() || draft.password.length < 8) {
      setMessage('Username and password (minimum 8 characters) are required.')
      return
    }
    setBusy(true)
    setMessage(null)
    try {
      await createUser({
        username: draft.username.trim(),
        password: draft.password,
        roles: [draft.privilege],
      })
      setDraft({ username: '', password: '', privilege: 'user' })
      await load()
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  async function updatePrivilege(user: UserAdmin): Promise<void> {
    const privilege = privilegeEdits[user.id] || (user.roles.includes('admin') ? 'admin' : 'user')
    const nextRoles = [privilege]
    setBusy(true)
    setMessage(null)
    try {
      await updateUser(user.id, { roles: nextRoles })
      await load()
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  async function handleDelete(user: UserAdmin): Promise<void> {
    if (auth.user?.username === user.username) {
      setMessage('You cannot delete your own account while logged in.')
      return
    }
    if (!confirm(`Delete user '${user.username}'? This action cannot be undone.`)) return
    setBusy(true)
    setMessage(null)
    try {
      await deleteUser(user.id)
      await load()
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  async function handlePasswordReset(userId: number): Promise<void> {
    const nextPassword = (passwordResets[userId] || '').trim()
    if (nextPassword.length < 8) {
      setMessage('Password reset requires at least 8 characters.')
      return
    }
    setBusy(true)
    setMessage(null)
    try {
      await updateUser(userId, { password: nextPassword })
      setPasswordResets((current) => ({ ...current, [userId]: '' }))
      await load()
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid" style={{ gap: '1rem' }}>
      {message && <div className="feedback error">{message}</div>}

      <div className="card">
        <div className="page-head">
          <h3 style={{ margin: 0 }}>User management</h3>
          <button className="button ghost" onClick={() => void load()} disabled={loading || busy}>
            {loading ? 'Loading...' : 'Refresh'}
          </button>
        </div>
        <p className="muted">
          Privilege model is intentionally simple right now: choose either <strong>admin</strong> (full control) or{' '}
          <strong>user</strong> (standard access).
        </p>
      </div>

      <div className="card">
        <h4 style={{ marginTop: 0 }}>Create user</h4>
        <form onSubmit={handleCreate} className="grid two">
          <label>
            <span className="muted">Username</span>
            <input
              className="input"
              value={draft.username}
              onChange={(event) => setDraft((current) => ({ ...current, username: event.target.value }))}
              placeholder="jane.doe"
            />
          </label>
          <label>
            <span className="muted">Password</span>
            <input
              className="input"
              type="password"
              value={draft.password}
              onChange={(event) => setDraft((current) => ({ ...current, password: event.target.value }))}
              placeholder="Minimum 8 characters"
            />
          </label>
          <label>
            <span className="muted">Privilege</span>
            <select
              className="select"
              value={draft.privilege}
              onChange={(event) =>
                setDraft((current) => ({ ...current, privilege: event.target.value as 'admin' | 'user' }))
              }
            >
              <option value="user">user</option>
              <option value="admin">admin</option>
            </select>
          </label>
          <div>
            <button className="button" type="submit" disabled={busy}>
              {busy ? 'Saving...' : 'Create user'}
            </button>
          </div>
        </form>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>User</th>
              <th>Privilege</th>
              <th>Created</th>
              <th>Change privilege</th>
              <th>Password reset</th>
              <th>Delete</th>
            </tr>
          </thead>
          <tbody>
            {!loading && users.length === 0 ? (
              <tr>
                <td colSpan={6} className="empty">
                  No users found.
                </td>
              </tr>
            ) : (
              users.map((user) => {
                const isAdmin = user.roles.includes('admin')
                const isSelf = auth.user?.username === user.username
                const selectedPrivilege = privilegeEdits[user.id] || (isAdmin ? 'admin' : 'user')
                const demotingLastAdmin = isAdmin && adminCount === 1 && selectedPrivilege === 'user'
                const deletingLastAdmin = isAdmin && adminCount === 1
                return (
                  <tr key={user.id}>
                    <td>{user.username}</td>
                    <td>{isAdmin ? 'admin' : 'user'}</td>
                    <td>{prettyDate(user.created_at)}</td>
                    <td>
                      <div style={{ display: 'flex', gap: '0.5rem' }}>
                        <select
                          className="select"
                          value={selectedPrivilege}
                          onChange={(event) =>
                            setPrivilegeEdits((current) => ({
                              ...current,
                              [user.id]: event.target.value as 'admin' | 'user',
                            }))
                          }
                        >
                          <option value="user">user</option>
                          <option value="admin">admin</option>
                        </select>
                        <button
                          className="button secondary"
                          disabled={busy || demotingLastAdmin}
                          title={demotingLastAdmin ? 'At least one admin must remain.' : undefined}
                          onClick={() => void updatePrivilege(user)}
                        >
                          Apply
                        </button>
                      </div>
                    </td>
                    <td>
                      <div style={{ display: 'flex', gap: '0.5rem' }}>
                        <input
                          className="input"
                          type="password"
                          value={passwordResets[user.id] || ''}
                          placeholder="New password"
                          onChange={(event) =>
                            setPasswordResets((current) => ({
                              ...current,
                              [user.id]: event.target.value,
                            }))
                          }
                        />
                        <button className="button secondary" disabled={busy} onClick={() => void handlePasswordReset(user.id)}>
                          Apply
                        </button>
                      </div>
                    </td>
                    <td>
                      <button
                        className="button danger"
                        disabled={busy || isSelf || deletingLastAdmin}
                        title={
                          isSelf
                            ? 'You cannot delete your own account while logged in.'
                            : deletingLastAdmin
                              ? 'At least one admin must remain.'
                              : undefined
                        }
                        onClick={() => void handleDelete(user)}
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
