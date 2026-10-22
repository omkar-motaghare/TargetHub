import React, { useEffect, useMemo, useState } from 'react'

import { listAgents, listLabs } from '../../services/api'
import type { Agent } from '../../services/types'
import { errorMessage } from '../../utils/ui'

export default function AdminConfig() {
  const [labs, setLabs] = useState<string[]>([])
  const [agents, setAgents] = useState<Agent[]>([])
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    void load()
  }, [])

  async function load(): Promise<void> {
    setLoading(true)
    setMessage(null)
    try {
      const [labRows, agentRows] = await Promise.all([listLabs(), listAgents()])
      setLabs(labRows)
      setAgents(agentRows)
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }

  const online = useMemo(() => agents.filter((agent) => agent.enabled && agent.status === 'online').length, [agents])
  const offline = useMemo(() => agents.length - online, [agents.length, online])
  const resources = useMemo(
    () => agents.reduce((count, agent) => count + (agent.resources || []).filter((resource) => resource.available).length, 0),
    [agents],
  )

  return (
    <div className="grid" style={{ gap: '0.9rem' }}>
      {message && <div className="feedback error">{message}</div>}

      <div className="card">
        <div className="page-head">
          <h3 style={{ margin: 0 }}>Operational configuration</h3>
          <button className="button" onClick={() => void load()} disabled={loading}>
            {loading ? 'Loading...' : 'Refresh'}
          </button>
        </div>
        <p className="muted">
          Runtime configuration remains server-managed. This page shows backend-derived operational state for admin
          maintenance workflows.
        </p>
      </div>

      <div className="grid three">
        <div className="card">
          <div className="muted">Known labs</div>
          <h3>{labs.length}</h3>
        </div>
        <div className="card">
          <div className="muted">Online agents</div>
          <h3>{online}</h3>
        </div>
        <div className="card">
          <div className="muted">Available resources</div>
          <h3>{resources}</h3>
        </div>
      </div>

      <div className="card">
        <h4 style={{ marginTop: 0 }}>Lab inventory</h4>
        {labs.length ? (
          <div style={{ display: 'flex', gap: '0.55rem', flexWrap: 'wrap' }}>
            {labs.map((lab) => (
              <span key={lab} className="inline-note">
                {lab}
              </span>
            ))}
          </div>
        ) : (
          <div className="inline-note">No lab names reported yet.</div>
        )}
      </div>

      <div className="card">
        <h4 style={{ marginTop: 0 }}>Agent availability</h4>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Agent</th>
                <th>Status</th>
                <th>Enabled</th>
                <th>Available resources</th>
              </tr>
            </thead>
            <tbody>
              {agents.length ? (
                agents.map((agent) => (
                  <tr key={agent.id}>
                    <td>{agent.name}</td>
                    <td>{agent.status}</td>
                    <td>{agent.enabled ? 'yes' : 'no'}</td>
                    <td>{agent.resources.filter((resource) => resource.available).length}</td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td className="empty" colSpan={4}>
                    No agents available.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <p className="muted" style={{ marginBottom: 0 }}>
          Offline agents or zero available resources will prevent resource-backed capability execution.
        </p>
      </div>

      <div className="inline-note">Offline-agent and unavailable-resource conditions should be treated as operational alerts.</div>
    </div>
  )
}
