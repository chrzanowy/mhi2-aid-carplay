# ---- fault injection (review harness) ----
if [ -n "${PMCP_KILL_AT:-}" ]; then
_fi_hit() {
    case "$*" in *"/mnt/"*) ;; *) return 0 ;; esac
    _fi_n=`cat "$PMCP_FI_CNT" 2>/dev/null`; _fi_n=$(( ${_fi_n:-0} + 1 )); echo $_fi_n > "$PMCP_FI_CNT"
    if [ "$_fi_n" -ge "$PMCP_KILL_AT" ]; then echo "FI_KILLED $_fi_n: $*" >> "$PMCP_FI_LOG"; echo "FI_KILLED"; kill -9 $$; exit 137; fi
    return 0
}
cp() { command cp "$@"; }
mv() { _fi_hit mv "$@"; command mv "$@"; }
rm() { _fi_hit rm "$@"; command rm "$@"; }
touch() { _fi_hit touch "$@"; command touch "$@"; }
mkdir() { command mkdir "$@"; }
chmod() { command chmod "$@"; }
fi
# ---- end fault injection ----
