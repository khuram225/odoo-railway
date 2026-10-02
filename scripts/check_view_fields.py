#!/usr/bin/env python3
"""Every `<field name="x">` in a view must name a field the model has.

The failure this exists for: phase 7d removed `option_label` and
`max_span_mm` from `aw.profile.section.line`, and
`profile_section_views.xml` still listed both. Nothing in the suite
looked, the deploy went out green, and the CORE UPGRADE DIED with

    ParseError ... Field `option_label` does not exist

which is the worst place to find out -- mid-upgrade, on the client's
instance, with the module half-loaded.

Every other check here looks at ONE side. `check_view_schemas.py`
validates the arch's shape against Odoo's RelaxNG, which does not know
what a model has. `check_view_buttons.py` resolves button METHODS. This
is the field equivalent, and it closes the last gap in "could this view
load at all".

**How the model is resolved**, which is the part that makes it useful
rather than noisy:

- The view's own `model` names the base.
- A `<field name="x">` that CONTAINS a sub-view (`<list>`, `<form>`,
  `<kanban>`) switches the model to x's comodel for everything inside
  it, which is how an embedded order-line list or a spec's profile lines
  are checked against the right model rather than the parent.
- Fields come from the Python of our modules AND of core's dependency
  closure, via the same scanner `check_view_buttons.py` uses, so
  `product.template`'s own fields are known as well as ours.
- An INHERITED view is skipped: its model is whatever the parent view's
  xpath lands in, and resolving that needs the composition machinery in
  `check_inherited_xpaths.py`. The view that broke the upgrade was a
  standalone one, which is the common case.

Needs `../odoo-src` to know what core provides; skips cleanly without
it, because a run that cannot see core's fields would flag half of
every product view.
"""
import ast
import importlib.util
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADDONS = ROOT / 'odoo' / 'addons'
ODOO_SRC = ROOT.parent / 'odoo-src'

# Tags that open a sub-view, so a <field> holding one switches model.
SUBVIEW_TAGS = {'list', 'tree', 'form', 'kanban', 'calendar', 'graph',
                'pivot', 'search', 'gantt', 'activity', 'hierarchy'}

# Not fields: a <field> inside one of these is a RECORD's column, not a
# view's. `arch` itself is the obvious one.
RECORD_LEVEL = {'record', 'function', 'value'}

# `record.<name>` inside a kanban QWeb expression -- t-att-*, t-esc,
# t-out, t-if, or element text.
RECORD_REF = re.compile(r'\brecord\.([A-Za-z_]\w*)')

# Present on every kanban record whether or not the arch declares it.
ALWAYS_ON_RECORD = {'id'}


def our_modules():
    """Every module in this repo, found rather than listed, at any depth."""
    if not ADDONS.is_dir():
        return ()
    return tuple(sorted(
        manifest.parent.relative_to(ADDONS).as_posix()
        for manifest in ADDONS.rglob('__manifest__.py')))


def load_buttons_helpers():
    """Reuse check_view_buttons.py's scanner rather than copying it."""
    spec = importlib.util.spec_from_file_location(
        'check_view_buttons', Path(__file__).with_name('check_view_buttons.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def inheritance_map(directories):
    """model -> the models it inherits from.

    `scan_python` keys fields by every name a class declares, so a mixin's
    OWN fields land under the mixin's name and not under the models that
    inherit it. Without this, `aw.mesh.type.line` looked as though it had
    none of `aw.type.line.mixin`'s fields and every one of them was
    reported -- twelve false alarms on the first run, which is how a
    check gets switched off.
    """
    parents = {}
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in directory.rglob('*.py'):
            if '__pycache__' in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding='utf-8'))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                name, inherits = None, []
                for statement in node.body:
                    if not isinstance(statement, ast.Assign):
                        continue
                    for target in statement.targets:
                        if not isinstance(target, ast.Name):
                            continue
                        value = statement.value
                        if (isinstance(value, ast.Constant)
                                and isinstance(value.value, str)):
                            values = [value.value]
                        elif isinstance(value, (ast.List, ast.Tuple)):
                            values = [
                                item.value for item in value.elts
                                if isinstance(item, ast.Constant)
                                and isinstance(item.value, str)]
                        else:
                            continue
                        if target.id == '_name':
                            name = values[0]
                        elif target.id == '_inherit':
                            inherits = values
                if name and inherits:
                    parents.setdefault(name, set()).update(inherits)
    return parents


def resolve_fields(model, fieldnames, parents, seen=None):
    """A model's own fields plus every ancestor's."""
    seen = seen or set()
    if model in seen:
        return set()
    seen = seen | {model}
    known = set(fieldnames.get(model, ()))
    for parent in parents.get(model, ()):
        known |= resolve_fields(parent, fieldnames, parents, seen)
    return known


def manifest_views(module):
    """The XML files the manifest loads, in order."""
    manifest = ADDONS / module / '__manifest__.py'
    if not manifest.is_file():
        return []
    try:
        values = eval(  # noqa: S307 - our own manifest
            manifest.read_text(encoding='utf-8'), {'__builtins__': {}}, {})
    except Exception:
        return []
    return [ADDONS / module / f for f in values.get('data', [])
            if f.endswith('.xml')]


def walk(node, model, known_for, comodels, problems, path, lineno_of):
    """Check every <field> under `node`, switching model into sub-views."""
    checked = 0
    for child in node:
        if not isinstance(child.tag, str):
            continue
        if child.tag != 'field':
            checked += walk(child, model, known_for, comodels, problems,
                            path, lineno_of)
            continue

        name = child.get('name')
        if not name:
            continue
        known = known_for(model)
        checked += 1
        # A model we have no Python for at all is unknown rather than
        # wrong -- flagging every field of it would be noise.
        if known and name not in known:
            problems.append(
                '%s:%s: <field name="%s"> is not a field of %s'
                % (path.relative_to(ROOT), lineno_of(child), name, model))

        # Does this field open a sub-view? Then everything inside it
        # belongs to its comodel.
        inner = [c for c in child if isinstance(c.tag, str)
                 and c.tag in SUBVIEW_TAGS]
        next_model = comodels.get(model, {}).get(name) or model
        for sub in inner:
            checked += walk(sub, next_model, known_for, comodels, problems,
                            path, lineno_of)
    return checked


def kanban_scopes(node, model, comodels):
    """Yield (kanban element, the model its `record` refers to).

    A kanban reached through a `<field>` holding a sub-view belongs to
    that field's comodel, not the view's own, so the model is carried
    down the same way `walk` carries it.
    """
    for child in node:
        if not isinstance(child.tag, str):
            continue
        if child.tag == 'kanban':
            yield child, model
            yield from kanban_scopes(child, model, comodels)
        elif child.tag == 'field':
            next_model = comodels.get(model, {}).get(child.get('name')) or model
            yield from kanban_scopes(child, next_model, comodels)
        else:
            yield from kanban_scopes(child, model, comodels)


def declared_fields(node):
    """Field names this kanban declares, anywhere in its own arch.

    Both placements count, because Odoo collects its fieldNodes from the
    whole arch: the `<field>` list above `<templates>` and a `<field>`
    used inside the card itself. Descent stops at a `<field>` that opens
    a sub-view, whose contents describe another model.
    """
    names = set()
    for child in node:
        if not isinstance(child.tag, str):
            continue
        if child.tag == 'field':
            name = child.get('name')
            if name:
                names.add(name)
            if any(c.tag in SUBVIEW_TAGS for c in child
                   if isinstance(c.tag, str)):
                continue
            names |= declared_fields(child)
        elif child.tag in SUBVIEW_TAGS:
            continue
        else:
            names |= declared_fields(child)
    return names


def record_refs(node):
    """Every `record.<name>` in this kanban's expressions and text."""
    names = []
    for element in node.iter():
        if not isinstance(element.tag, str):
            continue
        for value in list(element.attrib.values()) + [element.text]:
            if value:
                names.extend(RECORD_REF.findall(value))
    return names


def check_kanbans(arch, model, known_for, comodels, problems, path, ref_lineno):
    """`record.x.value` in a kanban must be declared AND be a real field.

    Two separate rules, and the FIRST is the one that bites. A kanban
    populates `record` only from the arch's own fieldNodes, so reading an
    undeclared field yields `undefined` rather than an empty value, and
    the card dies on open with

        TypeError: Cannot read properties of undefined (reading 'value')

    Phase 7e added `t-att-title="record.name.value"` to the Window
    Systems card without adding `<field name="name"/>`, and every kanban
    check here was blind to it: the XML is well formed, RelaxNG ships no
    kanban schema, `check_kanban_fields.py` only looks for QWeb
    directives sitting on a `<field>`, and this check only read
    `<field name=...>`. Nothing looked at the expressions.

    The second rule catches the same thing as the rest of this script --
    a field that was renamed or removed -- reached through a template
    expression instead of a `<field>` tag.
    """
    checked = 0
    for kanban, kanban_model in kanban_scopes(arch, model, comodels):
        declared = declared_fields(kanban)
        known = known_for(kanban_model)
        for name in sorted(set(record_refs(kanban))):
            if name in ALWAYS_ON_RECORD:
                continue
            checked += 1
            if name not in declared:
                problems.append(
                    '%s:%s: the kanban template reads record.%s but the arch '
                    'does not declare <field name="%s"/>, so `record.%s` is '
                    'undefined and the card dies on open with "Cannot read '
                    'properties of undefined"'
                    % (path.relative_to(ROOT), ref_lineno(name), name, name,
                       name))
            elif known and name not in known:
                problems.append(
                    '%s:%s: the kanban template reads record.%s, which is not '
                    'a field of %s'
                    % (path.relative_to(ROOT), ref_lineno(name), name,
                       kanban_model))
    return checked


def main():
    if not ODOO_SRC.is_dir():
        print('check_view_fields: ../odoo-src not found, skipping')
        return 0

    helpers = load_buttons_helpers()
    core = helpers.core_module_dirs()
    ours = [ADDONS / name for name in our_modules()]
    directories = list(core.values()) + ours
    _methods, comodels, fieldnames = helpers.scan_python(directories)
    parents = inheritance_map(directories)
    cache = {}

    def known_for(model):
        if model not in cache:
            cache[model] = resolve_fields(model, fieldnames, parents)
        return cache[model]

    problems = []
    checked = views = refs = 0

    for module in our_modules():
        for path in manifest_views(module):
            if not path.is_file():
                continue
            try:
                tree = ET.parse(str(path))
            except ET.ParseError as exc:
                # REPORTED, never skipped. The first version of this
                # check did `continue` here on the grounds that
                # check_xml_comments.py owns malformed XML -- and then a
                # double hyphen in a comment made this very file
                # unparseable, so it was given ZERO field checking and
                # the run still printed "all exist". A check that passes
                # for a file it could not open is the failure it was
                # written to prevent.
                problems.append(
                    '%s: will not parse, so NOTHING in it was checked: %s'
                    % (path.relative_to(ROOT), exc))
                continue
            # ET gives no line numbers; find them by searching the text
            # for the field's own spelling. Approximate on purpose -- it
            # is a pointer for a human, and the field name in the message
            # is what identifies it.
            text = path.read_text(encoding='utf-8').split('\n')

            def lineno_of(element, _text=text):
                needle = 'name="%s"' % (element.get('name') or '')
                for index, line in enumerate(_text, start=1):
                    if needle in line:
                        return index
                return 0

            def ref_lineno(name, _text=text):
                needle = 'record.%s' % name
                for index, line in enumerate(_text, start=1):
                    if needle in line:
                        return index
                return 0

            for record in tree.getroot().iter('record'):
                if record.get('model') != 'ir.ui.view':
                    continue
                if record.find("field[@name='inherit_id']") is not None:
                    continue    # see the module docstring
                model_field = record.find("field[@name='model']")
                arch = record.find("field[@name='arch']")
                if model_field is None or arch is None:
                    continue
                model = (model_field.text or '').strip()
                if not model:
                    continue
                views += 1
                checked += walk(arch, model, known_for, comodels, problems,
                                path, lineno_of)
                refs += check_kanbans(arch, model, known_for, comodels,
                                      problems, path, ref_lineno)

    if problems:
        print('Views naming fields their model does not have:')
        for problem in sorted(set(problems)):
            print('  %s' % problem)
        return 1

    print('%s field reference(s) in %s standalone view arch(es) all exist '
          'on their model; %s kanban record.<field> reference(s) are both '
          'declared and real.' % (checked, views, refs))
    return 0


if __name__ == '__main__':
    sys.exit(main())
