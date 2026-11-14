/* SPDX-License-Identifier: GPL-3.0-or-later
 * Host test shim, see host_shim.h. */
#include <stdint.h>
#include <stdlib.h>
#include <time.h>

const char *pmcp_host_path(const char *env_name, const char *fallback)
{
    const char *value = getenv(env_name);
    return value != NULL && value[0] != '\0' ? value : fallback;
}

static uint64_t g_start_us;

static uint64_t now_us(void)
{
    struct timespec value;
    if (clock_gettime(CLOCK_MONOTONIC, &value) != 0) return 0;
    return (uint64_t)value.tv_sec * 1000000ULL + (uint64_t)value.tv_nsec / 1000ULL;
}

__attribute__((constructor)) static void pmcp_host_start(void)
{
    g_start_us = now_us();
}

uint64_t pmcp_host_reclaim_window_us(void)
{
    const char *value = getenv("HOST_RECLAIM_WINDOW_US");
    uint64_t window = value != NULL ? strtoull(value, NULL, 10) : 180000000ULL;
    return g_start_us + window;
}
