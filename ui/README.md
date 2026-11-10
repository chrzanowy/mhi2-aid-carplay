# CarPlay settings page in the head unit menu (package `ui`)

This Java package adds an entry **AID navigation configuration** to App-Connect > Settings on the head unit
(MU1161, the 1280x640 VW skin). The entry opens a page that uses the factory look, with native rows, drop-down lists,
touch input and a back button. Main menu *4. Install additional features* installs it.

| Row | Choices | What it changes |
|---|---|---|
| Changes | Save: everything works | During a trial start (the first start after a change from the card), the same as GEM *5. Confirm*: the Java set (`ok.SET`) and/or the Android Auto set (`aa-ok.SET`) now load on every start. Without it, the next restart loads none of our JARs (lsd.sh; not the previously saved set). No SD card needed. |
| Speed limit | Off / Before street name / Street name (trial) | `/mnt/persist/pmcp/native-speedlimit-mode`, the same file and bytes as the GEM buttons (`pmcp.sh speedlimit-mode off\|turnto\|street`). Package `sl` reads it within about a second. |

The page applies the same rules as GEM. *Off* is always allowed. The other two need package `sl` in a confirmed Java
set that is running in this boot, and *Before street name* also needs `rg`. A choice that is not allowed shows the
reason under the row. While a GEM action holds the lock `/ramdisk/pmcp-speedlimit.lock`, the page writes nothing.

*Save* follows `pmcp.sh` (`java_confirm_try`, `aa_confirm_try`): only in the start that is the trial (lsd.sh wrote
`last-boot` "set=SET use=trial" in this start; for Android Auto the RAM marker of this start), never after the rescue
card. Unlike GEM it cannot check the card, the firmware or the installed files; it relies on the trial that is running.

Planned rows (later, they need changes in `core.so`): map layout, fps, IDR.

## How it works

- A copy of the factory class `de.vw.mib.view.internal.AbstractViewHandler` (MU1161, sha256 `7afadc2e…`, the same file
  as in MU1367) has five extra calls into `com.pmcp.ui.MenuHook`:

  | Method | Point | Call |
  |---|---|---|
  | `init(boolean)` | start, before the factory `View.init` | `attach` |
  | `activate()` | end | `refresh` |
  | `deinit()` | end | `detach` |
  | `destroy()` | end | `detach` |
  | `fatalError()` | start | `failure` |

  Each call is wrapped in `catch (Throwable)` ([`buildtools/Guard.java`](../buildtools/Guard.java)), so nothing
  from these hooks can reach the HMI, not even a missing class. The other way in is the factory calling our code:
  the button listeners and the list's clone factory. Each of them catches every `Throwable` as well; when our entry
  clone fails, the list gets a factory clone of the factory entry instead and the page is off from the next start. The build compares every method with the factory
  one ([`patcher/TestMenuHookPatch.java`](patcher/TestMenuHookPatch.java)).
- `attach` runs at the start of `init` rather than at the end of `setup`. The factory can run `deinit` and then `init`
  again without a new `setup`, and the entry must come back in that case too.
- `attach` acts only on the view `SMI_SETUP_MAIN` on a 1280x640 canvas. It finds every factory widget it needs by
  targetId before it changes anything. If any of them is missing, or the canvas is a different size, the view stays
  factory and the reason is written to the log.
- The page is made of clones of factory widgets from the same view, with their own controllers. The factory widgets
  are not changed. Only three things change: the setup list gets one more entry, the view gets the page and the popup,
  and the list gets a clone factory that also knows our entry. `detach` puts back the original arrays and factory, one
  step at a time.
- Log: `/ramdisk/pmcp-ui.log` (RAM, up to 64 KB). It also records how long `attach` took (`ATTACH_MS`).
- Off switch for the current boot: create `/ramdisk/pmcp-ui-off` (RAM, gone at the next unit start). A lifecycle
  error reported for the App-Connect view (factory `fatalError`, which only logs and goes on) sets this switch. The
  page stays in the tree until that view's next `deinit` or `destroy`, whose end hook detaches it as usual, so the
  factory teardown still finds our clone factory and widgets. From then on the view is factory until the next start.
- The mode file is written as `.pmcp-new`, synced, renamed over the file and read back. Unlike `pmcp.sh`, there is no
  file-system `sync` after the rename, so a power cut right after a change can bring back the previous mode.
- A save holds the lock `/ramdisk/pmcp-speedlimit.lock` across the `fsync`, on the HMI thread (milliseconds). If the
  HMI dies inside that window, the lock stays until the next unit start, and until then GEM speed-limit and package
  actions, also main 4 (features-reset takes the same lock), answer `SPEEDLIMIT_LOCK_BUSY`. A unit restart clears it.
- The page checks fewer things than `pmcp.sh`: it cannot see the card or the firmware and does not compute the unit
  state; it relies on the Java set that is confirmed and running in this boot.
- **Going back to a card without `ui`:** a card with the new GEM menu (main screen `pmcp_stream_map_aid`) replaces a
  Java set it does not know with *4. Install additional features*, so nothing is needed first. Older cards (v1.5.0
  and earlier) see such a set as PARTIAL and change nothing (fail-closed): press *Off ui* on the `ui` card first, or
  only *Remove everything* helps there (installer test [40]).
- To remove the package for good, use *Off ui* in GEM `features_advanced`. All Java packages also have the usual
  safety net: the trial boot plus *5. Confirm*, and the rescue card.

## Build

```sh
ASM_DIR=/path/to/asm-9.7 ui/build.sh <converted MU1161 lsd.jar> <fresh dir>
```

The build checks the hash of every input. It then runs these steps:

1. patches and diff-tests the hook class;
2. writes `pmcp-ui.jar` with fixed timestamps, so the bytes are the same every time;
3. checks every reference against the unit's own class library (RefCheck) and verifies the bytecode;
4. runs the host tests, which use real factory widget classes (services are stubbed);
5. runs the hook class without the helper classes and checks that every lifecycle method still finishes.

## Credits

The page technique is from omonob's
[MHI2-Carplay-Maps](https://github.com/omonob/MHI2-Carplay-Maps) `src/vc-menu`: `IndependentMenuViewBridge` and
`BuildNativeHook` (GPL-3.0). `SettingsPage.java` is a reduced port of that bridge. Tomasz Twardzicki's MU1367
`settings-v2` showed that the hook on `AbstractViewHandler` alone is enough.
