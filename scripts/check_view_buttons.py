#!/usr/bin/env python3
"""Every <button type="object"> must name a method the model really has.

The bug this exists for, and why the obvious version of this check
would have missed it:

    A stat button was added to product.template's form, inside
    //div[@name='button_box']. The method exists on product.template,
    so "does the declaring view's model have it?" says yes. But
    `product.product_normal_form_view` is mode="primary" on
    **product.product** and inherits the product.template form, so the
    button propagated into the variant form and the upgrade died with
    "action_aw_update_costs_from_rates is not a valid action on
    product.product".

So the rule is: a button must exist on the declaring view's model AND
on the model of every view that inherits, transitively, the view being
patched. Anything added to a parent lands in all of them.

Nothing else catches this. The XML is well-formed, load order is fine,
the RelaxNG schemas do not know what a method is, and form views have
no schema anyway. It fails only at Upgrade.

Needs the ../odoo-src clone to know core's methods and view graph;
skips cleanly (exit 0) without it.
"""
import ast
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADDONS = ROOT / 'odoo' / 'addons'
ODOO_SRC = ROOT.parent / 'odoo-src'

OUR_MODULES = ('aw_fenestration_core', 'aw_fenestration_design',
               'aluminum_inventory', 'hello_check')


# ----------------------------------------------------------------------
# module graph
# ----------------------------------------------------------------------
def manifest_depends(module_dir):
    manifest = module_dir / '__manifest__.py'
    if not manifest.is_file():
        return []
    match = re.search(r"'depends'\s*:\s*\[(.*?)\]",
                      manifest.read_text(encoding='utf-8'), re.S)
    return re.findall(r"'([^']+)'", match.group(1)) if match else []


def core_module_dirs():
    """Only the dependency closure, not all of odoo-src.

    Scanning every addon would be minutes; the closure is a few dozen
    modules and is the only place a model we touch can be defined.
    """
    roots = [ODOO_SRC / 'addons', ODOO_SRC / 'odoo' / 'addons']
    found, seen, queue = {}, set(), []
    for name in OUR_MODULES:
        queue.extend(manifest_depends(ADDONS / name))
    queue.append('base')
    while queue:
        name = queue.pop()
        if name in seen:
            continue
        seen.add(name)
        for root in roots:
            candidate = root / name
            if candidate.is_dir():
                found[name] = candidate
                queue.extend(manifest_depends(candidate))
                break
    return found


# ----------------------------------------------------------------------
# what each model has
# ----------------------------------------------------------------------
def scan_python(directories):
    """model -> set(method names), and model -> {field: comodel}."""
    methods = defaultdict(set)
    comodels = defaultdict(dict)
    for directory in directories:
        candidates = list(directory.glob('*.py'))
        for sub in ('models', 'wizard', 'wizards', 'report', 'reports'):
            candidates.extend((directory / sub).rglob('*.py'))
        for path in candidates:
            try:
                tree = ast.parse(path.read_text(encoding='utf-8'))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                names = set()
                for statement in node.body:
                    if not isinstance(statement, ast.Assign):
                        continue
                    for target in statement.targets:
                        if not isinstance(target, ast.Name):
                            continue
                        if target.id not in ('_name', '_inherit'):
                            continue
                        value = statement.value
                        if isinstance(value, ast.Constant) and \
                                isinstance(value.value, str):
                            names.add(value.value)
                        elif isinstance(value, (ast.List, ast.Tuple)):
                            names.update(
                                item.value for item in value.elts
                                if isinstance(item, ast.Constant)
                                and isinstance(item.value, str))
                if not names:
                    continue
                for statement in node.body:
                    if isinstance(statement, (ast.FunctionDef,
                                              ast.AsyncFunctionDef)):
                        for name in names:
                            methods[name].add(statement.name)
                    elif isinstance(statement, ast.Assign):
                        comodel = _comodel(statement)
                        if comodel:
                            field, target = comodel
                            for name in names:
                                comodels[name][field] = target
    return methods, comodels


def _comodel(statement):
    """(field name, comodel) for a relational field assignment."""
    target = statement.targets[0]
    if not isinstance(target, ast.Name):
        return None
    call = statement.value
    if not isinstance(call, ast.Call):
        return None
    func = call.func
    if not (isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == 'fields'
            and func.attr in ('Many2one', 'One2many', 'Many2many')):
        return None
    for argument in call.args:
        if isinstance(argument, ast.Constant) and \
                isinstance(argument.value, str) and '.' in argument.value:
            return target.id, argument.value
    for keyword in call.keywords:
        if keyword.arg == 'comodel_name' and \
                isinstance(keyword.value, ast.Constant):
            return target.id, keyword.value.value
    return None


# ----------------------------------------------------------------------
# the view graph
# ----------------------------------------------------------------------
def scan_views(module_dirs, module_names):
    """xmlid -> (model, inherit xmlid or None), plus our own records."""
    views, ours = {}, []
    for name, directory in zip(module_names, module_dirs):
        for path in sorted(directory.rglob('*.xml')):
            if 'static' in path.parts:
                continue
            try:
                tree = ET.parse(path)
            except ET.ParseError:
                continue
            for record in tree.getroot().iter('record'):
                if record.get('model') != 'ir.ui.view':
                    continue
                xmlid = record.get('id') or ''
                if '.' not in xmlid:
                    xmlid = '%s.%s' % (name, xmlid)
                model_node = record.find("field[@name='model']")
                model = (model_node.text or '').strip() if model_node is not None else ''
                inherit = record.find("field[@name='inherit_id']")
                parent = inherit.get('ref') if inherit is not None else None
                if parent and '.' not in parent:
                    parent = '%s.%s' % (name, parent)
                views[xmlid] = (model, parent)
                if name in OUR_MODULES:
                    arch = record.find("field[@name='arch']")
                    if arch is not None:
                        ours.append((path, xmlid, model, parent, arch))
    return views, ours


def models_reached(xmlid, views, children):
    """Every model a button added to `xmlid` can end up on."""
    seen, stack, result = set(), [xmlid], set()
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        entry = views.get(current)
        if entry and entry[0]:
            result.add(entry[0])
        stack.extend(children.get(current, ()))
    return result


# ----------------------------------------------------------------------
XPATH_FIELD = re.compile(r"field\[@name='([^']+)'\]")


def model_after_xpath(expr, model, comodels):
    """Where an xpath lands, model-wise.

    `//field[@name='order_line']/list/field[@name='name']` puts its
    children inside the order_line subview, so a button inserted there
    belongs to sale.order.line and not to sale.order. Following the
    relational hops in the expression is the only way to know that --
    and without it this check reports a false positive on every button
    inserted into an embedded list by xpath.
    """
    for field_name in XPATH_FIELD.findall(expr or ''):
        target = comodels.get(model, {}).get(field_name)
        if target:
            model = target
    return model


def walk(element, model, comodels, on_button):
    """Recurse, switching model when entering an embedded subview."""
    for child in element:
        next_model = model
        if child.tag == 'field' and len(child):
            target = comodels.get(model, {}).get(child.get('name'))
            if target:
                next_model = target
        elif child.tag == 'xpath':
            next_model = model_after_xpath(
                child.get('expr'), model, comodels)
        elif child.tag == 'button' and child.get('type') == 'object':
            on_button(child.get('name'), model)
        walk(child, next_model, comodels, on_button)


def main():
    if not ODOO_SRC.is_dir():
        print('check_view_buttons: ../odoo-src not found, skipping')
        return 0

    core = core_module_dirs()
    our_dirs = [ADDONS / name for name in OUR_MODULES
                if (ADDONS / name).is_dir()]
    our_names = [name for name in OUR_MODULES if (ADDONS / name).is_dir()]

    methods, comodels = scan_python(list(core.values()) + our_dirs)
    views, ours = scan_views(
        list(core.values()) + our_dirs, list(core.keys()) + our_names)

    children = defaultdict(list)
    for xmlid, (_model, parent) in views.items():
        if parent:
            children[parent].append(xmlid)

    problems = []
    checked = 0
    for path, xmlid, model, parent, arch in ours:
        # A button lands on the declaring view's model and on every
        # model that inherits the view being patched.
        targets = {model} if model else set()
        if parent:
            targets |= models_reached(parent, views, children)
        targets.discard('')

        def report(name, current_model, _path=path, _xmlid=xmlid,
                   _targets=targets):
            if not name:
                return
            # A button inside an embedded subview belongs to the
            # comodel, not to whatever inherits the outer view.
            scope = ({current_model} if current_model != model
                     else _targets or {current_model})
            missing = sorted(
                candidate for candidate in scope
                if candidate and name not in methods.get(candidate, ()))
            if missing:
                problems.append(
                    "%s: view '%s' has <button name=\"%s\"> but %s "
                    "%s not have that method"
                    % (_path.relative_to(ROOT), _xmlid, name,
                       ' and '.join(missing),
                       'does' if len(missing) == 1 else 'do'))

        def counted(name, current_model):
            nonlocal checked
            checked += 1
            report(name, current_model)

        walk(arch, model, comodels, counted)

    if problems:
        print('View button problems:')
        for problem in sorted(set(problems)):
            print('  %s' % problem)
        return 1

    print('%s object button(s) in our views all name a method their '
          'model has, including every view that inherits them.' % checked)
    return 0


if __name__ == '__main__':
    sys.exit(main())
