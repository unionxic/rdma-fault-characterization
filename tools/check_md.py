#!/usr/bin/env python3
"""check_md.py [file.md ...] - refuse Markdown that GitHub would render with an accidental strikethrough.

GitHub reads ~text~ (one tilde or two) as strikethrough, so two range tildes such as "3.5~3.8 s ...
58.5~58.8 s" in one paragraph, list item or table cell strike out the text between them. Outside code,
a tilde must have whitespace on both sides; write ranges with an en dash (3.5–3.8) and "about" as
"약 N" or "≈N". Without arguments every tracked .md file is checked, except the files fixed by a
pre-registration tag, which are never edited. Exits 1 and lists the places it found.
"""
import re, subprocess, sys

FROZEN = ("harness/gpu-initiated/propagation/PREDICTIONS.md",
          "harness/gpu-initiated/propagation/REVIEW_20261006.md",
          "harness/gpu-initiated/propagation/review_20261006/")


def bad_tildes(text):
    found = []
    parts = re.split(r"(```.*?```)", text, flags=re.S)
    line_no = 1
    for k, part in enumerate(parts):
        if k % 2 == 0:
            for j, line in enumerate(part.split("\n")):
                plain = re.sub(r"`[^`]*`", lambda m: " " * len(m.group(0)), line)
                for m in re.finditer("~", plain):
                    a = plain[m.start() - 1] if m.start() > 0 else " "
                    b = plain[m.end()] if m.end() < len(plain) else " "
                    if not (a.isspace() and b.isspace()):
                        found.append((line_no + j, line.strip()[:80]))
        line_no += part.count("\n")
    return found


def main():
    files = sys.argv[1:] or subprocess.run(["git", "ls-files", "*.md"], capture_output=True,
                                           text=True, check=True).stdout.split()
    bad = 0
    for f in files:
        if f.startswith(FROZEN):
            continue
        for n, line in bad_tildes(open(f, encoding="utf-8").read()):
            print(f"{f}:{n}: tilde outside code: {line}")
            bad += 1
    if bad:
        print(f"{bad} tilde(s) GitHub may render as strikethrough; use – for ranges, 약/≈ for about")
        sys.exit(1)


if __name__ == "__main__":
    main()
