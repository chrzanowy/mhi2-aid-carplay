# SPDX-License-Identifier: GPL-3.0-or-later
# SHA-256 (FIPS 180-4) in plain gawk, for the head unit's gawk 3.1.5 (MMX /mnt/app/armle/usr/bin/gawk),
# which has no sha256/md5/cksum tool. Output per file: "<64 hex>  <size>  <path>", like sha256sum plus size.
#
#   LC_ALL=C gawk -f sha256.awk FILE...
#
# Binary safe: RS is a byte that is only used to split, and RT (gawk >= 3.0) gives the exact separator
# that ended each record, so NULs and missing final newlines are reproduced byte for byte.
# Run the self test (selftest.bin, all 256 byte values) before trusting the result on a new unit.

function init_state() {
    H0 = 1779033703; H1 = 3144134277; H2 = 1013904242; H3 = 2773480762
    H4 = 1359893119; H5 = 2600822924; H6 = 528734635;  H7 = 1541459225
    nbytes = 0; nbuf = 0
}

# Rotations are written out arithmetically: for 0 <= x < 2^32, rotr(x, n) = int(x / 2^n) + (x % 2^n) * 2^(32-n),
# exact in IEEE doubles. Function calls are the main cost in gawk 3.1.5, so the round loop has none of our own.
function block(   t, a, b, c, d, e, f, g, h, s0, s1, ch, maj, t1, x) {
    for (t = 0; t < 16; t++)
        W[t] = buf[4*t] * 16777216 + buf[4*t+1] * 65536 + buf[4*t+2] * 256 + buf[4*t+3]
    for (t = 16; t < 64; t++) {
        x = W[t-15]
        s0 = xor(xor(int(x / 128) + (x % 128) * 33554432, int(x / 262144) + (x % 262144) * 16384), int(x / 8))
        x = W[t-2]
        s1 = xor(xor(int(x / 131072) + (x % 131072) * 32768, int(x / 524288) + (x % 524288) * 8192), int(x / 1024))
        W[t] = (W[t-16] + s0 + W[t-7] + s1) % 4294967296
    }
    a = H0; b = H1; c = H2; d = H3; e = H4; f = H5; g = H6; h = H7
    for (t = 0; t < 64; t++) {
        s1 = xor(xor(int(e / 64) + (e % 64) * 67108864, int(e / 2048) + (e % 2048) * 2097152), int(e / 33554432) + (e % 33554432) * 128)
        ch = xor(and(e, f), and(4294967295 - e, g))
        t1 = h + s1 + ch + K[t] + W[t]
        s0 = xor(xor(int(a / 4) + (a % 4) * 1073741824, int(a / 8192) + (a % 8192) * 524288), int(a / 4194304) + (a % 4194304) * 1024)
        maj = xor(xor(and(a, b), and(a, c)), and(b, c))
        h = g; g = f; f = e; e = (d + t1) % 4294967296; d = c; c = b; b = a; a = (t1 + s0 + maj) % 4294967296
    }
    H0 = (H0 + a) % 4294967296; H1 = (H1 + b) % 4294967296; H2 = (H2 + c) % 4294967296; H3 = (H3 + d) % 4294967296
    H4 = (H4 + e) % 4294967296; H5 = (H5 + f) % 4294967296; H6 = (H6 + g) % 4294967296; H7 = (H7 + h) % 4294967296
    nbuf = 0
}

function feed(s,   i, n) {
    n = length(s)
    for (i = 1; i <= n; i++) {
        buf[nbuf++] = ORD[substr(s, i, 1)]
        if (nbuf == 64) block()
    }
    nbytes += n
}

function finish(   bits, i) {
    bits = nbytes * 8
    buf[nbuf++] = 128
    if (nbuf > 56) { while (nbuf < 64) buf[nbuf++] = 0; block() }
    while (nbuf < 56) buf[nbuf++] = 0
    for (i = 7; i >= 0; i--) { buf[56 + i] = bits % 256; bits = int(bits / 256) }
    nbuf = 64; block()
    return sprintf("%08x%08x%08x%08x%08x%08x%08x%08x", H0, H1, H2, H3, H4, H5, H6, H7)
}

function done_file() {
    if (cur != "") printf "%s  %d  %s\n", finish(), nbytes, cur
}

BEGIN {
    RS = "\n"
    for (i = 0; i < 256; i++) ORD[sprintf("%c", i)] = i
    if (length(sprintf("%c", 0)) != 1 || length(ORD) != 256) { print "SHA256_AWK_BYTE_TABLE_BROKEN" > "/dev/stderr"; broken = 1; exit 3 }
    split("1116352408 1899447441 3049323471 3921009573 961987163 1508970993 2453635748 2870763221 " \
          "3624381080 310598401 607225278 1426881987 1925078388 2162078206 2614888103 3248222580 " \
          "3835390401 4022224774 264347078 604807628 770255983 1249150122 1555081692 1996064986 " \
          "2554220882 2821834349 2952996808 3210313671 3336571891 3584528711 113926993 338241895 " \
          "666307205 773529912 1294757372 1396182291 1695183700 1986661051 2177026350 2456956037 " \
          "2730485921 2820302411 3259730800 3345764771 3516065817 3600352804 4094571909 275423344 " \
          "430227734 506948616 659060556 883997877 958139571 1322822218 1537002063 1747873779 " \
          "1955562222 2024104815 2227730452 2361852424 2428436474 2756734187 3204031479 3329325298", k, " ")
    for (i = 0; i < 64; i++) K[i] = k[i + 1] + 0
    cur = ""
}

FNR == 1 { done_file(); cur = FILENAME; seen[FILENAME] = 1; init_state() }
{ feed($0 RT) }
END {
    # exit in BEGIN still runs END: print nothing rather than a hash of an uninitialised state
    if (broken) exit 3
    done_file()
    # An empty file produces no record; report it so a caller never gets a silent gap.
    for (i = 1; i < ARGC; i++)
        if (ARGV[i] != "" && !(ARGV[i] in seen)) { cur = ARGV[i]; init_state(); done_file() }
}
