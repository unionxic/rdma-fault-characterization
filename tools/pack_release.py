#!/usr/bin/env python3
"""pack_release.py - pack the raw data (files git ignores) into one .tar.xz per result folder.

usage: pack_release.py <out_dir> [--only <folder> ...]

A result folder is <...>/results/<run>; files directly under <...>/results form their own
folder, and harness/nccl-integration/logs is packed too. Before packing, the real management
addresses (from ~/.config/rdma-error/mgmt.env, never committed) become 192.0.2.193/194 in every
file. Nested .gz/.xz/.tar.* archives are opened, fixed and re-packed the same way. Every final
archive is then scanned again, recursively, for the address prefix in any spelling
(digits separated by up to three non-digits). Writes SHA256SUMS and assets.tsv in <out_dir>.
"""
import gzip, hashlib, io, lzma, os, re, subprocess, sys, tarfile

REPO = os.path.expanduser("~/rdma-error")
DOC = ("192.0.2.193", "192.0.2.194")


def mgmt():
    path = os.environ.get("MGMT_ENV", os.path.expanduser("~/.config/rdma-error/mgmt.env"))
    kv = dict(l.strip().split("=", 1) for l in open(path) if "=" in l)
    return kv["MGMT_A"], kv["MGMT_B"]


A, B = mgmt()
SUBS = [(A.encode(), DOC[0].encode()), (B.encode(), DOC[1].encode())]
o = A.split(".")[:3]
LEAK = re.compile(o[0].encode() + rb"\D{1,3}" + o[1].encode() + rb"\D{1,3}" + o[2].encode())


def fix_bytes(b):
    """Replace the addresses in b; recurse into gzip / xz / tar containers.
    Content without the address is returned unchanged, byte for byte."""
    if not leaks(b):
        return b
    if b[:2] == b"\x1f\x8b":
        try:
            return gzip.compress(fix_bytes(gzip.decompress(b)), mtime=0)
        except Exception:
            pass
    if b[:6] == b"\xfd7zXZ\x00":
        try:
            return lzma.compress(fix_bytes(lzma.decompress(b)))
        except Exception:
            pass
    if len(b) > 262 and b[257:262] == b"ustar":
        try:
            src = tarfile.open(fileobj=io.BytesIO(b), mode="r:")
            out = io.BytesIO()
            dst = tarfile.open(fileobj=out, mode="w:", format=tarfile.PAX_FORMAT)
            for m in src.getmembers():
                if m.isfile():
                    data = fix_bytes(src.extractfile(m).read())
                    m.size = len(data)
                    dst.addfile(m, io.BytesIO(data))
                else:
                    dst.addfile(m)
            dst.close()
            return out.getvalue()
        except Exception:
            pass
    for a, c in SUBS:
        b = b.replace(a, c)
    return b


def leaks(b, name=""):
    """Names of leaves (recursively) that still match the address prefix."""
    found = []
    if b[:2] == b"\x1f\x8b":
        try:
            return leaks(gzip.decompress(b), name)
        except Exception:
            pass
    if b[:6] == b"\xfd7zXZ\x00":
        try:
            return leaks(lzma.decompress(b), name)
        except Exception:
            pass
    if len(b) > 262 and b[257:262] == b"ustar":
        try:
            t = tarfile.open(fileobj=io.BytesIO(b), mode="r:")
            for m in t.getmembers():
                if m.isfile():
                    found += leaks(t.extractfile(m).read(), name + "/" + m.name)
            return found
        except Exception:
            pass
    return [name] if LEAK.search(b) else []


def ignored_files():
    out = subprocess.run(["git", "-C", REPO, "status", "--porcelain", "--ignored", "-uall"],
                         capture_output=True, text=True, check=True).stdout
    return [l[3:] for l in out.splitlines() if l.startswith("!! ")]


def folder_of(path):
    parts = path.split("/")
    if "results" in parts:
        i = parts.index("results")
        return "/".join(parts[:i + 2]) if len(parts) > i + 2 else "/".join(parts[:i + 1])
    if path.startswith("harness/nccl-integration/logs/"):
        return "harness/nccl-integration/logs"
    return None


def main():
    out_dir = sys.argv[1]
    only = sys.argv[sys.argv.index("--only") + 1:] if "--only" in sys.argv else None
    os.makedirs(out_dir, exist_ok=True)
    groups = {}
    for p in ignored_files():
        if "__pycache__" in p or "/.claude/" in p:
            continue
        f = folder_of(p)
        if f and os.path.isfile(os.path.join(REPO, p)):
            groups.setdefault(f, []).append(p)
    rows = []
    for folder in sorted(groups):
        if only and folder not in only:
            continue
        name = folder.replace("/", "__") + ".tar.xz"
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:", format=tarfile.PAX_FORMAT) as tar:
            for p in sorted(groups[folder]):
                fp = os.path.join(REPO, p)
                data = fix_bytes(open(fp, "rb").read())
                ti = tarfile.TarInfo(p)
                st = os.stat(fp)
                ti.size, ti.mtime, ti.mode = len(data), int(st.st_mtime), st.st_mode & 0o777
                tar.addfile(ti, io.BytesIO(data))
        xz = lzma.compress(buf.getvalue(), preset=9)
        bad = leaks(xz, name)
        if bad:
            sys.exit(f"address left in {bad[:5]}; nothing written for {folder}")
        open(os.path.join(out_dir, name), "wb").write(xz)
        sha = hashlib.sha256(xz).hexdigest()
        rows.append((folder, name, len(groups[folder]), len(xz), sha))
        print(f"{len(xz)/1e6:8.2f} MB {len(groups[folder]):5d} files  {name}")
    with open(os.path.join(out_dir, "SHA256SUMS"), "w") as f:
        for r in rows:
            f.write(f"{r[4]}  {r[1]}\n")
    with open(os.path.join(out_dir, "assets.tsv"), "w") as f:
        f.write("folder\tasset\tfiles\tbytes\tsha256\n")
        for r in rows:
            f.write("\t".join(map(str, r)) + "\n")


if __name__ == "__main__":
    main()
