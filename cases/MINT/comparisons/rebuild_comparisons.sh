#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CASE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKSPACE_ROOT="$(cd "$CASE_DIR/../../.." && pwd)"
OFFICIAL_REPO="${MINT_OFFICIAL_REPO:-$WORKSPACE_ROOT/MINT}"
NORMALIZED="$SCRIPT_DIR/normalized"
PATCHES="$SCRIPT_DIR/patches"
LEGACY_REV=4eab5795345721001c412ff1ca2c886a11eab606
MAIN_REV=691a5e650fbccceaf70568799294eba24f79e114
MISSING_REV=59fa23d0537f545ca07b7d111a9f5697bbabe11e

if ! git -C "$OFFICIAL_REPO" cat-file -e "$LEGACY_REV^{commit}" ||
   ! git -C "$OFFICIAL_REPO" cat-file -e "$MAIN_REV^{commit}"; then
    echo "Official MINT repository lacks one or both fixed commits: $OFFICIAL_REPO" >&2
    exit 2
fi

before_status="$(git -C "$OFFICIAL_REPO" status --porcelain=v1 | sha256sum | cut -d' ' -f1)"
temp_root="$(mktemp -d)"
trap 'rm -rf -- "$temp_root"' EXIT

recovery_status=missing
git init --bare --initial-branch=main "$temp_root/recovery.git" >/dev/null
git -C "$temp_root/recovery.git" remote add origin "$(git -C "$OFFICIAL_REPO" remote get-url origin)"
if git -C "$temp_root/recovery.git" fetch --quiet --depth=1 origin "$MISSING_REV" \
    >"$temp_root/recovery.log" 2>&1; then
    recovery_status=recovered_in_temporary_repository
fi

mkdir -p "$NORMALIZED" "$PATCHES"
for target in official-legacy-4eab579 official-main-691a5e6 official-declared-59fa23d ascend-v043 ascend-v062; do
    find "$NORMALIZED/$target" -mindepth 1 -delete 2>/dev/null || true
    mkdir -p "$NORMALIZED/$target/project" "$NORMALIZED/$target/package"
done

materialize_git_source() {
    local repository="$1"
    local revision="$2"
    local package_root="$3"
    local target="$4"
    local archive_dir="$temp_root/archive-$target"
    mkdir -p "$archive_dir"
    git -C "$repository" archive "$revision" | tar -x -C "$archive_dir"
    cp "$archive_dir/README.md" "$NORMALIZED/$target/project/README.md"
    if [[ -f "$archive_dir/LICENSE" ]]; then
        cp "$archive_dir/LICENSE" "$NORMALIZED/$target/project/LICENSE"
    fi
    if [[ -f "$archive_dir/requirements.txt" ]]; then
        cp "$archive_dir/requirements.txt" "$NORMALIZED/$target/project/requirements.txt"
    fi
    cp -a "$archive_dir/$package_root/." "$NORMALIZED/$target/package/"
}

materialize_ascend() {
    local source="$1"
    local target="$2"
    cp "$source/README.md" "$NORMALIZED/$target/project/README.md"
    cp "$source/LICENSE" "$NORMALIZED/$target/project/LICENSE"
    cp -a "$source/lerobot_policy_mint/." "$NORMALIZED/$target/package/"
    if [[ -d "$source/scripts/ascend" ]]; then
        mkdir -p "$NORMALIZED/$target/project/scripts"
        cp -a "$source/scripts/ascend/." "$NORMALIZED/$target/project/scripts/"
    fi
}

materialize_git_source "$OFFICIAL_REPO" "$LEGACY_REV" lerobot_policy_mint official-legacy-4eab579
materialize_git_source "$OFFICIAL_REPO" "$MAIN_REV" policy/lerobot_policy_mint official-main-691a5e6
if [[ "$recovery_status" == recovered_in_temporary_repository ]]; then
    materialize_git_source "$temp_root/recovery.git" FETCH_HEAD lerobot_policy_mint official-declared-59fa23d
fi
materialize_ascend "$CASE_DIR/sources/ascend-v043" ascend-v043
materialize_ascend "$CASE_DIR/sources/ascend-v062" ascend-v062

# Remove host umask differences so patches retain only intentional executable bits.
find "$NORMALIZED" -type d -exec chmod 0755 {} +
find "$NORMALIZED" -type f -exec chmod 0644 {} +
find "$NORMALIZED" -type f -name '*.sh' -exec chmod 0755 {} +

make_patch() {
    local left="$1"
    local right="$2"
    local name="$3"
    (
        cd "$NORMALIZED"
        git diff --no-index --no-ext-diff --src-prefix=a/ --dst-prefix=b/ \
            -- "$left" "$right" >"$PATCHES/$name.patch" || [[ $? -eq 1 ]]
        git diff --no-index --no-ext-diff --stat -- "$left" "$right" \
            >"$PATCHES/$name.stat" || [[ $? -eq 1 ]]
    )
}

make_patch official-legacy-4eab579 ascend-v043 official-legacy-4eab579_vs_ascend-v043
make_patch ascend-v043 ascend-v062 ascend-v043_vs_ascend-v062
make_patch official-main-691a5e6 ascend-v062 official-main-691a5e6_vs_ascend-v062

recovered_readme_matches=false
recovered_package_changed_files=null
recovered_modeling_hunks=null
if [[ "$recovery_status" == recovered_in_temporary_repository ]]; then
    if cmp -s "$NORMALIZED/official-declared-59fa23d/project/README.md" \
        "$NORMALIZED/ascend-v043/project/README.md"; then
        recovered_readme_matches=true
    fi
    package_diff="$(diff -qr "$NORMALIZED/official-declared-59fa23d/package" \
        "$NORMALIZED/ascend-v043/package" || true)"
    recovered_package_changed_files="$(printf '%s\n' "$package_diff" | sed '/^$/d' | wc -l)"
    (
        cd "$NORMALIZED"
        git diff --no-index --no-ext-diff --src-prefix=a/ --dst-prefix=b/ -- \
            official-declared-59fa23d/package ascend-v043/package \
            >"$PATCHES/supplemental-official-declared-59fa23d_vs_ascend-v043-package.patch" \
            || [[ $? -eq 1 ]]
        git diff --no-index --no-ext-diff --stat -- \
            official-declared-59fa23d/package ascend-v043/package \
            >"$PATCHES/supplemental-official-declared-59fa23d_vs_ascend-v043-package.stat" \
            || [[ $? -eq 1 ]]
    )
    recovered_modeling_hunks="$(grep -c '^@@' \
        "$PATCHES/supplemental-official-declared-59fa23d_vs_ascend-v043-package.patch")"
else
    find "$PATCHES" -maxdepth 1 -type f \
        -name 'supplemental-official-declared-59fa23d_vs_ascend-v043-package.*' -delete
fi

cat >"$SCRIPT_DIR/provenance-gap.json" <<EOF
{
  "declared_revision": "$MISSING_REV",
  "temporary_fetch_attempted": true,
  "temporary_fetch_status": "$recovery_status",
  "recovered_readme_matches_snapshot": $recovered_readme_matches,
  "recovered_package_changed_files": $recovered_package_changed_files,
  "recovered_modeling_diff_hunks": $recovered_modeling_hunks,
  "supplemental_patch": "patches/supplemental-official-declared-59fa23d_vs_ascend-v043-package.patch",
  "comparison_baseline": "$LEGACY_REV",
  "baseline_role": "reconstructable_same-version-neighbor",
  "warning": "The planned comparison still uses 4eab579; do not attribute that complete diff to Ascend."
}
EOF

after_status="$(git -C "$OFFICIAL_REPO" status --porcelain=v1 | sha256sum | cut -d' ' -f1)"
if [[ "$before_status" != "$after_status" ]]; then
    echo "Official worktree status changed while comparisons were built" >&2
    exit 3
fi

echo "Rebuilt normalized sources and three patches under $SCRIPT_DIR"
