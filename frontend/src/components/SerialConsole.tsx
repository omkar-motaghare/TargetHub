import React, { useCallback, useEffect, useRef, useState } from 'react'
import { FitAddon } from '@xterm/addon-fit'
import { Terminal } from '@xterm/xterm'
import '@xterm/xterm/css/xterm.css'

import { getAuthToken, refreshAccessToken, serialLog, serialSocketUrl } from '../services/api'
import { downloadText, errorMessage } from '../utils/ui'

type ConsoleState = 'connecting' | 'connected' | 'reconnecting' | 'ended' | 'error'

const MAX_RECONNECTS = 6

/** Interactive serial console: xterm.js over the session WebSocket. */
export default function SerialConsole({ sessionId, onEnded }: { sessionId: string; onEnded?: (reason: string) => void }) {
  const host = useRef<HTMLDivElement>(null)
  const term = useRef<Terminal | null>(null)
  const socket = useRef<WebSocket | null>(null)
  const attempts = useRef(0)
  const ended = useRef(false)
  const triedRefresh = useRef(false)
  const [state, setState] = useState<ConsoleState>('connecting')
  const [detail, setDetail] = useState('')

  const connect = useCallback(() => {
    if (ended.current) return
    setState(attempts.current ? 'reconnecting' : 'connecting')
    const ws = new WebSocket(serialSocketUrl(sessionId))
    socket.current = ws
    ws.onopen = () => ws.send(JSON.stringify({ type: 'auth', token: getAuthToken() }))
    ws.onmessage = (event) => {
      let message: { type: string; data?: string; message?: string; reason?: string }
      try {
        message = JSON.parse(String(event.data))
      } catch {
        return
      }
      if (message.type === 'ready') {
        attempts.current = 0
        triedRefresh.current = false
        setState('connected')
        setDetail('')
        term.current?.focus()
      } else if (message.type === 'output' && message.data) {
        term.current?.write(message.data)
      } else if (message.type === 'notice' && message.message) {
        term.current?.write(`\r\n\x1b[33m[targethub] ${message.message}\x1b[0m\r\n`)
      } else if (message.type === 'closed') {
        const reason = message.reason || 'Console closed'
        if (reason === 'Authentication failed' && !triedRefresh.current) {
          // Access token expired: renew once and reconnect.
          triedRefresh.current = true
          ws.onclose = null
          ws.close()
          void refreshAccessToken().then((ok) => (ok ? connect() : (setState('error'), setDetail('Please sign in again.'))))
          return
        }
        ended.current = true
        setState('ended')
        setDetail(reason)
        term.current?.write(`\r\n\x1b[31m[targethub] ${reason}\x1b[0m\r\n`)
        onEnded?.(reason)
      }
    }
    ws.onclose = () => {
      if (ended.current || socket.current !== ws) return
      if (attempts.current >= MAX_RECONNECTS) {
        setState('error')
        setDetail('Connection lost. Use Reconnect to try again.')
        return
      }
      attempts.current += 1
      setState('reconnecting')
      window.setTimeout(connect, Math.min(1000 * 2 ** (attempts.current - 1), 10_000))
    }
  }, [sessionId, onEnded])

  useEffect(() => {
    const terminal = new Terminal({
      convertEol: false,
      cursorBlink: true,
      fontFamily: '"JetBrains Mono", "Cascadia Mono", Consolas, monospace',
      fontSize: 13,
      scrollback: 10_000,
      theme: { background: '#0b1622', foreground: '#d7e3f0' },
    })
    const fit = new FitAddon()
    terminal.loadAddon(fit)
    if (host.current) {
      terminal.open(host.current)
      try {
        fit.fit()
      } catch {
        // Not measurable yet (e.g. hidden); fitted again on resize.
      }
    }
    terminal.onData((data) => {
      const ws = socket.current
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'input', data }))
    })
    term.current = terminal
    const onResize = () => {
      try {
        fit.fit()
      } catch {
        // ignore
      }
    }
    window.addEventListener('resize', onResize)
    ended.current = false
    attempts.current = 0
    connect()
    return () => {
      window.removeEventListener('resize', onResize)
      ended.current = true
      const ws = socket.current
      socket.current = null
      ws?.close()
      terminal.dispose()
    }
  }, [connect])

  async function download(): Promise<void> {
    try {
      downloadText(`targethub-serial-${sessionId.slice(0, 8)}.log`, await serialLog(sessionId))
    } catch (error) {
      setDetail(errorMessage(error))
    }
  }

  function reconnect(): void {
    socket.current?.close()
    ended.current = false
    attempts.current = 0
    connect()
  }

  const label: Record<ConsoleState, string> = {
    connecting: 'Connecting…',
    connected: 'Connected',
    reconnecting: 'Reconnecting…',
    ended: 'Session ended',
    error: 'Disconnected',
  }

  return (
    <section className="card">
      <div className="page-head">
        <h3 style={{ margin: 0 }}>Serial console</h3>
        <div className="toolbar">
          <span className={`status-pill ${state}`} aria-live="polite">
            {label[state]}
          </span>
          <button className="button ghost" type="button" onClick={() => term.current?.clear()}>
            Clear
          </button>
          <button className="button ghost" type="button" onClick={() => void download()}>
            Download log
          </button>
          {(state === 'error' || state === 'ended') && (
            <button className="button secondary" type="button" onClick={reconnect} disabled={state === 'ended'}>
              Reconnect
            </button>
          )}
        </div>
      </div>
      {detail && <div className="muted" style={{ marginBottom: '0.5rem' }}>{detail}</div>}
      <div className="terminal-host" ref={host} aria-label="serial console" />
      <p className="muted small">Click the console and type; keystrokes go straight to the device. Ctrl+C is sent to the target.</p>
    </section>
  )
}
