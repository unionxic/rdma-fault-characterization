# Verification: can an RDMA counter alone split the RETRY_EXC (0x81) pair?

**Question.** The CQE fingerprint RETRY_EXC (12 / 0x81) covers two causes with the
same status+vendor_err: the responder QP went to ERR (node alive), or the responder
process was killed (node's RDMA context gone). The repo docs
(`docs/theory/05_counter_observability.md` §5.3, `docs/theory/04` §4.3) claim these
have **identical RDMA traffic** (15 wire packets, identical sysfs signatures) and are
split only by the **non-RDMA TCP sideband** (process alive → FIN, ~12-13 pkts;
`kill -9` → RST, ~8 pkts) — i.e. by process liveness, not by an RDMA counter.

Earlier in this work I claimed the responder `port_rcv_packets` delta (peer_rx ≈ 40)
distinguished them. This verifies that claim on ConnectX-6 Dx (fw 20.43.4100).

**Method.** `verify_0x81_counter.sh` reads the responder's RDMA port counters
(`port_rcv_packets`, `port_xmit_packets`) externally over the fault window for each
cause (N=5, recovery off). Separately the harness now has the responder self-report
its fault-window rx/tx deltas in the PROBE reply (pre-recovery), giving a clean
fault-window measurement for the alive case.

**Results.**

| cause | port_rcv_packets Δ | port_xmit_packets Δ (fault window) |
|---|---:|---:|
| server_qp_err (node alive, QP ERR) | 40–57 | **0** |
| proc_kill (process dead) | 44–52 | 0 |

- `port_rcv_packets` is **the same** for both (~40–52): the requester's retransmits
  reach the responder NIC whether or not a QP exists to consume them. It does **not**
  distinguish the two causes.
- `port_xmit_packets` is **0 for both** in the fault window: a QP in ERR does not NAK,
  and a dead process cannot transmit. (An earlier external reading showed 5 vs 0, but
  that 5 was the post-recovery verify READ response — an artifact of the alive case
  recovering while the dead case cannot, not a fault-window signal.)

**Conclusion.** On this hardware, **no RDMA port counter separates the 0x81 pair** —
confirming the docs. The discriminator is **process liveness**: the docs read it from
the TCP sideband (FIN vs RST); this harness reads it from the control channel (a PROBE
that gets a reply vs a dead connection). Both are the same class of signal at the
TCP/liveness layer, not an RDMA counter. The harness sub-classifier was corrected to
decide `server_qp_err` vs `proc_kill` by liveness, and to report peer_rx/peer_tx as
diagnostics only. My earlier "peer_rx distinguishes them" claim was wrong.

**Where a counter still helps.** `link_down` is separated by the requester's own RDMA
port state (not ACTIVE). And a node-level telemetry daemon on the responder (surviving
process death) could use liveness of the process plus port counters for out-of-band
confirmation — but the in-band discriminator remains liveness.
