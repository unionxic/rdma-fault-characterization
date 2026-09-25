#!/usr/bin/env python3
"""assemble_doc.py <template.md> <analysis.md> <out.md>
Replace each '<!--T:key-->' line of the template with the body of the analysis section '### key. ...'
(the table and its notes, without the '### ' heading line); '<!--TH:key-->' also keeps the heading
text as a bold line. Fails if a key is missing or unused."""
import re, sys

tpl, ana, out = sys.argv[1:4]
sec, head, cur = {}, {}, None
for line in open(ana).read().splitlines():
    m = re.match(r'^### (\w+)\. (.*)$', line)
    if m:
        cur = m.group(1)
        sec[cur] = []
        head[cur] = m.group(2)
        continue
    if cur:
        sec[cur].append(line)
used = set()
res = []
for line in open(tpl).read().splitlines():
    m = re.match(r'^<!--T(H?):(\w+)-->$', line.strip())
    if m:
        k = m.group(2)
        if m.group(1) == 'H' and k in head:
            res.extend(['**' + head[k] + '**', ''])
        if k not in sec:
            sys.exit('missing analysis section %s' % k)
        body = sec[k]
        while body and not body[0].strip():
            body = body[1:]
        while body and not body[-1].strip():
            body = body[:-1]
        res.extend(body)
        used.add(k)
    else:
        res.append(line)
unused = set(sec) - used
if unused:
    sys.exit('analysis sections not used: %s' % sorted(unused))
open(out, 'w').write('\n'.join(res) + '\n')
print('wrote %s (%d sections)' % (out, len(used)))
