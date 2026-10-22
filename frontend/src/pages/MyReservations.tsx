import React, { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { createSession, listReservations, listSessions, listTargets, releaseReservation } from '../services/api'
import { useAuth } from '../services/auth'
import type { Reservation, Session, Target, TargetCapability } from '../services/types'
import { errorMessage, prettyDate } from '../utils/ui'

export default function MyReservations() {
  const auth = useAuth()
  const navigate = useNavigate()
  const [reservations, setReservations] = useState<Reservation[]>([])
  const [targets, setTargets] = useState<Target[]>([])
  const [sessions, setSessions] = useState<Session[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    void refresh()
  }, [])

  async function refresh(): Promise<void> {
    setLoading(true)
    setMessage(null)
    try {
      const [reservationRows, targetRows, sessionRows] = await Promise.all([
        listReservations(),
        listTargets(),
        listSessions(),
      ])
      setReservations(reservationRows)
      setTargets(targetRows)
      setSessions(sessionRows)
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }

  async function handleRelease(reservation: Reservation): Promise<void> {
    if (!auth.user) return
    setBusy(true)
    setMessage(null)
    try {
      await releaseReservation(reservation.id, auth.user.username)
      await refresh()
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  function openableCapabilities(target: Target | undefined): TargetCapability[] {
    if (!target) return []
    return (target.capabilities || []).filter((capability) => capability.enabled)
  }

  async function handleOpenSession(reservation: Reservation, capability: TargetCapability): Promise<void> {
    if (!auth.user) return
    setBusy(true)
    setMessage(null)
    try {
      const session = await createSession(reservation.id, auth.user.username, capability.capability_type, capability.id)
      navigate(`/sessions/${session.id}`)
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  const mine = useMemo(
    () => reservations.filter((reservation) => reservation.user_id === auth.user?.username),
    [reservations, auth.user?.username],
  )

  return (
    <div>
      <div className="page-head">
        <div>
          <h2 className="page-title">My Reservations</h2>
          <p className="muted">Open capability sessions and release reservations.</p>
        </div>
        <button className="button" onClick={() => void refresh()} disabled={loading || busy}>
          {loading ? 'Loading...' : 'Refresh'}
        </button>
      </div>

      {message && <div className="feedback error">{message}</div>}

      <div className="list">
        {!loading && mine.length === 0 && (
          <div className="card">No active reservations. Reserve a target first from the Targets page.</div>
        )}
        {mine.map((reservation) => {
          const target = targets.find((item) => item.id === reservation.target_id)
          const activeSession = sessions.find(
            (session) => session.reservation_id === reservation.id && session.status === 'active',
          )
          const capabilities = openableCapabilities(target)
          return (
            <article key={reservation.id} className="list-item stacked">
              <div>
                <div style={{ fontWeight: 700 }}>{target?.name || reservation.target_id}</div>
                <div className="muted">Start: {prettyDate(reservation.starts_at)}</div>
                <div className="muted">End: {prettyDate(reservation.ends_at)}</div>
              </div>

              <div style={{ display: 'flex', gap: '0.6rem', flexWrap: 'wrap' }}>
                {activeSession ? (
                  <div className="inline-note">
                    Session active: {activeSession.capability_type} (expires {prettyDate(activeSession.expires_at)}){' '}
                    <Link to={`/sessions/${activeSession.id}`}>Open workspace</Link>
                  </div>
                ) : capabilities.length > 0 ? (
                  capabilities.map((capability) => (
                    <button
                      key={capability.id}
                      className="button"
                      onClick={() => void handleOpenSession(reservation, capability)}
                      disabled={busy}
                    >
                      Open {capability.capability_type} session
                    </button>
                  ))
                ) : (
                  <div className="inline-note">No enabled capabilities are mapped for this target.</div>
                )}
                <button className="button secondary" onClick={() => void handleRelease(reservation)} disabled={busy}>
                  Release
                </button>
              </div>
            </article>
          )
        })}
      </div>
    </div>
  )
}
