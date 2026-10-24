#!/usr/bin/env python3
"""Find code references to a byte range in an ARM (A32) PIC shared object. Read-only.

Usage: python3 -I arm_pic_xrefs.py <objdump -d --triple=armv7 output> <elf> <lo_hex> <hi_hex> [got_hex]

Resolves the two GCC PIC idioms:
  ldr rX, [pc, #n]   ; literal L
  add rY, pc, rX     ; target = L + addr(add) + 8             (PC-relative)
  ldr rX, [pc, #n]   ; literal L, with rB holding the GOT base
  add/ldr .., rB, rX ; target = GOT + L                       (GOT-relative, needs got_hex)
Every literal value that falls in [lo, hi) after either rule is reported with its function.
Also reports raw literals equal to an address in range (absolute pointers, relocated data).
"""
import re
import struct
import sys

dis_path, elf_path, lo, hi = sys.argv[1], sys.argv[2], int(sys.argv[3], 16), int(sys.argv[4], 16)
got = int(sys.argv[5], 16) if len(sys.argv) > 5 else None
data = open(elf_path, 'rb').read()

ins = []  # (addr, text, func)
func = None
for line in open(dis_path):
    m = re.match(r'^([0-9a-f]+) <(.+)>:', line)
    if m:
        func = m.group(2)
        continue
    m = re.match(r'^\s*([0-9a-f]+):\s+([0-9a-f]{8})\s+(.*)$', line)
    if m:
        t = re.sub(r'\s+', ' ', m.group(3).split('@')[0]).strip()
        ins.append((int(m.group(1), 16), t, func))

def word(addr):
    return struct.unpack_from('<I', data, addr)[0]

hits = []
for i, (a, t, f) in enumerate(ins):
    m = re.match(r'ldr (r\d+|lr), \[pc, #(-?0x[0-9a-f]+|-?\d+)\]$', t)
    if not m:
        m2 = re.match(r'ldr (r\d+|lr), \[pc\]$', t)
        if not m2:
            continue
        reg, off = m2.group(1), 0
    else:
        reg, off = m.group(1), int(m.group(2), 0)
    lit_addr = a + 8 + off
    L = word(lit_addr)
    for b, u, g in ins[i + 1:i + 48]:
        m3 = re.match(r'add (\S+), pc, ' + reg + r'$', u)
        if m3:
            tgt = (L + b + 8) & 0xffffffff
            if lo <= tgt < hi:
                hits.append((tgt, a, b, 'pc-rel', f, t + ' | ' + u))
            break
        if got is not None and re.match(r'(add|ldr) \S+, \[?r\d+, ' + reg + r'\]?$', u):
            tgt = (got + L) & 0xffffffff
            if lo <= tgt < hi:
                hits.append((tgt, a, b, 'got-rel', f, t + ' | ' + u))
            break
    if lo <= L < hi:
        hits.append((L, a, lit_addr, 'literal', f, t))

for h in sorted(hits):
    s = data[h[0]:data.index(b'\0', h[0])].decode('latin1')
    print(f'target {h[0]:#06x} "{s}"  from {h[1]:#06x}/{h[2]:#06x} {h[3]:8s} in {h[4]}: {h[5]}')
print(f'# {len(hits)} reference(s) into [{lo:#x}, {hi:#x})')
