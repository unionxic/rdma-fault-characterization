#!/usr/bin/env python3
# [한국어 요약] fio JSON에서 "p50 p99 max err" 4필드를 한 줄로 추출.
# 실패/잘린 JSON이면 호출부(fio_latency)가 "NA NA NA 124" 폴백을 쓴다.
# parse_fio.py — extract latency percentiles + error from a fio --output-format=json
# result. Prints "p50us p99us maxus errcode" (space separated) to stdout.
# Usage: parse_fio.py <fio_json_file> <read|write>
# On any parse failure prints "NA NA NA NA" (exit 0) so the caller can proceed.
import sys, json

def main():
    if len(sys.argv) != 3:
        print("NA NA NA NA"); return
    path, rw = sys.argv[1], sys.argv[2]
    try:
        with open(path) as f:
            j = json.load(f)
        job = j["jobs"][0]
        sec = job["read"] if rw.startswith("read") else job["write"]
        cl = sec.get("clat_ns") or sec.get("lat_ns") or {}
        pct = cl.get("percentile", {})
        p50 = float(pct.get("50.000000", 0)) / 1000.0
        p99 = float(pct.get("99.000000", 0)) / 1000.0
        mx = float(cl.get("max", 0)) / 1000.0
        err = job.get("error", 0)
        print(f"{p50:.1f} {p99:.1f} {mx:.1f} {err}")
    except Exception:
        print("NA NA NA NA")

if __name__ == "__main__":
    main()
