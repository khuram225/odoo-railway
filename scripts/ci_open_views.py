"""Open every view our modules own, the way the web client opens one.

Piped into `odoo shell`, which `exec`s a non-tty stdin with `env` in scope
(`odoo/cli/shell.py:80`):

    AW_CI_MODULES=mod1,mod2 odoo shell -d aw_boot --addons-path=... \
        < scripts/ci_open_views.py

**What this catches that installing does not.** An install validates each
arch as it loads it. It does not compose and post-process a view the way
a request does, and that is a different operation with its own failures:
`get_view()` resolves every field against the model, applies every
inheriting view's xpaths, and runs access-rights post-processing. The
`option_label` upgrade death and the missing `button_box` were both of
that kind. Install-time validation is also per-module, so our extension
of a CORE view is only ever composed when something asks for the core
view -- which nothing in CI did until now.

**What it does NOT catch, stated plainly so this is not mistaken for
cover it does not give:** anything that only happens in a browser.
`get_view` returns the arch; it never compiles an OWL template. So the
kanban failure this was written alongside -- `record.name.value` on a
field the arch does not declare, which throws "Cannot read properties of
undefined" at render -- would sail through here. That class is caught
statically by `check_view_fields.py`. The two are complements, not
substitutes.

Which views: every `ir.ui.view` owned by the modules named in
AW_CI_MODULES. For one of ours in `mode='extension'`, the nearest
PRIMARY ancestor is opened instead, because that is what the client
actually requests and composing it is what applies our xpaths -- so an
xpath of ours into a core form is exercised through core's own view.
`qweb` views are skipped: report templates are rendered, not opened with
`get_view`.
"""
import os
import sys

# Discovered by the workflow and passed in, never a second hardcoded list
# -- a stale list here would quietly stop covering new modules, which has
# already happened three times in this repo.
MODULES = [name for name in (os.environ.get('AW_CI_MODULES') or '').split(',')
           if name.strip()]

SKIP_TYPES = {'qweb'}

failures = []


def nearest_primary(view):
    """The view the client would actually ask for."""
    current = view
    # Terminates: the topmost view has no inherit_id and is primary.
    while current and current.mode != 'primary':
        current = current.inherit_id
    return current


def main(env):
    if not MODULES:
        print('FATAL: AW_CI_MODULES is empty, so no view would be opened '
              'and this check would pass having done nothing')
        return 1

    data = env['ir.model.data'].search([
        ('model', '=', 'ir.ui.view'),
        ('module', 'in', MODULES),
    ])
    ours = env['ir.ui.view'].browse(data.mapped('res_id')).exists()
    if not ours:
        print('FATAL: %s own no ir.ui.view records -- discovery found '
              'nothing, so nothing was opened' % (', '.join(MODULES),))
        return 1

    targets = env['ir.ui.view']
    for view in ours:
        if view.type in SKIP_TYPES:
            continue
        primary = nearest_primary(view)
        if primary:
            targets |= primary

    by_type = {}
    for view in targets:
        if view.type in SKIP_TYPES or not view.model:
            continue
        if view.model not in env:
            # A view for a model this database does not have is a problem
            # of its own, and a silent skip is how it would survive.
            failures.append('%s (%s): model %s is not in the registry'
                            % (view.xml_id or view.id, view.type, view.model))
            continue
        try:
            env[view.model].get_view(view.id, view.type)
        except Exception as exc:
            failures.append('%s (%s on %s): %s: %s' % (
                view.xml_id or view.id, view.type, view.model,
                type(exc).__name__, str(exc).replace('\n', ' ')[:400]))
        else:
            by_type[view.type] = by_type.get(view.type, 0) + 1

    opened = sum(by_type.values())
    summary = ', '.join('%s %s' % (count, name)
                        for name, count in sorted(by_type.items()))

    if failures:
        print('Views that will not open:')
        for problem in failures:
            print('  %s' % problem)
        print('::error::%s view(s) failed to open' % len(failures))
        return 1

    if not opened:
        print('FATAL: zero views opened, which is not a pass')
        return 1

    print('::notice::opened %s view(s) via get_view: %s' % (opened, summary))
    print('OK_VIEWS_OPENED %s' % opened)
    return 0


# `env` is injected by odoo shell; referenced via globals() so a linter
# reading this file standalone does not call it undefined.
sys.exit(main(globals()['env']))
