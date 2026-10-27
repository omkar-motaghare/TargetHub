# Security

## Model

- **Server:** single source of truth for who may use which board and when. Every hardware operation is
  checked against an active, unexpired session owned by the caller.
- **Agents** only make outbound connections and only act on hardware declared in their **local**
  configuration. The server can ask an agent to open an allowed serial port, switch a configured relay or
  run a configured deploy command for an owned session, and nothing else. There is no remote shell.
- **Power-system secrets** (DD key, PDU tokens) live in the server environment and are referenced by
  variable name; inline keys are rejected and never returned by the API.

## Accounts and tokens

- Passwords: PBKDF2-SHA256, 600,000 iterations, per-user salt; older hashes are upgraded on next login.
- Login, password change and bootstrap are rate limited per client IP.
- Access tokens (JWT, HS256 with `SECRET_KEY`) expire after 15 minutes. Refresh tokens rotate on every use;
  reuse of an old refresh token revokes the whole family (theft detection).
- Disabling a user, resetting their password or *sign out everywhere* revokes all their tokens immediately.
- Personal API tokens (`thp_…`) are stored hashed, can expire, and are revocable; they carry the user's role.
- The bootstrap token works only while no user exists.
- Non-admin API responses never include provider configuration, agent IDs or resource IDs.

## Deployment checklist

- [ ] HTTPS in front of the server (`--domain`, or your proxy). Set `TARGETHUB_PUBLIC_URL` to the https URL.
- [ ] `.env` readable only by the operator account and backed up securely (it holds `SECRET_KEY` and the DB password).
- [ ] Database not published outside the host (default compose does not publish it).
- [ ] `/metrics` scraped with `METRICS_TOKEN` from the internal network only.
- [ ] `ALLOW_SIMULATED_PROVIDERS` unset in production.
- [ ] Few admins; normal work done with *user* accounts; *viewer* for read-only stakeholders.
- [ ] CI uses dedicated accounts with expiring API tokens.
- [ ] Backups encrypted and stored off the host (they contain password and credential hashes).
- [ ] Agents on a lab network segment; their hosts patched; their config files left at 0600 / ACL-protected.
- [ ] Revoke an agent's credential when a host is lost, re-imaged or retired.

## Audit

The activity log records sign-ins, user and role changes, token creation/revocation, target and capability
changes, reservations (create, extend, release, force-release), sessions and hardware operations (serial
reads/writes go to metrics and the transcript rather than one audit row per keystroke), webhook changes
and console admin actions (`manage.*`). Retention is set in the reservation policy (365 days by default).

## Reporting a vulnerability

Please report security issues privately to the maintainer (see the repository's security policy or
contact the author) rather than in a public issue.
