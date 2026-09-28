#!/usr/bin/env python3
"""Every `self._method(...)` must exist, and every `self.x = ...` must
be a field.

Two failures that pyflakes cannot see, because both are valid Python
whatever `self` turns out to be, and both only surface when the line
runs.

pyflakes cannot see this: `self._starting_system()` is valid Python
whatever `self` turns out to be, so an undefined method is only found
when the line runs. In Odoo that usually means a user clicking a button
and getting an AttributeError.

That is not hypothetical. A patch added calls to `_starting_system()`
in the Add Position wizard and was supposed to add the method in the
same pass, but its anchor named a method that did not exist
(`action_create` instead of `action_confirm`), so the definition was
silently never inserted. The calls shipped. Confirming the wizard with
"use as default" ticked raised
"'aw.design.position.wizard' object has no attribute
'_starting_system'".

The second: **Odoo 19 records use `__slots__`**, so a record cannot
carry ad-hoc attributes -- only fields. `self._aw_spans = {}` in the
explosion engine raised
"'aw.design' object has no attribute '_aw_spans'" on the very first
save of any design.

Resolution follows `_name`/`_inherit` across OUR modules, and allows
anything defined on the same model by core or on BaseModel -- calling
`self._compute_field()` or writing a core field is not our business to
police.

Needs ../odoo-src to know what core provides; skips cleanly without it.
"""
import ast
import importlib.util
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADDONS = ROOT / 'odoo' / 'addons'
ODOO_SRC = ROOT.parent / 'odoo-src'
OUR_MODULES = ('aw_fenestration_core', 'aw_fenestration_design',
               'aluminum_inventory', 'hello_check')

# Assignable on a record without being a field of it. Deliberately
# tiny: the point of the check is that almost nothing qualifies.
ALLOWED_ATTRIBUTES = {'env'}


def load_buttons_helpers():
    """Reuse the model scanner from check_view_buttons.py.

    Same dependency-closure walk and the same AST model map; keeping a
    second copy of that would be one more thing to drift.
    """
    spec = importlib.util.spec_from_file_location(
        'check_view_buttons', Path(__file__).with_name('check_view_buttons.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def base_model_methods():
    """Everything BaseModel and the ORM provide, allowed everywhere."""
    names = set()
    for relative in ('odoo/orm', 'odoo/tools'):
        directory = ODOO_SRC / relative
        if not directory.is_dir():
            continue
        for path in directory.rglob('*.py'):
            try:
                tree = ast.parse(path.read_text(encoding='utf-8'))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names.add(node.name)
    return names


def class_models(node):
    """The model names a ClassDef declares via _name / _inherit."""
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
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                names.add(value.value)
            elif isinstance(value, (ast.List, ast.Tuple)):
                names.update(
                    item.value for item in value.elts
                    if isinstance(item, ast.Constant)
                    and isinstance(item.value, str))
    return names


def self_assignments(node):
    """(attribute, line) for every `self.x = ...` inside this class."""
    found = []
    for child in ast.walk(node):
        targets = []
        if isinstance(child, ast.Assign):
            targets = child.targets
        elif isinstance(child, (ast.AugAssign, ast.AnnAssign)):
            targets = [child.target]
        for target in targets:
            for item in (target.elts
                         if isinstance(target, (ast.Tuple, ast.List))
                         else [target]):
                if (isinstance(item, ast.Attribute)
                        and isinstance(item.value, ast.Name)
                        and item.value.id == 'self'):
                    found.append((item.attr,
                                  getattr(child, 'lineno', 0)))
    return found


def self_calls(node):
    """(method name, line) for every self._x(...) inside this class."""
    found = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if not isinstance(func, ast.Attribute):
            continue
        if not (isinstance(func.value, ast.Name) and func.value.id == 'self'):
            continue
        if not func.attr.startswith('_'):
            continue
        found.append((func.attr, getattr(child, 'lineno', 0)))
    return found


def main():
    if not ODOO_SRC.is_dir():
        print('check_self_methods: ../odoo-src not found, skipping')
        return 0

    helpers = load_buttons_helpers()
    core = helpers.core_module_dirs()
    our_dirs = [ADDONS / name for name in OUR_MODULES
                if (ADDONS / name).is_dir()]
    methods, _comodels, fieldnames = helpers.scan_python(
        list(core.values()) + our_dirs)
    allowed_everywhere = base_model_methods()

    problems = []
    checked = 0
    for directory in our_dirs:
        candidates = list(directory.glob('*.py'))
        for sub in ('models', 'wizard', 'wizards', 'report', 'reports'):
            candidates.extend((directory / sub).rglob('*.py'))
        for path in sorted(candidates):
            try:
                tree = ast.parse(path.read_text(encoding='utf-8'))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                models = class_models(node)
                if not models:
                    continue
                # Anything defined on ANY of this class's models, by us
                # or by core, plus what every model inherits.
                available = set(allowed_everywhere)
                for model in models:
                    available |= methods.get(model, set())
                # Methods defined on the class itself but on no model
                # name (rare, e.g. a plain helper) still count.
                available |= {
                    statement.name for statement in node.body
                    if isinstance(statement, (ast.FunctionDef,
                                              ast.AsyncFunctionDef))}

                for name, line in self_calls(node):
                    checked += 1
                    if name in available:
                        continue
                    problems.append(
                        '%s:%s: self.%s() is not defined on %s'
                        % (path.relative_to(ROOT), line, name,
                           ' / '.join(sorted(models))))

                writable = set()
                for model in models:
                    writable |= fieldnames.get(model, set())
                for name, line in self_assignments(node):
                    checked += 1
                    if name in writable or name in ALLOWED_ATTRIBUTES:
                        continue
                    problems.append(
                        '%s:%s: self.%s = ... is not a field of %s '
                        '(records use __slots__, so this raises at '
                        'runtime)'
                        % (path.relative_to(ROOT), line, name,
                           ' / '.join(sorted(models))))

    if problems:
        print('Missing methods (these raise AttributeError at runtime):')
        for problem in sorted(set(problems)):
            print('  %s' % problem)
        return 1

    print('%s self._method() call(s) and self.x assignment(s) are '
          'sound.' % checked)
    return 0


if __name__ == '__main__':
    sys.exit(main())
