import React, { useEffect, useMemo, useState } from 'react'

import {
  closeSession,
  executeSessionOperation,
  listSessionOperations,
  listSessions,
  serialRead,
  serialWrite,
} from '../services/api'
import { useAuth } from '../services/auth'
import type { Session } from '../services/types'
import { errorMessage, prettyDate } from '../utils/ui'

const PARAMETER_PROMPTS: Record<string, { key: string; label: string }> = {
  write: { key: 'text', label: 'Text to write' },
  exec: { key: 'command', label: 'Command to execute' },
  deploy: { key: 'artifact', label: 'Artifact name' },
}

export default function Sessions() {
  const auth = useAuth()
  const [sessions, setSessions] = useState<Session[]>([])
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [operationConsole, setOperationConsole] = useState<string>('No session output yet.')

  useEffect(() => {
    void refresh()
  }, [])

  async function refresh(): Promise<void> {
    setLoading(true)
    setMessage(null)
    try {
      setSessions(await listSessions())
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }

  async function handleClose(sessionId: string): Promise<void> {
    if (!auth.user) return
    setBusy(true)
    setMessage(null)
    try {
      await closeSession(sessionId, auth.user.username)
      await refresh()
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  function appendConsole(session: Session, operation: string, result: Record<string, unknown>): void {
    const stamp = new Date().toLocaleTimeString()
    const info = `[${stamp}] ${session.capability_type}/${operation}`
    const body = JSON.stringify(result, null, 2)
    setOperationConsole((current) => {
      const base = current === 'No session output yet.' ? '' : `${current}\n`
      return `${base}${info}\n${body}`
    })
  }

  async function runOperation(session: Session, operation: string): Promise<void> {
    setBusy(true)
    setMessage(null)
    try {
      let result: Record<string, unknown>
      if (session.capability_type === 'serial' && operation === 'read') {
        result = (await serialRead(session.id)) as unknown as Record<string, unknown>
      } else if (session.capability_type === 'serial' && operation === 'write') {
        const promptValue = window.prompt('Text to write to serial session')
        if (promptValue === null) return
        result = (await serialWrite(session.id, promptValue)) as unknown as Record<string, unknown>
      } else {
        const template = PARAMETER_PROMPTS[operation]
        const params: Record<string, unknown> = {}
        if (template) {
          const entered = window.prompt(template.label)
          if (entered === null) return
          params[template.key] = entered
        }
        result = (await executeSessionOperation(session.id, operation, params)) as unknown as Record<string, unknown>
      }
      appendConsole(session, operation, result)
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  async function handleOperations(session: Session): Promise<void> {
    setBusy(true)
    setMessage(null)
    try {
      const operations = await listSessionOperations(session.id)
      if (!operations.length) {
        setMessage('No operations are available for this session.')
        return
      }
      const selected = window.prompt(
        `Available operations: ${operations.join(', ')}\nType the operation to run:`,
        operations[0],
      )
      if (!selected) return
      if (!operations.includes(selected)) {
        setMessage(`Operation '${selected}' is not available for this session.`)
        return
      }
      await runOperation(session, selected)
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  const mine = useMemo(
    () => sessions.filter((session) => session.user_id === auth.user?.username),
    [sessions, auth.user?.username],
  )

  return (
    <div>
      <div className="page-head">
        <div>
          <h2 className="page-title">My Sessions</h2>
          <p className="muted">Discover capability operations, execute commands, and close sessions safely.</p>
        </div>
        <button className="button" onClick={() => void refresh()} disabled={loading || busy}>
          {loading ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      {message && <div className="feedback error">{message}</div>}

      <div className="list">
        {!loading && mine.length === 0 && <div className="card">No sessions yet. Open one from My Reservations.</div>}
        {mine.map((session) => (
          <article key={session.id} className="list-item">
            <div>
              <div style={{ fontWeight: 700 }}>
                {session.capability_type} on target {session.target_id}
              </div>
              <div className="muted">
                Status: {session.status} | Expires: {prettyDate(session.expires_at)}
              </div>
              {session.provider_key && <div className="muted">Provider: {session.provider_key}</div>}
            </div>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              {session.status === 'active' && (
                <>
                  <button className="button ghost" onClick={() => void handleOperations(session)} disabled={busy}>
                    Operations
                  </button>
                  <button className="button secondary" onClick={() => void handleClose(session.id)} disabled={busy}>
                    Close Session
                  </button>
                </>
              )}
            </div>
          </article>
        ))}
      </div>

      <section className="card" style={{ marginTop: '0.8rem' }}>
        <h3>Session output</h3>
        <pre className="log-console">{operationConsole}</pre>
      </section>
    </div>
  )
}
