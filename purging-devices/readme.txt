# UniFi Bulk Client Cleanup Scripts

Small Python scripts to bulk-remove ("forget") client entries from a UniFi
controller (UDM, UDM Pro, UDM SE, Cloud Key, self-hosted, etc.) — without
clicking "Forget" one device at a time in the UI.

There are two scripts:

- **`unifi_purge_stale_clients.py`** — forgets clients that haven't been seen
  in more than N days (e.g. clean out everything offline for 7+ days).
- **`unifi_purge_by_mac_prefix.py`** — forgets clients whose MAC address
  starts with a specific prefix (e.g. clean out a batch of devices sharing a
  known bogus/placeholder OUI).

Both work by logging into the controller's own web API and calling the same
`forget-sta` command the UI uses when you forget a client manually, then
looping through matches in batches. They do **not** touch the underlying
database directly, so they're safer than raw DB-edit approaches floating
around various forums.

## Why this exists

UniFi's client list has no built-in "select all offline clients and forget"
option — you either forget devices one at a time, or you don't. If you've
ever ended up with thousands of stale/ghost client entries (common after
MAC randomization cycling, IoT devices reconnecting with new MACs, etc.),
this is a way to clear them out in one pass.

## Requirements

- Python 3
- The `requests` package: `pip3 install requests`
- A **local admin account** on the controller (Settings → Admins), not just
  a cloud/SSO-only login — the API calls in this script require local
  access.

## Usage

### Forget clients unseen for more than N days

```
python3 unifi_purge_stale_clients.py --host 192.168.1.1 --user admin --days 7 --dry-run
```

Review the output, then drop `--dry-run` to actually forget them:

```
python3 unifi_purge_stale_clients.py --host 192.168.1.1 --user admin --days 7
```

### Forget clients matching a MAC prefix

```
python3 unifi_purge_by_mac_prefix.py --host 192.168.1.1 --user admin --prefix AA:BB:CC:DD --dry-run
```

Then, once you've confirmed the matches look right:

```
python3 unifi_purge_by_mac_prefix.py --host 192.168.1.1 --user admin --prefix AA:BB:CC:DD
```

`--prefix` accepts colons, dashes, or no separators (`AA:BB:CC:DD`,
`AA-BB-CC-DD`, or `AABBCCDD` all work).

### Common flags

| Flag | Description |
|---|---|
| `--host` | IP or hostname of your controller (required) |
| `--user` | Local admin username (required) |
| `--site` | Site name, default `default` |
| `--dry-run` | List matches only, no deletion |
| `--yes` | Skip the confirmation prompt |
| `--batch-size` | Clients per `forget-sta` call (default 200) |

## ⚠️ Before you run this for real

- **Back up your controller first.** Settings → System → Backups. This
  action is not reversible.
- **Always run `--dry-run` first** and read through the matches — especially
  for the MAC-prefix script, since an overly broad prefix could match real,
  active devices.
- These scripts use an undocumented private UniFi API endpoint
  (`cmd/stamgr`). It's widely used by community tools and stable across
  recent versions, but Ubiquiti could change it without notice in a future
  firmware update.
- Tested against UniFi OS consoles (UDM/UDM Pro/UDM SE) using the
  `/proxy/network/...` API path. If you're on an older self-hosted
  controller and get 404s, try dropping the `/proxy/network` prefix from
  the URLs in the script.

## How it works

1. Logs into the controller and captures the CSRF token UniFi OS requires
   on write requests.
2. Fetches the full client list (`stat/alluser`).
3. Filters by age (`last_seen`) or MAC prefix, depending on the script.
4. Calls `cmd/stamgr` with `forget-sta` in batches to remove matches.
