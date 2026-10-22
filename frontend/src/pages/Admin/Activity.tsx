import React, { useEffect, useState } from 'react'

import { listAuditEntries } from '../../services/api'
import type { AuditEntry } from '../../services/types'
import { errorMessage, prettyDate } from '../../utils/ui'

export default function AdminActivity() {
  const [entries, setEntries] = useState<AuditEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [limit, setLimit] = useState(100)
  const [userId, setUserId] = useState('')
  const [targetId, setTargetId] = useState('')
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    void load()
  }, [])

  async function load(): Promise<void> {
    setLoading(true)
    setMessage(null)
    try {
      const rows = await listAuditEntries({
        limit,
        user_id: userId.trim() || undefined,
        target_id: targetId.trim() || undefined,
      })
      setEntries(rows)
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="grid" style={{ gap: '0.8rem' }}>
      {message && <div className="feedback error">{message}</div>}

      <div className="card">
        <div className="page-head">
          <h3 style={{ margin: 0 }}>Activity log</h3>
          <button className="button" onClick={() => void load()} disabled={loading}>
            {loading ? 'Loading...' : 'Apply filters'}
          </button>
        </div>
        <div className="grid three">
          <label>
            <span className="muted">User ID</span>
            <input className="input" value={userId} onChange={(event) => setUserId(event.target.value)} />
          </label>
          <label>
            <span className="muted">Target ID</span>
            <input className="input" value={targetId} onChange={(event) => setTargetId(event.target.value)} />
          </label>
          <label>
            <span className="muted">Limit</span>
            <input
              className="input"
              type="number"
              min={1}
              max={1000}
              value={limit}
              onChange={(event) => setLimit(Math.max(1, Number(event.target.value || 100)))}
            />
          </label>
        </div>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>User</th>
              <th>Action</th>
              <th>Capability</th>
              <th>Operation</th>
              <th>Result</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>
            {!loading && entries.length === 0 ? (
              <tr>
                <td colSpan={7} className="empty">
                  No activity records found.
                </td>
              </tr>
            ) : (
              entries.map((entry) => (
                <tr key={entry.id}>
                  <td>{prettyDate(entry.created_at)}</td>
                  <td>{entry.user_id || '-'}</td>
                  <td>{entry.action}</td>
                  <td>{entry.capability_type || '-'}</td>
                  <td>{entry.operation || '-'}</td>
                  <td>{entry.success ? 'ok' : 'failed'}</td>
                  <td>{entry.detail || '-'}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
