# TargetHub documentation

TargetHub lets an embedded team share lab hardware safely: reserve a board, get exclusive access to its
serial console, power and firmware deploy, and give it back, from the browser, CLI, SDK, VS Code or CI.

## Start here

| I want to… | Read |
| --- | --- |
| Install a server for my team | [Installation](getting-started/install.md) |
| Use the lab as an engineer | [User guide](user-guide/using-targethub.md) |
| Add boards, users, policy, webhooks | [Administration](admin-guide/administration.md) |
| Attach boards via a Raspberry Pi, Linux PC or Windows PC | [Agent guide](agents/agent-guide.md) |
| Control DD power | [DD power system](power/dd-power.md) |
| Use TargetHub from scripts and CI | [CLI, SDK and CI](automation/ci-hil.md) |
| Try it with no hardware | [Simulators and demo lab](development/simulators.md) |
| Upgrade or fix something | [Upgrade](operations/upgrade.md) · [Troubleshooting](operations/troubleshooting.md) |

## Typical setups

- **Reservations only**: server, targets without capabilities. Booking board for shared hardware.
- **Reservations + DD power**: server talks to the DD power system directly. No agents.
- **Full lab**: agents next to the boards provide serial consoles, relays and flashing; power from DD,
  HTTP PDUs or agent relays.
