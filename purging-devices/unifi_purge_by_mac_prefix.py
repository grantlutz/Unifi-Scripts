#!/usr/bin/env python3
"""
Bulk-forget UniFi clients whose MAC address starts with a given prefix.

Same approach as unifi_purge_stale_clients.py, but filters by MAC prefix
instead of last-seen age. Useful for clearing out a batch of devices you
know share a bogus/placeholder OUI (e.g. "00:00:11:22").

USAGE:
    python3 unifi_purge_by_mac_prefix.py --host 192.168.1.1 --user tempadmin \
        --prefix 00:00:11:22 [--site default] [--dry-run] [--yes]
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


def normalize_prefix(prefix):
    # Accept "00:00:11:22", "00-00-11-22", or "00001122" and normalize to lowercase hex-only
    return "".join(ch for ch in prefix if ch.isalnum()).lower()


def normalize_mac(mac):
    return "".join(ch for ch in mac if ch.isalnum()).lower()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True, help="UDM IP or hostname")
    ap.add_argument("--user", required=True, help="Local admin username")
    ap.add_argument("--site", default="default", help="Site name (default: 'default')")
    ap.add_argument("--prefix", required=True, help="MAC prefix to match, e.g. 00:00:11:22")
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

    prefix = normalize_prefix(args.prefix)
    matches = [c for c in clients if c.get("mac") and normalize_mac(c["mac"]).startswith(prefix)]

    print(f"Found {len(matches)} clients with MAC starting '{args.prefix}'.")
    if not matches:
        print("Nothing to do.")
        return

    if args.dry_run:
        for c in matches[:30]:
            print(f"  {c.get('mac')}  name={c.get('hostname') or c.get('name') or ''}")
        if len(matches) > 30:
            print(f"  ... and {len(matches) - 30} more")
        print("\nDry run only -- nothing was deleted.")
        return

    if not args.yes:
        confirm = input(f"About to forget {len(matches)} clients matching '{args.prefix}'. Type 'yes' to proceed: ")
        if confirm.strip().lower() != "yes":
            print("Aborted.")
            sys.exit(1)

    macs = [c["mac"] for c in matches]
    for i in range(0, len(macs), args.batch_size):
        batch = macs[i : i + args.batch_size]
        print(f"Forgetting batch {i // args.batch_size + 1} ({len(batch)} clients)...")
        forget_clients(session, args.host, args.site, batch)
        time.sleep(1)

    print("Done.")


if __name__ == "__main__":
    main()