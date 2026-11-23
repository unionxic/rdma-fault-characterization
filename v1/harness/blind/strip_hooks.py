#!/usr/bin/env python3
"""strip_hooks.py - blind-apps: the evaluator's view of one rank's log (EXPERIMENT.md 5, pre-registered).

A log line is dropped when it was written by a fault hook or a test switch, or names one: those lines would tell the
evaluator what was injected. Everything else the application and the libraries printed is kept, in order. The
receipt time of each kept line is shown relative to the trial's start.

Dropped (HOOK): the Stage 2 hook lines ([FAULT-INJECT], the silent-mode drain line, the test mute), the GIN hook lines
(GIN/FAULT: armed, fired, trigger, shot) and test-switch lines (GIN/TS: TEST ...), the NVSHMEM hook lines
([nvshmem-fault-inject] ...) and test switches (FT_TEST, T1_TEST), any line naming a hook variable (FAULT_INJECT) or a
harness variable (BLIND_), any line carrying a hook fire time (fire_mono_ms).
Every IPv4 address in a kept line is replaced by <ip>. A kept line must not match LEAK (audit): handoff.py refuses to
build the evaluator's folder if one does.

    strip_hooks.py <raw log> [t0]     print the view of one log (for checking by hand)
"""
import re, sys

HOOK = re.compile(r"\[FAULT-INJECT\]|SILENT test mode|RDMA_FAULT_TEST|FAULT_INJECT|GIN/FAULT:|GIN/TS: TEST\b|"
                  r"\[nvshmem-fault-inject\]|FT_TEST|T1_TEST|BLIND_|fire_mono_ms", re.I)
LEAK = re.compile(r"inject|hook (armed|fired)|fault fired|forced (send|recv) QP|SIGSTOP|SIGCONT|SIGKILL sent|"
                  r"iptables|blind-\d+-|^AGENT ", re.I)


IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")


def view(lines, t0):
    """lines: [(rain mono, text)] -> [(seconds since t0, text)] without hook lines; IPv4 addresses become <ip> (the
    management addresses are never written into the repository, and the evaluator's notes are committed)."""
    return [(t - t0, IPV4.sub("<ip>", l)) for t, l in lines if not HOOK.search(l)]


def leaks(view_lines):
    return [l for _, l in view_lines if LEAK.search(l)]


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    t0 = float(sys.argv[2]) if len(sys.argv) > 2 else None
    lines = []
    for l in open(sys.argv[1], errors="replace"):
        t, _, rest = l.rstrip("\n").partition(" ")
        lines.append((float(t), rest))
    if t0 is None:
        t0 = lines[0][0] if lines else 0.0
    for t, l in view(lines, t0):
        print("%9.3f %s" % (t, l))


if __name__ == "__main__":
    main()
