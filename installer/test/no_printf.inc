# The GEM shell on MU1161 has no printf (v1.4.1 bug, PR #5: "printf: cannot execute"). Every test run of pmcp.sh gets
# this stand-in after its environment setup (`unset LD_PRELOAD`), so a printf call fails here the way it fails on the unit.
printf() { echo "printf: cannot execute - No such file or directory" >&2; return 1; }
