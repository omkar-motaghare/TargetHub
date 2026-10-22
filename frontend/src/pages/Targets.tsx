import React, { useEffect, useMemo, useState } from 'react'

import { createReservation, listReservations, listTargets, releaseReservation } from '../services/api'
import { useAuth } from '../services/auth'
import type { Reservation, Target } from '../services/types'
import { classifyTargetStatus, errorMessage, prettyDate, toLocalInputValue } from '../utils/ui'

function findActiveReservation(targetId: string, reservations: Reservation[]): Reservation | undefined {
  return reservations.find((item) => item.target_id === targetId && item.status === 'active')
}

export default function Targets() {
  const auth = useAuth()
  const [targets, setTargets] = useState<Target[]>([])
  const [reservations, setReservations] = useState<Reservation[]>([])
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState<string | null>(null)
  const [reservingTarget, setReservingTarget] = useState<string | null>(null)
  const [startsAt, setStartsAt] = useState<string>('')
  const [endsAt, setEndsAt] = useState<string>('')
  const [actionBusy, setActionBusy] = useState(false)

  const stats = useMemo(() => {
    const total = targets.length
    const available = targets.filter(
      (target) => classifyTargetStatus(target.enabled, !!findActiveReservation(target.id, reservations)) === 'available',
    ).length
    const reserved = targets.filter(
      (target) => classifyTargetStatus(target.enabled, !!findActiveReservation(target.id, reservations)) === 'reserved',
    ).length
    return { total, available, reserved }
  }, [targets, reservations])

  useEffect(() => {
    void refresh()
  }, [])

  async function refresh(): Promise<void> {
    setLoading(true)
    setMessage(null)
    try {
      const [targetRows, reservationRows] = await Promise.all([listTargets(), listReservations()])
      setTargets(targetRows)
      setReservations(reservationRows)
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }

  function openReserveModal(targetId: string): void {
    setReservingTarget(targetId)
    const now = new Date()
    setStartsAt(toLocalInputValue(now))
    setEndsAt(toLocalInputValue(new Date(now.getTime() + 30 * 60 * 1000)))
  }

  async function handleReserve(targetId: string): Promise<void> {
    if (!auth.user) return
    if (!startsAt || !endsAt) {
      setMessage('Please select both reservation start and end timestamps.')
      return
    }

    setActionBusy(true)
    setMessage(null)
    try {
      await createReservation(targetId, auth.user.username, new Date(startsAt).toISOString(), new Date(endsAt).toISOString())
      setReservingTarget(null)
      await refresh()
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setActionBusy(false)
    }
  }

  async function handleRelease(targetId: string): Promise<void> {
    if (!auth.user) return
    const reservation = reservations.find(
      (entry) => entry.target_id === targetId && entry.user_id === auth.user?.username && entry.status === 'active',
    )
    if (!reservation) {
      setMessage('No active reservation was found for your user on this target.')
      return
    }
    setActionBusy(true)
    setMessage(null)
    try {
      await releaseReservation(reservation.id, auth.user.username)
      await refresh()
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setActionBusy(false)
    }
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <h2 className="page-title">Targets</h2>
          <p className="muted">Reserve shared hardware and inspect mapped capabilities.</p>
        </div>
        <button className="button" onClick={() => void refresh()} disabled={loading}>
          {loading ? 'Loading...' : 'Refresh'}
        </button>
      </div>

      {message && <div className="feedback error">{message}</div>}

      <div className="grid three" style={{ marginBottom: '0.9rem' }}>
        <div className="card">
          <div className="muted">Total targets</div>
          <h3>{stats.total}</h3>
        </div>
        <div className="card">
          <div className="muted">Available</div>
          <h3>{stats.available}</h3>
        </div>
        <div className="card">
          <div className="muted">Reserved</div>
          <h3>{stats.reserved}</h3>
        </div>
      </div>

      <div className="list">
        {!loading && targets.length === 0 && <div className="card">No targets found.</div>}
        {targets.map((target) => {
          const activeReservation = findActiveReservation(target.id, reservations)
          const status = classifyTargetStatus(target.enabled, !!activeReservation)
          const isMine = activeReservation?.user_id === auth.user?.username
          return (
            <article key={target.id} className="list-item stacked">
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.8rem' }}>
                <div>
                  <div style={{ fontWeight: 800 }}>{target.name}</div>
                  <div className="muted">
                    {target.vendor || '-'} / {target.board_model || '-'} / {target.location || '-'}
                  </div>
                </div>
                <span className={`badge ${status}`}>{status}</span>
              </div>

              <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                {(target.capabilities || []).map((capability) => (
                  <span key={capability.id} className="inline-note">
                    {capability.name} ({capability.capability_type})
                  </span>
                ))}
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap' }}>
                <div className="muted">
                  {activeReservation
                    ? `Reserved by ${activeReservation.user_id} until ${prettyDate(activeReservation.ends_at)}`
                    : 'No active reservation'}
                </div>
                <div style={{ display: 'flex', gap: '0.55rem' }}>
                  {!activeReservation && target.enabled && (
                    <button className="button" onClick={() => openReserveModal(target.id)} disabled={actionBusy}>
                      Reserve
                    </button>
                  )}
                  {isMine && (
                    <button
                      className="button secondary"
                      onClick={() => void handleRelease(target.id)}
                      disabled={actionBusy}
                    >
                      Release
                    </button>
                  )}
                </div>
              </div>
            </article>
          )
        })}
      </div>

      {reservingTarget && (
        <div className="card" style={{ marginTop: '0.9rem' }}>
          <h3>Create reservation window</h3>
          <div className="grid two">
            <label>
              <span className="muted">Starts</span>
              <input
                className="input"
                type="datetime-local"
                value={startsAt}
                onChange={(event) => setStartsAt(event.target.value)}
              />
            </label>
            <label>
              <span className="muted">Ends</span>
              <input
                className="input"
                type="datetime-local"
                value={endsAt}
                onChange={(event) => setEndsAt(event.target.value)}
              />
            </label>
          </div>
          <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.8rem' }}>
            <button className="button" onClick={() => void handleReserve(reservingTarget)} disabled={actionBusy}>
              Confirm
            </button>
            <button className="button secondary" onClick={() => setReservingTarget(null)} disabled={actionBusy}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
