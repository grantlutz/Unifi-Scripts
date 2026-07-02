#!/usr/bin/env python3
"""
Bulk-forget stale/offline clients on a UniFi UDM controller.

Uses the controller's own (undocumented but stable) API instead of touching
the MongoDB directly -- this goes through the same "forget-sta" command the
web UI uses when you forget a single client, so it won't corrupt aliases,
icons, or DPI history the way raw DB deletes sometimes do.

USAGE:
    python3 unifi_purge_stale_clients.py --host 192.168.1.1 --user admin \
        --days 7 [--site default] [--dry-run] [--yes]

Notes:
  - Run this FROM a machine on your LAN with access to the UDM's HTTPS UI.
  - The UDM's cert is self-signed by default, so SSL verification is disabled.
  - This is a local admin login (not your Ubiquiti cloud SSO account) --
    create a local admin under Settings > Admins if you don't have one.
  - Back up your controller (Settings > System > Backups) before running
    this against thousands of clients. It's not reversible.
"""

import argparse
import getpass
import sys
import time

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def login(session, host, username, password):
    url = f"https://{host}/api/auth/login"
    resp = session.post(url, json={"username": username, "password": password}, verify=False)
    resp.raise_for_status()
    csrf = resp.headers.get("X-CSRF-Token") or resp.headers.get("x-csrf-token")
    if csrf:
        session.headers.update({"X-CSRF-Token": csrf})
    return resp


def refresh_csrf(session, resp):
    # UniFi OS rotates the CSRF token on some responses; keep the session current.
    csrf = resp.headers.get("X-Updated-CSRF-Token") or resp.headers.get("x-updated-csrf-token")
    if csrf:
        session.headers.update({"X-CSRF-Token": csrf})


def get_all_clients(session, host, site):
    url = f"https://{host}/proxy/network/api/s/{site}/stat/alluser"
    resp = session.get(url, verify=False)
    resp.raise_for_status()
    refresh_csrf(session, resp)
    return resp.json().get("data", [])


def forget_clients(session, host, site, macs):
    url = f"https://{host}/proxy/network/api/s/{site}/cmd/stamgr"
    payload = {"cmd": "forget-sta", "macs": macs}
    resp = session.post(url, json=payload, verify=False)
    resp.raise_for_status()
    refresh_csrf(session, resp)
    return resp.json()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True, help="UDM IP or hostname")
    ap.add_argument("--user", required=True, help="Local admin username")
    ap.add_argument("--site", default="default", help="Site name (default: 'default')")
    ap.add_argument("--days", type=int, default=7, help="Forget clients unseen for this many days")
    ap.add_argument("--batch-size", type=int, default=200, help="MACs per forget-sta call")
    ap.add_argument("--dry-run", action="store_true", help="List matching clients, don't delete")
    ap.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    args = ap.parse_args()

    password = getpass.getpass(f"Password for {args.user}@{args.host}: ")

    session = requests.Session()
    print("Logging in...")
    login(session, args.host, args.user, password)

    print("Fetching client list (this can take a bit on large controllers)...")
    clients = get_all_clients(session, args.host, args.site)
    print(f"Retrieved {len(clients)} known clients.")

    cutoff = time.time() - (args.days * 86400)
    stale = [c for c in clients if c.get("last_seen", 0) and c["last_seen"] < cutoff]

    print(f"Found {len(stale)} clients not seen in the last {args.days} days.")
    if not stale:
        print("Nothing to do.")
        return

    if args.dry_run:
        for c in stale[:20]:
            print(f"  {c.get('mac')}  last_seen={time.ctime(c['last_seen'])}  name={c.get('hostname') or c.get('name') or ''}")
        if len(stale) > 20:
            print(f"  ... and {len(stale) - 20} more")
        print("\nDry run only -- nothing was deleted.")
        return

    if not args.yes:
        confirm = input(f"About to forget {len(stale)} clients. Type 'yes' to proceed: ")
        if confirm.strip().lower() != "yes":
            print("Aborted.")
            sys.exit(1)

    macs = [c["mac"] for c in stale]
    for i in range(0, len(macs), args.batch_size):
        batch = macs[i : i + args.batch_size]
        print(f"Forgetting batch {i // args.batch_size + 1} ({len(batch)} clients)...")
        forget_clients(session, args.host, args.site, batch)
        time.sleep(1)  # be gentle with the controller

    print("Done.")


if __name__ == "__main__":
    main()