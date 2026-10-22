import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import {
  closeSession,
  executeSessionOperation,
  getSession,
  listSessionOperations,
  serialRead,
  serialWrite,
} from '../services/api'
import { useAuth } from '../services/auth'
import type { Session } from '../services/types'
import { errorMessage, prettyDate } from '../utils/ui'

const SERIAL_POLL_MS = 1000
const POWER_OPERATIONS = ['on', 'off', 'status', 'cycle', 'reset']

function SerialTerminal({ session, onError }: { session: Session; onError: (message: string) => void }) {
  const [output, setOutput] = useState('')
  const [line, setLine] = useState('')
  const [ready, setReady] = useState(false)
  const screen = useRef<HTMLPreElement>(null)

  useEffect(() => {
    let cancelled = false
    executeSessionOperation(session.id, 'open', {})
      .then(() => {
        if (!cancelled) setReady(true)
      })
      .catch((error) => {
        if (!cancelled) onError(errorMessage(error))
      })
    return () => {
      cancelled = true
    }
  }, [session.id, onError])

  useEffect(() => {
    if (!ready) return
    let cancelled = false
    const timer = window.setInterval(() => {
      serialRead(session.id)
        .then((result) => {
          const text = result.data.data_text
          if (!cancelled && typeof text === 'string' && text) setOutput((current) => current + text)
        })
        .catch((error) => {
          if (!cancelled) onError(errorMessage(error))
        })
    }, SERIAL_POLL_MS)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [ready, session.id, onError])

  useEffect(() => {
    if (screen.current) screen.current.scrollTop = screen.current.scrollHeight
  }, [output])

  async function send(event: React.FormEvent): Promise<void> {
    event.preventDefault()
    try {
      await serialWrite(session.id, `${line}\n`)
      setLine('')
    } catch (error) {
      onError(errorMessage(error))
    }
  }

  return (
    <section className="card">
      <h3>Serial terminal</h3>
      <pre className="log-console" ref={screen} aria-label="serial output">
        {output || (ready ? 'Waiting for device output...' : 'Opening serial port...')}
      </pre>
      <form onSubmit={(event) => void send(event)} style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem' }}>
        <input
          aria-label="serial input"
          value={line}
          onChange={(event) => setLine(event.target.value)}
          disabled={!ready}
          style={{ flex: 1 }}
        />
        <button className="button" type="submit" disabled={!ready}>
          Send
        </button>
        <button className="button ghost" type="button" onClick={() => setOutput('')}>
          Clear
        </button>
      </form>
    </section>
  )
}

function PowerPanel({
  operations,
  run,
  busy,
}: {
  operations: string[]
  run: (operation: string) => Promise<void>
  busy: boolean
}) {
  return (
    <section className="card">
      <h3>Power control</h3>
      <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
        {POWER_OPERATIONS.filter((operation) => operations.includes(operation)).map((operation) => (
          <button
            key={operation}
            className={operation === 'off' || operation === 'cycle' || operation === 'reset' ? 'button secondary' : 'button'}
            onClick={() => void run(operation)}
            disabled={busy}
            type="button"
          >
            {operation}
          </button>
        ))}
      </div>
    </section>
  )
}

function DeployPanel({
  run,
  busy,
}: {
  run: (operation: string, params: Record<string, unknown>) => Promise<void>
  busy: boolean
}) {
  const [url, setUrl] = useState('')
  const [sha256, setSha256] = useState('')

  return (
    <section className="card">
      <h3>Deploy artifact</h3>
      <form
        onSubmit={(event) => {
          event.preventDefault()
          void run('deploy', { url, sha256 })
        }}
        style={{ display: 'grid', gap: '0.5rem' }}
      >
        <input aria-label="artifact url" placeholder="https://host/firmware.bin" value={url} onChange={(e) => setUrl(e.target.value)} required />
        <input
          aria-label="artifact sha256"
          placeholder="sha256 (64 hex chars)"
          value={sha256}
          onChange={(e) => setSha256(e.target.value)}
          pattern="[0-9a-fA-F]{64}"
          required
        />
        <button className="button" type="submit" disabled={busy}>
          Deploy
        </button>
      </form>
    </section>
  )
}

export default function SessionWorkspace() {
  const { sessionId = '' } = useParams()
  const auth = useAuth()
  const [session, setSession] = useState<Session | null>(null)
  const [operations, setOperations] = useState<string[]>([])
  const [log, setLog] = useState<string[]>([])
  const [message, setMessage] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const showError = useCallback((text: string) => setMessage(text), [])

  useEffect(() => {
    let cancelled = false
    async function load(): Promise<void> {
      try {
        const loaded = await getSession(sessionId)
        if (cancelled) return
        setSession(loaded)
        if (loaded.status === 'active') {
          const available = await listSessionOperations(sessionId)
          if (!cancelled) setOperations(available.operations)
        }
      } catch (error) {
        if (!cancelled) setMessage(errorMessage(error))
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [sessionId])

  async function run(operation: string, params: Record<string, unknown> = {}): Promise<void> {
    setBusy(true)
    setMessage(null)
    try {
      const result = await executeSessionOperation(sessionId, operation, params)
      const detail = Object.keys(result.data).length ? ` ${JSON.stringify(result.data)}` : ''
      setLog((current) => [...current, `[${new Date().toLocaleTimeString()}] ${operation}: ${result.message}${detail}`])
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  async function handleClose(): Promise<void> {
    if (!auth.user) return
    setBusy(true)
    try {
      setSession(await closeSession(sessionId, auth.user.username))
      setOperations([])
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  if (!session) {
    return message ? <div className="feedback error">{message}</div> : <div className="card">Loading session...</div>
  }

  const active = session.status === 'active'

  return (
    <div>
      <div className="page-head">
        <div>
          <h2 className="page-title">
            {session.capability_type} session
          </h2>
          <p className="muted">
            Target {session.target_id} | Status: {session.status} | Expires: {prettyDate(session.expires_at)}
          </p>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <Link to="/sessions" className="button ghost">
            Back
          </Link>
          {active && (
            <button className="button secondary" onClick={() => void handleClose()} disabled={busy} type="button">
              Close Session
            </button>
          )}
        </div>
      </div>

      {message && <div className="feedback error">{message}</div>}
      {!active && <div className="card">This session is {session.status}; operations are unavailable.</div>}

      {active && session.capability_type === 'serial' && <SerialTerminal session={session} onError={showError} />}
      {active && session.capability_type === 'power' && <PowerPanel operations={operations} run={run} busy={busy} />}
      {active && session.capability_type === 'deploy' && <DeployPanel run={run} busy={busy} />}
      {active && !['serial', 'power', 'deploy'].includes(session.capability_type) && (
        <section className="card">
          <h3>Operations</h3>
          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
            {operations.map((operation) => (
              <button key={operation} className="button" onClick={() => void run(operation)} disabled={busy} type="button">
                {operation}
              </button>
            ))}
          </div>
        </section>
      )}

      <section className="card" style={{ marginTop: '0.8rem' }}>
        <h3>Operation log</h3>
        <pre className="log-console">{log.length ? log.join('\n') : 'No operations yet.'}</pre>
      </section>
    </div>
  )
}
