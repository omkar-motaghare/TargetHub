import * as vscode from 'vscode'

import { HubClient, HubError } from './client'

const TOKEN_KEY = 'targethub.token'
const DURATIONS = ['30', '60', '120', '240']

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

async function pick<T extends vscode.QuickPickItem>(items: T[], placeHolder: string): Promise<T | undefined> {
  if (items.length === 0) {
    void vscode.window.showInformationMessage(`TargetHub: nothing to choose (${placeHolder})`)
    return undefined
  }
  return vscode.window.showQuickPick(items, { placeHolder })
}

async function askMinutes(): Promise<number | undefined> {
  const choice = await vscode.window.showQuickPick(DURATIONS.map((value) => `${value} minutes`), { placeHolder: 'Duration' })
  return choice ? Number.parseInt(choice, 10) : undefined
}

/** Raw-keystroke console: keys go straight to the device, output arrives via long reads. */
export function serialTerminal(hub: HubClient, sessionId: string, name: string): vscode.Pseudoterminal {
  const output = new vscode.EventEmitter<string>()
  let running = false
  const pump = async () => {
    while (running) {
      try {
        const text = await hub.serialRead(sessionId)
        if (text) output.fire(text)
      } catch (error) {
        output.fire(`\r\n[${name}] ${error instanceof HubError ? error.message : String(error)}\r\n`)
        if (error instanceof HubError && error.status === 409) {
          running = false
          return
        }
        await new Promise((resolve) => setTimeout(resolve, 2000))
      }
    }
  }
  return {
    onDidWrite: output.event,
    open: () => {
      void hub.execute(sessionId, 'open').then(
        () => {
          running = true
          void pump()
        },
        (error: unknown) => output.fire(`[${name}] open failed: ${String(error)}\r\n`),
      )
    },
    close: () => {
      running = false
    },
    handleInput: (data: string) => {
      hub.serialWrite(sessionId, data).catch((error: unknown) => output.fire(`\r\n[${name}] write failed: ${String(error)}\r\n`))
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
    await context.secrets.store(TOKEN_KEY, await hub.login(username, password, `vscode@${vscode.env.machineId.slice(0, 8)}`))
    void vscode.window.showInformationMessage(`TargetHub: signed in as ${username}`)
  })

  register('targethub.useToken', async () => {
    const token = await vscode.window.showInputBox({ prompt: 'Personal API token (Account → API tokens)', password: true })
    if (!token) return
    await context.secrets.store(TOKEN_KEY, token.trim())
    const hub = await client(context)
    void vscode.window.showInformationMessage(`TargetHub: signed in as ${await hub.username()}`)
  })

  register('targethub.logout', async () => {
    await context.secrets.delete(TOKEN_KEY)
    void vscode.window.showInformationMessage('TargetHub: signed out (revoke the token under Account → API tokens if needed)')
  })

  register('targethub.reserve', async () => {
    const hub = await client(context)
    const targets = (await hub.listTargets()).filter((t) => t.enabled)
    const chosen = await pick(
      targets.map((t) => ({
        label: t.name,
        description: t.availability?.state ?? '',
        detail: t.availability?.reserved_by ? `reserved by ${t.availability.reserved_by}` : undefined,
        id: t.id,
      })),
      'Target to reserve',
    )
    if (!chosen) return
    const minutes = await askMinutes()
    if (!minutes) return
    await hub.reserve(chosen.id, minutes)
    void vscode.window.showInformationMessage(`TargetHub: reserved ${chosen.label} for ${minutes} minutes`)
  })

  register('targethub.reserveTag', async () => {
    const hub = await client(context)
    const tags = [...new Set((await hub.listTargets()).flatMap((t) => t.tags ?? []))].sort()
    const tag = await pick(tags.map((label) => ({ label })), 'Reserve any free target with tag')
    if (!tag) return
    const minutes = await askMinutes()
    if (!minutes) return
    const reservation = await hub.reserveAny(tag.label, minutes)
    const target = (await hub.listTargets()).find((t) => t.id === reservation.target_id)
    void vscode.window.showInformationMessage(`TargetHub: reserved ${target?.name ?? reservation.target_id} for ${minutes} minutes`)
  })

  const pickReservation = async (hub: HubClient, placeHolder: string) => {
    const names = Object.fromEntries((await hub.listTargets()).map((t) => [t.id, t.name]))
    return pick(
      (await hub.myReservations()).map((r) => ({
        label: names[r.target_id] ?? r.target_id,
        description: r.ends_at ? `until ${new Date(r.ends_at).toLocaleTimeString()}` : '',
        id: r.id,
      })),
      placeHolder,
    )
  }

  register('targethub.extend', async () => {
    const hub = await client(context)
    const chosen = await pickReservation(hub, 'Reservation to extend')
    if (!chosen) return
    const minutes = await askMinutes()
    if (!minutes) return
    const updated = await hub.extend(chosen.id, minutes)
    void vscode.window.showInformationMessage(
      `TargetHub: ${chosen.label} extended until ${updated.ends_at ? new Date(updated.ends_at).toLocaleTimeString() : '?'}`,
    )
  })

  register('targethub.release', async () => {
    const hub = await client(context)
    const chosen = await pickReservation(hub, 'Reservation to release')
    if (chosen) {
      await hub.release(chosen.id)
      void vscode.window.showInformationMessage(`TargetHub: released ${chosen.label}`)
    }
  })

  const sessionFor = async (hub: HubClient, capability: string) => {
    const names = Object.fromEntries((await hub.listTargets()).map((t) => [t.id, t.name]))
    const existing = await hub.activeSessions(capability)
    if (existing.length) {
      return pick(existing.map((s) => ({ label: names[s.target_id] ?? s.target_id, id: s.id })), `${capability} session`)
    }
    const reservation = await pickReservation(hub, `Reservation to open a ${capability} session on`)
    if (!reservation) return undefined
    const session = await hub.openSession(reservation.id, capability)
    return { label: reservation.label, id: session.id }
  }

  register('targethub.power', async () => {
    const hub = await client(context)
    const session = await sessionFor(hub, 'power')
    if (!session) return
    const operation = await vscode.window.showQuickPick(['on', 'off', 'status', 'cycle', 'reset'], { placeHolder: 'Operation' })
    if (!operation) return
    const result = await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: `TargetHub: power ${operation}…` },
      () => hub.execute(session.id, operation),
    )
    void vscode.window.showInformationMessage(`TargetHub: ${session.label}: ${result.message}`)
  })

  register('targethub.serial', async () => {
    const hub = await client(context)
    const session = await sessionFor(hub, 'serial')
    if (!session) return
    const name = `TargetHub ${session.label}`
    vscode.window.createTerminal({ name, pty: serialTerminal(hub, session.id, name) }).show()
  })
}

export function deactivate(): void {}
