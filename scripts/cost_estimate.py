#!/usr/bin/env python3
"""Pre-deploy cost estimate for the RetroCloud worker (run this BEFORE `terraform apply`).

    python3 scripts/cost_estimate.py --machine e2-standard-4 --hours 120 --players 1
    python3 scripts/cost_estimate.py --machine e2-standard-8 --hours 120 --players 2 --spot

Prices are USD list prices collected on 2026-11-10 from third-party mirrors of the GCP
price list (see docs/cost-analysis.md for sources). They are estimates: always confirm
with the official calculator (https://cloud.google.com/products/calculator) and remember
that taxes are not included. Free-trial credit pays these amounts but they still count.
"""
from __future__ import annotations

import argparse

# europe-west3 (Frankfurt), USD per hour: (on-demand, spot)
VM_PRICES = {
    "e2-standard-2": (0.0864, 0.052),   # half of e2-standard-4 (derived)
    "e2-standard-4": (0.173, 0.104),
    "e2-standard-8": (0.345, 0.207),
    "n2d-standard-8": (0.435, 0.245),
    "c2d-standard-8": (0.468, 0.134),
    "c4d-standard-8": (0.437, 0.261),
}
DISK_GB_MONTH = {"pd-standard": 0.048, "pd-balanced": 0.12}  # europe-west3
EPHEMERAL_IP_HOUR = 0.005          # in-use external IPv4 (not charged while VM is stopped)
EGRESS = {"STANDARD": (200, 0.085), "PREMIUM": (0, 0.12)}  # (free GiB/month, $/GiB after)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--machine", default="e2-standard-4", choices=VM_PRICES)
    ap.add_argument("--hours", type=float, default=120, help="VM running hours per month")
    ap.add_argument("--play-hours", type=float, help="hours actually streamed per player (default = --hours)")
    ap.add_argument("--players", type=int, default=1)
    ap.add_argument("--mbps", type=float, default=3.0, help="video+audio bitrate per player")
    ap.add_argument("--disk-gb", type=float, default=30, help="boot + data disk")
    ap.add_argument("--disk-type", default="pd-balanced", choices=DISK_GB_MONTH)
    ap.add_argument("--tier", default="STANDARD", choices=EGRESS)
    ap.add_argument("--spot", action="store_true")
    a = ap.parse_args()

    od, sp = VM_PRICES[a.machine]
    vm_rate = sp if a.spot else od
    vm = vm_rate * a.hours
    disk = DISK_GB_MONTH[a.disk_type] * a.disk_gb
    ip = EPHEMERAL_IP_HOUR * a.hours
    play_h = a.play_hours if a.play_hours is not None else a.hours
    gib = a.mbps * 1e6 / 8 * 3600 * play_h * a.players / 2**30
    free, per = EGRESS[a.tier]
    egress = max(0.0, gib - free) * per
    total = vm + disk + ip + egress

    print(f"machine {a.machine} ({'spot' if a.spot else 'on-demand'}) @ ${vm_rate}/h x {a.hours:.0f} h")
    print(f"  VM compute ............ ${vm:8.2f}")
    print(f"  disks {a.disk_gb:.0f} GB {a.disk_type:11s} ${disk:8.2f}   <- billed even when the VM is stopped")
    print(f"  external IP ........... ${ip:8.2f}")
    print(f"  egress {gib:6.1f} GiB {a.tier:8s} ${egress:8.2f}   ({a.players} player(s) x {play_h:.0f} h x {a.mbps} Mbps)")
    print(f"  TOTAL / month ......... ${total:8.2f}   (+ tax; logging/monitoring within free allotment)")
    print(f"  idle month (VM stopped) ${disk:8.2f}")
    print(f"  $300 trial credit lasts ~{300 / total:.1f} months at this usage (but expires after 90 days)")


if __name__ == "__main__":
    main()
