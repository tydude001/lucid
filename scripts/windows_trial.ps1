# proofcut on Windows, in one file - docs/plans/PORTABILITY.md step 5b, scripts/mac_trial.sh's twin.
#
#   powershell -ExecutionPolicy Bypass -File proofcut\scripts\windows_trial.ps1              run the test
#   powershell -ExecutionPolicy Bypass -File proofcut\scripts\windows_trial.ps1 -Uninstall   remove what it added
#
# Run from a clone of the public repo. It installs the tools, runs docs/DEMO.md in that clone's
# checkout, and zips a report for a GitHub issue, with the home folder replaced by `~` in every
# text file in it. It runs DEMO.md's commands as written, into the test folder instead of
# ~/proofcut-demo, and stops at the first one that fails, since that is the finding.
#
# What it installs, and why this shape: everything is a portable download into ONE folder,
# %LOCALAPPDATA%\proofcut-windows-trial, never winget. winget is not on every Windows 10, is not
# guaranteed on GitHub's runner, and uninstalls per package; a folder needs no admin, runs the
# same on the runner (.github/workflows/windows-demo.yml) and on a person's PC, and uninstalls by
# deleting it. Each download is pinned by URL and SHA-256 below.
#   - uv, the standalone zip. uv's own caches, Pythons and tools are pointed into the folder too.
#   - ffmpeg, gyan.dev's essentials build: libx264, drawtext and libass, which proofcut doctor's
#     ffmpeg row checks. It is the build Chocolatey's ffmpeg is (GitHub run 34779525442).
#   - auto-editor, the release binary. PyPI's is a stale fork.
#   - espeak-ng, only to build the demo voice: its MSI unpacked with `msiexec /a`, which installs
#     nothing and needs no admin, and pointed at its data with ESPEAK_DATA_PATH.
#   - melt from Shotcut's portable zip. Portable Shotcut is not where proofcut looks for one, so
#     PROOFCUT_MELT names it. Its modules are unmeasured on Windows, so the two frames in the report
#     are the check, not melt's exit code.
#   - whisper, by `uv tool install`, into the folder.
#   - no ImageMagick: only cards need it and the demo draws none.
#
# Written for Windows PowerShell 5.1, which is what a stock Windows has, and kept to ASCII: 5.1
# reads a script with no byte-order mark as the ANSI code page.

param(
    [switch]$Uninstall,
    # No questions: the CI job, which has nobody to press Enter.
    [switch]$Unattended
)

$ErrorActionPreference = 'Continue'   # a native command writing to stderr is not a failure; exit codes are checked
$ProgressPreference = 'SilentlyContinue'   # 5.1's download progress bar costs more than the download
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$ISSUE_URL = 'https://github.com/tydude001/proofcut/issues/new?template=windows-test.yml'
# The PROOFCUT_TRIAL_* overrides exist for the CI job, which uploads the report rather than leaving it on a Desktop.
$W = if ($env:PROOFCUT_TRIAL_DIR) { $env:PROOFCUT_TRIAL_DIR } else { Join-Path $env:LOCALAPPDATA 'proofcut-windows-trial' }
$MARKER = Join-Path $W '.proofcut-windows-trial'
$MANIFEST = Join-Path $W 'installed.txt'
$TOOLS = Join-Path $W 'tools'
$DEMO = Join-Path $W 'demo'
$REPORT = if ($env:PROOFCUT_TRIAL_REPORT) { $env:PROOFCUT_TRIAL_REPORT } else { Join-Path ([Environment]::GetFolderPath('Desktop')) 'proofcut-windows-report.zip' }
$RULE = [string][char]0x2500 + [char]0x2500   # the step header mark scripts/trial_check.py looks for

# name, url, sha256, what it is for
$PINNED = @(
    @{ Name = 'uv'; What = 'uv 0.12.13 (Python project manager)';
       Url = 'https://github.com/astral-sh/uv/releases/download/0.12.13/uv-x86_64-pc-windows-msvc.zip';
       Sha256 = 'a86c9dc7bad9b03f388583b7187c05fe9951c2e0d392217e8fd43d97787f6ec2' },
    @{ Name = 'ffmpeg'; What = 'ffmpeg 9.0.1 (gyan.dev essentials build)';
       Url = 'https://github.com/GyanD/codexffmpeg/releases/download/9.0.1/ffmpeg-9.0.1-essentials_build.zip';
       Sha256 = 'fec81ae03971d9dd4be3ebe02e263bd2ec1d789483f931bdba5f5715e65da2e9' },
    @{ Name = 'auto-editor'; What = 'auto-editor 31.4.2';
       Url = 'https://github.com/WyattBlue/auto-editor/releases/download/31.4.2/auto-editor-windows-x86_64.exe';
       Sha256 = 'e66cdfab84002200a45369a76ff945df3b7c068a379dd65e4403a5d20b630513' },
    @{ Name = 'espeak-ng'; What = 'espeak-ng 1.52.0 (builds the demo voice)';
       Url = 'https://github.com/espeak-ng/espeak-ng/releases/download/1.52.0/espeak-ng.msi';
       Sha256 = '7f673c709ea5dd579d3b5ebb98688cc575328a6ab7438d2bc405b88cedaeafb9' },
    @{ Name = 'shotcut'; What = 'Shotcut 26.8.1, portable (for its melt renderer)';
       Url = 'https://github.com/mltframework/shotcut/releases/download/v26.8.1/shotcut-win64-26.8.1.zip';
       Sha256 = 'b0148856de01b39add4bf4d6a813bfbc554b4663b65e3ca25cb2589f47555a6a' }
)

function Ask([string]$Question) {
    if ($Unattended) { return $true }
    $answer = Read-Host "$Question [y/N]"
    return ($answer -eq 'y' -or $answer -eq 'Y')
}

# ---- -Uninstall ---------------------------------------------------------------------------
if ($Uninstall) {
    if (-not (Test-Path -LiteralPath $MARKER)) {
        Write-Host "No record of a proofcut test on this PC ($MARKER is missing), so nothing to remove."
        exit 0
    }
    Write-Host ''
    Write-Host '  This removes what the proofcut test added to this PC, and nothing else:'
    if (Test-Path -LiteralPath $MANIFEST) {
        Get-Content -LiteralPath $MANIFEST | ForEach-Object { Write-Host "    - $_" }
    }
    Write-Host "    - the folder all of it is in: $W"
    Write-Host ''
    if (-not (Ask '  Go ahead?')) { exit 0 }
    # Nothing was installed anywhere else: no registry keys, no PATH change, no Start menu entry.
    # Every tool, uv's caches and the speech model live in this one folder.
    Remove-Item -LiteralPath $W -Recurse -Force
    if (Test-Path -LiteralPath $W) {
        Write-Host "  Some files could not be removed (is a program still using them?): $W"
        exit 1
    }
    Write-Host ''
    Write-Host '  Done. The report on your Desktop (proofcut-windows-report.zip) is yours to delete once sent.'
    Write-Host "  The proofcut folder you cloned is yours too: delete it when you are finished with it."
    Write-Host "  Its .venv folder uses a Python that was in the removed folder, so run 'uv sync' again if you keep using it."
    exit 0
}

# ---- the test -----------------------------------------------------------------------------
$REPO = Split-Path -Parent $PSScriptRoot
$pyproject = Join-Path $REPO 'pyproject.toml'
if (-not (Test-Path -LiteralPath (Join-Path $REPO 'scripts\make_demo.py')) -or
    -not (Test-Path -LiteralPath $pyproject) -or
    -not (Select-String -LiteralPath $pyproject -Pattern '^name = "proofcut"' -Quiet)) {
    Write-Host 'This copy is not inside a proofcut checkout.'
    Write-Host 'Clone the repo and run it from there:  git clone https://github.com/tydude001/proofcut'
    exit 1
}
if (($REPO + '\').StartsWith($W + '\', [StringComparison]::OrdinalIgnoreCase)) {
    Write-Host "The checkout is inside $W, which every run clears. Clone it somewhere else."
    exit 1
}
$REV = 'no-git'
if (Get-Command git -ErrorAction SilentlyContinue) {
    $rev = & git -C $REPO rev-parse --short HEAD 2>$null
    if ($LASTEXITCODE -eq 0 -and $rev) { $REV = "$rev".Trim() }
}

Write-Host @"

  proofcut - Windows test
  -----------------------
  This will:
    1. download the tools proofcut needs (uv, ffmpeg, auto-editor, espeak-ng, Shotcut, whisper)
       into one folder: $W
       Nothing is installed system-wide, and it needs no administrator rights.
    2. make a short test video and let proofcut edit it
    3. put proofcut-windows-report.zip on your Desktop, with your home folder's name taken out

  It takes 15-30 minutes, mostly downloading (about 2 GB, most of it the speech model and
  whisper's PyTorch). You can leave it running.
  To remove everything it added afterwards, run this same file with -Uninstall.

"@
if (-not $Unattended) {
    Read-Host '  Press Enter to start, or Ctrl-C to stop' | Out-Null
}

# A re-run starts clean, keeping the record of what an earlier run added.
if (Test-Path -LiteralPath $MARKER) {
    $kept = if (Test-Path -LiteralPath $MANIFEST) { Get-Content -LiteralPath $MANIFEST } else { @() }
    Remove-Item -LiteralPath $W -Recurse -Force
}
elseif (Test-Path -LiteralPath $W) {
    Write-Host "$W exists and was not made by this test, so it is left alone. Move it, or set PROOFCUT_TRIAL_DIR."
    exit 1
}
else {
    $kept = @()
}
New-Item -ItemType Directory -Force -Path $W, $TOOLS | Out-Null
New-Item -ItemType File -Force -Path $MARKER, $MANIFEST | Out-Null
foreach ($line in $kept) { Add-Content -LiteralPath $MANIFEST -Value $line -Encoding ASCII }

$LOG = Join-Path $W 'report.txt'
# UTF-8 without a byte-order mark, written through one handle: 5.1's Tee-Object and Out-File write
# UTF-16, which the check cannot read, and proofcut's own output carries non-ASCII.
$utf8 = New-Object System.Text.UTF8Encoding $false
$script:logw = New-Object System.IO.StreamWriter($LOG, $true, $utf8)
$script:logw.AutoFlush = $true
try { [Console]::OutputEncoding = $utf8 } catch { }   # no console at all under some hosts
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

function Say([string]$Line) {
    Write-Host $Line
    $script:logw.WriteLine($Line)
}

function Record([string]$Line) {
    if (-not (Select-String -LiteralPath $MANIFEST -SimpleMatch -Pattern $Line -Quiet)) {
        Add-Content -LiteralPath $MANIFEST -Value $Line -Encoding ASCII
    }
}

$script:STEPS = New-Object System.Collections.Generic.List[string]
$script:FAIL = ''

function Note-Step([string]$What, [bool]$Ok, [double]$Seconds, [string]$Why) {
    $took = '{0}s' -f [int]$Seconds
    if ($Ok) {
        $script:STEPS.Add("ok    $took  $What")
    }
    else {
        $script:STEPS.Add("FAIL  $took  $What  ($Why)")
        $script:FAIL = $What
        Say "!! failed ($Why) after $took"
    }
}

# A native command, its output streamed to the screen and the log. True when it exited 0.
function Step([string]$What, [string]$Exe, [string[]]$ArgList) {
    Say ''
    Say "$RULE $What"
    Say ('$ ' + ((@($Exe) + $ArgList) -join ' '))
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $code = $null
    try {
        & $Exe @ArgList 2>&1 | ForEach-Object {
            if ($_ -is [System.Management.Automation.ErrorRecord]) { Say $_.Exception.Message } else { Say "$_" }
        }
        $code = $LASTEXITCODE
    }
    catch {
        Say "$_"
    }
    $ok = ($code -eq 0)
    $why = if ($null -eq $code) { 'could not run' } else { "exit $code" }
    Note-Step $What $ok $clock.Elapsed.TotalSeconds $why
    return $ok
}

# PowerShell work (a download, an unpack). True when the block threw nothing.
function Task([string]$What, [scriptblock]$Block) {
    Say ''
    Say "$RULE $What"
    $clock = [Diagnostics.Stopwatch]::StartNew()
    try {
        & $Block | ForEach-Object { Say "$_" }
        Note-Step $What $true $clock.Elapsed.TotalSeconds ''
        return $true
    }
    catch {
        Say "$_"
        Note-Step $What $false $clock.Elapsed.TotalSeconds 'error'
        return $false
    }
}

function Get-Pinned($Piece) {
    $downloads = Join-Path $W 'downloads'
    New-Item -ItemType Directory -Force -Path $downloads | Out-Null
    $file = Join-Path $downloads ([IO.Path]::GetFileName($Piece.Url))
    Say "downloading $($Piece.Url)"
    Invoke-WebRequest -UseBasicParsing -Uri $Piece.Url -OutFile $file
    $got = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($got -ne $Piece.Sha256) {
        Remove-Item -LiteralPath $file -Force
        throw "$([IO.Path]::GetFileName($file)): SHA-256 is $got, expected $($Piece.Sha256). Not using it."
    }
    Say "sha256 ok: $got"
    return $file
}

function Expand-Zip([string]$Zip, [string]$Into) {
    # ZipFile, not 5.1's Expand-Archive, which takes minutes over Shotcut's 225 MB.
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::ExtractToDirectory($Zip, $Into)
}

function Find-One([string]$Under, [string]$Name) {
    $hit = Get-ChildItem -LiteralPath $Under -Recurse -Filter $Name -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $hit) { throw "no $Name anywhere under $Under" }
    return $hit
}

function Hide-Home([string]$Text) {
    # A path appears as written, JSON-escaped, and with forward slashes; the username is the only
    # personal thing in any of them.
    $homeDir = $env:USERPROFILE
    foreach ($form in @($homeDir.Replace('\', '\\'), $homeDir, $homeDir.Replace('\', '/'))) {
        $Text = [regex]::Replace($Text, [regex]::Escape($form), '~', 'IgnoreCase')
    }
    return $Text
}

$script:FINISHED = $false
function Finish {
    if ($script:FINISHED) { return }
    $script:FINISHED = $true
    $os = Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue
    $arch = $env:PROCESSOR_ARCHITECTURE
    if ($env:PROCESSOR_ARCHITEW6432) { $arch = "$env:PROCESSOR_ARCHITEW6432 (this shell: $arch)" }
    Say ''
    Say "$([char]0x2550)$([char]0x2550)$([char]0x2550)$([char]0x2550) summary"
    Say "proofcut $REV $([char]0x00B7) $($os.Caption) $($os.Version) $([char]0x00B7) $arch"
    foreach ($s in $script:STEPS) { Say "  $s" }
    if ($script:FAIL) { Say "STOPPED AT: $($script:FAIL)" } else { Say 'ALL STEPS RAN' }
    $script:logw.Close()

    $out = Join-Path $W 'report'
    if (Test-Path -LiteralPath $out) { Remove-Item -LiteralPath $out -Recurse -Force }
    if (Test-Path -LiteralPath $REPORT) { Remove-Item -LiteralPath $REPORT -Force }
    New-Item -ItemType Directory -Force -Path $out | Out-Null
    foreach ($f in @($LOG, (Join-Path $DEMO 'proj\proofcut.json'), (Join-Path $DEMO 'proj\project.otio'))) {
        if (Test-Path -LiteralPath $f) {
            $text = [IO.File]::ReadAllText($f, $utf8)
            [IO.File]::WriteAllText((Join-Path $out ([IO.Path]::GetFileName($f))), (Hide-Home $text), $utf8)
        }
    }
    foreach ($f in @((Join-Path $W 'frame-3s.png'), (Join-Path $W 'frame-10s.png'), (Join-Path $DEMO 'demo.mp4'))) {
        if (Test-Path -LiteralPath $f) { Copy-Item -LiteralPath $f -Destination $out }
    }
    Compress-Archive -Path (Join-Path $out '*') -DestinationPath $REPORT -Force
    Write-Host ''
    Write-Host "  Done. The report is on your Desktop:  $([IO.Path]::GetFileName($REPORT))"
    Write-Host "  Please attach it to a Windows test report: $ISSUE_URL"
    Write-Host "  To remove everything the test installed:  powershell -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Uninstall"
    Write-Host ''
}

# The whole run sits in try/finally, so Ctrl-C mid-download still writes the summary and the report.
try {
    $winver = Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue
    $cs = Get-CimInstance Win32_ComputerSystem -ErrorAction SilentlyContinue
    $cpu = Get-CimInstance Win32_Processor -ErrorAction SilentlyContinue | Select-Object -First 1
    $drive = Get-PSDrive -Name ($W.Substring(0, 1)) -ErrorAction SilentlyContinue
    Say "proofcut Windows test $([char]0x00B7) proofcut $REV $([char]0x00B7) $(Get-Date -Format 'yyyy-MM-dd HH:mm K')"
    Say "$($winver.Caption) $($winver.Version) $([char]0x00B7) $env:PROCESSOR_ARCHITECTURE $([char]0x00B7) $($cpu.Name)"
    Say ("memory {0} GB $([char]0x00B7) free disk {1} GB $([char]0x00B7) PowerShell {2}" -f [int]($cs.TotalPhysicalMemory / 1GB), [int]($drive.Free / 1GB), $PSVersionTable.PSVersion)
    Say "proofcut checkout: $(Hide-Home $REPO)"

    # Everything uv and whisper would otherwise put under the user profile goes in the folder.
    $env:UV_CACHE_DIR = Join-Path $W 'uv\cache'
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $W 'uv\python'
    $env:UV_TOOL_DIR = Join-Path $W 'uv\tools'
    $env:UV_TOOL_BIN_DIR = Join-Path $W 'uv\bin'
    # Without this, `uv sync` takes a Python 3.13 the PC already has (a person's laptop did, from
    # AppData\Local\Programs) and the .venv then depends on something outside the folder.
    $env:UV_PYTHON_PREFERENCE = 'only-managed'
    $env:XDG_CACHE_HOME = Join-Path $W 'cache'   # whisper keeps its speech model under here

    $bin = Join-Path $TOOLS 'bin'
    $ok = Task 'download tools (pinned, checked by SHA-256)' {
        New-Item -ItemType Directory -Force -Path $bin | Out-Null
        foreach ($piece in $PINNED) {
            $file = Get-Pinned $piece
            switch ($piece.Name) {
                'uv' { Expand-Zip $file $bin }
                'ffmpeg' { Expand-Zip $file (Join-Path $TOOLS 'ffmpeg') }
                'auto-editor' { Copy-Item -LiteralPath $file -Destination (Join-Path $bin 'auto-editor.exe') }
                'espeak-ng' {
                    $into = Join-Path $TOOLS 'espeak-ng'
                    $p = Start-Process msiexec.exe -Wait -PassThru -ArgumentList @('/a', "`"$file`"", '/qn', "TARGETDIR=`"$into`"")
                    if ($p.ExitCode -ne 0) { throw "msiexec /a exited $($p.ExitCode) unpacking espeak-ng" }
                }
                'shotcut' { Expand-Zip $file (Join-Path $TOOLS 'shotcut') }
            }
            Record $piece.What
            Remove-Item -LiteralPath $file -Force
        }
    }
    if (-not $ok) { return }

    $ffmpegExe = Find-One (Join-Path $TOOLS 'ffmpeg') 'ffmpeg.exe'
    $espeakExe = Find-One (Join-Path $TOOLS 'espeak-ng') 'espeak-ng.exe'
    $espeakData = Find-One (Join-Path $TOOLS 'espeak-ng') 'espeak-ng-data'
    $meltExe = Find-One (Join-Path $TOOLS 'shotcut') 'melt.exe'
    $env:PATH = (@($env:UV_TOOL_BIN_DIR, $bin, $ffmpegExe.DirectoryName, $espeakExe.DirectoryName) -join ';') + ';' + $env:PATH
    # espeak-ng finds its data through the registry an MSI install writes; an unpacked MSI wrote none.
    $env:ESPEAK_DATA_PATH = $espeakData.Parent.FullName
    $env:PROOFCUT_MELT = $meltExe.FullName
    Say "melt: $(Hide-Home $env:PROOFCUT_MELT)"
    Say "ESPEAK_DATA_PATH: $(Hide-Home $env:ESPEAK_DATA_PATH)"
    $uv = Join-Path $bin 'uv.exe'

    if (-not (Step 'espeak-ng runs from the unpacked MSI' $espeakExe.FullName @('--version'))) { return }
    if (-not (Step 'install whisper (uv tool)' $uv @('tool', 'install', '--python', '3.12', 'openai-whisper'))) { return }
    Record 'whisper (speech-to-text), and the speech model it downloads'

    Set-Location -LiteralPath $REPO
    if (-not (Step 'uv sync' $uv @('sync'))) { return }
    Step 'proofcut doctor (informational)' $uv @('run', 'proofcut', 'doctor') | Out-Null
    $script:FAIL = ''   # the demo below is the verdict

    $proj = Join-Path $DEMO 'proj'
    $L = @('run', 'proofcut', '-C', $proj)
    # Each step's arguments are parenthesised: `,` binds tighter than `+`, so `'name', $L + @(...)`
    # is `('name', $L) + @(...)`, and the step ran `lucid -C proj` with its command dropped
    # (the first windows-demo run).
    $demoSteps = @(
        @('DEMO 1 make the footage', @('run', 'python', 'scripts\make_demo.py', $DEMO)),
        @('DEMO 2 init', @('run', 'proofcut', 'init', $proj)),
        @('DEMO 2 import vo', ($L + @('import', (Join-Path $DEMO 'vo.wav'), '--clip-id', 'vo'))),
        @('DEMO 2 import blue', ($L + @('import', (Join-Path $DEMO 'broll-blue.mp4'), '--clip-id', 'blue'))),
        @('DEMO 2 import rust', ($L + @('import', (Join-Path $DEMO 'broll-rust.mp4'), '--clip-id', 'rust'))),
        @('DEMO 2 transcribe (first run downloads a 1.5 GB speech model)', ($L + @('transcribe', 'vo'))),
        @('DEMO 2 seed', ($L + @('seed', 'vo'))),
        @('DEMO 3 find the retake', ($L + @('transcript', 'vo', '--search', 'let me try that again'))),
        @('DEMO 3 read around it', ($L + @('transcript', 'vo', '--first', '8', '--last', '26'))),
        @('DEMO 4 cut --plan', ($L + @('cut', 'vo', '11:23', '--plan'))),
        @('DEMO 4 cut', ($L + @('cut', 'vo', '11:23', '--pad', '0.1'))),
        @('DEMO 5 cue blue', ($L + @('cue', 'add', 'vo', '--phrase', 'Every cut you make names a word', 'blue'))),
        @('DEMO 5 cue rust', ($L + @('cue', 'add', 'vo', '--phrase', 'the render can be checked', 'rust'))),
        @('DEMO 5 shots', ($L + @('shots'))),
        @('DEMO 6 render (melt)', ($L + @('export', (Join-Path $DEMO 'demo.mp4'), '--render'))),
        @('DEMO 6 verify', ($L + @('verify', (Join-Path $DEMO 'demo.mp4')))),
        @('DEMO 6 frames', ($L + @('frames', (Join-Path $DEMO 'demo.mp4'))))
    )
    foreach ($s in $demoSteps) {
        if (-not (Step $s[0] $uv $s[1])) { break }
    }

    # DEMO.md section 7: at ~3s the frame should read "BLUE 3s", at ~10s "RUST 0s". A person reads these.
    $video = Join-Path $DEMO 'demo.mp4'
    if (Test-Path -LiteralPath $video) {
        & $ffmpegExe.FullName -v error -y -ss 3 -i $video -frames:v 1 (Join-Path $W 'frame-3s.png') 2>&1 | Out-Null
        & $ffmpegExe.FullName -v error -y -ss 10 -i $video -frames:v 1 (Join-Path $W 'frame-10s.png') 2>&1 | Out-Null
    }
}
finally {
    if (-not $script:FINISHED) {
        if (-not $script:FAIL -and $script:STEPS.Count -eq 0) { $script:FAIL = 'stopped before the first step' }
        Finish
    }
}

if (-not $script:FAIL -and -not $Unattended) {
    if (Ask "  Want to see proofcut's editor window with the result?") {
        & (Join-Path $TOOLS 'bin\uv.exe') run proofcut -C (Join-Path $DEMO 'proj') open
    }
}
exit 0
