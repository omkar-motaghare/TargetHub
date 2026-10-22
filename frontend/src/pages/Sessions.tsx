import React, { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { closeSession, listSessions } from '../services/api'
import { useAuth } from '../services/auth'
import type { Session } from '../services/types'
import { errorMessage, prettyDate } from '../utils/ui'

export default function Sessions() {
  const auth = useAuth()
  const [sessions, setSessions] = useState<Session[]>([])
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    void refresh()
  }, [])

  async function refresh(): Promise<void> {
    setLoading(true)
    setMessage(null)
    try {
      setSessions(await listSessions())
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }

  async function handleClose(sessionId: string): Promise<void> {
    if (!auth.user) return
    setBusy(true)
    setMessage(null)
    try {
      await closeSession(sessionId, auth.user.username)
      await refresh()
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  const mine = useMemo(
    () => sessions.filter((session) => session.user_id === auth.user?.username),
    [sessions, auth.user?.username],
  )

  return (
    <div>
      <div className="page-head">
        <div>
          <h2 className="page-title">My Sessions</h2>
          <p className="muted">Open a session to use its serial terminal, power controls or deploy form.</p>
        </div>
        <button className="button" onClick={() => void refresh()} disabled={loading || busy}>
          {loading ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      {message && <div className="feedback error">{message}</div>}

      <div className="list">
        {!loading && mine.length === 0 && <div className="card">No sessions yet. Open one from My Reservations.</div>}
        {mine.map((session) => (
          <article key={session.id} className="list-item">
            <div>
              <div style={{ fontWeight: 700 }}>
                {session.capability_type} on target {session.target_id}
              </div>
              <div className="muted">
                Status: {session.status} | Expires: {prettyDate(session.expires_at)}
              </div>
            </div>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              {session.status === 'active' && (
                <>
                  <Link className="button ghost" to={`/sessions/${session.id}`}>
                    Open
                  </Link>
                  <button className="button secondary" onClick={() => void handleClose(session.id)} disabled={busy}>
                    Close Session
                  </button>
                </>
              )}
            </div>
          </article>
        ))}
      </div>

    </div>
  )
}
