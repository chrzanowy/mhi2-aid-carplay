# CarPlay settings page in the head unit menu (package `ui`, experimental)

This optional Java package adds an entry **CarPlay (pmcp)** to App-Connect > Settings on the head unit
(MU1161, the 1280x640 VW skin). The entry opens a page that uses the factory look, with native rows, drop-down lists,
touch input and a back button.

First version: one row.

| Row | Choices | What it changes |
|---|---|---|
| Speed limit | Off / Before street name / Street name (trial) | `/mnt/persist/pmcp/native-speedlimit-mode`, the same file and bytes as the GEM buttons (`pmcp.sh speedlimit-mode off\|turnto\|street`). Package `sl` reads it within about a second. |

The page applies the same rules as GEM. *Off* is always allowed. The other two need package `sl` in a confirmed Java
set that is running in this boot, and *Before street name* also needs `rg`. A choice that is not allowed shows the
reason under the row. While a GEM action holds the lock `/ramdisk/pmcp-speedlimit.lock`, the page writes nothing.

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
  from this package can reach the HMI, not even a missing class. The build compares every method with the factory
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
- Log: `/tmp/pmcp-ui.log` (RAM, up to 64 KB).
- Off switch for the current boot: create `/tmp/pmcp-ui-off`. A lifecycle error in the App-Connect view sets this
  switch automatically and puts the factory widget tree back at once. A factory lifecycle-order message counts as an
  error here; that is the safe side.
- The mode file is written as `.pmcp-new`, synced, renamed over the file and read back. Unlike `pmcp.sh`, there is no
  file-system `sync` after the rename, so a power cut right after a change can bring back the previous mode.
- If the HMI restarts while a save holds the lock (a very short window), the lock stays in `/ramdisk` until the next
  unit start. Until then, GEM speed-limit and package actions answer `SPEEDLIMIT_LOCK_BUSY`.
- **Before you go back to a card without `ui`** (any release card): press *Off ui* on the `ui` card first. A card
  that does not know `ui` sees the Java set as PARTIAL and changes nothing (fail-closed); only *Remove everything*
  would then help (installer test [26]).
- To remove the package for good, use GEM *Off ui*. All Java packages also have the usual safety net: the trial boot
  plus *4. Confirm*, and the rescue card.

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
