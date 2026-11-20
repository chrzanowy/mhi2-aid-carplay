"""Host test of the feeder's H.264 keep-alive pictures (h264_ka.c, feeder v17, A215-AA).

usage: python3 -I run_ka_test.py STREAM.h264 [OUT_DIR] [CC]
  STREAM.h264  a phone cluster stream as the hook serves it (Annex B), e.g. a feeder capture (PMCP_AA_CAPTURE)

Keep-alive pictures are inserted after chosen phone pictures (also several in a row, also before the first IDR, where
none may be made), the phone pictures after them are shifted; ffmpeg decodes the original and the result with every
error check on. Passes when the result decodes without one error, every phone picture decodes to the same pixels as
in the original (framemd5), and every keep-alive picture equals the picture before it.
"""
import os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(sys.argv[1])
OUT = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else tempfile.mkdtemp(prefix='pmcp-ka-')
CC = sys.argv[3] if len(sys.argv) > 3 else 'cc'
os.makedirs(OUT, exist_ok=True)
fails = []


def check(cond, msg):
    print(('ok    ' if cond else 'FAILED ') + msg)
    if not cond:
        fails.append(msg)


def framemd5(path):
    r = subprocess.run(['ffmpeg', '-v', 'error', '-err_detect', 'crccheck+bitstream+buffer+explode', '-f', 'h264',
                        '-i', path, '-f', 'framemd5', '-'], capture_output=True, text=True)
    md5 = [l.split(',')[-1].strip() for l in r.stdout.splitlines() if l and not l.startswith('#')]
    return r.returncode, r.stderr.strip(), md5


exe = os.path.join(OUT, 'ka_insert')
subprocess.run([CC, '-O2', '-Wall', '-Wextra', '-Werror', '-std=gnu99', '-o', exe,
                os.path.join(HERE, 'ka_insert.c'), os.path.join(HERE, '..', 'h264_ka.c')], check=True)

rc, err, orig = framemd5(SRC)
check(rc == 0 and err == '', 'original decodes cleanly (%d pictures) %s' % (len(orig), err[:200]))

PLANS = {
    'one-each': ','.join('%d:1' % a for a in range(0, 400, 3)),
    'runs': ','.join('%d:%d' % (a, 1 + a % 9) for a in range(0, 600, 7)),
    'long-silence': '5:600,200:300,350:1',
    'first-pic': '0:4',
}
for name, plan in PLANS.items():
    o = os.path.join(OUT, name + '.h264')
    m = os.path.join(OUT, name + '.map')
    subprocess.run([exe, SRC, o, m, plan], check=True)
    lines = open(m).read().splitlines()
    kinds = [l for l in lines if l in ('p', 'k')]
    stats = lines[-1]
    errs = [l for l in lines if l.startswith('err')]
    rc, err, got = framemd5(o)
    check(rc == 0 and err == '', '%s: decodes without an error (%s) %s' % (name, stats, err[:300]))
    check(not errs, '%s: every phone slice shifted (%s)' % (name, errs[:3]))
    check(len(got) == len(kinds), '%s: %d pictures decoded, %d written' % (name, len(got), len(kinds)))
    phone = [md for md, kd in zip(got, kinds) if kd == 'p']
    check(phone == orig, '%s: phone pictures identical to the original (%d)' % (name, len(phone)))
    bad = [i for i, kd in enumerate(kinds) if kd == 'k' and (i == 0 or got[i] != got[i - 1])]
    check(not bad and kinds.count('k') > 0,
          '%s: %d keep-alive pictures, each equal to the one before (bad at %s)' % (name, kinds.count('k'), bad[:5]))

print('KA CHECKS FAILED: %d' % len(fails))
sys.exit(1 if fails else 0)
