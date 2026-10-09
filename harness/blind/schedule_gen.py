#!/usr/bin/env python3
"""schedule_gen.py - blind-apps: the fault agent's schedule generator (run by the fault agent, never by the evaluator).

    schedule_gen.py check  [--config schedule_config.json] [--out ~/blind-seal/schedule.json]   (pre-flight, no draw)
    schedule_gen.py make   [--config schedule_config.json] [--out ~/blind-seal/schedule.json]
    schedule_gen.py verify <schedule.json> [--config schedule_config.json]

make
  - refuses unless schedule_config.json and predictions.csv are committed and unchanged in the working tree (the
    predictions are fixed before any schedule exists), and unless --out does not exist yet;
  - draws 32 bytes from /dev/urandom (os.urandom) and seeds random.Random with them;
  - per workload: the trial list (classes x counts of the config), shuffled; per trial a random target rank (classes
    in "targeted"), two uniform fractions u_t (when, mapped by calib.json) and u_d (how long, mapped by the config's
    durations), a direction for management mutes, and an opaque 8-hex-digit trial id (unique across workloads);
  - packs each workload's shuffled list into holds of "per_hold" trials (D1, D2, ..., G1, ..., N1, ...);
  - writes the schedule (JSON, mode 0600) and <out>.sha256, and prints only the file's sha256, the trial count per
    workload and the hold names with their trial counts. It never prints a trial's class, target or time.
  The header records the seed, the git commit, and the sha256 of the config, predictions.csv and this file, so that
  verify can re-derive every trial after the reveal.
verify
  re-derives the trials from the recorded seed with the given config and checks that they equal the file's trials and
  that the recorded hashes match; prints OK or the first difference.
"""
import argparse, datetime, hashlib, json, os, random, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def git(*a):
    return subprocess.run(["git", "-C", HERE] + list(a), capture_output=True, text=True).stdout.strip()


def draw(cfg, seed_hex):
    rng = random.Random(int(seed_hex, 16))
    nhex = int(cfg.get("trial_id_hex_digits", 8))
    used, trials = set(), []
    for wl in sorted(cfg["workloads"]):
        w = cfg["workloads"][wl]
        lst = [c for c in sorted(w["classes"]) for _ in range(int(w["classes"][c]))]
        rng.shuffle(lst)
        per = int(w["per_hold"])
        for i, c in enumerate(lst):
            while True:
                tid = "%0*x" % (nhex, rng.getrandbits(4 * nhex))
                if tid not in used:
                    used.add(tid)
                    break
            target = rng.choice([0, 1]) if c in w["targeted"] else None
            u_t, u_d = rng.random(), rng.random()
            d = rng.choice(cfg["mute_directions"]) if c == "mute" else None
            trials.append({"id": tid, "workload": wl, "order": i, "hold": "%s%d" % (w["hold_prefix"], i // per + 1),
                           "cls": c, "target": target, "u_t": round(u_t, 6), "u_d": round(u_d, 6), "dir": d})
    return trials


def committed_unchanged(paths):
    """[] if every path is tracked and unchanged in the working tree, else the offending paths."""
    top = git("rev-parse", "--show-toplevel")
    bad = []
    for p in paths:
        rel = os.path.relpath(p, top)
        tracked = subprocess.run(["git", "-C", top, "ls-files", "--error-unmatch", "--", rel], capture_output=True).returncode == 0
        dirty = subprocess.run(["git", "-C", top, "status", "--porcelain", "--", rel], capture_output=True,
                               text=True).stdout.strip()
        if not tracked or dirty:
            bad.append(rel)
    return bad


def cmd_check(a):
    bad = committed_unchanged([os.path.abspath(a.config), os.path.join(HERE, "predictions.csv")])
    out = os.path.expanduser(a.out)
    print("committed and unchanged: %s" % ("yes" if not bad else "NO " + " ".join(bad)))
    print("%s exists: %s" % (out, "YES (make will refuse)" if os.path.exists(out) else "no"))
    sys.exit(1 if bad or os.path.exists(out) else 0)


def cmd_make(a):
    cfg_path = os.path.abspath(a.config)
    pred_path = os.path.join(HERE, "predictions.csv")
    out = os.path.expanduser(a.out)
    bad = committed_unchanged([cfg_path, pred_path])
    if bad:
        sys.exit("refused: %s not committed or changed (predictions and config are fixed first)" % " ".join(bad))
    if os.path.exists(out):
        sys.exit("refused: %s exists (a schedule is generated once)" % out)
    cfg = json.load(open(cfg_path))
    seed_hex = os.urandom(32).hex()
    trials = draw(cfg, seed_hex)
    header = {"study": cfg.get("study"), "created": datetime.datetime.now().isoformat(timespec="seconds"),
              "seed_hex": seed_hex, "git_head": git("rev-parse", "HEAD"),
              "config_sha256": sha256_file(cfg_path), "predictions_sha256": sha256_file(pred_path),
              "generator_sha256": sha256_file(os.path.abspath(__file__)), "config": cfg}
    os.makedirs(os.path.dirname(out), mode=0o700, exist_ok=True)
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"header": header, "trials": trials}, f, indent=1, sort_keys=True)
        f.write("\n")
    digest = sha256_file(out)
    with open(out + ".sha256", "w") as f:
        f.write("%s  %s\n" % (digest, os.path.basename(out)))
    os.chmod(out + ".sha256", 0o600)
    print("schedule: %s" % out)
    print("sha256: %s" % digest)
    for wl in sorted(cfg["workloads"]):
        holds = {}
        for t in trials:
            if t["workload"] == wl:
                holds[t["hold"]] = holds.get(t["hold"], 0) + 1
        print("%s: %d trials; holds %s" % (wl, sum(holds.values()),
                                           " ".join("%s(%d)" % (h, holds[h]) for h in sorted(holds, key=lambda x: (len(x), x)))))


def cmd_verify(a):
    s = json.load(open(os.path.expanduser(a.schedule)))
    cfg = json.load(open(a.config))
    h = s["header"]
    bad = []
    if h["config"] != cfg:
        bad.append("the header's config differs from %s" % a.config)
    if h["config_sha256"] != sha256_file(a.config):
        bad.append("config sha256 differs (header %s)" % h["config_sha256"][:12])
    if s["trials"] != draw(h["config"], h["seed_hex"]):
        bad.append("the trials are not the ones the recorded seed and config give")
    print("OK" if not bad else "DIFFERENT: " + "; ".join(bad))
    sys.exit(0 if not bad else 1)


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    for name in ("make", "check"):
        m = sp.add_parser(name)
        m.add_argument("--config", default=os.path.join(HERE, "schedule_config.json"))
        m.add_argument("--out", default="~/blind-seal/schedule.json")
    v = sp.add_parser("verify")
    v.add_argument("schedule")
    v.add_argument("--config", default=os.path.join(HERE, "schedule_config.json"))
    a = ap.parse_args()
    {"make": cmd_make, "check": cmd_check, "verify": cmd_verify}[a.cmd](a)


if __name__ == "__main__":
    main()
