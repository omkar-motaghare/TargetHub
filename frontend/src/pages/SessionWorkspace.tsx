import React, { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router'

import SerialConsole from '../components/SerialConsole'
import {
  closeSession,
  deleteArtifact,
  executeSessionOperation,
  getOperationStatus,
  getSession,
  getTarget,
  listArtifacts,
  listSessionOperations,
  serialLog,
  submitSessionOperation,
  uploadArtifact,
} from '../services/api'
import type { Artifact, ProviderResult, Session, Target } from '../services/types'
import { capabilityModeLabel, downloadText, errorMessage, prettyTime, relativeTime } from '../utils/ui'

const POWER_OPERATIONS: { op: string; label: string; confirm?: string }[] = [
  { op: 'on', label: 'Power on' },
  { op: 'off', label: 'Power off', confirm: 'Power the target off?' },
  { op: 'cycle', label: 'Power cycle', confirm: 'Power-cycle the target? It will reboot.' },
  { op: 'reset', label: 'Reset', confirm: 'Reset the target? It will reboot.' },
  { op: 'status', label: 'Refresh status' },
]

type LogLine = { at: string; text: string; ok: boolean }

function powerState(result: ProviderResult | null): string | null {
  const data = result?.data || {}
  const value = (data.power ?? data.state) as string | undefined
  return typeof value === 'string' ? value : null
}

function PowerPanel({ sessionId, operations, log }: { sessionId: string; operations: string[]; log: (line: LogLine) => void }) {
  const [state, setState] = useState<string | null>(null)
  const [confirmed, setConfirmed] = useState<boolean | null>(null)
  const [running, setRunning] = useState<string | null>(null)

  const run = useCallback(
    async (operation: string, confirmText?: string) => {
      if (confirmText && !window.confirm(confirmText)) return
      setRunning(operation)
      try {
        const result = await executeSessionOperation(sessionId, operation)
        setState(powerState(result) ?? state)
        const data = result.data || {}
        setConfirmed(typeof data.confirmed === 'boolean' ? (data.confirmed as boolean) : null)
        log({ at: new Date().toISOString(), text: `${operation}: ${result.message}`, ok: true })
      } catch (error) {
        log({ at: new Date().toISOString(), text: `${operation}: ${errorMessage(error)}`, ok: false })
      } finally {
        setRunning(null)
      }
    },
    [sessionId, log, state],
  )

  useEffect(() => {
    if (operations.includes('status')) void run('status')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [operations.join(',')])

  return (
    <section className="card">
      <div className="page-head">
        <h3 style={{ margin: 0 }}>Power</h3>
        <span className={`power-state ${state || 'unknown'}`} aria-label="power state">
          {state ? state.toUpperCase() : 'UNKNOWN'}
          {confirmed === false && ' (unconfirmed)'}
        </span>
      </div>
      <div className="toolbar">
        {POWER_OPERATIONS.filter((item) => operations.includes(item.op)).map((item) => (
          <button key={item.op} type="button" disabled={running !== null}
            className={item.op === 'on' || item.op === 'status' ? 'button' : 'button secondary'}
            onClick={() => void run(item.op, item.confirm)}>
            {running === item.op ? `${item.label}…` : item.label}
          </button>
        ))}
      </div>
      {running && <p className="muted small">Waiting for the power system to confirm…</p>}
    </section>
  )
}

function formatSize(bytes: number): string {
  if (bytes >= 1_048_576) return `${(bytes / 1_048_576).toFixed(1)} MiB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KiB`
  return `${bytes} B`
}

function DeployPanel({ sessionId, log }: { sessionId: string; log: (line: LogLine) => void }) {
  const [mode, setMode] = useState<'upload' | 'url'>('upload')
  const [url, setUrl] = useState('')
  const [sha256, setSha256] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [artifacts, setArtifacts] = useState<Artifact[]>([])
  const [artifactId, setArtifactId] = useState('')
  const [status, setStatus] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const refreshArtifacts = useCallback(async () => {
    try {
      const mine = await listArtifacts(true)
      setArtifacts(Array.isArray(mine) ? mine.slice(0, 20) : [])
    } catch {
      setArtifacts([]) // the list is a convenience; deploying by URL still works
    }
  }, [])

  useEffect(() => {
    void refreshArtifacts()
  }, [refreshArtifacts])

  async function deploy(event: React.FormEvent): Promise<void> {
    event.preventDefault()
    setBusy(true)
    setStatus('queued')
    try {
      let params: Record<string, unknown> = { url, sha256 }
      if (mode === 'upload') {
        let chosen = artifactId
        if (!chosen) {
          if (!file) throw new Error('Choose a firmware file or a previously uploaded image.')
          setStatus('uploading')
          const uploaded = await uploadArtifact(file)
          chosen = uploaded.id
          setArtifactId(uploaded.id)
          setFile(null)
          log({ at: new Date().toISOString(), text: `uploaded ${uploaded.name} (${formatSize(uploaded.size_bytes)}, sha256 ${uploaded.sha256.slice(0, 12)}…)`, ok: true })
          void refreshArtifacts()
        }
        params = { artifact_id: chosen }
        setStatus('queued')
      }
      const queued = await submitSessionOperation(sessionId, 'deploy', params)
      if (!queued.operation_id) {
        log({ at: new Date().toISOString(), text: `deploy: ${queued.message}`, ok: true })
        setStatus('completed')
        return
      }
      for (;;) {
        await new Promise((resolve) => setTimeout(resolve, 1500))
        const current = await getOperationStatus(sessionId, queued.operation_id)
        setStatus(current.status)
        if (['completed', 'failed', 'cancelled', 'timed_out'].includes(current.status)) {
          const output = (current.data?.output as string | undefined) || ''
          log({
            at: new Date().toISOString(),
            text: `deploy ${current.status}: ${current.message || ''}${output ? `\n${output}` : ''}`,
            ok: current.status === 'completed',
          })
          break
        }
      }
    } catch (error) {
      setStatus('failed')
      log({ at: new Date().toISOString(), text: `deploy: ${errorMessage(error)}`, ok: false })
    } finally {
      setBusy(false)
    }
  }

  async function removeSelected(): Promise<void> {
    if (!artifactId || !window.confirm('Delete this uploaded firmware from TargetHub?')) return
    try {
      await deleteArtifact(artifactId)
      setArtifactId('')
      void refreshArtifacts()
    } catch (error) {
      log({ at: new Date().toISOString(), text: `delete artifact: ${errorMessage(error)}`, ok: false })
    }
  }

  return (
    <section className="card">
      <h3 style={{ marginTop: 0 }}>Deploy firmware</h3>
      <p className="muted small">The Agent downloads the firmware, verifies its SHA-256 and runs the flash command configured on the Agent host.</p>
      <div className="chip-row" role="group" aria-label="firmware source">
        <button type="button" className={`chip ${mode === 'upload' ? 'active' : ''}`} onClick={() => setMode('upload')}>Upload a file</button>
        <button type="button" className={`chip ${mode === 'url' ? 'active' : ''}`} onClick={() => setMode('url')}>Use a URL</button>
      </div>
      <form onSubmit={(event) => void deploy(event)} className="stack" style={{ marginTop: '0.6rem' }}>
        {mode === 'upload' ? (
          <>
            <input className="input" type="file" aria-label="firmware file"
              onChange={(event) => { setFile(event.target.files?.[0] ?? null); setArtifactId('') }} />
            {artifacts.length > 0 && (
              <div className="toolbar">
                <select className="input" aria-label="uploaded firmware" value={artifactId}
                  onChange={(event) => { setArtifactId(event.target.value); if (event.target.value) setFile(null) }}>
                  <option value="">Or pick one you uploaded earlier…</option>
                  {artifacts.map((item) => (
                    <option key={item.id} value={item.id}>{item.name} · {formatSize(item.size_bytes)} · {item.sha256.slice(0, 8)}</option>
                  ))}
                </select>
                {artifactId && <button type="button" className="button ghost danger" onClick={() => void removeSelected()}>Delete</button>}
              </div>
            )}
            <p className="muted small">Uploaded files are stored on the TargetHub server and handed to the Agent through a short-lived link.</p>
          </>
        ) : (
          <>
            <input className="input" aria-label="artifact url" placeholder="https://artifacts.example.com/firmware.bin"
              value={url} onChange={(event) => setUrl(event.target.value)} required />
            <input className="input mono" aria-label="artifact sha256" placeholder="sha256 (64 hex characters)" value={sha256}
              onChange={(event) => setSha256(event.target.value.trim())} pattern="[0-9a-fA-F]{64}" required />
          </>
        )}
        <div className="toolbar">
          <button className="button" type="submit" disabled={busy}>{busy ? 'Deploying…' : 'Deploy'}</button>
          {status && <span className={`status-pill ${status}`}>{status.replace('_', ' ')}</span>}
        </div>
      </form>
    </section>
  )
}

export default function SessionWorkspace() {
  const { sessionId = '' } = useParams()
  const [session, setSession] = useState<Session | null>(null)
  const [target, setTarget] = useState<Target | null>(null)
  const [operations, setOperations] = useState<string[]>([])
  const [log, setLog] = useState<LogLine[]>([])
  const [message, setMessage] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [, setTick] = useState(0)
  const addLog = useCallback((line: LogLine) => setLog((current) => [...current.slice(-199), line]), [])

  const load = useCallback(async () => {
    try {
      const loaded = await getSession(sessionId)
      setSession(loaded)
      getTarget(loaded.target_id).then(setTarget).catch(() => undefined)
      if (loaded.status === 'active') setOperations((await listSessionOperations(sessionId)).operations)
    } catch (error) {
      setMessage(errorMessage(error))
    }
  }, [sessionId])

  useEffect(() => {
    void load()
    const timer = window.setInterval(() => setTick((value) => value + 1), 30_000)
    return () => window.clearInterval(timer)
  }, [load])

  async function handleClose(): Promise<void> {
    setBusy(true)
    try {
      setSession(await closeSession(sessionId))
      setOperations([])
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  async function runGeneric(operation: string): Promise<void> {
    setBusy(true)
    try {
      const result = await executeSessionOperation(sessionId, operation)
      const detail = result.data && Object.keys(result.data).length ? ` ${JSON.stringify(result.data)}` : ''
      addLog({ at: new Date().toISOString(), text: `${operation}: ${result.message}${detail}`, ok: true })
    } catch (error) {
      addLog({ at: new Date().toISOString(), text: `${operation}: ${errorMessage(error)}`, ok: false })
    } finally {
      setBusy(false)
    }
  }

  const onConsoleEnded = useCallback(() => void load(), [load])

  if (!session) {
    return message ? <div className="feedback error">{message}</div> : <div className="card">Loading session…</div>
  }

  const active = session.status === 'active'
  const capability = target?.capabilities.find((item) => item.id === session.capability_id)
  const kind = session.capability_type

  return (
    <div>
      <div className="page-head">
        <div>
          <h2 className="page-title">
            {target?.name || 'Target'} · {capability?.name || kind}
          </h2>
          <p className="muted">
            {capability ? `${capabilityModeLabel(capability)} · ` : ''}
            {active ? `Session ends ${prettyTime(session.expires_at)} (${relativeTime(session.expires_at)})` : `Session ${session.status}`}
          </p>
        </div>
        <div className="toolbar">
          <Link to="/my" className="button ghost">Back</Link>
          {active && (
            <button className="button secondary" onClick={() => void handleClose()} disabled={busy} type="button">
              Close session
            </button>
          )}
        </div>
      </div>

      {message && <div className="feedback error">{message}</div>}
      {capability?.mode === 'simulated' && (
        <div className="feedback info">This capability is simulated: no real hardware is being controlled.</div>
      )}
      {!active && (
        <div className="card">
          This session is {session.status}. Open a new one from My reservations.
          {kind === 'serial' && (
            <div style={{ marginTop: '0.6rem' }}>
              <button className="button ghost" type="button"
                onClick={() => void serialLog(session.id, true).then((text) => downloadText(`targethub-serial-${session.id.slice(0, 8)}.log`, text)).catch((error) => setMessage(errorMessage(error)))}>
                Download console log
              </button>
            </div>
          )}
        </div>
      )}

      {active && kind === 'serial' && <SerialConsole sessionId={session.id} onEnded={onConsoleEnded} />}
      {active && (kind === 'power' || kind === 'reset') && <PowerPanel sessionId={session.id} operations={operations} log={addLog} />}
      {active && kind === 'deploy' && <DeployPanel sessionId={session.id} log={addLog} />}
      {active && !['serial', 'power', 'reset', 'deploy'].includes(kind) && (
        <section className="card">
          <h3 style={{ marginTop: 0 }}>Operations</h3>
          <div className="toolbar">
            {operations.map((operation) => (
              <button key={operation} className="button" onClick={() => void runGeneric(operation)} disabled={busy} type="button">
                {operation}
              </button>
            ))}
          </div>
        </section>
      )}

      {kind !== 'serial' && (
        <section className="card" style={{ marginTop: '0.8rem' }}>
          <h3 style={{ marginTop: 0 }}>Activity</h3>
          <pre className="log-console" aria-label="operation log">
            {log.length
              ? log.map((line) => `${line.ok ? '✓' : '✗'} [${new Date(line.at).toLocaleTimeString()}] ${line.text}`).join('\n')
              : 'No operations yet.'}
          </pre>
        </section>
      )}
    </div>
  )
}
