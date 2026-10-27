import React, { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router'

import {
  createSession,
  extendReservation,
  leaveWaitlist,
  listReservations,
  listSessions,
  listTargets,
  listWaitlist,
  releaseReservation,
} from '../services/api'
import { useAuth } from '../services/auth'
import type { Reservation, Session, Target, TargetCapability, WaitlistEntry } from '../services/types'
import { capabilityModeLabel, errorMessage, formatDuration, prettyDate, prettyTime, relativeTime } from '../utils/ui'

const EXTEND_OPTIONS = [15, 30, 60]

export default function MyReservations() {
  const auth = useAuth()
  const navigate = useNavigate()
  const [reservations, setReservations] = useState<Reservation[]>([])
  const [targets, setTargets] = useState<Target[]>([])
  const [sessions, setSessions] = useState<Session[]>([])
  const [waitlist, setWaitlist] = useState<WaitlistEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ kind: 'error' | 'info'; text: string } | null>(null)
  const [, setTick] = useState(0)

  async function refresh(): Promise<void> {
    setLoading(true)
    try {
      const [reservationRows, targetRows, sessionRows, waitRows] = await Promise.all([
        listReservations(),
        listTargets(),
        listSessions(),
        listWaitlist(),
      ])
      setReservations(reservationRows.filter((item) => item.user_id === auth.user?.username))
      setTargets(targetRows)
      setSessions(sessionRows)
      setWaitlist(waitRows)
    } catch (error) {
      setMessage({ kind: 'error', text: errorMessage(error) })
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void refresh()
    const timer = window.setInterval(() => setTick((value) => value + 1), 30_000)
    return () => window.clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const targetsById = useMemo(() => Object.fromEntries(targets.map((target) => [target.id, target])), [targets])
  const active = reservations.filter((item) => item.status === 'active')
  const history = reservations
    .filter((item) => item.status !== 'active')
    .sort((a, b) => b.ends_at.localeCompare(a.ends_at))
    .slice(0, 10)

  async function act(work: () => Promise<unknown>, success?: string): Promise<void> {
    setBusy(true)
    setMessage(null)
    try {
      await work()
      if (success) setMessage({ kind: 'info', text: success })
      await refresh()
    } catch (error) {
      setMessage({ kind: 'error', text: errorMessage(error) })
    } finally {
      setBusy(false)
    }
  }

  async function openSession(reservation: Reservation, capability: TargetCapability): Promise<void> {
    setBusy(true)
    setMessage(null)
    try {
      const session = await createSession(reservation.id, capability.capability_type, capability.id)
      navigate(`/sessions/${session.id}`)
    } catch (error) {
      setMessage({ kind: 'error', text: errorMessage(error) })
      setBusy(false)
    }
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <h2 className="page-title">My reservations</h2>
          <p className="muted">Open a console or power session, extend your time, or release the board for others.</p>
        </div>
        <button className="button" onClick={() => void refresh()} disabled={loading || busy}>
          {loading ? 'Loading…' : 'Refresh'}
        </button>
      </div>

      {message && <div className={`feedback ${message.kind}`} role={message.kind === 'error' ? 'alert' : 'status'}>{message.text}</div>}

      <div className="list">
        {!loading && active.length === 0 && (
          <div className="card empty">
            No active reservations. <Link to="/targets">Reserve a target</Link>.
          </div>
        )}
        {active.map((reservation) => {
          const target = targetsById[reservation.target_id]
          const started = new Date(reservation.starts_at).getTime() <= Date.now()
          const minutesLeft = Math.round((new Date(reservation.ends_at).getTime() - Date.now()) / 60_000)
          const reservationSessions = sessions.filter(
            (session) => session.reservation_id === reservation.id && session.status === 'active',
          )
          return (
            <article key={reservation.id} className="list-item stacked">
              <div className="row-between">
                <div>
                  <div className="target-name">{target?.name || reservation.target_id}</div>
                  <div className="muted">
                    {prettyTime(reservation.starts_at)} – {prettyTime(reservation.ends_at)}
                    {started ? ` · ends ${relativeTime(reservation.ends_at)}` : ` · starts ${relativeTime(reservation.starts_at)}`}
                  </div>
                  {reservation.note && <div className="muted small">“{reservation.note}”</div>}
                </div>
                {started && minutesLeft <= 10 && <span className="badge reserved">Ending soon</span>}
              </div>

              {started ? (
                <div className="chip-row">
                  {(target?.capabilities || []).filter((capability) => capability.enabled).map((capability) => {
                    const existing = reservationSessions.find((session) => session.capability_id === capability.id)
                    return existing ? (
                      <Link key={capability.id} className="button ghost" to={`/sessions/${existing.id}`}>
                        Resume {capability.name}
                      </Link>
                    ) : (
                      <button key={capability.id} className="button" disabled={busy}
                        onClick={() => void openSession(reservation, capability)}
                        title={capabilityModeLabel(capability)}>
                        Open {capability.name}
                      </button>
                    )
                  })}
                  {!target?.capabilities?.some((capability) => capability.enabled) && (
                    <span className="inline-note">No capabilities configured; this reservation only books the board.</span>
                  )}
                </div>
              ) : (
                <div className="inline-note">Sessions can be opened once the reservation starts.</div>
              )}

              <div className="toolbar">
                <span className="muted">Extend:</span>
                {EXTEND_OPTIONS.map((minutes) => (
                  <button key={minutes} className="chip" type="button" disabled={busy}
                    onClick={() => void act(() => extendReservation(reservation.id, minutes), `Extended by ${formatDuration(minutes)}.`)}>
                    +{formatDuration(minutes)}
                  </button>
                ))}
                <span className="spacer" />
                <button className="button secondary" disabled={busy}
                  onClick={() => void act(() => releaseReservation(reservation.id), `${target?.name || 'Target'} released.`)}>
                  Release
                </button>
              </div>
            </article>
          )
        })}
      </div>

      {waitlist.length > 0 && (
        <section className="card" style={{ marginTop: '1rem' }}>
          <h3 style={{ marginTop: 0 }}>Waiting for</h3>
          <div className="list">
            {waitlist.map((entry) => (
              <div key={entry.id} className="list-item">
                <div>
                  <strong>{entry.target_id ? targetsById[entry.target_id]?.name || 'target' : `any #${entry.tag}`}</strong>
                  <div className="muted">
                    #{entry.position} in queue · {formatDuration(entry.duration_minutes)} · joined {relativeTime(entry.created_at)}
                  </div>
                </div>
                <button className="button ghost" disabled={busy} onClick={() => void act(() => leaveWaitlist(entry.id), 'Left the waitlist.')}>
                  Leave
                </button>
              </div>
            ))}
          </div>
        </section>
      )}

      {history.length > 0 && (
        <section className="card" style={{ marginTop: '1rem' }}>
          <h3 style={{ marginTop: 0 }}>Recent</h3>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>Target</th><th>From</th><th>To</th><th>Status</th></tr>
              </thead>
              <tbody>
                {history.map((item) => (
                  <tr key={item.id}>
                    <td>{targetsById[item.target_id]?.name || item.target_id}</td>
                    <td>{prettyDate(item.starts_at)}</td>
                    <td>{prettyDate(item.released_at || item.ends_at)}</td>
                    <td>{item.status}{item.released_by && item.released_by !== item.user_id ? ` by ${item.released_by}` : ''}</td>
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
