#!/bin/sh
# Run every check in scripts/ and fail on anything that is not a clean pass.
#
# Usage:
#   scripts/check_all.sh            local: a SKIP is a warning
#   scripts/check_all.sh --strict   CI: a SKIP is a FAILURE
#
# Three outcomes per check, not two, and that distinction is the whole
# point of this script:
#
#   PASS  exit 0, and it did not say it was skipping anything
#   FAIL  non-zero exit
#   SKIP  exit 0 but it could not read what it needed -- no ../odoo-src,
#         no lxml, no pyflakes, no vendor zip, AW_SKIP_SLOW_CHECKS set
#
# A SKIP is exit 0 today, which is right for a laptop without the Odoo
# source clone and WRONG for a gate. Three times in one session a check
# reported green over code it never opened -- twice from a hardcoded
# module list, once from a file it could not parse. --strict is how that
# class stops being able to hide: in CI, "I could not look" fails.
#
# The checks are DISCOVERED, not listed. A list here would be a fourth
# place to forget a new check, and this script exists to be the one place
# that cannot forget. A discovered check that needs arguments and is not
# in ARGS below fails loudly rather than being skipped.
set -u

cd "$(dirname "$0")/.." || exit 1

STRICT=0
[ "${1:-}" = "--strict" ] && STRICT=1

# Checks that need arguments. The key is the basename; the value is
# evaluated by the shell, so it may be a command substitution.
# check_xml_comments takes the files to read; everything else finds its
# own input.
args_for() {
    case "$1" in
        check_xml_comments.py)
            # Every XML in the repo, tracked or not: an untracked view is
            # still a view that will be deployed. `git ls-files` alone
            # would miss one somebody has not added yet.
            find odoo -name '*.xml' -not -path '*/node_modules/*' 2>/dev/null
            ;;
        *) : ;;
    esac
}

# A check whose SKIP is accepted even under --strict, with the reason.
# Deliberately tiny, and each entry is a thing CI genuinely cannot have
# rather than a thing nobody got round to.
#
#   check_catalogue_import  the Chawla vendor zip is gitignored, so it
#                           can never exist on a CI runner. It is the
#                           only one.
strict_exempt() {
    case "$1" in
        check_catalogue_import.py) return 0 ;;
        *) return 1 ;;
    esac
}

passed=0
failed=0
skipped=0
exempt=0
fail_names=""
skip_names=""

run_check() {
    script=$1
    name=$(basename "$script")
    case "$name" in
        *.mjs) runner=node ;;
        *) runner=python ;;
    esac

    # shellcheck disable=SC2046
    output=$($runner "$script" $(args_for "$name") 2>&1)
    status=$?

    if [ "$status" -ne 0 ]; then
        failed=$((failed + 1))
        fail_names="$fail_names $name"
        printf 'FAIL  %s\n' "$name"
        printf '%s\n' "$output" | sed 's/^/      /'
        return
    fi

    # Exit 0, but did it actually look? Every skip in this repo says so
    # on stdout, in one of these shapes.
    if printf '%s' "$output" | grep -qiE 'skipping|AW_SKIP_SLOW_CHECKS'; then
        if [ "$STRICT" -eq 1 ] && ! strict_exempt "$name"; then
            failed=$((failed + 1))
            fail_names="$fail_names $name(skipped)"
            printf 'FAIL  %s -- skipped, and --strict does not allow it\n' "$name"
            printf '%s\n' "$output" | sed 's/^/      /'
            return
        fi
        if strict_exempt "$name"; then
            exempt=$((exempt + 1))
            printf 'SKIP* %s (exempt under --strict)\n' "$name"
        else
            skipped=$((skipped + 1))
            skip_names="$skip_names $name"
            printf 'SKIP  %s\n' "$name"
        fi
        printf '%s\n' "$output" | sed 's/^/      /'
        return
    fi

    passed=$((passed + 1))
    printf 'ok    %s\n' "$name"
}

# ---------------------------------------------------------------------
# Discover. Sorted, so the order is stable and a diff of two runs is
# readable. rebuild_melt_and_import.py is a TOOL, not a check, and is the
# only script here that is not named check_*.
# ---------------------------------------------------------------------
found=$(ls scripts/check_*.py scripts/check_*.mjs 2>/dev/null | sort)
if [ -z "$found" ]; then
    echo "FATAL: no checks found in scripts/ -- this script is looking in the wrong place." >&2
    exit 1
fi

echo "Running every check in scripts/ ($(echo "$found" | wc -l | tr -d ' ') found)"
[ "$STRICT" -eq 1 ] && echo "--strict: a check that cannot read its input FAILS"
echo

for script in $found; do
    run_check "$script"
done

echo
echo "----------------------------------------------------------------"
printf '%s passed, %s failed, %s skipped' "$passed" "$failed" "$skipped"
[ "$exempt" -gt 0 ] && printf ', %s exempt' "$exempt"
echo
[ -n "$fail_names" ] && echo "failed:$fail_names"
[ -n "$skip_names" ] && echo "skipped:$skip_names"

if [ "$failed" -gt 0 ]; then
    echo
    echo "NOT SAFE TO DEPLOY."
    exit 1
fi

if [ "$skipped" -gt 0 ]; then
    echo
    echo "Passed, but $skipped check(s) could not read their input, so the"
    echo "suite is narrower than it looks. Run with --strict before a"
    echo "deploy, or install what they are missing:"
    echo "  ../odoo-src   git clone --depth 1 --branch 19.0 \\"
    echo "                  https://github.com/odoo/odoo.git ../odoo-src"
    echo "  python        pip install pyflakes lxml pulp==2.9.0"
fi
exit 0
