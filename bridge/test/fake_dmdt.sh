#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Fake /eso/bin/apps/dmdt for the host tests: logs its arguments, exits 0.
echo "$*" >> "$FAKE_DMDT_LOG"
exit 0
