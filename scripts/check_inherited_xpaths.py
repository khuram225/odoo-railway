#!/usr/bin/env python3
"""Every inherited view's xpath must resolve against its parent arch.

The failure this exists for took a whole module's upgrade down. Phase 7d
rebuilt `view_aw_window_series_form` in core and, in rewriting it,
dropped the `<div name="button_box">`. The design module xpaths its
Layout Presets stat button into that div -- it has to, since it owns
`aw.layout.preset` and core cannot reference it -- so the Upgrade died
with:

    Element '<xpath expr="//div[@name='button_box']">' cannot be
    located in parent view

Nothing else could see it. Both files are well-formed XML, both validate
against Odoo's RelaxNG, load order is fine, and the two views are in
DIFFERENT MODULES: the one that broke was not even edited. The mismatch
exists only between a parent and a child, which is the shape of gap that
needs a script rather than vigilance.

For each of our inherited views the parent arch is COMPOSED the way the
server composes it -- the root primary view, then every inheriting view
along the chain, then every one of OUR views that extends it, in
manifest load order -- and each locator is evaluated with lxml. A parent
from core Odoo is read out of `../odoo-src`.

**Two things it does not pretend to do.** It does not implement Odoo's
inheritance engine: `position="attributes"` is ignored and `replace` /
`move` are applied only far enough to keep the tree honest for a later
xpath. And for a CORE parent it applies only that view's own chain, not
every other core module that might extend it -- so a locator aimed at
something a third module adds cannot be verified. Those are reported as
NOT CHECKED rather than as failures: a check that cries wolf is a check
somebody switches off, and the one real bug it exists for is in our own
views, where the arch is fully known.
"""
import copy
import sys
from pathlib import Path

try:
    from lxml import etree
except ImportError:
    print('check_inherited_xpaths: lxml not installed, skipping')
    sys.exit(0)

ROOT = Path(__file__).resolve().parent.parent
ADDONS = ROOT / 'odoo' / 'addons'
ODOO_SRC = ROOT.parent / 'odoo-src'
OUR_MODULES = ('aw_fenestration_core', 'aw_fenestration_design',
               'aluminum_inventory', 'hello_check')


# ---------------------------------------------------------------------
# reading views
# ---------------------------------------------------------------------
def manifest_data_files(module):
    manifest = ADDONS / module / '__manifest__.py'
    if not manifest.is_file():
        return []
    try:
        values = eval(  # noqa: S307 - our own manifest
            manifest.read_text(encoding='utf-8'), {'__builtins__': {}}, {})
    except Exception:
        return []
    return [f for f in values.get('data', []) if f.endswith('.xml')]


def read_views(path, module):
    """Every ir.ui.view in one file, in document order."""
    out = []
    try:
        tree = etree.parse(str(path))
    except etree.XMLSyntaxError:
        return out
    for record in tree.getroot().iter('record'):
        if record.get('model') != 'ir.ui.view':
            continue
        rid = record.get('id') or ''
        if '.' not in rid:
            rid = '%s.%s' % (module, rid)
        arch = record.find("field[@name='arch']")
        inherit = record.find("field[@name='inherit_id']")
        out.append({
            'xmlid': rid,
            'path': path,
            'nodes': top_nodes(arch),
            'inherit': (inherit.get('ref') or '')
                       if inherit is not None else '',
        })
    return out


def top_nodes(arch):
    """The top-level elements inside <field name="arch">.

    A LIST, not one element: an inheriting arch legitimately carries
    several xpath/field edits side by side, and taking only the first
    silently stopped checking the rest -- which is how this script's
    own first version reported two false alarms.
    """
    if arch is None:
        return []
    return [copy.deepcopy(c) for c in arch if isinstance(c.tag, str)]


def collect_ours():
    views = []
    for module in OUR_MODULES:
        for relative in manifest_data_files(module):
            path = ADDONS / module / relative
            if path.is_file():
                views.extend(read_views(path, module))
    return views


_CORE_CACHE = {}


def core_view(xmlid):
    """A core Odoo view, by xmlid, out of the odoo-src clone."""
    if xmlid in _CORE_CACHE:
        return _CORE_CACHE[xmlid]
    found = None
    if ODOO_SRC.is_dir() and '.' in xmlid:
        module, name = xmlid.split('.', 1)
        for base in (ODOO_SRC / 'addons' / module,
                     ODOO_SRC / 'odoo' / 'addons' / module):
            if not base.is_dir():
                continue
            for path in sorted(base.rglob('*.xml')):
                try:
                    tree = etree.parse(str(path))
                except etree.XMLSyntaxError:
                    continue
                for record in tree.getroot().iter('record'):
                    if (record.get('model') == 'ir.ui.view'
                            and record.get('id') == name):
                        arch = record.find("field[@name='arch']")
                        inherit = record.find("field[@name='inherit_id']")
                        found = {
                            'xmlid': xmlid,
                            'path': path,
                            'nodes': top_nodes(arch),
                            'inherit': (inherit.get('ref') or '')
                                       if inherit is not None else '',
                        }
                        break
                if found:
                    break
            if found:
                break
    _CORE_CACHE[xmlid] = found
    return found


# ---------------------------------------------------------------------
# composing an arch
# ---------------------------------------------------------------------
def wrap(nodes):
    """One root holding `nodes`, so `//x` can be evaluated over them."""
    root = etree.Element('aw-arch')
    for node in nodes:
        root.append(copy.deepcopy(node))
    return root


def locators(nodes):
    """Every locator in an inheriting arch, as (expr, lineno).

    `<xpath expr="...">` gives its expr. A bare `<field name="x"
    position="after">` is what apply_inheritance_specs resolves by tag
    plus attributes, so it becomes the equivalent expression and is
    checked the same way.
    """
    found = []
    for node in nodes:
        if node.tag == 'data':
            found.extend(locators(list(node)))
            continue
        if node.tag == 'xpath':
            expr = node.get('expr')
            if expr:
                found.append((expr, node.sourceline))
            continue
        if not node.get('position'):
            continue
        tests = ''.join(
            "[@%s='%s']" % (key, value)
            for key, value in sorted(node.attrib.items())
            if key != 'position')
        found.append(('//%s%s' % (node.tag, tests), node.sourceline))
    return found


def apply_spec(parent, nodes):
    """Apply an inheriting arch to `parent`, structurally.

    Enough to keep the tree honest for a LATER view's locator: what
    matters is which elements exist afterwards.
    """
    for node in nodes:
        if node.tag == 'data':
            apply_spec(parent, list(node))
            continue
        position = node.get('position') or 'inside'
        if node.tag == 'xpath':
            expr = node.get('expr')
            if not expr:
                continue
        else:
            if not node.get('position'):
                continue
            tests = ''.join(
                "[@%s='%s']" % (k, v)
                for k, v in sorted(node.attrib.items()) if k != 'position')
            expr = '//%s%s' % (node.tag, tests)
        try:
            targets = parent.xpath(expr)
        except etree.XPathEvalError:
            continue
        if not targets:
            continue
        target = targets[0]
        payload = [c for c in node if isinstance(c.tag, str)]
        if position == 'inside':
            for child in payload:
                target.append(copy.deepcopy(child))
        elif position == 'after':
            anchor = target
            for child in payload:
                copied = copy.deepcopy(child)
                anchor.addnext(copied)
                anchor = copied
        elif position == 'before':
            for child in payload:
                target.addprevious(copy.deepcopy(child))
        elif position == 'replace':
            for child in payload:
                target.addprevious(copy.deepcopy(child))
            holder = target.getparent()
            if holder is not None:
                holder.remove(target)
        # 'attributes' changes no structure.


def compose(xmlid, ours_by_id, extenders, seen=None):
    """The arch of `xmlid` as the server would build it.

    Walks UP the inherit chain to the root primary, applies each view
    along the way, then applies every one of OUR views that extends it
    in load order. Returns (root, origin) or (None, reason).
    """
    seen = seen or set()
    if xmlid in seen:
        return None, 'inherit cycle'
    seen = seen | {xmlid}

    view = ours_by_id.get(xmlid)
    origin = 'ours'
    if view is None:
        view = core_view(xmlid)
        origin = 'core'
    if view is None:
        return None, 'parent %s not found' % xmlid
    if not view['nodes']:
        return None, 'parent %s has no arch' % xmlid

    if view['inherit']:
        base, reason = compose(view['inherit'], ours_by_id, extenders, seen)
        if base is None:
            return None, reason
        apply_spec(base, view['nodes'])
        root = base
    else:
        root = wrap(view['nodes'])

    # Our own extensions of it, in load order. A core view extended by
    # another CORE module is the gap this cannot see -- see the module
    # docstring.
    for extender in extenders.get(xmlid, []):
        apply_spec(root, extender['nodes'])
    return root, origin


# ---------------------------------------------------------------------
def main():
    ours = collect_ours()
    ours_by_id = {view['xmlid']: view for view in ours}

    problems, skipped = [], []
    checked = 0

    for view in ours:
        parent_id = view['inherit']
        if not parent_id or not view['nodes']:
            continue

        # Everything of ours that extends the same parent and loads
        # BEFORE this one, so a locator aimed at what a sibling added
        # resolves.
        earlier = {}
        for other in ours:
            if other is view:
                break
            if other['inherit']:
                earlier.setdefault(other['inherit'], []).append(other)

        parent, origin = compose(parent_id, ours_by_id, earlier)
        if parent is None:
            skipped.append('%s: %s' % (view['xmlid'], origin))
            continue

        for expr, lineno in locators(view['nodes']):
            checked += 1
            try:
                matches = parent.xpath(expr)
            except etree.XPathEvalError as exc:
                problems.append(
                    '%s:%s: %s is not valid XPath (%s)'
                    % (view['path'].relative_to(ROOT), lineno, expr, exc))
                continue
            if matches:
                continue
            if origin == 'core':
                # Another core module may add the target; we only know
                # this view's own chain. Reported, never failed.
                skipped.append(
                    '%s:%s: %s not found in %s -- core parent, so it may '
                    'come from a module this cannot see'
                    % (view['path'].relative_to(ROOT), lineno, expr,
                       parent_id))
                continue
            problems.append(
                '%s:%s: %s matches nothing in %s -- the Upgrade fails '
                'with "cannot be located in parent view"'
                % (view['path'].relative_to(ROOT), lineno, expr, parent_id))

    if problems:
        print('Inherited views whose xpath does not resolve:')
        for problem in problems:
            print('  %s' % problem)
        return 1

    print('%s inherited xpath(s) resolve against their parent arch.'
          % checked)
    for note in skipped:
        print('  not checked: %s' % note)
    return 0


if __name__ == '__main__':
    sys.exit(main())
