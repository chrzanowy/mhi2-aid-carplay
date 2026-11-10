/* HOST shim for QNX <devctl.h>: devctl() is implemented in host_mlb.c and
 * records every call (code, direction, value, status) in the MOST log. */
#ifndef HOST_DEVCTL_H
#define HOST_DEVCTL_H
#include <stddef.h>
int devctl(int fd, int dcmd, void *dev_data_ptr, size_t n_bytes, int *dev_info_ptr);
#endif
