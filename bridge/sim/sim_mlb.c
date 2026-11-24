/* SPDX-License-Identifier: GPL-3.0-or-later
 *
 * fake-car client: the simulated /dev/mlb/isoTX2 of docs/28 (symulator auta).
 * Drop-in for aa/most/test/host_mlb.c (same four functions, MOST_HOST_SIM seam of aa/most/most_writer.c), but the
 * channel lives in the fake-car process (bridge/sim/fakecar.py), shared by every writer of the simulated unit.
 *
 * Every open is one unix-socket connection to $FAKECAR_SOCK; the socket fd is the device fd the caller gets, so the
 * channel is released when the caller closes it or dies (as the driver does on process exit).
 * Request:  u8 op ('O' open, 'D' devctl, 'W' write), 3 x u8 0, i32 a, i32 b, u32 len, then len bytes.
 *   O: a = flags, b = pid, payload = "<tag>\0<path>" (tag = $FAKECAR_TAG, default "cp")
 *   D: a = dcmd, b = 0, payload = 4 bytes in (to/inout) or none
 *   W: payload = the bytes to write
 * Reply:    i32 ret, i32 err, u32 value.
 */
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <sys/un.h>
#include <unistd.h>

#define SIM_MAX_FDS 16

static pthread_mutex_t g_lock = PTHREAD_MUTEX_INITIALIZER;
static volatile int g_fds[SIM_MAX_FDS] = { -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1 };

static int is_sim_fd(int fd)
{
    int i;
    if (fd < 0) return 0;
    for (i = 0; i < SIM_MAX_FDS; ++i)
        if (g_fds[i] == fd) return 1;
    return 0;
}

static int send_all(int fd, const void *data, size_t size)
{
    const uint8_t *p = (const uint8_t *)data;
    while (size > 0) {
        ssize_t n = send(fd, p, size, 0);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return -1;
        p += n;
        size -= (size_t)n;
    }
    return 0;
}

static int recv_all(int fd, void *data, size_t size)
{
    uint8_t *p = (uint8_t *)data;
    while (size > 0) {
        ssize_t n = recv(fd, p, size, 0);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return -1;
        p += n;
        size -= (size_t)n;
    }
    return 0;
}

/* One request/reply. Returns ret; errno = err on ret < 0. The car closing the socket = EIO. */
static int call(int fd, char op, int32_t a, int32_t b, const void *payload, uint32_t len, uint32_t *value)
{
    uint8_t head[16];
    int32_t reply[3];
    memset(head, 0, sizeof(head));
    head[0] = (uint8_t)op;
    memcpy(head + 4, &a, 4);
    memcpy(head + 8, &b, 4);
    memcpy(head + 12, &len, 4);
    pthread_mutex_lock(&g_lock);
    if (send_all(fd, head, sizeof(head)) < 0 || (len && send_all(fd, payload, len) < 0) ||
        recv_all(fd, reply, sizeof(reply)) < 0) {
        pthread_mutex_unlock(&g_lock);
        errno = EIO;
        return -1;
    }
    pthread_mutex_unlock(&g_lock);
    if (value) memcpy(value, &reply[2], 4);
    if (reply[0] < 0) errno = reply[1];
    return reply[0];
}

int host_open64(const char *path, int flags, ...)
{
    struct sockaddr_un sa;
    char payload[600];
    const char *sock = getenv("FAKECAR_SOCK");
    const char *tag = getenv("FAKECAR_TAG");
    size_t tl, pl;
    int fd, i, r, saved;
    if (!sock || strlen(sock) >= sizeof(sa.sun_path)) { errno = ENOENT; return -1; }
    if (!tag || !*tag) tag = "cp";
    tl = strlen(tag);
    pl = strlen(path);
    if (tl + 1 + pl > sizeof(payload)) { errno = ENAMETOOLONG; return -1; }
    fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) return -1;
    memset(&sa, 0, sizeof(sa));
    sa.sun_family = AF_UNIX;
    memcpy(sa.sun_path, sock, strlen(sock));
    if (connect(fd, (struct sockaddr *)&sa, sizeof(sa)) < 0) {
        saved = errno;
        close(fd);
        errno = saved == ENOENT || saved == ECONNREFUSED ? ENOENT : saved;
        return -1;
    }
    (void)fcntl(fd, F_SETFD, FD_CLOEXEC);
    memcpy(payload, tag, tl + 1);
    memcpy(payload + tl + 1, path, pl);
    r = call(fd, 'O', flags, (int32_t)getpid(), payload, (uint32_t)(tl + 1 + pl), NULL);
    if (r < 0) {
        saved = errno;
        close(fd);
        errno = saved;
        return -1;
    }
    for (i = 0; i < SIM_MAX_FDS; ++i)
        if (g_fds[i] < 0) { g_fds[i] = fd; return fd; }
    close(fd);
    errno = EMFILE;
    return -1;
}

int devctl(int fd, int dcmd, void *data, size_t n_bytes, int *info)
{
    uint32_t code = (uint32_t)dcmd;
    uint32_t value = 0;
    int r;
    (void)info;
    if (!is_sim_fd(fd)) return EBADF;
    if ((code & 0x80000000U) && data && n_bytes >= 4)
        r = call(fd, 'D', (int32_t)code, 0, data, 4, &value);
    else
        r = call(fd, 'D', (int32_t)code, 0, NULL, 0, &value);
    if (r < 0) return errno;
    if ((code & 0x40000000U) && data && n_bytes >= 4) memcpy(data, &value, 4);
    return r; /* devctl returns the status (0 = EOK), not -1/errno */
}

ssize_t host_write(int fd, const void *data, size_t size)
{
    if (!is_sim_fd(fd)) return write(fd, data, size);
    if (size > 0x7fffffffU) { errno = EINVAL; return -1; }
    return (ssize_t)call(fd, 'W', 0, 0, data, (uint32_t)size, NULL);
}

int host_close(int fd)
{
    int i;
    /* May run in the bridge's signal handler: no locks, no messages; the car sees the socket close. */
    for (i = 0; i < SIM_MAX_FDS; ++i)
        if (g_fds[i] == fd) g_fds[i] = -1;
    return close(fd);
}
