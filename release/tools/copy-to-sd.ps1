# SPDX-License-Identifier: GPL-3.0-or-later
# Copy CARD 1 (install) or CARD 2 (rescue) from this package onto an EMPTY FAT32 SD card, then check every file.
# Never formats, never deletes anything that was on the card. Windows PowerShell 5.1 (built into Windows 10/11).
$ErrorActionPreference = 'Stop'
$Here = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Log = Join-Path $Here ("copy-log-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + ".txt")
try { Start-Transcript -LiteralPath $Log | Out-Null } catch { }

function Say($t) { Write-Host $t }
function Ok($t) { Write-Host ("  [ OK ] " + $t) -ForegroundColor Green }
function Line { Say "------------------------------------------------------------------------" }
function Finish($code) {
    Say ""; Say ("  Log saved to: " + $Log)
    try { Stop-Transcript | Out-Null } catch { }
    Read-Host "  Press Enter to close this window" | Out-Null
    exit $code
}
function Fail($why, $what) {
    Say ""; Line
    Write-Host ("  [STOP] " + $why) -ForegroundColor Red
    if ($what) { Say ("         " + $what) }
    Say "         Nothing on the card was deleted."
    Line
    Finish 1
}
function Ask($q) { return (Read-Host ("  ?  " + $q)).Trim() }
function Sha($path) { return (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLower() }
$System = @('System Volume Information', '$RECYCLE.BIN', '.fseventsd', '.Spotlight-V100', '.Trashes')

try {
    Say ""
    Say "  CarPlay map on the AID - SD card copy helper"
    Line
    Say "  Which card do you want to make?"
    Say "    2 = CARD 2, RESCUE  (make this one first; only for emergencies, it starts by itself)"
    Say "    1 = CARD 1, INSTALL (used from the green menu in the car)"
    $choice = Ask "Type 1 or 2 and press Enter"
    switch ($choice) {
        '1' { $Src = Join-Path $Here 'card1-install'; $Man = 'PMCP_CARD_MANIFEST.txt'; $Name = 'CARD 1 (INSTALL)'; $Label = 'INSTALL' }
        '2' { $Src = Join-Path $Here 'card2-rescue'; $Man = 'PMCP_RESCUE_MANIFEST.txt'; $Name = 'CARD 2 (RESCUE)'; $Label = 'RESCUE - DO NOT INSERT' }
        default { Fail "Please type 1 or 2." "Start the helper again." }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $Src $Man))) {
        Fail ("The folder " + (Split-Path -Leaf $Src) + " is missing next to this helper.") `
             "Right-click the zip -> Extract All, then start the helper from the extracted folder (not from inside the zip)."
    }

    # manifest lines: <sha256>  <size>  <path>; card 1's first line is the build name
    $List = @()
    foreach ($l in [System.IO.File]::ReadAllLines((Join-Path $Src $Man))) {
        if ($l -match '^([0-9a-f]{64}) +([0-9]+)  (.+)$') {
            $List += [pscustomobject]@{ Hash = $Matches[1]; Size = [int64]$Matches[2]; Path = $Matches[3] }
        }
    }
    $Count = $List.Count
    Say ""
    Say ("  Step 1 of 4: checking the files of " + $Name + " in this package (" + $Count + " files)...")
    $bad = 0
    foreach ($e in $List) {
        $f = Join-Path $Src $e.Path
        if (-not (Test-Path -LiteralPath $f) -or (Sha $f) -ne $e.Hash) { Say ("    damaged or missing: " + $e.Path); $bad++ }
    }
    if ($bad) { Fail ("" + $bad + " files in this package are damaged.") "Download the zip again and extract it again." }
    Ok ("all " + $Count + " files are complete")
    $Need = ($List | Measure-Object -Property Size -Sum).Sum + 4MB

    Say ""
    Say "  Step 2 of 4: choose the SD card"
    while ($true) {
        Ask ("Insert an EMPTY SD card (FAT32) for " + $Name + ", wait until it shows in File Explorer, then press Enter") | Out-Null
        # DriveType 2 = removable (SD cards and card readers); works without administrator rights
        $Cards = @(Get-CimInstance Win32_LogicalDisk | Where-Object { $_.DriveType -eq 2 -and $_.FileSystem -eq 'FAT32' } |
                   Sort-Object DeviceID)
        if ($Cards.Count -gt 0) { break }
        Say "    No FAT32 SD card found. Cards in other formats are not shown."
        Say "    To format a card (this ERASES it): File Explorer -> right-click the card -> Format -> FAT32."
        Say "    Windows offers FAT32 only for cards up to 32 GB."
    }
    if ($Cards.Count -eq 1) {
        $Card = $Cards[0]
    } else {
        for ($i = 0; $i -lt $Cards.Count; $i++) {
            $c = $Cards[$i]
            Say ("    " + ($i + 1) + ") " + $c.DeviceID + "  " + $c.VolumeName + "  (" + [math]::Round($c.Size / 1GB, 1) + " GB)")
        }
        $n = 0
        if (-not [int]::TryParse((Ask "Type the number of the card"), [ref]$n) -or $n -lt 1 -or $n -gt $Cards.Count) { Fail "No card with that number." }
        $Card = $Cards[$n - 1]
    }
    $Root = $Card.DeviceID + "\"
    Say ("    card: " + $Card.DeviceID + "  " + $Card.VolumeName + "  (" + [math]::Round($Card.Size / 1GB, 1) + " GB, FAT32)")
    $Other = @(Get-ChildItem -LiteralPath $Root -Force | Where-Object { $System -notcontains $_.Name })
    if ($Other.Count -gt 0) {
        Fail ("The card " + $Card.DeviceID + " is not empty (for example: " + $Other[0].Name + ").") `
             "Use an empty card, or copy its files somewhere safe and format it as FAT32."
    }
    if ($Card.FreeSpace -lt $Need) { Fail ("The card is too small (" + [math]::Round($Card.FreeSpace / 1MB) + " MB free).") }
    Ok "the card is empty and large enough"
    $yes = Ask ("Copy " + $Name + " to card " + $Card.DeviceID + "? Type YES to continue")
    if ($yes -ne 'YES' -and $yes -ne 'yes') { Fail "Not confirmed." "Start the helper again when you are ready." }

    Say ""
    Say ("  Step 3 of 4: copying " + $Count + " files (the card's autostart file, if any, is copied last)...")
    function CopyOne($rel) {
        $from = Join-Path $Src $rel
        $to = Join-Path $Root $rel
        $dir = Split-Path -Parent $to
        if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        Copy-Item -LiteralPath $from -Destination ($to + '.pmcp-tmp') -Force
        Move-Item -LiteralPath ($to + '.pmcp-tmp') -Destination $to -Force
    }
    $i = 0
    foreach ($e in $List) {
        if ($e.Path -eq 'Swdlautorun.txt') { continue }
        CopyOne $e.Path; $i++
        if ($i % 50 -eq 0) { Say ("    " + $i + " / " + $Count) }
    }
    if ($List | Where-Object { $_.Path -eq 'Swdlautorun.txt' }) { CopyOne 'Swdlautorun.txt' }
    CopyOne $Man
    Ok "copied"

    Say ""
    Say "  Step 4 of 4: checking every file on the card..."
    $bad = 0
    foreach ($e in $List) {
        $f = Join-Path $Root $e.Path
        if (-not (Test-Path -LiteralPath $f) -or (Sha $f) -ne $e.Hash) { Say ("    differs on the card: " + $e.Path); $bad++ }
    }
    if ((Sha (Join-Path $Root $Man)) -ne (Sha (Join-Path $Src $Man))) { $bad++ }
    if ($bad) { Fail ("" + $bad + " files on the card are wrong.") "Do NOT use this card in the car. Try another card." }
    Ok ("all " + $Count + " files on the card are correct")
    try {
        (New-Object -ComObject Shell.Application).Namespace(17).ParseName($Root).InvokeVerb("Eject")
        Ok "card ejected, you can remove it"
    } catch {
        Say "    Use 'Safely Remove Hardware' (taskbar) before removing the card."
    }

    Say ""
    Line
    Say ("  DONE: " + $Name + " is ready. Write on it:  " + $Label)
    if ($Label -eq 'INSTALL') {
        Say "  Next: follow PART 2 in README-FIRST.txt (start with the rescue card test)."
    } else {
        Say "  Next: start this helper again and make CARD 1 (INSTALL)."
    }
    Line
    Finish 0
} catch {
    Fail ("Unexpected error: " + $_.Exception.Message) "Do not use this card in the car. Send the log file to the project."
}
