#!/bin/sh
# Sabotage the module graph on purpose, so CI can prove its own gates fail.
#
# A healthcheck that has only ever returned 200, and a boot test that has
# only ever run on code that works, are both unverified. Worse: this
# repo's boot test was RED on main and red on a deliberately broken
# branch, and comparing those two reds looked like proof that the break
# had been caught. It was not. So the break is reintroduced by CI itself,
# on every push, and the gates have to react to it.
#
# The fault is 7549098's exactly: `_inherit = 'aw.design'` inside
# aw_fenestration_core. aw.design is defined in aw_fenestration_design,
# which DEPENDS on core -- so core cannot see it, the registry raises
# "Model 'aw.design' does not exist in registry", and (this is the part
# that caused a ten-minute outage) the container still starts and
# /web/health still answers 200.
#
# Usage: scripts/ci_break_registry.sh
#
# Only ever run this against a throwaway checkout. It edits the working
# tree and does not put it back.
set -eu

target=odoo/addons/aw_fenestration_core/models/finish_migration.py
[ -f "$target" ] || {
    echo "::error::$target is gone -- ci_break_registry.sh needs updating, and" \
         "until it is, the health gate is proving nothing" >&2
    exit 1
}

# `models` must already be imported for the break to be the REGISTRY
# failure rather than a NameError at import time -- a different fault with
# a different signature, which would pass the test for the wrong reason.
grep -qE '^from odoo import .*\bmodels\b|^from odoo import models' "$target" || {
    echo "::error::$target does not import models; this script would test a" \
         "NameError, not a registry failure" >&2
    exit 1
}

cat >> "$target" <<'PY'


class AwDesignCiProbe(models.Model):
    """CI ONLY -- appended by scripts/ci_break_registry.sh, never committed.

    aw.design lives in aw_fenestration_design, which depends on this
    module and not the other way round, so this _inherit cannot resolve
    and the registry will not build.
    """
    _inherit = 'aw.design'
PY

echo "broke the registry on purpose: appended an _inherit of aw.design to $target"
