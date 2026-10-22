import React, { useEffect, useState } from 'react'

import {
  createAgentEnrollment,
  disableAgent,
  enableAgent,
  listAgentEnrollments,
  listAgents,
  revokeAgentCredential,
} from '../../services/api'
import type { Agent, AgentEnrollment } from '../../services/types'
import { errorMessage, prettyDate } from '../../utils/ui'

export default function AdminAgents() {
  const [name, setName] = useState('')
  const [agents, setAgents] = useState<Agent[]>([])
  const [enrollments, setEnrollments] = useState<AgentEnrollment[]>([])
  const [latestEnrollment, setLatestEnrollment] = useState<AgentEnrollment | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    void load()
  }, [])

  async function load(): Promise<void> {
    setLoading(true)
    setMessage(null)
    try {
      const [agentRows, enrollmentRows] = await Promise.all([listAgents(), listAgentEnrollments()])
      setAgents(agentRows)
      setEnrollments(enrollmentRows)
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }

  async function handleCreate(event: React.FormEvent): Promise<void> {
    event.preventDefault()
    if (!name.trim()) {
      setMessage('Agent name is required.')
      return
    }
    setBusy(true)
    setMessage(null)
    try {
      const res = await createAgentEnrollment(name)
      setLatestEnrollment(res)
      setName('')
      await load()
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  async function handleDisable(agentId: string): Promise<void> {
    setBusy(true)
    setMessage(null)
    try {
      await disableAgent(agentId)
      await load()
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  async function handleEnable(agentId: string): Promise<void> {
    setBusy(true)
    setMessage(null)
    try {
      await enableAgent(agentId)
      await load()
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  async function handleRevoke(agentId: string): Promise<void> {
    if (!confirm('Revoke current agent credential?')) return
    setBusy(true)
    setMessage(null)
    try {
      await revokeAgentCredential(agentId)
      await load()
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid" style={{ gap: '1rem' }}>
      {message && <div className="feedback error">{message}</div>}

      <div className="card">
        <div className="page-head">
          <h3 style={{ margin: 0 }}>Create enrollment</h3>
          <button className="button ghost" onClick={() => void load()} disabled={loading || busy}>
            {loading ? 'Loading...' : 'Refresh'}
          </button>
        </div>
        <form onSubmit={handleCreate}>
          <div className="grid two">
            <input
              className="input"
              placeholder="Agent name"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
            <button className="button" type="submit" disabled={busy}>
              {busy ? 'Creating...' : 'Create Enrollment'}
            </button>
          </div>
        </form>
      </div>

      {latestEnrollment && (
        <div className="card">
          <h4 style={{ marginTop: 0 }}>Latest enrollment token</h4>
          <p className="inline-note">Token: {latestEnrollment.token || '-'}</p>
          <p className="muted" style={{ marginBottom: '0.4rem' }}>
            Expires: {prettyDate(latestEnrollment.expires_at)}
          </p>
          <p className="muted">Install command:</p>
          <pre className="log-console">{latestEnrollment.install_command || 'No install command returned.'}</pre>
        </div>
      )}

      <div className="card">
        <h3 style={{ marginTop: 0 }}>Agents</h3>
        <div className="list">
          {!loading && agents.length === 0 && <div className="card">No agents discovered yet.</div>}
          {agents.map((agent) => {
            const online = agent.enabled && agent.status === 'online'
            return (
              <article className="list-item stacked" key={agent.id}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.6rem' }}>
                  <div>
                    <div style={{ fontWeight: 700 }}>{agent.name}</div>
                    <div className="muted">Host: {agent.hostname || 'unknown-host'}</div>
                    <div className="muted">Last seen: {prettyDate(agent.last_seen_at)}</div>
                  </div>
                  <span className={`badge ${online ? 'available' : 'disabled'}`}>{online ? 'online' : 'offline'}</span>
                </div>

                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Resource</th>
                        <th>Type</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {agent.resources.length ? (
                        agent.resources.map((resource) => (
                          <tr key={resource.id}>
                            <td>{resource.display_name}</td>
                            <td>{resource.resource_type}</td>
                            <td>{resource.available ? 'available' : 'unavailable'}</td>
                          </tr>
                        ))
                      ) : (
                        <tr>
                          <td className="empty" colSpan={3}>
                            No discovered resources
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>

                <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                  {agent.enabled ? (
                    <button className="button secondary" onClick={() => void handleDisable(agent.id)} disabled={busy}>
                      Disable
                    </button>
                  ) : (
                    <button className="button" onClick={() => void handleEnable(agent.id)} disabled={busy}>
                      Enable
                    </button>
                  )}
                  <button className="button ghost" onClick={() => void handleRevoke(agent.id)} disabled={busy}>
                    Revoke credential
                  </button>
                </div>
              </article>
            )
          })}
        </div>
      </div>

      <div className="card">
        <h3 style={{ marginTop: 0 }}>Recent enrollments</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Agent name</th>
                <th>Created</th>
                <th>Expires</th>
                <th>Used</th>
              </tr>
            </thead>
            <tbody>
              {enrollments.length ? (
                enrollments.map((entry) => (
                  <tr key={entry.id}>
                    <td>{entry.agent_name}</td>
                    <td>{prettyDate(entry.created_at)}</td>
                    <td>{prettyDate(entry.expires_at)}</td>
                    <td>{entry.used_at ? prettyDate(entry.used_at) : 'not used'}</td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td className="empty" colSpan={4}>
                    No enrollments
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
