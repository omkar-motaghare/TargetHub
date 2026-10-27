import React, { useEffect, useMemo, useState } from 'react'

import { listTargets, reservationCalendar } from '../services/api'
import { useAuth } from '../services/auth'
import type { Reservation, Target } from '../services/types'
import { errorMessage, prettyTime } from '../utils/ui'

const WINDOWS = [
  { label: 'Today', hours: 24 },
  { label: '3 days', hours: 72 },
  { label: 'Week', hours: 168 },
]

export default function Calendar() {
  const auth = useAuth()
  const [hours, setHours] = useState(24)
  const [targets, setTargets] = useState<Target[]>([])
  const [reservations, setReservations] = useState<Reservation[]>([])
  const [message, setMessage] = useState<string | null>(null)
  const [now] = useState(() => Date.now())

  const start = useMemo(() => {
    const value = new Date(now)
    value.setMinutes(0, 0, 0)
    return value.getTime() - 60 * 60_000
  }, [now])
  const end = start + hours * 60 * 60_000

  useEffect(() => {
    Promise.all([
      listTargets(),
      reservationCalendar({ from: new Date(start).toISOString(), to: new Date(end).toISOString() }),
    ])
      .then(([targetRows, reservationRows]) => {
        setTargets(targetRows)
        setReservations(reservationRows)
      })
      .catch((error) => setMessage(errorMessage(error)))
  }, [start, end])

  const ticks = useMemo(() => {
    const step = hours <= 24 ? 3 : hours <= 72 ? 12 : 24
    const values: number[] = []
    for (let at = start; at < end; at += step * 60 * 60_000) values.push(at)
    return values
  }, [start, end, hours])

  const position = (value: number) => `${Math.max(0, Math.min(100, ((value - start) / (end - start)) * 100))}%`

  return (
    <div>
      <div className="page-head">
        <div>
          <h2 className="page-title">Lab calendar</h2>
          <p className="muted">Everyone’s bookings, so you can plan without asking around.</p>
        </div>
        <div className="chip-row">
          {WINDOWS.map((item) => (
            <button key={item.hours} type="button" className={`chip ${hours === item.hours ? 'active' : ''}`} onClick={() => setHours(item.hours)}>
              {item.label}
            </button>
          ))}
        </div>
      </div>
      {message && <div className="feedback error">{message}</div>}

      <div className="card timeline">
        <div className="timeline-row timeline-axis">
          <div className="timeline-label" />
          <div className="timeline-track">
            {ticks.map((tick) => (
              <span key={tick} className="timeline-tick" style={{ left: position(tick) }}>
                {new Date(tick).toLocaleString([], hours <= 24 ? { hour: '2-digit', minute: '2-digit' } : { weekday: 'short', hour: '2-digit' })}
              </span>
            ))}
            <span className="timeline-now" style={{ left: position(Date.now()) }} title="now" />
          </div>
        </div>
        {targets.map((target) => (
          <div className="timeline-row" key={target.id}>
            <div className="timeline-label" title={target.name}>{target.name}</div>
            <div className="timeline-track">
              {reservations
                .filter((reservation) => reservation.target_id === target.id)
                .map((reservation) => {
                  const from = new Date(reservation.starts_at).getTime()
                  const to = new Date(reservation.ends_at).getTime()
                  const left = Math.max(from, start)
                  const width = ((Math.min(to, end) - left) / (end - start)) * 100
                  const mine = reservation.user_id === auth.user?.username
                  return (
                    <span key={reservation.id} className={`timeline-bar ${mine ? 'mine' : ''}`}
                      style={{ left: position(left), width: `${Math.max(width, 0.8)}%` }}
                      title={`${reservation.user_id}: ${prettyTime(reservation.starts_at)} – ${prettyTime(reservation.ends_at)}${reservation.note ? ` · ${reservation.note}` : ''}`}>
                      {reservation.user_id}
                    </span>
                  )
                })}
              {target.status !== 'available' && <span className="timeline-blocked">{target.status}</span>}
            </div>
          </div>
        ))}
        {targets.length === 0 && <div className="muted">No targets.</div>}
      </div>
    </div>
  )
}
