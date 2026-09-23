#!/usr/bin/env python3
"""Catches forward-references in an Odoo module's data-loading order.

Three of these have broken real installs in this repo already, all the
same root cause: `ref="..."` on a scalar field, `%(xmlid)d` inside a
type="xml" field, and `parent="..."`/`action="..."` on a <menuitem> all
resolve EAGERLY at XML-parse time (odoo/tools/convert.py's
_tag_record/_eval_xml/_tag_menuitem -> self.id_get()), not lazily at
render time. The target external ID must already exist at that exact
point in the manifest's `data` list -- not just be defined somewhere
else in the module.

Usage:
    python scripts/check_load_order.py [module_dir ...]

With no arguments, checks every module directory directly under
odoo/addons/ that has a __manifest__.py. Exits non-zero if any module
has a forward reference.
"""
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ADDONS_DIR = REPO_ROOT / 'odoo' / 'addons'

BLOCK_RE = re.compile(
    r'<record\s+[^>]*?\bid="(?P<rid>[^"]+)"[^>]*>(?P<rbody>.*?)</record>'
    r'|<menuitem\b[^>]*?/>',
    re.DOTALL,
)
ID_RE = re.compile(r'\bid="([^"]+)"')
REF_RE = re.compile(r'ref="([a-zA-Z_][a-zA-Z0-9_]*)"')
ACTION_RE = re.compile(r'action="([a-zA-Z_][a-zA-Z0-9_]*)"')
PARENT_RE = re.compile(r'parent="([a-zA-Z_][a-zA-Z0-9_]*)"')
PCT_RE = re.compile(r'%\(([a-zA-Z_][a-zA-Z0-9_]*)\)[ds]')


def check_module(module_dir: Path) -> list[str]:
    manifest_path = module_dir / '__manifest__.py'
    manifest = manifest_path.read_text(encoding='utf-8')
    match = re.search(r"'data':\s*\[(.*?)\]", manifest, re.DOTALL)
    if not match:
        return []
    files = re.findall(r"'([^']+)'", match.group(1))

    defined_so_far = set()
    problems = []

    for f in files:
        if not f.endswith('.xml'):
            continue
        path = module_dir / f
        if not path.is_file():
            continue
        text = path.read_text(encoding='utf-8')
        for m in BLOCK_RE.finditer(text):
            block_text = m.group(0)
            this_id_match = ID_RE.search(block_text)
            this_id = this_id_match.group(1) if this_id_match else None

            refs = (set(REF_RE.findall(block_text)) | set(ACTION_RE.findall(block_text))
                    | set(PCT_RE.findall(block_text)) | set(PARENT_RE.findall(block_text)))
            for r in refs:
                if '.' in r:
                    continue  # cross-module: resolved after full dependency install
                if r not in defined_so_far:
                    problems.append(f"{module_dir.name}/{f} record '{this_id}' references '{r}' before it's defined")

            if this_id:
                defined_so_far.add(this_id)

    return problems


def main(argv: list[str]) -> int:
    if argv:
        module_dirs = [Path(a) for a in argv]
    else:
        module_dirs = sorted(
            p.parent for p in ADDONS_DIR.glob('*/__manifest__.py')
        )

    all_problems = []
    for module_dir in module_dirs:
        all_problems.extend(check_module(module_dir))

    if all_problems:
        print('Forward-reference problems (ref=/%()d/parent=/action= resolved before target is defined):')
        for p in all_problems:
            print(f'  {p}')
        return 1

    print(f'No forward-reference problems in {len(module_dirs)} module(s).')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
