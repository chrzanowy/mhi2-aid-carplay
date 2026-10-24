# lsd.jxe K4525 (MU1367): conversion to JAR, decompilation, analysis of the AID map

The analysis was done on the HMI image from K4525 (MU1367). The classes, attribute IDs and hook points described below
were later confirmed on MU1161.

Input: `archives/x-k4525/stage2/ifs/lsd.jxe` (55,840,541 B, SHA-256 `09167f1d0ae5…a07507a`, read-only).
Output: `archives/x-k4525/jar/lsd-k4525.jar` and `archives/x-k4525/src/` (the whole image after Vineflower).
The `archives/…` and `upstream/…` paths are a local working directory layout (not part of this repository). All source
paths below are relative to `archives/x-k4525/src/`. Line numbers refer to the Vineflower output.

## 1. Toolchain

| Step | Tool | Version / source | SHA-256 |
|---|---|---|---|
| JXE → JAR | `luka-dev/jxe2jar` (`src/*.py`, successor of `moradek/jxe2jar`) | git `9eeb45bbf14bf8afe3452c7be96a4d1f0206a286` (2026-09-30), `upstream/tools/jxe2jar/repo` | `jxe2jar.py` `9f56143a…5b7c9`, `jxe.py` `82dd48ee…89039`, `bytecode.py` `ed6587a6…bb4`, `constpool.py` `66da7ba7…34a4`, `common.py` `be0371b8…c6db`, `bitstring.py` `04daec6b…cee0` |
| Wrapper | [`scripts/jxe2jar_run.py`](../../scripts/jxe2jar_run.py) (ours) | runs the converter under `python3 -I`, `--check` counts classes | `a375a37e…450a` |
| Decompiler | Vineflower 1.12.0, Maven Central `https://repo1.maven.org/maven2/org/vineflower/vineflower/1.12.0/vineflower-1.12.0.jar` (SHA-1 matches `.sha1`) | `upstream/tools/vineflower/` | `1dfcfe974395734fa467ce620661c7623d05ba83670de0529b1fbd63ff548b9d` |
| Fallback decompiler | CFR 0.152, `https://repo1.maven.org/maven2/org/benf/cfr/0.152/cfr-0.152.jar` | `upstream/tools/cfr/` | `f686e8f3ded377d7bc87d216a90e9e9512df4156e75b06c655a16648ae8765b2` |
| JVM | OpenJDK 25.0.2 (sdkman) | | |

Safety: the converter code was reviewed before running it. It uses only the stdlib (`struct`, `io`, `zipfile`,
`argparse`, `os.makedirs`), no network and no `subprocess`.
It was run under `python3 -I` with cwd `/tmp`, and the `src` directory was added to `sys.path` explicitly, because `-I`
does not add it.
The `.jar` files shipped in the jxe2jar repo (vineflower, cfr, jd-cli) were **not** run. The separately downloaded
Vineflower has the same hash as the copy in that repo.

Commands:

```sh
python3 -I scripts/jxe2jar_run.py upstream/tools/jxe2jar/repo/src archives/x-k4525/stage2/ifs/lsd.jxe archives/x-k4525/jar/lsd-k4525.jar
java -Xmx14g -jar upstream/tools/vineflower/vineflower-1.12.0.jar --decompile-java4=true --remove-synthetic=true \
     --variable-renaming=jad --ignore-invalid-bytecode=true … archives/x-k4525/jar/lsd-k4525.jar archives/x-k4525/src
```

The Vineflower options match `tools/vineflower.sh` from the jxe2jar repo, without `--include-runtime`, because the JAR
contains its own `java.*`.

### Validation

| Criterion | Result |
|---|---|
| Classes in ROM (`class_count` in the header) | 26,291 |
| Classes written to the JAR | **26,291**, 0 "bad class", 0 bad magic. Class versions: 46 (21,646) and 49 (4,645) |
| Comparison with maxim's | MU1439: 28,528 classes. K4525 is older and smaller, so the order of magnitude fits |
| `lsd-k4525.jar` | 125,024,329 B, SHA-256 `f996e81650e9d748a4d6d3d072f1739bbd718d7b55a27dc9acb80b21b5ec1a2b`, 26,404 entries (classes + resources from the JXE) |
| `javap -p -c` | OK on `GfxStreamSinkController`, `NavigationHandler`, `ChangeDataRate`, `java.lang.String` (valid bytecode, constants, calls) |
| Vineflower | 22,377 `.java` files (inner classes were inlined), 162 MB. **1** method failed to decompile: `com/ibm/oti/util/DefaultPolicy#loadKeystore` (irrelevant) |
| Quality | readable code. `static final` constants are inlined as literals (e.g. `2110010`), and local variable names are `i, j, flag` (stripped by the romizer) |

Practical note: some `grep` wrappers skip binary files. For `.class` files use `/usr/bin/grep -a`.

## 2. Map stream to the AID over MOST (`de/vw/mib/asl/internal/mostkombi/streamsink/**`)

### Architecture

- `GfxStreamSinkController` (target `1490002`, `controller/GfxStreamSinkController.java:50`) is an HSM. It registers
  service `5000001` (`:93`).
- `StreamSinkCategoryManager#createCategories` (`controller/StreamSinkCategoryManager.java:47`) creates 5 use cases. It
  also provides the adapters `DisplayManagementAdapter`, `NavigationMapAdapter`, `NavInfoAdapter`, `AdaptationAdapter`.
- States: `InitializeState` → `WaitForServices` → `RunningState` (`states/StreamSinkHsmContext.java`).
- Sequences (`StreamSinkSequence`) run step by step. Each step has a 15 s timeout (`TIMER_WAIT_FOR_STEP_TO_EXECUTE`).
  On timeout `sequenceStepFailed` is called and the sequence moves on.

Use case IDs (`common/api/MostKombiIdentifier.java`):

| ID | Class | Role |
|---|---|---|
| 1490004 / 05 | `ChangeDataRate` / `ChangeDataRateSequence` | passes the data rate requested by the cluster on to the DisplayManager |
| 1490006 / 07 | `SwitchToPermanentMap` / `…Sequence` | cluster without map switching (map permanently on the AID) |
| 1490009 | `MostUnlockUseCase` | sink gone: map invisible, rate 0 |
| 1490010 / 11 | `SwitchMapFromABTToKombi` / `…Sequence` | moves the map from the central screen (ABT) to the AID |
| 1490012 / 13 | `SwitchMapFromKombiToABT` / `…Sequence` | moves it back |
| 1490031 | `mostkombi/navinfo/functions/RouteGuidanceMode` | `DSIKOMONavInfo.setRgSelect(mode)` |

### DSI and constants

`org.dsi.ifc.komogfxstreamsink.DSIKOMOGfxStreamSink` (v2.11.2):

| Element | Values |
|---|---|
| Methods | `setFGLayer(int)`, `fadeIn(int,int,int)`, `fadeOut(int)` |
| Attributes | `ATTR_GFXSTATE=1` (0 = unavailable, 1 = available), `ATTR_REQUESTSYNC=2`, **`ATTR_DATARATE=3`** (`OFF=0`, `REDUCEDBANDWIDTH=1`, `FULL=2`) |
| Layer `FGREFPIC` | `EMPTY=0`, `KDK=1`, `EV=2`, `MAP=3` |
| `FADESPEED` | `BLIT=0`, `FADE=1` |
| Listener | `updateGfxState`, `updateDataRate(rate, validity)`, `setFGLayerResult`, `fadeInResult`, `fadeOutResult` |

`DSIDisplayManagement` (handled by
`de/vw/mib/asl/framework/internal/displaymanagement/ASLDisplayManagementKomonavTarget.java`, target 1120002):

| Event / callback | Action |
|---|---|
| Event `1075841828` `SWITCH_TO_KOMBI_DISPLAY_CONTEXT` | the first time `setDisplayType(4 = DISPLAYID_CLUSTER, 2 = DISPLAYTYPE_H264_MOST)`, then `switchContext(ctx, 4, 0)`. Map context = **70** |
| Event `1075841829` `SET_DATA_FRAME_RATE` | `setUpdateRate(4, rate)`. Rate in ASL: `OFF=0`, `REDUCED=1`, `FULL=10` (`DisplayManagement.java`) |
| `dsiDisplayManagementActiveContext` (`:22`) | datapool `2110010` `KOMBI_DISPLAY` (−2 not started, −1 no context, 70 map) |
| `dsiDisplayManagementSetUpdateRateResult` (`:36`) | datapool `2110011` `DATA_FRAME_RATE` |
| Event `4300080` | datapool `2110014` `MOST_CAPABILITY_FOR_MAP` and `2110015` `…_FOR_KDK` |
| Event `4300081` | datapool `2110016..18` (images: cover, call, station) |

### Logic

- `WaitForServices#_checkServiceStates` (`states/WaitForServices.java:99`) moves to `Running` when **all** conditions
  hold:
  - `gfxState==1`;
  - `KombiDisplay != −2`;
  - `MostCapabilityForMap == 2` (MOST streaming);
  - `KombiMapStatus == 2` (READY) **or** (map switch supported and navigation fully running and
    `ICMapServiceState == 10`).
- `RunningState#stateStart` (`states/RunningState.java:89`):
  - no map switch: `SwitchToPermanentMap`;
  - map switch present, and the map is being moved to the cluster or `RouteGuidanceMode == 3` (MAP): `ABT→Kombi`;
  - otherwise: `ChangeDataRate`.
- `RunningState#updateNavInfo`:
  - BAP NavSD `ActiveRgType` (fct 39) == 3 (MAP) while the map is in the ABT: `ABT→Kombi`;
  - `!= 3` while the map is in the cluster: `Kombi→ABT`.
- `ChangeDataRate#dsiKOMOGfxStreamSinkUpdateDataRate` (`usecases/ChangeDataRate.java:207`): **the cluster (sink)
  decides the data rate**. The HMI then runs `ChangeDataRateSequence`:
  1. `_stepVisibleChange` (`:182`): rate 0 or 1 → `setMapInvisible()` (event `1074841846`); rate 2 → `setMapVisible()`
     (event `1074841845`);
  2. `_stepChangeDataRate` (`:201`): 0 → 0, 1 → 1, 2 → **10** (`setDataFrameRate`).
- `SwitchToPermanentMapSequence#executeNextStep` (`:149`), steps:
  1. `fadeOut(1)`;
  2. `switchToKombiDisplayContext(70)`, if `KombiDisplay == −1`;
  3. `RouteGuidanceMode` (`setRgSelect`);
  4. `ChangeDataRate`;
  5. `setFGLayer(3 = MAP)`;
  6. `fadeIn(1,0,0)`.
- `SwitchMapFromABTToKombiSequence#executeNextStep` (`:221`), steps:
  1. `setMapSwitchState(5)` (`:234`), then wait for 5;
  2. `fadeOut(1)`;
  3. `setRgSelect`;
  4. wait until the map in the ABT is invisible;
  5. wait for `DATARATE ∈ {1,2}`;
  6. `ChangeDataRate`;
  7. `fadeIn`;
  8. `setMapSwitchState(2)`.
- `SwitchMapFromKombiToABTSequence#executeNextStep` (`:278`), steps:
  1. state 3;
  2. `fadeOut`;
  3. wait for `DATARATE == 0`;
  4. `setDataFrameRate(0)`;
  5. state 4;
  6. wait until the map in the ABT is visible;
  7. state 1;
  8. `fadeIn`.
- Map switch states (`api/navimap/asl/NavigationMap.java`): `0` unavailable, `1` visible in ABT, `2` visible in cluster,
  `3` request to move to ABT, `4` ABT shows the map, `5` switching to cluster.
- `MostUnlockUseCase#executeSequence` (`:59`): `setMapInvisible()` and `setDataFrameRate(0)`. Called when `GfxState`
  drops to 0.

### Resolution, viewport, coding (outside the streamsink package)

| Source | Value |
|---|---|
| "Dashboard display config" coding (`DashboardDisplayConfigSetter`) | **1172**: map transmission (`0` off, `1` MOST high, **`2` MOST streaming**, `3` LVDS FPK; `isFpkOverLVDS = (1172 == 3)`) |
| | **171**: compression (`1` H.264). `isFPKMapAvailable = (1172 == 2 && 171 == 1)` |
| | **1173**: KDK |
| | **1176**: `isNavMapSwitch` (datapool `1610050`, flag `ASL.Configuration.isNavMapSwitch`) |
| | **172**: resolution class of MapViewer 3 (cluster) |
| `AdaptationAdapter#isNavigationMapSwitchSupported` (`common/api/adaption/AdaptationAdapter.java:49`) | datapool `1110170` **or** feature flag `140` |
| Viewport of MapViewer instance 3 (cluster) | `DSIMapViewerStatusTarget#mapViewerReady3Configure` (`navigation/map/dsi/factories/impl/mapviewer/status/DSIMapViewerStatusTarget.java:415`), by coding 172: |
| | `0` → `800×480` (`SCREEN_VIEW_PORT_MAP_KOMBI`) |
| | `1` → `800×298` (`…_KOMBI_CHN`) |
| | **`2` → `1010×376`** (`…_KOMBI_FPK_ENTRY_HIGH`, `:32`) |
| | then `setFrameRateMode(5 = LIMITED_CLUSTER_INSTRUMENT)` |
| Main map while the map is in the cluster (`mapViewerReady0`, `:339`) | max `1010×480` (`FPK_ENTRY_STD`), viewport `1010×376` |
| Car position / hotpoint on the AID (`MapViewerKombiTargetHSM#getCarPosition`, `:197`) | class 2: `(505,188)` north-up, `(505,249)` heading-up. Class 0: `(400,248/353)`. Class 1: `(400,154/250)` |
| Zoom area on the AID (`ASLNavigationMapConfiguration`, `:46-62`) | `ZOOM_AREA_DEFAULT_FPK_ENTRY 1010×376` |
| | `2D3D (368,111,274,194)` |
| | `OVERVIEW (354,105,302,244)` |
| | `FPK_ENTRY_RESOLUTION_CLASS = 2` |

**Conclusion:** the HMI renders the AID map as a separate MapViewer instance no. 3
(`DSIMapViewerManager#createMapViewerKombi`, `:183`, `createMapViewer(…, 3)`). For the "FPK entry high" AID this is
**1010×376 px**. The coding sends it as H.264 over MOST (`DISPLAYTYPE_H264_MOST`), in DisplayManager context 70.
There is no encoder and no bitrate parameter in Java. The only thing there is the "update rate" level 0/1/10
(OFF/REDUCED/FULL).

## 3. AID size (small/large) and layout detection

- `ConfigurationManager.INSTRUMENTCLUSTER_SIZE_SMALL=0`, `_LARGE=1` (`de/vw/mib/configuration/ConfigurationManager.java:37`).
  The representations are `"IC_Size_Small"`, `"IC_Size_Large"` (`ConfigurationManagerImpl.java:136`).
- `ConfigurationManagerImpl#setInstrumentClusterSize` (`:1066`) accepts only 0 or 1. On change it calls
  `notifyNvListener(4 = NV_INSTRUMENTCLUSTERSIZE)`.
- **Source of the value:** BAP LSG **SDS_SD**, function **16 `ASG_Capabilities`**, field `displaySizeClass`: `0` SMALL,
  `1` MEDIUM, `2` LARGE (`bap/mqbab2/generated/sdssd/serializer/ASG_Capabilities_SetGet.java`).
  - `sdssd/functions/ASGCapabilities#setGetProperty` (`:60`): the cluster sends SetGet, and `displaySizeChanged`
    (`:109`) stores the value in the `SDSSD_ASGCapabilities` persistence (`instrumentcluster/persistence`, default 1)
    and calls `ConfigurationAdapter#setInstrumentClusterDisplaySize`.
  - BAP→system mapping (`ConfigurationAdapter.java:177`): 0 → 0, and 1 and 2 → 1.
- **The only consumer** of `NV_INSTRUMENTCLUSTERSIZE` is `ScaledI18nDatapoolUpdater`
  (`de/vw/mib/datapool/internal/ScaledI18nDatapoolUpdater.java:49-66`). It loads size-dependent texts
  (`<lang>-<size>.res`, tag `"de_DE-1"`). `ConfigurationAdapter#notifyNvListener` only calls `languageChanged()`.
  - **The size does not affect the map or the stream.** It is the size class of the cluster display (short or long
    texts), not a dial layout switch.
- **The event "driver changes the AID view"** has no dedicated "small/large dials" event. There are two signals:
  1. MOST `DSIKOMOGfxStreamSinkListener.updateDataRate` (`ATTR_DATARATE`). The AID requests `FULL` when the map is
     visible in the selected layout, and `OFF` or `REDUCED` when it is not. Handled in
     `ChangeDataRate#dsiKOMOGfxStreamSinkUpdateDataRate`.
  2. BAP NavSD **fct 39 `ActiveRgType`** SetGet from the cluster (`bap/mqbab2/navsd/functions/ActiveRgType.java:97`).
     `rgtype`: `0` RGI (arrows from ManeuverDescriptor), `1` MOST KDK, `2` compass, `3` MOST MAP, `4/5` LVDS map/KDK,
     `255` default.
     - With map switch it is accepted only in states 0, 1 and 2.
     - `mostkombi/navinfo/api/navi/NavInfoAdapter#_storeBapInfoData` (`:323`, `case 39` `:369`) observes BAP LCU 50
       and maps the value to `RouteGuidanceMode` (`RGMODE_RGI=0`, `KDK=1`, `COMPASS=2`, `MAP=3`). This value drives
       the ABT/Kombi switching in `RunningState#updateNavInfo` and is sent back via `DSIKOMONavInfo.setRgSelect`.
- `ActiveRgType#setCurrentRGType` (`:150`): without the map switch function it returns `rgtype = 3` when
  `KombiMapStatus != 0`, otherwise the last value.

## 4. CarPlay (`de/vw/mib/asl/internal/carplay/**`)

- `generated/de/vw/mib/asl/internal/carplay/ic/ASLCarPlayICDeviceImpl` (`"CarPlay.IC"`, target **13904**) is only a
  model device (data for the HMI cluster view), with no logic.
  - Properties: `ROUTE_GUIDANCE_ACTIVE = 2910009`, `PHONE_CALL_PRESENT = 2910010`.
  - List `2910011` `DeviceState`: signal strength 0..5, operator, `valid`.
  - **No video stream and no manoeuvre data here.**
- `common/NavigationHandler#updateGuidanceActive` (`:17`), the HMI navigation listener:
  - native guidance starts while CarPlay is connected: `DSICarPlay.requestModeChange(resource 0, appState 2)`, i.e. the
    HMI takes over navigation;
  - native guidance ends and `activeNavigation == 3`: appState 6;
  - at the end always `CarPlayGlobalProperies#setHmiRouteGuidanceActive(flag)` (`:374`).
- `CarPlayModeHandling` (`:192` onwards), based on `updateMode` from the iPhone (`getNavigationType`):
  - `2` (iPhone): `2910009 := true`, `activeNavigation = 2`, native guidance stopped via `navServices.stopGuidance(6)`,
    then `ExboxGuidanceListenerImpl#setSmartphoneGuidanceActive`;
  - `3` (HMI): `2910009 := false`;
  - `1` (none): `2910009 := false`.
- `api/impl/ASLCarplayServicesImpl#isCarPlayRouteGuidanceActive` (`:82`) returns `activeNavigation == 2`.
  - Consumed by BAP: `bap/mqbab2/navsd/functions/InfoStates#getCurrentBAPInfoState` (`:70`). When CarPlay, AA or
    CarLife is guiding, NavSD **fct 38 `InfoStates` = 6 `NAVIGATION_IN_MOBILE_DEVICE_ACTIVE`**.
  - `NavigationASLDataAdapter#isGALRouteGuidanceActive` (`:223`) reads `2910009`.
- `common/ExboxGuidanceListenerImpl` is the bridge to exboxm (§5). When the exbox reports ACTIVE:
  `updateGuidanceActive(true)` and the reply "smartphone INACTIVE".
- `DSICarPlay` / `DSICarPlayListener` (`org/dsi/ifc/carplay`) **have no route guidance callbacks at all** (only mode,
  call, now playing, cover art).
  - `ServiceConfiguration` has one screen (`xResolution`, `yResolution`, offset, `physicalDisplay*`), no alt screen for
    the cluster.
  - CarPlay canvas: `ASLHandler` (`:443`), from the coding `getLayoutCarplayCanvasDimensionWidth/Height`.

## 5. exboxm guidance (`de/vw/mib/asl/api/exboxm/guidance/**`)

- API: `ExboxGuidanceManager { addListener, removeListener, getGuidanceState, changeSmartphoneGuidanceStateTo(GuidanceState) }`,
  `GuidanceState { INACTIVE=0, ACTIVE=1 }`, `ExboxGuidanceListener#onExboxGuidanceStateChanged`.
- Implementation: `internal/exboxm/api/impl/guidance/ExboxGuidanceManagerImpl` and
  `internal/exboxm/state/ExboxStateServiceImpl`.
  - The exbox state comes from
    `DSIExBoxMListener.updateMobileDeviceLinkStatus(…, ExBoxState.isExBoxNavigationActive())` (`:221`).
  - The smartphone state goes to `DSIExBoxM.setMobileDeviceLink(MobileDeviceLinkStatus)` (`:245-258`).
- **This is only arbitration of "who is guiding" (exbox = external navigation module, e.g. KOR/CHN, or the
  smartphone).** The API carries no manoeuvres, distance, streets, lanes or ETA. It is no use for TBT injection.

### The real TBT path to the cluster: BAP NavSD fed from ASL lists

The BAP NavSD functions (`bap/mqbab2/navsd/functions/*`) read `NavigationService`
(`common/api/navigation/NavigationASLDataAdapter`). That in turn reads ASL properties and lists:

| BAP NavSD fct | Class | ASL source | Who writes it (natively) |
|---|---|---|---|
| 17 `RG_Status` | `RGStatus#setRouteGuidanceStatus` (`:49`) | prop `733` (navigation status, must be 0), prop **`732`** (0 none, 1 active, 2 calculating) | `navigation/bap/HsmTargetBap` (`:190-215`, event `3497006`) |
| 18 `DistanceToNextManeuver` | `DistanceToNextManeuver` | list **741** (distance, unit, bar graph on/off, bar graph %) and 751; requires `732 == 1` | `ASLNavBAPAPI#updateBapDistanceToNextManeuver` |
| 20 `TurnToInfo` | `TurnToInfo#setTurnToInfoStatusData` | list **744** (street, signpost) | `ASLNavBAPAPI#updateBapTurnToInfo` |
| 21 `DistanceToDestination` | | list **749** | `ASLNavBAPAPI#updateBapDistanceToDestination` |
| 22 TimeToDestination / RTT | | lists **750**, **1110060** | `ASLNavBAPAPI#updateBapTimeToDestination2`, `…RTTandETA` |
| 23 `ManeuverDescriptor` | `ManeuverDescriptor#computeManeuverDescriptorStatus` (`:217`, only when `732 != 0`) | list **751** (`mainElement`, `direction`, `zLevel`, `sideStreets`) | **private** `HsmTargetBap#updateManeuverDescriptor` (`:342`), also to list 838 |
| 24 `LaneGuidance` | `LaneGuidance` | list **742** (`direction`, `sideStreets`, `laneType`, `markingL/R`, `description`, `guidanceInfo`), prop 731 | `ASLNavBAPAPI#updateBapLaneGuidance` |
| 38 `InfoStates` | `InfoStates` | 733, 734, `isCarPlayRouteGuidanceActive` | → 6 with CarPlay |

- Entry point: `de.vw.mib.asl.api.navbap.ASLNavBAPFactory.getNavBAPApi()` (singleton `ASLNavBAPAPIImpl`). Public
  methods:
  - `updateBapDistanceToNextManeuver(int dist, int unit, boolean bargraphOn, int bargraph%)`;
  - `updateBapTurnToInfo(String street, String signPost)`;
  - `updateBapLaneGuidance(INavLaneGuidanceDataNavBap[], boolean)`;
  - `updateBapDistanceToDestination(int, int, boolean)`;
  - `updateBapTimeToDestination2(h, m, k)`;
  - `updateBapTimeToDestinationRTTandETA(long, long)`;
  - `updateBapCompassInfo`.
- There is no public method for ManeuverDescriptor and `732`. You have to call
  `generated.de.vw.mib.asl.internal.ListManager.getGenericASLList(751).updateList(GenericCollector[])` directly
  (columns 0..3 as in `HsmTargetBap:342-380`) and `ServiceManager.aslPropertyManager.valueChangedInteger(732, 1)`.
- Precedent for a synthetic manoeuvre: `HsmTargetBap` `case 100100` (`:143`, WPM/offroad mode) builds
  `new BapManeuverDescriptor(6, direction, 0, null)`.
- `mainElement` (`ManeuverDescriptor_Status.MAIN_ELEMENT_*`), among others: `11` follow street, `13` turn, `15/16` exit
  R/L, `19/20` fork, `21..27` roundabout, `25` U-turn, `3` arrived. Mapping `32→15` and `33→16`
  (`ManeuverDescriptor#mapToBAPMainElement`).
- The same BAP stream (LCU 50: fct 18, 19, 20, 21, 39) is copied in parallel to MOST `DSIKOMONavInfo` by
  `NavInfoAdapter`. Injecting into the ASL lists therefore also feeds MOST NavInfo.
- Android Auto and CarLife have next-turn callbacks: `AndroidAutoTarget#dsiAndroidAuto2UpdateNavigationNextTurnEvent`
  (`:479`), `carlife/DSIHandler#handleDsiCarlifeUpdateNavigationNextTurnInfo` (`:95`). They are empty stubs (trace
  only), i.e. ready places to hook into. **CarPlay has no such callback in DSI.**

## 6. Hook points

### (a) Switching the AID layout and the map

| Hook | What it gives |
|---|---|
| `streamsink/usecases/ChangeDataRate#dsiKOMOGfxStreamSinkUpdateDataRate(int rate, int valid)` | the only live "AID wants / does not want the map" event (FULL / REDUCED / OFF). A good trigger to start/stop our stream |
| `ChangeDataRateSequence#_stepChangeDataRate` / `DisplayManagementAdapter#setDataFrameRate` (event `1075841829`) | where the HMI switches the DisplayManager (`setUpdateRate(4, 0/1/10)`) |
| `ASLDisplayManagementKomonavTarget#gotEvent` `case 1075841828` | `setDisplayType(4, H264_MOST)` + `switchContext(70, 4, 0)`: chooses what goes to the cluster. The source could be swapped here (e.g. a context with CarPlay video instead of MapViewer 3) |
| `SwitchToPermanentMapSequence` step `setFGLayer(3)` / `fadeIn` | layer and transitions on the AID |
| `bap/mqbab2/navsd/functions/ActiveRgType#setGetProperty` + `NavInfoAdapter case 39` | choice of the navigation view on the AID (RGI, compass, map) |
| `DSIMapViewerStatusTarget#mapViewerReady3Configure` (coding 172) | render size for the AID (1010×376). Target resolution if we substitute our own picture |
| `ConfigurationManagerImpl#setInstrumentClusterSize` / `NvListener(4)` | **not** the dial layout, only the text class. Little value for a mod |

### (b) Native guidance injection (TBT into the BAP NavSD widgets)

Status: this path is implemented in package E "System RG" and the [`rg/`](../../rg/) JAR (a port of
tomasz-twardzicki's solution) and works in the car: native turn arrow, distance and time to destination on the AID.

1. Data source: CarPlay RGI from iAP2 (natively `ipod-drvr-iap2` / `mm-ipod`, as with maxim's and harman-f's work),
   because `DSICarPlay` does not provide it.
2. Injection in Java (in the ASL thread context, e.g. via `ThreadSwitchingService`):
   - `ServiceManager.aslPropertyManager.valueChangedInteger(732, 1)` (RG active);
   - `ListManager.getGenericASLList(751).updateList(...)` (manoeuvre);
   - `ASLNavBAPFactory.getNavBAPApi().updateBapDistanceToNextManeuver(...)`, `.updateBapTurnToInfo(street, sign)`,
     `.updateBapLaneGuidance(...)`, `.updateBapDistanceToDestination(...)`, `.updateBapTimeToDestinationRTTandETA(...)`.
3. Conflicts to work around:
   - When the iPhone navigates, `CarPlayModeHandling` calls `navServices.stopGuidance(6)` and sets `2910009 = true`,
     which turns `InfoStates` to 6. The AID may then show a "navigation in device" screen instead of arrows. A patch of
     `InfoStates#getCurrentBAPInfoState` or `ASLCarplayServicesImpl#isCarPlayRouteGuidanceActive` is needed. In
     practice [NavActiveIgnore](../../navactiveignore/) solves this: while CarPlay is guiding, `CarPlayModeHandling`
     does not set `2910009` and calls neither `setActiveNavigation(2)` nor `stopGuidance(6)`.
   - `HsmTargetBap` (event `3497006`) and native DSI navigation overwrite 732, 751, 741 and 744 whenever native
     navigation reports something. They have to be silenced or gated by a flag.
   - Natively `RGStatus` requires `733 == 0` (navigation OK).
4. Low-risk alternative: fill the empty stubs `AndroidAutoTarget#dsiAndroidAuto2UpdateNavigationNextTurnEvent` and the
   CarPlay equivalent. Needs its own DSI source.

## 7. Open questions

- In the Passat B8 AID, is coding 1172 = 2 (MOST streaming) and 172 = 2 (1010×376)? Check in adaptation 5F (Dashboard
  display config) or in the `DSIMapViewerStatusTarget` log ("adaption api value for the resolution of MapViewer 3").
- How does the AID react to `InfoStates = 6` together with `RG_Status = 1` and a non-empty ManeuverDescriptor: does it
  show arrows or the "phone" screen?
  - **Answered:** with NavActiveIgnore and package E "System RG" the AID shows the native turn arrow plus distance and
    time to destination in the car while the iPhone is guiding.
- DisplayManager context 70 and the H.264 encoder (bitrate, GOP) are native (`DisplayManager` / `dio_manager`), not in
  Java. To be determined whether a source other than MapViewer 3 (e.g. CarPlay video) can be fed without native
  changes.
  - **Answered another way:** the CarPlay map reaches the AID through the native CarPlay cluster stream (`core.so`
    patches in [`patches/mu1161/`](../../patches/mu1161/)), with no changes in Java.
- Does the AID send `ASG_Capabilities.displaySizeClass` also when the dial view changes, or only at startup? The HMI
  code handles both cases, but the only effect is the text set.
- Who sets datapool `1110170` (map switch supported) apart from flag 140, and what is its value in the B8?
- No thread IDs or synchronisation for `ListManager` calls from outside the HSM. To be checked before patching.
