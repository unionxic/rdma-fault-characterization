#!/usr/bin/env python3
"""redact.py - copy logs for a public issue with hostnames and addresses replaced.

usage: redact.py <out_dir> <log>...

Management IPs become documentation addresses (192.0.2.x), node names become node0/node1,
and the RoCE IPv4 addresses (also inside IPv4-mapped GIDs) become 198.51.100.x.
"""
import os
import re
import sys


def mgmt_addresses():
    """The real management addresses, from a file outside the repository."""
    path = os.environ.get("MGMT_ENV", os.path.expanduser("~/.config/rdma-error/mgmt.env"))
    kv = dict(line.strip().split("=", 1) for line in open(path) if "=" in line)
    return kv["MGMT_A"], kv["MGMT_B"]


MGMT_A, MGMT_B = mgmt_addresses()
SUBS = [
    (re.escape(MGMT_A), "192.0.2.10"),
    (re.escape(MGMT_B), "192.0.2.11"),
    (r"\b30\.0\.0\.3\b", "198.51.100.3"),
    (r"\b30\.0\.0\.4\b", "198.51.100.4"),
    (r"ffff:1e00:0003", "ffff:c633:6403"),
    (r"ffff:1e00:0004", "ffff:c633:6404"),
    (r"\brain\b", "node0"),
    (r"\bsunny\b", "node1"),
    (r"/home/unionxic\b", "/home/user"),
    (r"\bunionxic\b", "user"),
]


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    for path in sys.argv[2:]:
        text = open(path, errors="replace").read()
        for pat, rep in SUBS:
            text = re.sub(pat, rep, text)
        left = re.findall(re.escape(MGMT_A.rsplit(".", 1)[0] + ".") + r"|\brain\b|\bsunny\b|unionxic", text)
        if left:
            sys.exit(f"{path}: unredacted text left: {sorted(set(left))}")
        dst = os.path.join(out, os.path.basename(path))
        with open(dst, "w") as f:
            f.write(text)
        print(dst)


if __name__ == "__main__":
    main()
