# TargetHub for VS Code

Command-palette access to a TargetHub server: reserve targets, control power and use a
serial console in a VS Code terminal.

| Command | What it does |
| --- | --- |
| `TargetHub: Sign In` | username/password; the token is kept in VS Code SecretStorage |
| `TargetHub: Reserve Target` | reserves an enabled target for 60 minutes |
| `TargetHub: Release Reservation` | releases one of your active reservations |
| `TargetHub: Power Control` | on/off/status/cycle/reset on an active power session |
| `TargetHub: Open Serial Console` | pseudo-terminal bridged to an active serial session (polls once a second) |

Set `targethub.url` (default `http://127.0.0.1:8000`; use `https://` in production).
Open sessions from the web UI or the `targethub` CLI first; the extension lists your active
sessions. It never stores passwords.

## Develop

```bash
cd vscode-extension
npm install
npm run compile   # tsc -> out/
npm test          # vitest: REST client unit tests (no VS Code needed)
```

Press F5 in VS Code with this folder open to launch an Extension Development Host.

## Status

The REST client is unit tested and the extension compiles against `@types/vscode`. The command
handlers and the serial pseudo-terminal were **not** exercised inside a running VS Code
instance (none available in the build environment); treat them as untested UI glue.
There is no packaged `.vsix` or Marketplace publication yet.
