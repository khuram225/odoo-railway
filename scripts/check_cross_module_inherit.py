#!/usr/bin/env python3
"""A module may only extend a model it can actually see.

`_inherit = 'aw.design'` inside `aw_fenestration_core` fails at registry
load with

    TypeError: Model 'aw.design' does not exist in registry.

because `aw.design` is defined in `aw_fenestration_design`, which depends
on core rather than the other way round. Phase 7e put a migration there
and **broke the live deploy**: the container still starts and still
answers the health check, so Railway reported SUCCESS while every actual
request returned 500. A deploy that is green and entirely broken is the
worst failure mode in this repo's history, and nothing was watching for
it.

`check_tenancy.py` was close but looks at the wrong thing -- it reads
manifest `depends` for cross-tenant dependencies. This reads the `_inherit`
in the PYTHON and asks whether the declaring module could possibly see
that model: it must be defined in the module itself, or in one of its
transitive dependencies, or by core Odoo.

Needs `../odoo-src` to know which models core Odoo defines; without it,
only OUR models can be judged and core model names are assumed fine
(which is the safe direction -- a false pass on `product.template`, never
a false alarm).
"""
import ast
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADDONS = ROOT / 'odoo' / 'addons'
ODOO_SRC = ROOT.parent / 'odoo-src'


def our_modules():
    """module path (relative to addons) -> absolute path, at any depth."""
    if not ADDONS.is_dir():
        return {}
    return {
        manifest.parent.relative_to(ADDONS).as_posix(): manifest.parent
        for manifest in ADDONS.rglob('__manifest__.py')
    }


def manifest_depends(path):
    try:
        values = eval(  # noqa: S307 - our own manifest
            (path / '__manifest__.py').read_text(encoding='utf-8'),
            {'__builtins__': {}}, {})
    except Exception:
        return []
    return list(values.get('depends') or [])


def declared_models(path):
    """(models defined with _name, models extended with _inherit) in a tree."""
    defined, extended = set(), []
    for py in sorted(path.rglob('*.py')):
        if '__pycache__' in py.parts:
            continue
        try:
            tree = ast.parse(py.read_text(encoding='utf-8'))
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
            if name:
                defined.add(name)
            for parent in inherits:
                # A class with BOTH is defining a new model that borrows
                # from another; without _name it is extending in place.
                extended.append((parent, py, node.lineno))
    return defined, extended


def core_models():
    """Every model name core Odoo defines, by module."""
    by_module = {}
    if not ODOO_SRC.is_dir():
        return by_module
    for base in (ODOO_SRC / 'addons', ODOO_SRC / 'odoo' / 'addons'):
        if not base.is_dir():
            continue
        for manifest in base.glob('*/__manifest__.py'):
            defined, _extended = declared_models(manifest.parent)
            if defined:
                by_module[manifest.parent.name] = defined
    return by_module


def resolve_deps(module, depends_of, seen=None):
    """Every module `module` can see, transitively."""
    seen = seen or set()
    for dependency in depends_of.get(module, ()):
        if dependency in seen:
            continue
        seen.add(dependency)
        resolve_deps(dependency, depends_of, seen)
    return seen


def main():
    modules = our_modules()
    if not modules:
        print('check_cross_module_inherit: no modules found, skipping')
        return 0

    depends_of = {}
    defined_by = {}
    extends = {}
    for name, path in modules.items():
        # A manifest's depends name BARE module names, so index by the
        # last path component: addons_print/pp_print_core is depended on
        # as "pp_print_core".
        bare = name.rsplit('/', 1)[-1]
        depends_of[bare] = manifest_depends(path)
        defined, extended = declared_models(path)
        defined_by[bare] = defined
        extends[bare] = extended

    core = core_models()
    for module, models in core.items():
        defined_by.setdefault(module, set()).update(models)
        depends_of.setdefault(module, [])

    problems = []
    checked = 0
    for module, extended in extends.items():
        # 'base' is IMPLICIT for every module -- odoo/orm/model_classes.py
        # appends it to parent_names for everything except base itself --
        # so a module never declares it and must still see res.partner,
        # res.config.settings and the rest. Without this the check's first
        # run flagged res_config_settings.py, which has worked for months.
        visible = {module, 'base'} | resolve_deps(module, depends_of)
        reachable = set()
        for name in visible:
            reachable |= defined_by.get(name, set())
        for model, path, lineno in extended:
            checked += 1
            if model in reachable:
                continue
            # Where IS it defined? Naming the module is what makes the
            # message actionable rather than a riddle.
            owners = sorted(
                name for name, models in defined_by.items()
                if model in models)
            if not owners:
                # Unknown to us and to core: an optional third-party
                # model, or one defined in a way the AST cannot see.
                # Unknown is not wrong.
                continue
            problems.append(
                "%s:%s: '%s' extends '%s', which is defined in %s -- and "
                "%s does not depend on it. The registry fails to load "
                "with \"Model '%s' does not exist in registry\", and the "
                "container still starts, so the DEPLOY LOOKS GREEN while "
                "every request 500s."
                % (path.relative_to(ROOT), lineno, module, model,
                   ' / '.join(owners), module, model))

    if problems:
        print('Models extended from a module that cannot see them:')
        for problem in sorted(set(problems)):
            print('  %s' % problem)
        return 1

    print('%s _inherit(s) all name a model their module can see.' % checked)
    return 0


if __name__ == '__main__':
    sys.exit(main())
