/* SPDX-License-Identifier: GPL-3.0-or-later
 * Host test shim, force-included (-include) before the bridge source in the
 * macOS build (ALTSCREEN_BRIDGE_FILE_OUTPUT: regular file instead of isoTX2,
 * no devctl). Only paths and the reclaim window are replaced; they come from
 * the environment so every test runs in its own temporary directory:
 *   HOST_RING_PATH, HOST_IDR_PATH, HOST_CACHE_LOCK, HOST_INTRO_ONCE_PATH,
 *   HOST_DMDT_PATH (a fake dmdt script),
 *   HOST_RECLAIM_WINDOW_US: reclaim window measured from process start
 *   (on the unit it is 180 s from boot; the Mac has been up much longer). */
#ifndef PMCP_HOST_SHIM_H
#define PMCP_HOST_SHIM_H
#include <stdint.h>

const char *pmcp_host_path(const char *env_name, const char *fallback);
uint64_t pmcp_host_reclaim_window_us(void);

#define ALT_FRAME_RING_PATH pmcp_host_path("HOST_RING_PATH", "/nonexistent/ring.bin")
#define ALT_FRAME_FORCE_IDR_PATH pmcp_host_path("HOST_IDR_PATH", "/nonexistent/force-idr.request")
#define CPMAP_CACHE_LOCK pmcp_host_path("HOST_CACHE_LOCK", "/nonexistent/cache.lock")
#define INTRO_ONCE_PATH pmcp_host_path("HOST_INTRO_ONCE_PATH", "/nonexistent/intro-played")
#define INTRO_POLICY_PATH "/nonexistent/intro-policy"
#define ALTSCREEN_BRIDGE_DMDT_PATH pmcp_host_path("HOST_DMDT_PATH", "/nonexistent/dmdt")
#define ALTSCREEN_BRIDGE_RECLAIM_WINDOW_US pmcp_host_reclaim_window_us()

#endif
