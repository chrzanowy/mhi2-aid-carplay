/* HOST shim for omonob's cpmap_intro_policy.h (v2-only).
 * v1.x has no intro policy: the intro plays whenever CARPLAY_CLUSTER_INTRO
 * is set. EVERY_CONNECT reproduces that (no boot marker, no settings file). */
#ifndef CPMAP_INTRO_POLICY_H
#define CPMAP_INTRO_POLICY_H

typedef enum CpmapIntroPolicy {
    CPMAP_INTRO_OFF = 0,
    CPMAP_INTRO_ONCE_PER_BOOT = 2,
    CPMAP_INTRO_EVERY_CONNECT = 1
} CpmapIntroPolicy;

static inline CpmapIntroPolicy cpmap_intro_read_policy(const char *path)
{
    (void)path;
    return CPMAP_INTRO_EVERY_CONNECT;
}

static inline int cpmap_intro_should_play(CpmapIntroPolicy policy,
                                          const char *boot_marker)
{
    (void)boot_marker;
    return policy != CPMAP_INTRO_OFF;
}

#endif
