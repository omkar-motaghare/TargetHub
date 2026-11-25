import React, { useCallback, useEffect, useState } from 'react'

import {
  deleteHealthCheck,
  getHealthCheck,
  healthCheckResults,
  listTargets,
  runHealthCheck,
  saveHealthCheck,
} from '../../services/api'
import type { HealthCheck, HealthCheckInput, HealthCheckResult, Target } from '../../services/types'
import { errorMessage, prettyTime, relativeTime } from '../../utils/ui'

const DEFAULTS: HealthCheckInput = {
  enabled: true,
  boot_pattern: '',
  interval_minutes: 1440,
  boot_timeout_seconds: 60,
  power_operation: 'cycle',
  failure_threshold: 2,
  auto_maintenance: true,
}

function pickInput(check: HealthCheck): HealthCheckInput {
  return {
    enabled: check.enabled,
    boot_pattern: check.boot_pattern,
    interval_minutes: check.interval_minutes,
    boot_timeout_seconds: check.boot_timeout_seconds,
    power_operation: check.power_operation,
    failure_threshold: check.failure_threshold,
    auto_maintenance: check.auto_maintenance,
  }
}

function statusLabel(check: HealthCheck | null | undefined): { text: string; tone: string } {
  if (!check) return { text: 'Not configured', tone: 'muted' }
  if (!check.enabled) return { text: 'Disabled', tone: 'muted' }
  if (check.last_status === 'failed') return { text: `Failing (${check.consecutive_failures})`, tone: 'error' }
  if (check.last_status === 'passed') return { text: 'Passing', tone: 'ok' }
  if (check.last_status === 'skipped') return { text: 'Skipped (board busy)', tone: 'warn' }
  return { text: 'Waiting for first run', tone: 'muted' }
}

function Editor({ target, check, onChanged }: { target: Target; check: HealthCheck | null; onChanged: () => void }) {
  const [form, setForm] = useState<HealthCheckInput>(check ? pickInput(check) : DEFAULTS)
  const [results, setResults] = useState<HealthCheckResult[]>([])
  const [busy, setBusy] = useState(false)
  const [running, setRunning] = useState(false)
  const [message, setMessage] = useState<{ kind: 'error' | 'success' | 'info'; text: string } | null>(null)

  const loadResults = useCallback(async () => {
    if (!check) return setResults([])
    try {
      setResults(await healthCheckResults(target.id))
    } catch {
      setResults([])
    }
  }, [check, target.id])

  useEffect(() => {
    void loadResults()
  }, [loadResults])

  const patch = (changes: Partial<HealthCheckInput>) => setForm((current) => ({ ...current, ...changes }))

  async function save(event: React.FormEvent): Promise<void> {
    event.preventDefault()
    setBusy(true)
    setMessage(null)
    try {
      await saveHealthCheck(target.id, form)
      setMessage({ kind: 'success', text: 'Health check saved.' })
      onChanged()
    } catch (error) {
      setMessage({ kind: 'error', text: errorMessage(error) })
    } finally {
      setBusy(false)
    }
  }

  async function remove(): Promise<void> {
    if (!window.confirm(`Remove the health check for ${target.name}?`)) return
    setBusy(true)
    try {
      await deleteHealthCheck(target.id)
      onChanged()
    } catch (error) {
      setMessage({ kind: 'error', text: errorMessage(error) })
    } finally {
      setBusy(false)
    }
  }

  async function runNow(): Promise<void> {
    if (!window.confirm(`Run the check now? ${target.name} will be power-${form.power_operation === 'on' ? 'on' : 'cycled'} and booked until it finishes.`)) return
    setRunning(true)
    setMessage({ kind: 'info', text: 'Running the check… this can take up to the boot timeout.' })
    try {
      const outcome = await runHealthCheck(target.id)
      setMessage({ kind: outcome.status === 'passed' ? 'success' : 'error', text: `${outcome.status}: ${outcome.message}` })
      onChanged()
      await loadResults()
    } catch (error) {
      setMessage({ kind: 'error', text: errorMessage(error) })
    } finally {
      setRunning(false)
    }
  }

  return (
    <section className="card" aria-label={`health check for ${target.name}`}>
      <h3 style={{ marginTop: 0 }}>{target.name}</h3>
      <p className="muted small">
        Powers the board and waits for text on its serial console. Needs one enabled serial and one enabled power capability.
        A board that fails repeatedly is put into maintenance and returns to service when a later check passes.
      </p>
      {message && <div className={`feedback ${message.kind}`} role={message.kind === 'error' ? 'alert' : 'status'}>{message.text}</div>}
      <form onSubmit={(event) => void save(event)} className="stack">
        <label className="small"><input type="checkbox" checked={form.enabled} onChange={(event) => patch({ enabled: event.target.checked })} /> Enabled</label>
        <label className="small">Text expected on the console
          <input className="input" aria-label="boot text" value={form.boot_pattern} required maxLength={200}
            placeholder="login:" onChange={(event) => patch({ boot_pattern: event.target.value })} />
        </label>
        <div className="grid two">
          <label className="small">Run every (minutes)
            <input className="input" type="number" aria-label="interval minutes" min={5} max={10080} value={form.interval_minutes}
              onChange={(event) => patch({ interval_minutes: Number(event.target.value) })} />
          </label>
          <label className="small">Wait up to (seconds)
            <input className="input" type="number" aria-label="boot timeout seconds" min={10} max={600} value={form.boot_timeout_seconds}
              onChange={(event) => patch({ boot_timeout_seconds: Number(event.target.value) })} />
          </label>
          <label className="small">Power action
            <select className="input" aria-label="power action" value={form.power_operation}
              onChange={(event) => patch({ power_operation: event.target.value as HealthCheckInput['power_operation'] })}>
              <option value="cycle">Power cycle</option>
              <option value="reset">Reset</option>
              <option value="on">Power on</option>
            </select>
          </label>
          <label className="small">Failures before maintenance
            <input className="input" type="number" aria-label="failure threshold" min={1} max={10} value={form.failure_threshold}
              onChange={(event) => patch({ failure_threshold: Number(event.target.value) })} />
          </label>
        </div>
        <label className="small"><input type="checkbox" checked={form.auto_maintenance}
          onChange={(event) => patch({ auto_maintenance: event.target.checked })} /> Put the board into maintenance when it keeps failing</label>
        <div className="toolbar">
          <button className="button" type="submit" disabled={busy || running}>Save</button>
          {check && <button type="button" className="button secondary" onClick={() => void runNow()} disabled={busy || running}>{running ? 'Running…' : 'Run now'}</button>}
          {check && <button type="button" className="button ghost danger" onClick={() => void remove()} disabled={busy || running}>Remove</button>}
        </div>
      </form>

      {check && (
        <>
          <h4 style={{ marginBottom: '0.3rem' }}>Recent results</h4>
          {results.length === 0 ? <p className="muted small">No results yet.</p> : (
            <div className="table-wrap">
              <table className="table" aria-label="recent results">
                <thead><tr><th>When</th><th>Result</th><th>How</th><th>Details</th></tr></thead>
                <tbody>
                  {results.map((item) => (
                    <tr key={item.started_at}>
                      <td>{prettyTime(item.started_at)}</td>
                      <td><span className={`badge ${item.status === 'passed' ? 'available' : item.status === 'failed' ? 'disabled' : 'maintenance'}`}>{item.status}</span></td>
                      <td>{item.trigger}</td>
                      <td className="small">{item.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  )
}

export default function AdminHealthChecks() {
  const [targets, setTargets] = useState<Target[]>([])
  const [checks, setChecks] = useState<Record<string, HealthCheck | null>>({})
  const [selected, setSelected] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const list = (await listTargets()).filter((target) => target.status !== 'retired')
      const entries = await Promise.all(list.map(async (target) => [target.id, await getHealthCheck(target.id)] as const))
      setTargets(list)
      setChecks(Object.fromEntries(entries))
      setMessage(null)
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const current = targets.find((target) => target.id === selected) || null

  return (
    <div className="grid" style={{ gap: '1rem' }}>
      <div className="card">
        <div className="page-head">
          <div>
            <h3 style={{ margin: 0 }}>Health checks</h3>
            <p className="muted" style={{ margin: '0.3rem 0 0' }}>Catch boards that stopped booting before an engineer does.</p>
          </div>
          <button className="button" onClick={() => void load()} disabled={loading}>{loading ? 'Loading…' : 'Refresh'}</button>
        </div>
      </div>
      {message && <div className="feedback error" role="alert">{message}</div>}

      <div className="card">
        <div className="table-wrap">
          <table className="table" aria-label="health check status">
            <thead><tr><th>Target</th><th>Board state</th><th>Check</th><th>Last run</th><th>Next run</th><th /></tr></thead>
            <tbody>
              {targets.map((target) => {
                const check = checks[target.id]
                const state = statusLabel(check)
                return (
                  <tr key={target.id}>
                    <td>{target.name}</td>
                    <td><span className={`badge ${target.status}`}>{target.status}</span></td>
                    <td className={state.tone}>{state.text}</td>
                    <td>{check?.last_run_at ? relativeTime(check.last_run_at) : '-'}</td>
                    <td>{check?.enabled && check.next_run_at ? relativeTime(check.next_run_at) : '-'}</td>
                    <td><button className="button ghost" onClick={() => setSelected(target.id)} aria-label={`configure ${target.name}`}>{check ? 'Edit' : 'Set up'}</button></td>
                  </tr>
                )
              })}
              {!loading && targets.length === 0 && <tr><td colSpan={6} className="muted">No targets yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      {current && <Editor key={`${current.id}:${checks[current.id] ? 'configured' : 'new'}`} target={current} check={checks[current.id] ?? null} onChanged={() => void load()} />}
    </div>
  )
}
