/* HOST shim, force-included (-include host_shim.h) before the bridge source.
 * Redirects only the QNX/target-specific calls of altscreen_most_bridge.c:
 *   open64()  -> host_open64(): opens the simulated /dev/mlb/isoTX2 (a recording file)
 *   write()   -> host_write():  MOST back-pressure model + recording (other fds: real write)
 *   close()   -> host_close():  logs the close of the MOST fd (other fds: real close)
 *   ring / force-IDR / intro-once paths -> runtime paths from the environment
 * The real system headers are included first, so their prototypes keep the real names. */
#ifndef HOST_SHIM_H
#define HOST_SHIM_H

#include <errno.h>
#include <fcntl.h>
#include <stddef.h>
#include <stdio.h>
#include <sys/types.h>
#include <unistd.h>

const char *host_ring_path(void);
const char *host_idr_path(void);
const char *host_intro_once_path(void);
int host_open64(const char *path, int flags, ...);
ssize_t host_write(int fd, const void *data, size_t size);
int host_close(int fd);

#define open64 host_open64
#define write host_write
#define close host_close

#define ALT_FRAME_RING_PATH host_ring_path()
#define ALT_FRAME_FORCE_IDR_PATH host_idr_path()
#define INTRO_ONCE_PATH host_intro_once_path()
#define INTRO_POLICY_PATH "/nonexistent/intro-policy"

#endif
