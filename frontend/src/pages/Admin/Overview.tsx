import React, { useEffect, useState } from 'react'
import { Link } from 'react-router'

import { getSystemOverview } from '../../services/api'
import type { SystemOverview } from '../../services/types'
import { errorMessage } from '../../utils/ui'

function Stat({ label, value, tone, hint }: { label: string; value: React.ReactNode; tone?: string; hint?: string }) {
  return (
    <div className="card stat">
      <div className="muted">{label}</div>
      <h3 className={tone}>{value}</h3>
      {hint && <div className="muted small">{hint}</div>}
    </div>
  )
}

export default function AdminOverview() {
  const [data, setData] = useState<SystemOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState<string | null>(null)

  async function load(): Promise<void> {
    setLoading(true)
    try {
      setData(await getSystemOverview())
      setMessage(null)
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
    const timer = window.setInterval(() => void load(), 30_000)
    return () => window.clearInterval(timer)
  }, [])

  const errors = data?.issues.filter((issue) => issue.severity === 'error') || []
  const warnings = data?.issues.filter((issue) => issue.severity === 'warning') || []

  return (
    <div className="grid" style={{ gap: '0.9rem' }}>
      <div className="card">
        <div className="page-head">
          <div>
            <h3 style={{ margin: 0 }}>Lab overview</h3>
            <p className="muted" style={{ margin: '0.3rem 0 0' }}>Live state of the lab and anything that needs an administrator.</p>
          </div>
          <button className="button" onClick={() => void load()} disabled={loading}>{loading ? 'Loading…' : 'Refresh'}</button>
        </div>
      </div>

      {message && <div className="feedback error">{message}</div>}

      {data && (
        <>
          <div className="grid four">
            <Stat label="Targets" value={data.targets.total}
              hint={`${data.targets.available || 0} available · ${data.targets.maintenance || 0} maintenance`} />
            <Stat label="Active reservations" value={data.reservations_active}
              hint={`${data.waitlist_waiting} waiting in queues`} />
            <Stat label="Open sessions" value={data.sessions_active} />
            <Stat label="Agents online" value={`${data.agents.online} / ${data.agents.total}`}
              tone={data.agents.total && data.agents.online < data.agents.total - data.agents.disabled ? 'warn' : 'ok'}
              hint={data.agents.disabled ? `${data.agents.disabled} disabled` : undefined} />
          </div>

          <div className="card">
            <div className="page-head">
              <h3 style={{ margin: 0 }}>Configuration check</h3>
              <Link className="button secondary" to="/admin/targets">Open targets</Link>
            </div>
            {data.issues.length === 0 ? (
              <p className="feedback success" style={{ marginBottom: 0 }}>No problems found: every enabled capability has a working backend configuration.</p>
            ) : (
              <ul className="issue-list">
                {[...errors, ...warnings].map((issue, index) => (
                  <li key={index} className={`issue ${issue.severity}`}>
                    <span className={`issue-badge ${issue.severity}`}>{issue.severity === 'error' ? 'Error' : 'Warning'}</span>
                    {issue.message}
                  </li>
                ))}
              </ul>
            )}
            <p className="muted small" style={{ marginBottom: 0 }}>
              Checks Agent bindings and status, power drivers, simulated capabilities and that every secret environment
              variable referenced by a capability is set on the server. Use <strong>Test connection</strong> in the target
              editor to reach a DD or HTTP power controller.
            </p>
          </div>

          <div className="card">
            <h3 style={{ marginTop: 0 }}>Server</h3>
            <dl className="kv">
              <dt>Version</dt><dd>{data.version}</dd>
              <dt>Environment</dt><dd>{data.environment}</dd>
              <dt>Database</dt><dd>{data.database}</dd>
              <dt>Public URL</dt><dd className="mono">{data.public_url}</dd>
              <dt>Users</dt><dd>{data.users.active} active of {data.users.total}</dd>
              <dt>Background maintenance</dt><dd>{data.scheduler_enabled ? 'running' : 'disabled (SCHEDULER_ENABLED=false)'}</dd>
              <dt>Simulated providers</dt>
              <dd>{data.simulation_enabled ? <span className="warn-text">allowed (demo/test mode)</span> : 'disabled'}</dd>
            </dl>
            {data.public_url.includes('localhost') && (
              <div className="inline-note warn">
                TARGETHUB_PUBLIC_URL points at localhost. Agents on other machines cannot use the generated install commands;
                set it to the address users and agents use.
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
