import React, { useState } from 'react'

import { changePassword } from '../services/api'
import { errorMessage } from '../utils/ui'

type Props = {
  /** Pre-filled username. */
  initialUsername?: string
  /** When true, the username field is fixed and not editable (used when already logged in). */
  lockUsername?: boolean
  onSuccess?: () => void
  onCancel?: () => void
}

export default function ChangePasswordForm({ initialUsername = '', lockUsername = false, onSuccess, onCancel }: Props) {
  const [username, setUsername] = useState(initialUsername)
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setMessage(null)

    if (newPassword.length < 8) {
      setMessage('New password must be at least 8 characters.')
      return
    }
    if (newPassword !== confirmPassword) {
      setMessage('New password and confirmation do not match.')
      return
    }
    if (newPassword === currentPassword) {
      setMessage('New password must be different from the current password.')
      return
    }

    setSubmitting(true)
    try {
      await changePassword({
        username: username.trim(),
        current_password: currentPassword,
        new_password: newPassword,
      })
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
      onSuccess?.()
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={submit}>
      {message && <div className="feedback error">{message}</div>}
      <div className="grid" style={{ marginTop: '0.6rem' }}>
        <label>
          <span className="muted">Username</span>
          <input
            className="input"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            required
            disabled={lockUsername}
            autoComplete="username"
          />
        </label>
      </div>
      <div className="grid" style={{ marginTop: '0.8rem' }}>
        <label>
          <span className="muted">Current password</span>
          <input
            className="input"
            type="password"
            value={currentPassword}
            onChange={(event) => setCurrentPassword(event.target.value)}
            required
            autoComplete="current-password"
          />
        </label>
      </div>
      <div className="grid" style={{ marginTop: '0.8rem' }}>
        <label>
          <span className="muted">New password</span>
          <input
            className="input"
            type="password"
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
            required
            minLength={8}
            autoComplete="new-password"
          />
        </label>
      </div>
      <div className="grid" style={{ marginTop: '0.8rem' }}>
        <label>
          <span className="muted">Confirm new password</span>
          <input
            className="input"
            type="password"
            value={confirmPassword}
            onChange={(event) => setConfirmPassword(event.target.value)}
            required
            minLength={8}
            autoComplete="new-password"
          />
        </label>
      </div>
      <div style={{ marginTop: '0.9rem', display: 'flex', gap: '0.6rem' }}>
        <button className="button" type="submit" disabled={submitting}>
          {submitting ? 'Updating...' : 'Change password'}
        </button>
        {onCancel && (
          <button className="button secondary" type="button" onClick={onCancel} disabled={submitting}>
            Cancel
          </button>
        )}
      </div>
    </form>
  )
}
