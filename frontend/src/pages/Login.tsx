import React, { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import ChangePasswordForm from '../components/ChangePasswordForm'
import { ApiError, getSetupStatus } from '../services/api'
import { useAuth } from '../services/auth'
import { errorMessage } from '../utils/ui'

export default function Login() {
  const auth = useAuth()
  const nav = useNavigate()
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [showChangePassword, setShowChangePassword] = useState(false)
  const [changeSuccess, setChangeSuccess] = useState(false)

  useEffect(() => {
    let cancelled = false
    getSetupStatus()
      .then((status) => {
        if (!cancelled && status.setup_required) nav('/setup', { replace: true })
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [nav])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitting(true)
    setMessage(null)
    try {
      await auth.login(name.trim(), password)
      nav('/')
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setMessage('Incorrect username or password.')
        return
      }
      setMessage(errorMessage(error))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="card" style={{ maxWidth: 520, margin: '0 auto' }}>
      <h2 className="page-title">Sign in to TargetHub</h2>
      <p className="muted">Use your TargetHub account to access targets, sessions, and administration workflows.</p>
      {auth.restoring && <div className="feedback info">Checking existing session...</div>}
      {message && <div className="feedback error">{message}</div>}
      {changeSuccess && <div className="feedback info">Password changed successfully. Please sign in.</div>}
      {!showChangePassword ? (
        <>
          <form onSubmit={submit}>
            <div className="grid">
              <label>
                <span className="muted">Username</span>
                <input
                  className="input"
                  placeholder="admin"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  required
                  autoComplete="username"
                />
              </label>
            </div>
            <div className="grid" style={{ marginTop: '0.8rem' }}>
              <label>
                <span className="muted">Password</span>
                <input
                  className="input"
                  placeholder="••••••••"
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  required
                  autoComplete="current-password"
                />
              </label>
            </div>
            <div style={{ marginTop: '0.9rem' }}>
              <button className="button" type="submit" disabled={submitting || auth.restoring}>
                {submitting ? 'Signing in...' : 'Login'}
              </button>
            </div>
          </form>
          <p className="muted" style={{ marginTop: '0.9rem' }}>
            <button
              type="button"
              className="link-button"
              onClick={() => {
                setChangeSuccess(false)
                setMessage(null)
                setShowChangePassword(true)
              }}
            >
              Change password
            </button>
          </p>
        </>
      ) : (
        <>
          <h3 className="page-title" style={{ marginTop: '1.2rem' }}>
            Change password
          </h3>
          <p className="muted">Enter your username and current password to set a new one.</p>
          <ChangePasswordForm
            initialUsername={name}
            onSuccess={() => {
              setShowChangePassword(false)
              setChangeSuccess(true)
              setPassword('')
            }}
            onCancel={() => setShowChangePassword(false)}
          />
        </>
      )}
    </div>
  )
}
