/* HOST shim for omonob's cpmap_resources.h (v2-only helpers).
 * v1.x (fed7dce4) logs with plain fprintf(stderr, ...) and has no log size
 * limit and no video-cache lease, so both are reduced to that here. */
#ifndef CPMAP_RESOURCES_H
#define CPMAP_RESOURCES_H

#include <errno.h>
#include <stdarg.h>
#include <stdio.h>

#define CPMAP_VIDEO_LOG_LIMIT (256U * 1024U)
#define CPMAP_BRIDGE_LOG_LIMIT (128U * 1024U)
#define CPMAP_SMALL_LOG_LIMIT (64U * 1024U)

static inline int cpmap_log_fprintf(FILE *file, size_t limit,
                                    const char *format, ...)
{
    int rc;
    int saved = errno;
    va_list ap;
    (void)limit;
    va_start(ap, format);
    rc = vfprintf(file, format, ap);
    va_end(ap);
    fflush(file);
    errno = saved;
    return rc;
}

static inline int cpmap_cache_acquire(void) { return 0; }
static inline void cpmap_cache_release(void) { }

#endif
