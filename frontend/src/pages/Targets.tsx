import React, { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router'

import StateBadge from '../components/StateBadge'
import {
  createReservation,
  getPolicy,
  joinWaitlist,
  listReservations,
  listTargets,
  releaseReservation,
  reserveAny,
} from '../services/api'
import { useAuth } from '../services/auth'
import type { Reservation, ReservationPolicy, Target } from '../services/types'
import {
  capabilityModeLabel,
  errorMessage,
  formatDuration,
  prettyTime,
  relativeTime,
  targetState,
  toLocalInputValue,
} from '../utils/ui'

const REFRESH_MS = 30_000
const PRESETS = [30, 60, 120, 240, 480]

type Dialog = { kind: 'reserve' | 'waitlist'; target: Target } | null

function ReserveDialog({
  dialog,
  policy,
  onClose,
  onDone,
}: {
  dialog: NonNullable<Dialog>
  policy: ReservationPolicy | null
  onClose: () => void
  onDone: (text: string) => void
}) {
  const maxMinutes = policy?.max_duration_minutes ?? 480
  const presets = PRESETS.filter((minutes) => minutes <= maxMinutes)
  const [duration, setDuration] = useState<number>(Math.min(policy?.default_duration_minutes ?? 60, maxMinutes))
  const [startLater, setStartLater] = useState(false)
  const [startsAt, setStartsAt] = useState(toLocalInputValue(new Date()))
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { kind, target } = dialog

  async function submit(event: React.FormEvent): Promise<void> {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (kind === 'waitlist') {
        const entry = await joinWaitlist({ target_id: target.id, duration_minutes: duration, note: note || null })
        onDone(
          entry.status === 'fulfilled'
            ? `${target.name} was free and is now reserved for you.`
            : `You are #${entry.position} in the queue for ${target.name}. It will be reserved for you automatically.`,
        )
      } else {
        const start = startLater ? new Date(startsAt) : new Date()
        const end = new Date(start.getTime() + duration * 60_000)
        await createReservation({
          target_id: target.id,
          starts_at: start.toISOString(),
          ends_at: end.toISOString(),
          note: note || null,
        })
        onDone(`${target.name} reserved until ${prettyTime(end.toISOString())}.`)
      }
    } catch (failure) {
      setError(errorMessage(failure))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <form className="modal card" role="dialog" aria-label={kind === 'reserve' ? 'Reserve target' : 'Join waitlist'}
        onClick={(event) => event.stopPropagation()} onSubmit={(event) => void submit(event)}>
        <h3 style={{ marginTop: 0 }}>{kind === 'reserve' ? `Reserve ${target.name}` : `Wait for ${target.name}`}</h3>
        {kind === 'waitlist' && (
          <p className="muted">
            {target.availability?.reserved_by
              ? `${target.availability.reserved_by} has it until ${prettyTime(target.availability.reserved_until)}. `
              : ''}
            You will get it automatically for the chosen duration as soon as it is free.
          </p>
        )}
        <div className="muted">Duration</div>
        <div className="chip-row">
          {presets.map((minutes) => (
            <button key={minutes} type="button" className={`chip ${duration === minutes ? 'active' : ''}`}
              onClick={() => setDuration(minutes)}>
              {formatDuration(minutes)}
            </button>
          ))}
          <label className="inline">
            <input className="input narrow" type="number" min={5} max={maxMinutes} step={5} value={duration}
              aria-label="duration in minutes" onChange={(event) => setDuration(Number(event.target.value))} /> min
          </label>
        </div>
        {kind === 'reserve' && (
          <label className="inline" style={{ marginTop: '0.6rem' }}>
            <input type="checkbox" checked={startLater} onChange={(event) => setStartLater(event.target.checked)} />
            Start later
          </label>
        )}
        {kind === 'reserve' && startLater && (
          <input className="input" type="datetime-local" aria-label="start time" value={startsAt}
            onChange={(event) => setStartsAt(event.target.value)} />
        )}
        <label style={{ display: 'block', marginTop: '0.6rem' }}>
          <span className="muted">Note (optional)</span>
          <input className="input" maxLength={500} value={note} placeholder="What are you testing?"
            onChange={(event) => setNote(event.target.value)} />
        </label>
        {policy && <p className="muted small">Lab policy: up to {formatDuration(policy.max_duration_minutes)} per reservation.</p>}
        {error && <div className="feedback error">{error}</div>}
        <div className="toolbar" style={{ marginTop: '0.8rem' }}>
          <button className="button" type="submit" disabled={busy || duration < 5}>
            {busy ? 'Working…' : kind === 'reserve' ? 'Reserve' : 'Join waitlist'}
          </button>
          <button className="button ghost" type="button" onClick={onClose} disabled={busy}>
            Cancel
          </button>
        </div>
      </form>
    </div>
  )
}

export default function Targets() {
  const auth = useAuth()
  const navigate = useNavigate()
  const [targets, setTargets] = useState<Target[]>([])
  const [mine, setMine] = useState<Reservation[]>([])
  const [policy, setPolicy] = useState<ReservationPolicy | null>(null)
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState<{ kind: 'error' | 'info'; text: string } | null>(null)
  const [dialog, setDialog] = useState<Dialog>(null)
  const [query, setQuery] = useState('')
  const [tag, setTag] = useState('')
  const [stateFilter, setStateFilter] = useState('')
  const [busy, setBusy] = useState(false)

  async function refresh(quiet = false): Promise<void> {
    if (!quiet) setLoading(true)
    try {
      const [targetRows, reservationRows] = await Promise.all([listTargets(), listReservations({ status: 'active' })])
      setTargets(targetRows)
      setMine(reservationRows.filter((item) => item.user_id === auth.user?.username))
    } catch (error) {
      setMessage({ kind: 'error', text: errorMessage(error) })
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void refresh()
    getPolicy().then(setPolicy).catch(() => undefined)
    const timer = window.setInterval(() => void refresh(true), REFRESH_MS)
    return () => window.clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const tags = useMemo(() => [...new Set(targets.flatMap((target) => target.tags || []))].sort(), [targets])

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return targets.filter((target) => {
      if (tag && !(target.tags || []).includes(tag)) return false
      if (stateFilter && targetState(target) !== stateFilter) return false
      if (!needle) return true
      return [target.name, target.vendor, target.board_model, target.lab_name, target.location, target.description]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(needle))
    })
  }, [targets, query, tag, stateFilter])

  const stats = useMemo(() => {
    const count = (state: string) => targets.filter((target) => targetState(target) === state).length
    return { total: targets.length, available: count('available'), reserved: count('reserved'), maintenance: count('maintenance') }
  }, [targets])

  async function release(target: Target): Promise<void> {
    const reservation = mine.find((item) => item.target_id === target.id)
    if (!reservation) return
    setBusy(true)
    try {
      await releaseReservation(reservation.id)
      setMessage({ kind: 'info', text: `${target.name} released.` })
      await refresh(true)
    } catch (error) {
      setMessage({ kind: 'error', text: errorMessage(error) })
    } finally {
      setBusy(false)
    }
  }

  async function reserveAnyWithTag(): Promise<void> {
    if (!tag) return
    setBusy(true)
    try {
      const reservation = await reserveAny({ tag, duration_minutes: policy?.default_duration_minutes ?? 60 })
      const target = targets.find((item) => item.id === reservation.target_id)
      setMessage({ kind: 'info', text: `Reserved ${target?.name || 'a target'} until ${prettyTime(reservation.ends_at)}.` })
      await refresh(true)
    } catch (error) {
      setMessage({ kind: 'error', text: errorMessage(error) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <h2 className="page-title">Targets</h2>
          <p className="muted">See who has which board, reserve hardware, or queue for a busy one.</p>
        </div>
        <button className="button" onClick={() => void refresh()} disabled={loading}>
          {loading ? 'Loading…' : 'Refresh'}
        </button>
      </div>

      {message && (
        <div className={`feedback ${message.kind}`} role={message.kind === 'error' ? 'alert' : 'status'}>
          {message.text}
          <button type="button" className="link-button" onClick={() => setMessage(null)} aria-label="dismiss">
            ✕
          </button>
        </div>
      )}

      <div className="grid four" style={{ marginBottom: '0.9rem' }}>
        <div className="card stat"><div className="muted">Targets</div><h3>{stats.total}</h3></div>
        <div className="card stat"><div className="muted">Available</div><h3 className="ok">{stats.available}</h3></div>
        <div className="card stat"><div className="muted">Reserved</div><h3 className="warn">{stats.reserved}</h3></div>
        <div className="card stat"><div className="muted">Maintenance</div><h3>{stats.maintenance}</h3></div>
      </div>

      <div className="card filters">
        <input className="input" placeholder="Search name, model, lab, location…" aria-label="search targets"
          value={query} onChange={(event) => setQuery(event.target.value)} />
        <select className="select" aria-label="filter by tag" value={tag} onChange={(event) => setTag(event.target.value)}>
          <option value="">All tags</option>
          {tags.map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
        <select className="select" aria-label="filter by state" value={stateFilter}
          onChange={(event) => setStateFilter(event.target.value)}>
          <option value="">Any state</option>
          <option value="available">Available</option>
          <option value="reserved">Reserved</option>
          <option value="maintenance">Maintenance</option>
        </select>
        {auth.canOperate && tag && (
          <button className="button" type="button" disabled={busy} onClick={() => void reserveAnyWithTag()}>
            Reserve any “{tag}”
          </button>
        )}
      </div>

      <div className="list">
        {!loading && visible.length === 0 && (
          <div className="card empty">{targets.length ? 'No targets match the filters.' : 'No targets yet. An admin can add them under Admin → Targets.'}</div>
        )}
        {visible.map((target) => {
          const state = targetState(target)
          const availability = target.availability
          const isMine = mine.some((item) => item.target_id === target.id)
          return (
            <article key={target.id} className="list-item stacked target-card">
              <div className="row-between">
                <div>
                  <div className="target-name">{target.name}</div>
                  <div className="muted">
                    {[target.vendor, target.board_model, target.lab_name, target.location].filter(Boolean).join(' · ') || '—'}
                  </div>
                </div>
                <StateBadge state={state} />
              </div>

              {target.description && <div className="muted small">{target.description}</div>}

              <div className="chip-row">
                {(target.tags || []).map((item) => (
                  <button key={item} type="button" className={`chip tag ${tag === item ? 'active' : ''}`} onClick={() => setTag(item)}>
                    #{item}
                  </button>
                ))}
                {(target.capabilities || []).filter((capability) => capability.enabled).map((capability) => (
                  <span key={capability.id} className={`inline-note ${capability.mode === 'simulated' ? 'warn' : ''}`}
                    title={capability.mode === 'simulated' ? 'Simulated: no real hardware behind this capability' : undefined}>
                    {capability.name} · {capabilityModeLabel(capability)}
                  </span>
                ))}
              </div>

              <div className="row-between">
                <div className="muted">
                  {state === 'maintenance' || state === 'retired'
                    ? `${state === 'maintenance' ? 'In maintenance' : 'Retired'}${availability?.reason ? `: ${availability.reason}` : ''}`
                    : availability?.reserved_by
                      ? `${isMine ? 'You have it' : `Reserved by ${availability.reserved_by}`} until ${prettyTime(availability.reserved_until)} (${relativeTime(availability.reserved_until)})`
                      : availability?.next_reservation_at
                        ? `Free now · next booking ${prettyTime(availability.next_reservation_at)} by ${availability.next_reserved_by}`
                        : 'Free'}
                </div>
                {auth.canOperate && (
                  <div className="toolbar">
                    {state === 'available' && (
                      <button className="button" disabled={busy} onClick={() => setDialog({ kind: 'reserve', target })}>
                        Reserve
                      </button>
                    )}
                    {state === 'reserved' && !isMine && (
                      <button className="button ghost" disabled={busy} onClick={() => setDialog({ kind: 'waitlist', target })}>
                        Join waitlist
                      </button>
                    )}
                    {isMine && (
                      <>
                        <button className="button" onClick={() => navigate('/my')}>Open</button>
                        <button className="button secondary" disabled={busy} onClick={() => void release(target)}>
                          Release
                        </button>
                      </>
                    )}
                  </div>
                )}
              </div>
            </article>
          )
        })}
      </div>

      {dialog && (
        <ReserveDialog
          dialog={dialog}
          policy={policy}
          onClose={() => setDialog(null)}
          onDone={(text) => {
            setDialog(null)
            setMessage({ kind: 'info', text })
            void refresh(true)
          }}
        />
      )}
    </div>
  )
}
