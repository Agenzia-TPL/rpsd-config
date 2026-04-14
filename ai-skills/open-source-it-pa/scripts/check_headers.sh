#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
#
# check_headers.sh — Check or fix SPDX copyright/licence headers in source files.
#
# Usage:
#   check_headers.sh [OPTIONS] [PATH...]
#
# Modes (mutually exclusive):
#   --check     Report files missing headers; exit 1 if any found.  (CI mode)
#   --fix       Add headers to files that are missing them.          (default)
#
# Options:
#   --copyright "TEXT"    Copyright string for the header line (required in --fix mode).
#                         Example: "2026 Acme Corp"
#   --license   SPDX-ID   SPDX licence identifier (required in --fix mode).
#                         Example: EUPL-1.2
#   --ext       LIST      Comma-separated file extensions to scan (no dots).
#                         Default: py,sh
#                         Example: --ext py,sh,js,ts,go
#   PATH...               Files or directories to scan (default: current directory).
#
# Examples:
#   # Check that all Python and shell files under src/ have headers:
#   check_headers.sh --check --ext py,sh src/
#
#   # Add missing headers to Python files:
#   check_headers.sh --fix --copyright "2026 Acme Corp" --license MIT src/
#
#   # Check a single file:
#   check_headers.sh --check src/mymodule.py

set -euo pipefail

# ---------------------------------------------------------------------------
# Comment-character lookup table.
# Add more extensions here as needed.
# Format: one "ext:char" entry per line (no spaces around colon).
# ---------------------------------------------------------------------------
declare -A COMMENT_CHAR=(
    [py]="#"
    [sh]="#"
    [bash]="#"
    [zsh]="#"
    [yaml]="#"
    [yml]="#"
    [toml]="#"
    [tf]="#"
    [tfvars]="#"
    [rb]="#"
    [r]="#"
    [pl]="#"
    [js]="//"
    [jsx]="//"
    [ts]="//"
    [tsx]="//"
    [go]="//"
    [java]="//"
    [kt]="//"
    [swift]="//"
    [c]="//"
    [h]="//"
    [cpp]="//"
    [hpp]="//"
    [cs]="//"
    [rs]="//"
    [php]="//"
    [scala]="//"
)

# ---------------------------------------------------------------------------
# Directories to always skip during recursive scan.
# ---------------------------------------------------------------------------
SKIP_DIRS=(
    ".git"
    ".venv"
    "venv"
    "node_modules"
    "dist"
    "build"
    "__pycache__"
    ".mypy_cache"
    ".ruff_cache"
    ".pytest_cache"
    "*.egg-info"
)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
MODE="fix"
COPYRIGHT=""
LICENSE_ID=""
EXTENSIONS="py,sh"
SCAN_PATHS=()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
red()    { printf '\033[31m%s\033[0m\n' "$*"; }
green()  { printf '\033[32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }
bold()   { printf '\033[1m%s\033[0m\n' "$*"; }

usage() {
    sed -n '/^# Usage:/,/^[^#]/{ /^#/{ s/^# \{0,1\}//; p } }' "$0"
    exit 0
}

die() { red "ERROR: $*" >&2; exit 1; }

# Build a find -prune expression for skipped directories.
build_prune_expr() {
    local expr=()
    local first=true
    for d in "${SKIP_DIRS[@]}"; do
        if $first; then
            first=false
        else
            expr+=("-o")
        fi
        expr+=("-name" "$d" "-prune")
    done
    printf '%s\n' "${expr[@]}"
}

# Return the comment character for a given extension (lowercase).
comment_char_for() {
    local ext="${1,,}"   # lowercase
    echo "${COMMENT_CHAR[$ext]:-#}"
}

# Return true if a file has both required SPDX tags anywhere in the first 10 lines.
has_spdx_headers() {
    local file="$1"
    local has_copyright has_license
    has_copyright=$(head -10 "$file" | grep -c "SPDX-FileCopyrightText" || true)
    has_license=$(head -10 "$file" | grep -c "SPDX-License-Identifier" || true)
    [[ "$has_copyright" -gt 0 && "$has_license" -gt 0 ]]
}

# Add SPDX headers to a file that is missing them.
# Handles shebang: if line 1 starts with "#!", insert headers after it.
add_headers() {
    local file="$1"
    local cchar="$2"
    local tmpfile
    tmpfile="$(mktemp)"

    local line1
    line1="$(head -1 "$file")"

    if [[ "$line1" == '#!'* ]]; then
        # Shebang present: write shebang, then headers, then rest of file.
        {
            echo "$line1"
            echo "${cchar} SPDX-FileCopyrightText: ${COPYRIGHT}"
            echo "${cchar} SPDX-License-Identifier: ${LICENSE_ID}"
            tail -n +2 "$file"
        } > "$tmpfile"
    else
        # No shebang: headers go first.
        {
            echo "${cchar} SPDX-FileCopyrightText: ${COPYRIGHT}"
            echo "${cchar} SPDX-License-Identifier: ${LICENSE_ID}"
            cat "$file"
        } > "$tmpfile"
    fi

    mv "$tmpfile" "$file"
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --check)  MODE="check"; shift ;;
        --fix)    MODE="fix";   shift ;;
        --copyright)
            [[ $# -ge 2 ]] || die "--copyright requires an argument."
            COPYRIGHT="$2"; shift 2 ;;
        --license)
            [[ $# -ge 2 ]] || die "--license requires an argument."
            LICENSE_ID="$2"; shift 2 ;;
        --ext)
            [[ $# -ge 2 ]] || die "--ext requires an argument."
            EXTENSIONS="$2"; shift 2 ;;
        --help|-h) usage ;;
        --) shift; SCAN_PATHS+=("$@"); break ;;
        -*) die "Unknown option: $1" ;;
        *)  SCAN_PATHS+=("$1"); shift ;;
    esac
done

[[ ${#SCAN_PATHS[@]} -eq 0 ]] && SCAN_PATHS=(".")

if [[ "$MODE" == "fix" ]]; then
    [[ -n "$COPYRIGHT"  ]] || die "In --fix mode, --copyright is required."
    [[ -n "$LICENSE_ID" ]] || die "In --fix mode, --license is required."
fi

# ---------------------------------------------------------------------------
# Build the list of extensions to match.
# ---------------------------------------------------------------------------
IFS=',' read -ra EXT_LIST <<< "$EXTENSIONS"

# ---------------------------------------------------------------------------
# Build find arguments for extension matching.
# ---------------------------------------------------------------------------
build_ext_expr() {
    local expr=()
    local first=true
    for ext in "${EXT_LIST[@]}"; do
        ext="${ext// /}"   # trim spaces
        if $first; then
            first=false
            expr+=("-name" "*.${ext}")
        else
            expr+=("-o" "-name" "*.${ext}")
        fi
    done
    printf '%s\n' "${expr[@]}"
}

# ---------------------------------------------------------------------------
# Main scan
# ---------------------------------------------------------------------------
total=0
compliant=0
missing=0
fixed=0
errors=0

missing_files=()

mapfile -t PRUNE_EXPR < <(build_prune_expr)
mapfile -t EXT_EXPR   < <(build_ext_expr)

while IFS= read -r -d '' file; do
    total=$((total + 1))
    ext="${file##*.}"
    ext="${ext,,}"

    if has_spdx_headers "$file"; then
        compliant=$((compliant + 1))
        continue
    fi

    # File is missing headers.
    missing_files+=("$file")
    missing=$((missing + 1))

    if [[ "$MODE" == "fix" ]]; then
        cchar="$(comment_char_for "$ext")"
        if add_headers "$file" "$cchar"; then
            yellow "  fixed: $file"
            fixed=$((fixed + 1))
        else
            red "  error: could not fix $file"
            errors=$((errors + 1))
        fi
    fi
done < <(
    find "${SCAN_PATHS[@]}" \
        \( "${PRUNE_EXPR[@]}" \) \
        -o \( \( "${EXT_EXPR[@]}" \) -type f -print0 \)
)

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
bold "SPDX header scan summary"
echo "  Extensions : ${EXTENSIONS}"
echo "  Paths      : ${SCAN_PATHS[*]}"
echo "  Mode       : ${MODE}"
echo "  Scanned    : ${total}"
green "  Compliant  : ${compliant}"

if [[ "$MODE" == "check" ]]; then
    if [[ "$missing" -gt 0 ]]; then
        red "  Missing    : ${missing}"
        echo ""
        red "Files missing SPDX headers:"
        for f in "${missing_files[@]}"; do
            echo "    $f"
        done
        echo ""
        die "${missing} file(s) are missing SPDX headers. Run with --fix to add them."
    else
        echo ""
        green "All files have SPDX headers."
    fi
else
    if [[ "$fixed" -gt 0 ]];  then yellow "  Fixed      : ${fixed}";  fi
    if [[ "$errors" -gt 0 ]]; then red    "  Errors     : ${errors}"; fi
    if [[ "$errors" -gt 0 ]]; then
        die "${errors} file(s) could not be fixed."
    fi
    if [[ "$fixed" -gt 0 ]]; then
        echo ""
        green "Done. ${fixed} file(s) updated."
    else
        echo ""
        green "All files already have SPDX headers. Nothing to do."
    fi
fi
