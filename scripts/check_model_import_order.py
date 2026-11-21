#!/usr/bin/env python3
"""A file that extends a model must be imported AFTER the file that defines it.

Odoo builds the registry by importing the addon's python files in the order of
its `__init__.py` files, and a class with `_inherit = 'aw.cut.plan'` is added
to the registry the moment it is imported. If the file that DEFINES
`aw.cut.plan` (`_name = 'aw.cut.plan'`) is imported later, the extension has
nothing to extend and the registry fails to load with

    TypeError: Model 'aw.cut.plan' does not exist in registry.

PR #134 did exactly that (`cut_summary` imported before `cut_plan`), the
upgrade in the entrypoint exited, and the service was down until a fix was
deployed. Nothing static looked at the ORDER: `check_cross_module_inherit.py`
asks whether the model is visible to the module at all, and the boot test
only runs after the merge button is already there.

This reads each addon's `__init__.py` chain (`from . import models`,
`from . import x`, ...) into one import order, finds the file that defines each
model of the addon (`_name`), and fails for every file that extends such a
model (`_inherit`, a string or a list) from a file imported before the
defining one. A model defined in a DEPENDENCY is fine wherever it is
extended, and so is a model the addon does not define at all (core Odoo).
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADDONS = ROOT / 'odoo' / 'addons'


def addon_dirs(base=ADDONS):
    return sorted(m.parent for m in base.rglob('__manifest__.py'))


def manifest_depends(path):
    try:
        values = eval(  # noqa: S307 - our own manifest
            (path / '__manifest__.py').read_text(encoding='utf-8'),
            {'__builtins__': {}}, {})
    except Exception:
        return []
    return list(values.get('depends') or [])


def imports_of(init_file):
    """Names imported by `from . import a, b` lines, in order."""
    tree = ast.parse(init_file.read_text(encoding='utf-8'))
    names = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level == 1 \
                and node.module is None:
            names.extend(alias.name for alias in node.names)
    return names


def import_order(package, seen=None):
    """Python files of a package in the order Odoo imports them."""
    seen = seen if seen is not None else set()
    init = package / '__init__.py'
    if not init.is_file():
        return []
    files = []
    for name in imports_of(init):
        module_file = package / (name + '.py')
        sub_package = package / name
        if sub_package.is_dir() and (sub_package / '__init__.py').is_file():
            files.extend(import_order(sub_package, seen))
        elif module_file.is_file() and module_file not in seen:
            seen.add(module_file)
            files.append(module_file)
    return files


def class_models(path):
    """[(defined _name or None, [inherited names])] for each class in a file."""
    try:
        tree = ast.parse(path.read_text(encoding='utf-8'))
    except SyntaxError:
        return []
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        name, inherits = None, []
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
                continue
            target = stmt.targets[0]
            if not isinstance(target, ast.Name):
                continue
            if target.id == '_name' and isinstance(stmt.value, ast.Constant):
                name = stmt.value.value
            elif target.id == '_inherit':
                value = stmt.value
                if isinstance(value, ast.Constant):
                    inherits = [value.value]
                elif isinstance(value, (ast.List, ast.Tuple)):
                    inherits = [e.value for e in value.elts
                                if isinstance(e, ast.Constant)]
        if name or inherits:
            found.append((name, inherits))
    return found


def problems_in(addon, dependency_models, base=ADDONS):
    order = import_order(addon)
    position = {path: index for index, path in enumerate(order)}
    defined_in = {}
    for path in order:
        for name, _inherits in class_models(path):
            if name:
                defined_in.setdefault(name, path)
    found = []
    for path in order:
        for name, inherits in class_models(path):
            for model in inherits:
                if model == name or model in dependency_models:
                    continue
                home = defined_in.get(model)
                if home and position[home] > position[path]:
                    found.append(
                        "%s extends '%s' but is imported BEFORE %s, which "
                        "defines it" % (
                            path.relative_to(base).as_posix(), model,
                            home.relative_to(base).as_posix()))
    return found


def models_by_addon(addons):
    return {a.name: {n for p in a.rglob('*.py') for n, _i in class_models(p) if n}
            for a in addons}


def all_problems(base=ADDONS):
    addons = addon_dirs(base)
    own = models_by_addon(addons)
    names = {a.name: a for a in addons}

    def depends_closure(addon, seen=None):
        seen = seen if seen is not None else set()
        for dep in manifest_depends(addon):
            if dep in names and dep not in seen:
                seen.add(dep)
                depends_closure(names[dep], seen)
        return seen

    found = []
    for addon in addons:
        dependency_models = set()
        for dep in depends_closure(addon):
            dependency_models |= own[dep]
        found.extend(problems_in(addon, dependency_models, base))
    return found, len(addons)


def self_test():
    """The rule must catch the order it was written for, and pass the other."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        pkg = base / 'demo' / 'models'
        pkg.mkdir(parents=True)
        (base / 'demo' / '__manifest__.py').write_text("{'depends': []}")
        (base / 'demo' / '__init__.py').write_text("from . import models\n")
        (pkg / 'plan.py').write_text(
            "class P:\n    _name = 'demo.plan'\n")
        (pkg / 'summary.py').write_text(
            "class S:\n    _inherit = 'demo.plan'\n")
        (pkg / 'core_ext.py').write_text(
            "class C:\n    _inherit = 'res.partner'\n")
        (pkg / '__init__.py').write_text(
            "from . import summary\nfrom . import plan\nfrom . import core_ext\n")
        wrong, _n = all_problems(base)
        (pkg / '__init__.py').write_text(
            "from . import plan\nfrom . import summary\nfrom . import core_ext\n")
        right, _n = all_problems(base)
    return wrong, right


def main():
    wrong, right = self_test()
    if len(wrong) != 1 or right:
        print("FAIL: the self-test of this check is wrong: %r / %r"
              % (wrong, right))
        return 1
    found, count = all_problems()
    if count == 0:
        print("FAIL: found no addons under %s" % ADDONS)
        return 1
    if found:
        print("FAIL: a file extends a model before the file that defines it "
              "is imported (the registry would not load):")
        for line in found:
            print("  - " + line)
        return 1
    print("model import order: %d addon(s), every extension comes after its "
          "definition" % count)
    return 0


if __name__ == '__main__':
    sys.exit(main())
