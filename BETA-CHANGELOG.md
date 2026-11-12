# Beta changelog

One entry per beta. How to install and test a beta: [BETA.md](BETA.md). Stable releases: [CHANGELOG.md](CHANGELOG.md).

## v1.7.0-mu1418-beta.1 (2026-11-12)

**First beta for MU1418:** VW Golf (US), Discover Pro MHI2 `MHI2_US_VWG13_P3662`, MU 1418, AID part 791. Installer version
`pmcp-0.7.0-mu1418-791-<build id>`. Built on stable v1.7.0 (same installer code, same tests).

**Not tested in a car yet.** Everything below is checked offline against this unit's own files (from an owner's M.I.B.
backup and raw `app.img`).

What it installs on MU1418:

- **CarPlay map on the AID** (main menu 2): the same cluster files as on MU1161 (the map files depend on the AID 791,
  not on the firmware version), with every map layout of the stable release.
- **Additional features** (main menu 4), each built from this unit's own HMI classes:
  - `nai`: the AID map stays while the iPhone navigates (our NavActiveIgnore, as `pmcp-nai.jar`);
  - `rg`: route guidance on the AID (VW arrows, lanes, distance bar, street name, reroute), with the iAP2 driver patch
    applied to this unit's factory driver;
  - `zoom`: map zoom with the steering wheel arrows;
  - `dn`: day/night of the map;
  - `sl` (advanced menu): optional native VW speed limit reader.
- **Not in this beta:** Android Auto, song title (`np`) and the settings page in App-Connect (`ui`). This unit's classes
  differ there; they come in a later beta.
- **The same menu as the stable release:** every button is there. Android Auto (3 and the `aa_advanced` screen) and the
  `np` / `ui` buttons say "not yet supported on this unit (MU1418)" and change nothing; 4 installs the features this unit
  has and names the ones it skips.
- **MIB Toolbox NavActiveIgnore taken over:** a unit whose `lsd.sh` has exactly the Toolbox line (and the Toolbox jar,
  both hashes checked) is accepted. Both files are saved on the unit first; with the additional features our own nai
  replaces the line. "Remove everything" goes back to the factory `lsd.sh`; the Toolbox one can be installed again from the
  Toolbox. Any other change to `lsd.sh` is refused, as before.
- **A card of one unit type never changes the other:** an MU1161 card on MU1418 (and the other way round) stops before
  it changes anything.
- **"CP save log"** now also saves which view the AID showed and when, so a cockpit that leaves the map during a route
  shows in the log.

Offline tests: installer tests in ksh and mksh 0 failures (factory `lsd.sh` and Toolbox `lsd.sh`), power-loss chain
0 failures, cross-unit tests (MU1161 card on MU1418 and back) 0 failures. Every Java package passes its host tests and the
J9 API check against this unit's classes.

Known risks for the first test:

- The cluster map transport is the one proven on MU1161; on this unit it is new. Visit 1 of [BETA.md](BETA.md) tests only
  the map.
- Another project reports that some US P3662 cockpits leave the phone's map while the iPhone guides a route. Our `nai`
  is meant to keep it, but this has not been seen on this unit yet; the new log section shows it.
