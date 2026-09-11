#!/bin/bash
# lucid on a Mac, in one file — docs/plans/LAUNCH.md § Step 2.
#
# One file, two jobs:
#
#   bash scripts/mac_trial.sh --pack OUT.sh    on the dev box: copy this script to OUT.sh and
#                                              append the repo at HEAD, so the tester needs no
#                                              repo access, git, or GitHub account
#   bash lucid-mac-test.sh                     on the Mac: unpack, install the tools with
#                                              Homebrew, run docs/DEMO.md, zip a report
#
# The Mac half runs DEMO.md's commands as written, into ~/lucid-mac-trial/demo instead of
# ~/lucid-demo, and stops at the first one that fails, since that is the finding. The install
# list is the Homebrew half of README.md § Requirements; whisper comes from `uv tool`, because
# Homebrew's openai-whisper pulls llvm and pytorch as formulae, gigabytes more than uv's wheels.
# Written for the macOS system bash (3.2): no associative arrays, no ${x,,}.

set -u

if [ "${1:-}" = "--pack" ]; then
    out="${2:?usage: mac_trial.sh --pack OUT.sh}"
    repo="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)" || exit 1
    if [ -n "$(git -C "$repo" status --porcelain)" ]; then
        echo "refusing: the working tree is dirty, and the pack is HEAD — commit first" >&2
        exit 1
    fi
    rev="$(git -C "$repo" rev-parse --short HEAD)"
    sed "s/^PACKED_REV=.*/PACKED_REV=$rev/" "$0" > "$out"
    echo "__PAYLOAD__" >> "$out"
    git -C "$repo" archive --format=tar.gz --prefix=lucid/ HEAD | base64 -w 76 >> "$out"
    echo "packed lucid $rev -> $out ($(du -h "$out" | cut -f1))"
    exit 0
fi

PACKED_REV=unpacked
W="${LUCID_TRIAL_DIR:-$HOME/lucid-mac-trial}"   # the two overrides exist for a dry run off the Mac
DEMO="$W/demo"
REPORT="${LUCID_TRIAL_REPORT:-$HOME/Desktop/lucid-mac-report.zip}"

if [ "$(uname -s)" != "Darwin" ]; then
    echo "This is the Mac test. Run it on a Mac." >&2
    exit 1
fi
if ! grep -q '^__PAYLOAD__$' "$0"; then
    echo "This copy has no lucid inside it. Ask Tyler for the packed file (lucid-mac-test.sh)." >&2
    exit 1
fi

cat <<'EOF'

  lucid — Mac test
  ----------------
  This will:
    1. install the video tools lucid needs, with Homebrew (a few GB of downloads)
    2. make a short test video and let lucid edit it
    3. put lucid-mac-report.zip on your Desktop for you to send back to Tyler

  It takes 15–40 minutes, mostly downloading. You can leave it running.
  Everything goes into Homebrew, ~/.local, and a folder called lucid-mac-trial in
  your home folder. Delete that folder afterwards if you like.

EOF
if [ "$(uname -m)" != "arm64" ]; then
    echo "  Note: this is an Intel Mac. Some tools will compile from source, which is slower."
    echo
fi
printf "  Press Enter to start, or Ctrl-C to stop. "
read -r _

if [ -f "$W/.lucid-mac-trial" ]; then
    rm -rf "$W"
fi
mkdir -p "$W"
touch "$W/.lucid-mac-trial"
LOG="$W/report.txt"
exec > >(tee -a "$LOG") 2>&1

STEPS=()
fail=""

step() {  # step "what this is" command args...
    local what="$1"; shift
    echo
    echo "── $what"
    echo "\$ $*"
    local t0=$SECONDS
    "$@"
    local rc=$?
    local took=$((SECONDS - t0))
    if [ $rc -eq 0 ]; then
        STEPS+=("ok    ${took}s  $what")
    else
        STEPS+=("FAIL  ${took}s  $what  (exit $rc)")
        fail="$what"
        echo "!! failed (exit $rc) after ${took}s"
    fi
    return $rc
}

finish() {
    echo
    echo "════ summary"
    echo "lucid $PACKED_REV · macOS $(sw_vers -productVersion) · $(uname -m)"
    for s in ${STEPS[@]+"${STEPS[@]}"}; do echo "  $s"; done
    if [ -n "$fail" ]; then
        echo "STOPPED AT: $fail"
    else
        echo "ALL STEPS RAN"
    fi

    # The report names files under this Mac's home folder; the username is the only personal thing
    # in it. A copy, never `sed -i`: tee still holds the log open and would keep writing to the
    # replaced file's old inode.
    sleep 1
    sed "s#$HOME#~#g" "$LOG" > "$W/report-clean.txt"
    rm -f "$REPORT"
    (
        cd "$W" || exit
        mv report-clean.txt report-for-tyler.txt
        files=(report-for-tyler.txt)
        for f in frame-3s.png frame-10s.png demo/demo.mp4 demo/proj/lucid.json demo/proj/project.otio; do
            [ -e "$f" ] && files+=("$f")
        done
        zip -q "$REPORT" "${files[@]}"
    )
    echo
    echo "  Done. Send Tyler this file from your Desktop:  lucid-mac-report.zip"
    echo
    open -R "$REPORT" 2>/dev/null
}

echo "lucid Mac test · lucid $PACKED_REV · $(date '+%Y-%m-%d %H:%M %Z')"
echo "macOS $(sw_vers -productVersion) ($(sw_vers -buildVersion)) · $(uname -m) · $(sysctl -n machdep.cpu.brand_string 2>/dev/null)"
echo "memory $(( $(sysctl -n hw.memsize) / 1073741824 )) GB · free disk $(df -h "$HOME" | awk 'NR==2 {print $4}')"

line=$(awk '/^__PAYLOAD__$/ {print NR + 1; exit}' "$0")
if ! step "unpack lucid" sh -c "tail -n +$line '$0' | base64 --decode | tar -xz -C '$W'"; then finish; exit 1; fi

# Homebrew. Its installer asks for the Mac's password and may install Apple's command line tools.
brew_bin=""
for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    [ -x "$b" ] && brew_bin="$b" && break
done
if [ -z "$brew_bin" ]; then
    echo
    echo "Homebrew is not installed. Installing it now — it will ask for your Mac password."
    step "install Homebrew" /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
        [ -x "$b" ] && brew_bin="$b" && break
    done
    if [ -z "$brew_bin" ]; then fail="install Homebrew"; finish; exit 1; fi
fi
eval "$("$brew_bin" shellenv)"
export PATH="$HOME/.local/bin:$PATH"

if ! step "install tools (Homebrew)" brew install uv ffmpeg espeak-ng mlt auto-editor imagemagick; then finish; exit 1; fi
if ! step "install whisper (uv tool)" uv tool install --python 3.12 openai-whisper; then finish; exit 1; fi
echo
brew list --versions uv ffmpeg espeak-ng mlt auto-editor imagemagick
echo "melt: $(command -v melt)"
echo "whisper: $(command -v whisper)"

cd "$W/lucid" || { fail="enter repo"; finish; exit 1; }
if ! step "uv sync" uv sync; then finish; exit 1; fi
step "lucid doctor (informational)" uv run lucid doctor || fail=""   # the demo below is the verdict

L() { uv run lucid -C "$DEMO/proj" "$@"; }

step "DEMO 1 make the footage" uv run python scripts/make_demo.py "$DEMO" &&
step "DEMO 2 init" uv run lucid init "$DEMO/proj" &&
step "DEMO 2 import vo" L import "$DEMO/vo.wav" --clip-id vo &&
step "DEMO 2 import blue" L import "$DEMO/broll-blue.mp4" --clip-id blue &&
step "DEMO 2 import rust" L import "$DEMO/broll-rust.mp4" --clip-id rust &&
step "DEMO 2 transcribe (first run downloads a whisper model)" L transcribe vo &&
step "DEMO 2 seed" L seed vo &&
step "DEMO 3 find the retake" L transcript vo --search "let me try that again" &&
step "DEMO 3 read around it" L transcript vo --first 8 --last 26 &&
step "DEMO 4 cut --plan" L cut vo 11:23 --plan &&
step "DEMO 4 cut" L cut vo 11:23 --pad 0.1 &&
step "DEMO 5 cue blue" L cue add vo --phrase "Every cut you make names a word" blue &&
step "DEMO 5 cue rust" L cue add vo --phrase "the render can be checked" rust &&
step "DEMO 5 shots" L shots &&
step "DEMO 6 render (melt)" L export "$DEMO/demo.mp4" --render &&
step "DEMO 6 verify" L verify "$DEMO/demo.mp4" &&
step "DEMO 6 frames" L frames "$DEMO/demo.mp4"

# DEMO.md § 7: at ~3s the frame should read "BLUE 3s", at ~10s "RUST 0s". Tyler reads these.
if [ -f "$DEMO/demo.mp4" ]; then
    ffmpeg -v error -y -ss 3 -i "$DEMO/demo.mp4" -frames:v 1 "$W/frame-3s.png"
    ffmpeg -v error -y -ss 10 -i "$DEMO/demo.mp4" -frames:v 1 "$W/frame-10s.png"
fi

finish

if [ -z "$fail" ]; then
    printf "  Want to see lucid's editor window with the result? Type y and Enter (Ctrl-C closes it): "
    read -r ans
    if [ "$ans" = "y" ] || [ "$ans" = "Y" ]; then
        uv run lucid -C "$DEMO/proj" open
    fi
fi
exit 0
