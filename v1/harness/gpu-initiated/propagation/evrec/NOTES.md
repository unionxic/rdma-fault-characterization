# evrec: async events and port counters of one RDMA device

`evrec` is instrument 1 of the propagation campaign (`../PREDICTIONS.md`). One copy runs on each
node for every trial. It:
- opens one RDMA device;
- logs every async event delivered to its context, one line each, with `CLOCK_MONOTONIC` and
  `CLOCK_REALTIME` nanoseconds;
- writes every file of `/sys/class/infiniband/<dev>/ports/<port>/hw_counters/` and `counters/`
  at start and at end.

The end is SIGTERM, SIGINT or SIGHUP, or the `-T` bound. evrec creates no PD, CQ, QP or MR, and
it never writes to the device or to sysfs. The only change it makes is `O_NONBLOCK` on its own
async-event descriptor.

## What it can and cannot see

- **It sees port and device events**: `PORT_ACTIVE`, `PORT_ERR`, `GID_CHANGE`, `LID_CHANGE`,
  `PKEY_CHANGE`, `SM_CHANGE`, `CLIENT_REREGISTER`, `DEVICE_FATAL`. The kernel sends these to
  every open context of the device.
- **It does not see QP-affiliated events of other processes' QPs.** QP, CQ, SRQ and WQ events
  go only to the context that owns the object. A `QP_ACCESS_ERR` on the harness responder's QP
  reaches `probe_server`'s own async thread, never evrec. The same holds for NCCL's and
  NVSHMEM's QPs, whether they are created through verbs or through DEVX.
- **The port counters may miss DEVX QPs.** In the official380 runs, rain's port `hw_counters`
  stayed at +0 while NVSHMEM's DEVX QPs failed (`../../nvshmem_rootcause/official380/`,
  NVIDIA/nvshmem#64). A +0 delta is therefore no proof that a DEVX QP saw no error.

## Usage

```
make
./evrec -d mlx5_1 -p 1 -o trial.evrec -T 300      # ends on SIGTERM/SIGINT/SIGHUP or after 300 s
```

| option | meaning | default |
|---|---|---|
| `-d dev` | RDMA device | required |
| `-p port` | port whose counters are written | 1 |
| `-o file` | output file (truncated) | stdout |
| `-T s` | stop after `s` seconds; `0` = only on a signal | 0 |

A runner starts evrec before the trial and sends SIGTERM after it. A signal that arrives while
evrec is still opening the device is held until the wait loop starts, so the end snapshot is
always written. SIGKILL skips the end snapshot.

Exit status: 0 = normal end (signal or `-T`), 1 = device or I/O error, 2 = bad arguments.

## Output

One record per line, `<kind> key=value ...`. The output is line-buffered.

```
start dev=mlx5_1 port=1 pid=3639662 max_s=1.5 mono_ns=... real_ns=...
port phase=start state=active phys_state=5
snap phase=start dir=hw_counters mono_ns=... real_ns=... files=30
ctr phase=start dir=hw_counters name=req_cqe_error value=24376
...
snap phase=start dir=counters mono_ns=... real_ns=... files=21
ctr phase=start dir=counters name=port_rcv_data value=7616154303850
...
event seq=1 mono_ns=... real_ns=... type=IBV_EVENT_GID_CHANGE code=18 elem=port port=1
port phase=end state=active phys_state=5
snap phase=end dir=hw_counters ...
ctr phase=end ...
end reason=sigterm events=1 mono_ns=... real_ns=...
```

- `snap` carries the time the directory was read. Reading `hw_counters` issues one firmware
  query per file and takes about 6 ms for 30 files on ConnectX-6.
- `ctr` values are written as read, so non-numeric files are kept. An unreadable file gives
  `value=? err=<reason>`.
- `event` `type` is the `enum ibv_event_type` name. The element is `port=N`, `qpn=0x..`,
  `wqn=0x..`, `cq`, `srq` or `device`.
- `end` `reason` is `sigterm`, `sigint`, `sighup`, `timeout` or `error`.

Counter deltas are end minus start for each `(dir, name)`. `lifespan` is a setting, not a
counter.

## Local check (2026-10-06, rain, no peer, no traffic generated)

- `-T 1.5` on `mlx5_1` port 1: exit 0, `end reason=timeout`, 30 `hw_counters` and 21 `counters`
  files at start and at end, port `active`, no events.
- Under `timeout -s TERM 1` and `timeout -s INT 1`: `end reason=sigterm` and `reason=sigint`,
  each with the end snapshot.
- No async event was produced locally. The event line format is checked only by the build.
