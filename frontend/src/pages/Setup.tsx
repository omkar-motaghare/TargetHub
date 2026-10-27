import React, { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router'

import { bootstrapAdmin, getSetupStatus } from '../services/api'
import { errorMessage } from '../utils/ui'

export default function Setup() {
  const navigate = useNavigate()
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [bootstrapToken, setBootstrapToken] = useState('')
  const [enabled, setEnabled] = useState<boolean | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [complete, setComplete] = useState(false)

  useEffect(() => {
    getSetupStatus()
      .then((status) => setEnabled(status.setup_required && status.bootstrap_enabled))
      .catch((error) => setMessage(errorMessage(error)))
  }, [])

  async function submit(event: React.FormEvent): Promise<void> {
    event.preventDefault()
    setMessage(null)
    if (password.length < 8) {
      setMessage('Password must be at least 8 characters.')
      return
    }
    if (password !== confirmPassword) {
      setMessage('Passwords do not match.')
      return
    }

    setSubmitting(true)
    try {
      await bootstrapAdmin({ username: username.trim(), password, bootstrap_token: bootstrapToken })
      setComplete(true)
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setSubmitting(false)
    }
  }

  if (complete) {
    return (
      <div className="card" style={{ maxWidth: 520, margin: '0 auto' }}>
        <h2 className="page-title">Setup complete</h2>
        <p className="muted">Your administrator account has been created.</p>
        <button className="button" type="button" onClick={() => navigate('/login', { replace: true })}>
          Continue to login
        </button>
      </div>
    )
  }

  return (
    <div className="card" style={{ maxWidth: 520, margin: '0 auto' }}>
      <h2 className="page-title">Set up TargetHub</h2>
      <p className="muted">Create the first administrator account for this TargetHub instance.</p>
      {enabled === false && <div className="feedback error">First-run setup is unavailable or already complete.</div>}
      {message && <div className="feedback error">{message}</div>}
      <form onSubmit={submit}>
        <label>
          <span className="muted">Admin username</span>
          <input className="input" value={username} onChange={(event) => setUsername(event.target.value)} required minLength={3} />
        </label>
        <label style={{ display: 'block', marginTop: '0.8rem' }}>
          <span className="muted">Password</span>
          <input
            className="input"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
            minLength={8}
            autoComplete="new-password"
          />
        </label>
        <label style={{ display: 'block', marginTop: '0.8rem' }}>
          <span className="muted">Confirm password</span>
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
        <label style={{ display: 'block', marginTop: '0.8rem' }}>
          <span className="muted">Bootstrap token</span>
          <input
            className="input"
            type="password"
            value={bootstrapToken}
            onChange={(event) => setBootstrapToken(event.target.value)}
            required
            autoComplete="off"
          />
        </label>
        <div style={{ marginTop: '0.9rem', display: 'flex', gap: '0.6rem' }}>
          <button className="button" type="submit" disabled={submitting || enabled === false}>
            {submitting ? 'Creating account...' : 'Create administrator'}
          </button>
          <Link className="button secondary" to="/login">
            Back to login
          </Link>
        </div>
      </form>
    </div>
  )
}