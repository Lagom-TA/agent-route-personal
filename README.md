# AgentRoute Personal

A public mirror of the upstream AgentRoute Mihomo rules, with a separate local macOS updater. Public rule data and source notices are mirrored without local nodes, subscriptions, exit addresses, or credentials.

## What runs where

- GitHub Actions checks the upstream release every six hours, verifies one immutable generation, compiles it using the pinned official Mihomo 1.19.33 binary, and publishes an ordinary commit on `rules`. Upstream documentation and code are mirrored as inert `.txt` snapshots on `upstream-docs`; their original paths and hashes are recorded in provenance.
- The Mac downloads from one pinned commit, checks integrity and its actual installed core, then loads all five datasets in one protected transaction. GUI persistence uses local file providers. A direct core API reload carries the same verified data as inline providers because Clash Verge's service core has a separate protected working directory. A normal GUI reload uses the app's own runtime bundle to stage the local files. Neither route needs administrator writes or restarting the core.
- A separate launchd process starts recovery if an application remains unaccepted after 150 seconds. It restores a per-operation snapshot; it never relies on a fixed old exit or the agent remaining connected.
- Local exact-host policy, exit credentials, expected IP, node definitions, and recovery material stay in a private directory outside this repository.
- Rule application and exit rotation share a lock. Downloaded data is not applied state. Failed generations are held instead of immediately retried.
- Downloaded documentation, templates, and updated programs never replace installed code automatically. The installed program is a snapshot of an explicitly installed Git commit.
- Review and failure events leave durable private notices and attempt a deduplicated macOS notification. A successful notification command does not prove the desktop displayed it; the local status launcher remains available.

This is initially adapted to Clash Verge Rev 2.5.10 / Mihomo 1.19.33 on macOS. Changed client/core versions require review. It does not claim every DNS, IPv6, browser, or account-level behavior is verified by a successful rule update.

## Commands

Use the installed launcher on the Mac, or run with its pinned program on `PYTHONPATH`:

```sh
python3 -m agentroute_sync.mac status
python3 -m agentroute_sync.mac check
python3 -m agentroute_sync.mac pause
python3 -m agentroute_sync.mac resume
python3 -m agentroute_sync.mac recover
```

`recover` explicitly restores the latest operation and pauses automatic application. It refuses to overwrite unrelated concurrent edits. The private recovery guide describes offline file restoration if the core control socket is unavailable.

Exit preparation uses a private JSON file with `proxy` (the actual entry host, port, type and credentials) and `expected_ip` (the address destinations should observe). They are different concepts. Never commit that file.

```sh
python3 -m agentroute_sync.mac preflight --spec /private/path/new-exit.json
python3 -m agentroute_sync.mac rotate --spec /private/path/new-exit.json
```

Preflight runs a time-limited child core bound to loopback and the physical interface, with no TUN or system-proxy changes. It builds the proposed exit using the currently selected original transit, not another chain through the old exit. Normal traffic is left on the main core. Rotation requires successful preflight and then verifies the main core after applying.

The Mac uses its existing Python 3.11+ runtime, Node runtime and system Ruby's YAML syntax tree parser. No Python packages are installed. The YAML parser preserves IPv6 literals and rejects custom object tags.

## Validation

```sh
python3 -m unittest discover -s tests -v
```

Tests cover generation integrity, failed/empty/stale bundles, exact policy persistence, idempotent exit-chain rendering, changed server/port/protocol, cycle/direct escape rejection, independent timeout recovery, invalid success records, concurrent selection/subscription changes and stale exit revisions. Network deployment evidence belongs in the private local report, not this public repository.

## Source and retention

Rule data originates from [ryuu-restart/agent-route](https://github.com/ryuu-restart/agent-route). Each published snapshot preserves the upstream manifest, index, source metadata and license notices. See the `rules` branch for those notices. This repository does not reclassify the upstream datasets; user policy is applied separately on the device.

Published history is not force-rewritten. Local successful generations and transaction records are retained; the updater does not prune user backups. Rules are continuously maintained upstream: keep following documentation and compatibility changes as well as the data feed.
