# Usage guide

## Run commands

Use the installed private launcher; it selects the pinned program from local settings.

```sh
python3 ~/AgentRoute/automation/control.py status
python3 ~/AgentRoute/automation/control.py verify-startup
python3 ~/AgentRoute/automation/control.py check --startup-check
python3 ~/AgentRoute/automation/control.py pause
python3 ~/AgentRoute/automation/control.py resume
python3 ~/AgentRoute/automation/control.py recover
```

`verify-startup` waits up to 180 seconds for the existing Clash core and TUN, checks the actual fixed-exit graph, protected rules, local rule files and DNS policy, and performs two rounds of HTTPS acceptance. It does not start, restart or reconfigure Clash. A successful check updates the latest local backup sets.

`STARTUP_PASSED` applies to the recorded boot and core process. `STARTUP_CACHED` means that identity was accepted earlier; it does not claim new network probes. `UNCHANGED` is a rule-generation result, not fresh network acceptance. Open the local startup report to check the recorded boot, core process and time.

This adapter currently requires Clash Verge Rev 2.5.10 / Mihomo 1.19.33, the existing Python 3.11+ and Node runtimes, and system Ruby. A changed client/core/source requires review. Startup acceptance does not imply complete browser, DNS, IPv6 or account-level acceptance.

## Scheduled checks

The installed Mac launchd job runs at login and at local 02:47, 08:47, 14:47 and 20:47. It waits for readiness before the initial acceptance and remote rule check. StartCalendarInterval coalesces missed events after wake; do not describe this as a tested sleep/wake cycle unless it was actually observed.

GitHub Actions checks upstream every six hours, verifies one immutable generation with the pinned official core, and publishes ordinary commits on `rules`. Documentation and code are kept as inert text snapshots on `upstream-docs`. On the Mac, only validated rules are applied automatically; documentation, templates and code updates leave review notices.

The Mac verifies the five GUI file providers and carries equivalent verified inline data during direct API reloads. GUI reactivation uses Clash's existing owner session to stage file providers into the service runtime. Do not write the protected service directory or broaden its permissions.

## Keep two latest backups

Configure a private `backup_directory` and the original subscription filename. Keep one latest set of each kind:

- `provider-original`: the unmodified provider subscription.
- `agentroute-current`: the last accepted local configuration, exit, required rules, settings and recovery code.

A successor is written and verified before replacing the previous set. Unfinished transactions keep their temporary snapshots. After acceptance, keep compact transaction/health evidence and remove completed config snapshots and obsolete managed generation caches. Do not call cache files or historical logs independent recovery points.

Default `recover` validates and restores `agentroute-current`, then pauses automatic application. The backup directory also contains a standalone recovery launcher using its own validated code. Importing `provider-original` is a separate explicit operation and changes the current routing/exit policy.

## Change an exit

Keep the new entry host, protocol, port and authentication in a private JSON `proxy` object, with `expected_ip` for the final public exit. Never commit that file.

```sh
python3 ~/AgentRoute/automation/control.py preflight --spec /private/path/new-exit.json
python3 ~/AgentRoute/automation/control.py rotate --spec /private/path/new-exit.json
python3 ~/AgentRoute/automation/control.py verify-persistence
```

Rotation includes a bounded loopback-only, no-TUN preflight using the currently selected original transit. The main application has an independent 150-second recovery deadline. `EXIT_HEALTHY_PERSISTENCE_PENDING` keeps rule application paused: open the current subscription page, run `verify-persistence`, wait for `READY_FOR_GUI_REACTIVATION`, then click Clash's “重新激活订阅”. Only unchanged-core, loaded-file and actual HTTPS acceptance completes persistence and promotes the new backup.

## Test and install code

```sh
python3 -m unittest discover -s tests -v
```

Use fixtures for corrupt/stale data, changed chains, direct escapes, boot transitions and retention failures. Native checks validate syntax/dependencies only. Shadow cores must be time-limited, have no TUN/system-proxy changes, bind loopback and have their exit verified. Do not interrupt the main proxy for comparison.

Commit tested code, freeze a new local snapshot, then update the installed settings and launchd job explicitly. Never edit the running snapshot in place or automatically execute upstream documents/scripts. Keep recovery available before installation.

The media probe reads 1,024 bytes with verified TLS, video type and MP4 signature. Curl's intentional write-stop 23 is accepted only when those conditions hold. Failed W3C attempts remain recorded if a Google sample is used. This does not replace real browser playback testing.

## Read local records

| Record | Use |
| --- | --- |
| `startup-report.json` | Boot/core-specific acceptance |
| `backup-status.json` | Latest backup verification |
| `status.json`, `active.json` | Rule operation and accepted revision |
| `transactions/` | Pending recovery material and completed evidence |
| `review-needed.md`, `notices.json` | Review/failure notices; desktop display is not guaranteed |

Local records can contain sensitive network data. Keep them out of GitHub and Issues. Follow the user's explicit publication choice.

Rule data and license/source notices remain attributed to [ryuu-restart/agent-route](https://github.com/ryuu-restart/agent-route); consult the published `rules` branch for their manifests and notices.
