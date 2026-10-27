import React, { useEffect, useState } from 'react'

import ChangePasswordForm from '../components/ChangePasswordForm'
import { createApiToken, listApiTokens, logoutEverywhere, revokeApiToken } from '../services/api'
import { useAuth } from '../services/auth'
import type { ApiToken } from '../services/types'
import { errorMessage, prettyDate, relativeTime } from '../utils/ui'

export default function Account() {
  const auth = useAuth()
  const [tokens, setTokens] = useState<ApiToken[]>([])
  const [name, setName] = useState('')
  const [days, setDays] = useState<string>('90')
  const [created, setCreated] = useState<ApiToken | null>(null)
  const [message, setMessage] = useState<{ kind: 'error' | 'info'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)

  async function load(): Promise<void> {
    try {
      setTokens(await listApiTokens())
    } catch (error) {
      setMessage({ kind: 'error', text: errorMessage(error) })
    }
  }

  useEffect(() => {
    void load()
  }, [])

  async function create(event: React.FormEvent): Promise<void> {
    event.preventDefault()
    setBusy(true)
    setMessage(null)
    try {
      const token = await createApiToken(name.trim(), days ? Number(days) : null)
      setCreated(token)
      setName('')
      await load()
    } catch (error) {
      setMessage({ kind: 'error', text: errorMessage(error) })
    } finally {
      setBusy(false)
    }
  }

  async function revoke(token: ApiToken): Promise<void> {
    if (!window.confirm(`Revoke "${token.name}"? Anything using it stops working immediately.`)) return
    await revokeApiToken(token.id).catch((error) => setMessage({ kind: 'error', text: errorMessage(error) }))
    await load()
  }

  async function signOutEverywhere(): Promise<void> {
    if (!window.confirm('Sign out of every browser and device (API tokens keep working)?')) return
    await logoutEverywhere().catch(() => undefined)
    auth.logout()
  }

  return (
    <div className="grid" style={{ gap: '1rem' }}>
      <div className="page-head">
        <div>
          <h2 className="page-title">Account</h2>
          <p className="muted">
            Signed in as <strong>{auth.user?.username}</strong> ({auth.user?.roles.join(', ')})
          </p>
        </div>
        <button className="button secondary" type="button" onClick={() => void signOutEverywhere()}>
          Sign out everywhere
        </button>
      </div>

      {message && <div className={`feedback ${message.kind}`}>{message.text}</div>}

      <section className="card">
        <h3 style={{ marginTop: 0 }}>API tokens</h3>
        <p className="muted">
          Personal tokens for the <code>targethub</code> CLI, the Python SDK, the VS Code extension and CI pipelines.
          A token acts with your roles. Treat it like a password.
        </p>
        <form className="toolbar" onSubmit={(event) => void create(event)}>
          <input className="input" aria-label="token name" placeholder="Name, e.g. laptop-cli or jenkins-hil"
            value={name} onChange={(event) => setName(event.target.value)} required maxLength={100} />
          <select className="select" aria-label="token lifetime" value={days} onChange={(event) => setDays(event.target.value)}>
            <option value="30">30 days</option>
            <option value="90">90 days</option>
            <option value="365">1 year</option>
            <option value="">No expiry</option>
          </select>
          <button className="button" type="submit" disabled={busy}>Create token</button>
        </form>
        {created?.token && (
          <div className="feedback info" role="status">
            <div>Copy this token now; it will not be shown again:</div>
            <pre className="log-console mono">{created.token}</pre>
            <button className="button ghost" type="button" onClick={() => void navigator.clipboard?.writeText(created.token || '')}>
              Copy
            </button>
          </div>
        )}
        <div className="table-wrap" style={{ marginTop: '0.8rem' }}>
          <table className="table">
            <thead><tr><th>Name</th><th>Prefix</th><th>Created</th><th>Last used</th><th>Expires</th><th /></tr></thead>
            <tbody>
              {tokens.map((token) => (
                <tr key={token.id} className={token.revoked_at ? 'muted' : ''}>
                  <td>{token.name}</td>
                  <td className="mono">{token.prefix}…</td>
                  <td>{prettyDate(token.created_at)}</td>
                  <td>{token.last_used_at ? relativeTime(token.last_used_at) : 'never'}</td>
                  <td>{token.revoked_at ? 'revoked' : token.expires_at ? prettyDate(token.expires_at) : 'never'}</td>
                  <td>{!token.revoked_at && <button className="button ghost" type="button" onClick={() => void revoke(token)}>Revoke</button>}</td>
                </tr>
              ))}
              {tokens.length === 0 && <tr><td colSpan={6} className="muted">No tokens yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card">
        <h3 style={{ marginTop: 0 }}>Change password</h3>
        <ChangePasswordForm initialUsername={auth.user?.username ?? ''} lockUsername onSuccess={() => auth.logout()} />
        <p className="muted small">Changing your password signs you out on every device.</p>
      </section>
    </div>
  )
}
