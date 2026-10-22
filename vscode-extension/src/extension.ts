import * as vscode from 'vscode'

import { HubClient, HubError } from './client'

const TOKEN_KEY = 'targethub.token'
const SERIAL_POLL_MS = 1000

async function client(context: vscode.ExtensionContext): Promise<HubClient> {
  const url = vscode.workspace.getConfiguration('targethub').get<string>('url', 'http://127.0.0.1:8000')
  const token = await context.secrets.get(TOKEN_KEY)
  return new HubClient(url, token)
}

async function guarded(action: () => Promise<void>): Promise<void> {
  try {
    await action()
  } catch (error) {
    const message = error instanceof HubError ? error.message : String(error)
    void vscode.window.showErrorMessage(`TargetHub: ${message}`)
  }
}

async function pick<T extends { label: string }>(items: T[], placeHolder: string): Promise<T | undefined> {
  if (items.length === 0) {
    void vscode.window.showInformationMessage(`TargetHub: nothing to choose (${placeHolder})`)
    return undefined
  }
  return vscode.window.showQuickPick(items, { placeHolder })
}

function serialTerminal(hub: HubClient, sessionId: string, name: string): vscode.Pseudoterminal {
  const output = new vscode.EventEmitter<string>()
  let timer: NodeJS.Timeout | undefined
  let line = ''
  return {
    onDidWrite: output.event,
    open: () => {
      void hub.execute(sessionId, 'open').then(
        () => {
          timer = setInterval(() => {
            hub.serialRead(sessionId).then(
              (text) => text && output.fire(text.replace(/\r?\n/g, '\r\n')),
              (error: unknown) => output.fire(`\r\n[${name}] read failed: ${String(error)}\r\n`),
            )
          }, SERIAL_POLL_MS)
        },
        (error: unknown) => output.fire(`[${name}] open failed: ${String(error)}\r\n`),
      )
    },
    close: () => {
      if (timer) clearInterval(timer)
    },
    handleInput: (data: string) => {
      for (const char of data) {
        if (char === '\r') {
          output.fire('\r\n')
          hub.serialWrite(sessionId, `${line}\n`).catch((error: unknown) =>
            output.fire(`[${name}] write failed: ${String(error)}\r\n`),
          )
          line = ''
        } else if (char === '\u007f') {
          line = line.slice(0, -1)
          output.fire('\b \b')
        } else {
          line += char
          output.fire(char)
        }
      }
    },
  }
}

export function activate(context: vscode.ExtensionContext): void {
  const register = (command: string, handler: () => Promise<void>) =>
    context.subscriptions.push(vscode.commands.registerCommand(command, () => guarded(handler)))

  register('targethub.login', async () => {
    const username = await vscode.window.showInputBox({ prompt: 'TargetHub username' })
    const password = username ? await vscode.window.showInputBox({ prompt: 'Password', password: true }) : undefined
    if (!username || !password) return
    const hub = await client(context)
    await context.secrets.store(TOKEN_KEY, await hub.login(username, password))
    void vscode.window.showInformationMessage(`TargetHub: signed in as ${username}`)
  })

  register('targethub.reserve', async () => {
    const hub = await client(context)
    const targets = (await hub.listTargets()).filter((t) => t.enabled)
    const chosen = await pick(targets.map((t) => ({ label: t.name, id: t.id })), 'Target to reserve')
    if (!chosen) return
    const reservation = await hub.reserve(chosen.id, 60)
    void vscode.window.showInformationMessage(`TargetHub: reserved ${chosen.label} (${reservation.id}) for 60 minutes`)
  })

  register('targethub.release', async () => {
    const hub = await client(context)
    const chosen = await pick(
      (await hub.myReservations()).map((r) => ({ label: r.target_id, description: r.id, id: r.id })),
      'Reservation to release',
    )
    if (chosen) await hub.release(chosen.id)
  })

  register('targethub.power', async () => {
    const hub = await client(context)
    const session = await pick(
      (await hub.activeSessions('power')).map((s) => ({ label: `Target ${s.target_id}`, id: s.id })),
      'Power session',
    )
    if (!session) return
    const operation = await vscode.window.showQuickPick(['on', 'off', 'status', 'cycle', 'reset'], {
      placeHolder: 'Operation',
    })
    if (!operation) return
    const result = await hub.execute(session.id, operation)
    void vscode.window.showInformationMessage(`TargetHub: ${result.message}`)
  })

  register('targethub.serial', async () => {
    const hub = await client(context)
    const session = await pick(
      (await hub.activeSessions('serial')).map((s) => ({ label: `Target ${s.target_id}`, id: s.id })),
      'Serial session',
    )
    if (!session) return
    const name = `TargetHub ${session.label}`
    vscode.window.createTerminal({ name, pty: serialTerminal(hub, session.id, name) }).show()
  })
}

export function deactivate(): void {}
