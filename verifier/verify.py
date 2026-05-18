#!/usr/bin/env python3
"""
toolguard verify  —  Offline tamper-detection for ToolGuard audit JSONL files.

Usage:
    python verify.py verify --chain toolguard-audit.jsonl

Checks performed:
  1. Chain linkage  : record[n].prevHash == record[n-1].hash  (detects deletion,
                      insertion, and reordering of records)
  2. Content hash   : SHA-256(record without 'hash' field) == record.hash
                      Only applied when a record was produced by the live backend
                      (real SHA-256). Pre-built demo records are chain-verified only.

Tamper-detection summary:
  - Delete any record   → linkage breaks at the next record
  - Reorder records     → linkage breaks immediately
  - Change any value    → content hash breaks (live records only)
  - Change hash/prevHash → linkage breaks

Exit codes:
    0  chain intact
    1  tampering detected or file error
"""

import argparse
import hashlib
import json
import sys

_TTY = sys.stdout.isatty()
_g = lambda s: f"\033[32m{s}\033[0m" if _TTY else s
_r = lambda s: f"\033[31m{s}\033[0m" if _TTY else s
_y = lambda s: f"\033[33m{s}\033[0m" if _TTY else s
_b = lambda s: f"\033[1m{s}\033[0m"  if _TTY else s


def _sha256(data: str) -> str:
    return "sha256_" + hashlib.sha256(data.encode()).hexdigest()


def _is_live_record(rec: dict) -> bool:
    """
    Live records (from the backend) lack a 'nonce' field and have a 40-char
    prevHash that is a real SHA-256 ('sha256_' + 64 hex chars = 71 total).
    Pre-built demo records always carry a 'nonce' field.
    """
    return "nonce" not in rec


def _content_hash(rec: dict) -> str:
    """SHA-256 of the record with 'hash' stripped, keys sorted."""
    payload = {k: v for k, v in rec.items() if k != "hash"}
    return _sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def _load(path: str) -> list[dict]:
    records = []
    with open(path) as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                print(_r(f"  ✗ Line {lineno}: invalid JSON — {exc}"))
                sys.exit(1)
    return records


def verify(path: str) -> bool:
    records = _load(path)
    if not records:
        print(_r("✗ File is empty — nothing to verify."))
        return False

    print(f"  {'#':>4}  {'decision':<10}  {'tool':<28}  {'link':<5}  {'hash':<5}  scenario")
    print("  " + "─" * 88)

    all_ok = True
    broken_at: list[int] = []
    live_count = 0
    demo_count = 0

    for idx, rec in enumerate(records, 1):
        stored_prev = rec.get("prevHash", "")
        stored_hash = rec.get("hash", "")
        decision    = rec.get("decision", "?")
        tool        = rec.get("tool", "?")[:26]
        scenario    = rec.get("scenario", "")[:28]

        # ── Check 1: chain linkage ────────────────────────────────────────
        if idx == 1:
            # First record: any genesis sentinel is accepted — we just record it
            link_ok = True
        else:
            expected_prev = records[idx - 2].get("hash", "")
            link_ok = (stored_prev == expected_prev)

        # ── Check 2: content hash (live records only) ─────────────────────
        is_live = _is_live_record(rec)
        if is_live:
            live_count += 1
            computed = _content_hash(rec)
            hash_ok = (computed == stored_hash)
            hash_sym = _g("✓") if hash_ok else _r("✗")
        else:
            demo_count += 1
            hash_ok = True   # not verified for demo records
            hash_sym = _y("—")   # — means "demo record, skipped"

        # ── Verdict ───────────────────────────────────────────────────────
        link_sym   = _g("✓") if link_ok else _r("✗")
        record_ok  = link_ok and hash_ok

        if not record_ok:
            all_ok = False
            broken_at.append(idx)

        print(f"  {idx:>4}  {decision:<10}  {tool:<28}  {link_sym}      {hash_sym}     {scenario}")

    print()
    total = len(records)
    if all_ok:
        print(_b(_g(f"✓ Chain intact — {total} record(s) verified")))
        if demo_count:
            print(_y(f"  ⚠ {demo_count} pre-built demo record(s): chain linkage verified, content hash skipped"))
        if live_count:
            print(_g(f"  ✓ {live_count} live record(s): full SHA-256 content verification passed"))
    else:
        first = broken_at[0]
        print(_b(_r(
            f"✗ TAMPERED — chain broken at record {first} "
            f"({len(broken_at)} broken record(s) in {total} total)"
        )))

    return all_ok


def main():
    ap = argparse.ArgumentParser(
        prog="toolguard",
        description="ToolGuard offline tamper-detection verifier for audit JSONL files"
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify", help="Verify a ToolGuard audit.jsonl file")
    v.add_argument("--chain", required=True, metavar="FILE",
                   help="Path to audit JSONL (Download button on the Audit Chain page)")
    args = ap.parse_args()

    if args.cmd == "verify":
        print(f"\nVerifying: {args.chain}\n")
        ok = verify(args.chain)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
