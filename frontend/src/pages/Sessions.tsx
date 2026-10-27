import React, { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router'

import { closeSession, listSessions, listTargets } from '../services/api'
import { useAuth } from '../services/auth'
import type { Session, Target } from '../services/types'
import { errorMessage, prettyDate, relativeTime } from '../utils/ui'

export default function Sessions() {
  const auth = useAuth()
  const [sessions, setSessions] = useState<Session[]>([])
  const [targets, setTargets] = useState<Target[]>([])
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  async function refresh(): Promise<void> {
    setLoading(true)
    setMessage(null)
    try {
      const [sessionRows, targetRows] = await Promise.all([listSessions(), listTargets()])
      setSessions(sessionRows)
      setTargets(targetRows)
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void refresh()
  }, [])

  async function handleClose(sessionId: string): Promise<void> {
    setBusy(true)
    try {
      await closeSession(sessionId)
      await refresh()
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  const names = useMemo(() => Object.fromEntries(targets.map((target) => [target.id, target.name])), [targets])
  const capabilityNames = useMemo(
    () => Object.fromEntries(targets.flatMap((target) => target.capabilities.map((item) => [item.id, item.name]))),
    [targets],
  )
  const mine = sessions.filter((session) => session.user_id === auth.user?.username)
  const active = mine.filter((session) => session.status === 'active')
  const ended = mine.filter((session) => session.status !== 'active').slice(0, 20)

  return (
    <div>
      <div className="page-head">
        <div>
          <h2 className="page-title">My sessions</h2>
          <p className="muted">A session is your authorized connection to one capability of a reserved target.</p>
        </div>
        <button className="button" onClick={() => void refresh()} disabled={loading || busy}>
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      {message && <div className="feedback error">{message}</div>}

      <div className="list">
        {!loading && active.length === 0 && (
          <div className="card empty">No active sessions. Open one from <Link to="/my">My reservations</Link>.</div>
        )}
        {active.map((session) => (
          <article key={session.id} className="list-item">
            <div>
              <div className="target-name">
                {names[session.target_id] || 'Target'} · {(session.capability_id && capabilityNames[session.capability_id]) || session.capability_type}
              </div>
              <div className="muted">Ends {relativeTime(session.expires_at)}</div>
            </div>
            <div className="toolbar">
              <Link className="button" to={`/sessions/${session.id}`}>Open</Link>
              <button className="button secondary" onClick={() => void handleClose(session.id)} disabled={busy}>
                Close
              </button>
            </div>
          </article>
        ))}
      </div>

      {ended.length > 0 && (
        <section className="card" style={{ marginTop: '1rem' }}>
          <h3 style={{ marginTop: 0 }}>Ended sessions</h3>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Target</th><th>Capability</th><th>Ended</th><th>Status</th><th /></tr></thead>
              <tbody>
                {ended.map((session) => (
                  <tr key={session.id}>
                    <td>{names[session.target_id] || session.target_id}</td>
                    <td>{(session.capability_id && capabilityNames[session.capability_id]) || session.capability_type}</td>
                    <td>{prettyDate(session.ended_at)}</td>
                    <td>{session.status}</td>
                    <td>{session.capability_type === 'serial' && <Link to={`/sessions/${session.id}`}>details</Link>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  )
}
