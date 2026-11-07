#!/usr/bin/env python3
"""Is what runs on Railway what is on main? Lists any CODE file that changed
since the deployed commit and was not deployed (a deploy wrongly skipped by
the watch paths, a failed deploy, or one still running).

    python scripts/deployed_check.py [--service odoo] [--assume-deployed SHA]

Needs the Railway CLI logged in and linked to the project, and git. It reads
`railway status --json` (nothing is written anywhere) and the watch paths in
scripts/railway_watch_paths.txt. Exit 0: nothing waiting. Exit 1: code on main
that is not deployed and no deploy is running. Exit 2: a deploy is running.
"""
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNING = {'INITIALIZING', 'QUEUED', 'WAITING', 'BUILDING', 'DEPLOYING'}


def git(*args):
    return subprocess.run(['git', '-C', ROOT] + list(args), capture_output=True,
                          text=True)


def pattern_regex(pattern):
    """One gitignore-style pattern, anchored at the repository root."""
    body = pattern.lstrip('/')
    out, i = '', 0
    while i < len(body):
        if body.startswith('**/', i):
            out += '(?:.*/)?'
            i += 3
        elif body.startswith('**', i):
            out += '.*'
            i += 2
        elif body[i] == '*':
            out += '[^/]*'
            i += 1
        else:
            out += re.escape(body[i])
            i += 1
    return re.compile('^' + out + '$')


def load_watch_paths():
    rules = []
    with open(os.path.join(ROOT, 'scripts', 'railway_watch_paths.txt'),
              encoding='utf-8') as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith('#'):
                rules.append((line.startswith('!'),
                              pattern_regex(line.lstrip('!'))))
    return rules


def deploys(path, rules):
    """Does a change to `path` deploy? The last matching rule wins."""
    result = False
    for negated, regex in rules:
        if regex.match(path):
            result = not negated
    return result


def railway_service(name):
    exe = shutil.which('railway') or shutil.which('railway.cmd')
    if not exe:
        sys.exit('the Railway CLI is not on the PATH')
    proc = subprocess.run([exe, 'status', '--json'],
                          capture_output=True, text=True)
    if proc.returncode or not proc.stdout.strip():
        sys.exit('railway status --json failed: %s' % proc.stderr.strip()[:200])
    data = json.loads(proc.stdout)
    for env in data['environments']['edges']:
        for edge in env['node']['serviceInstances']['edges']:
            node = edge['node']
            if node.get('serviceName') == name:
                return node
    sys.exit('no service named %r in this project' % name)


def main():
    service = 'odoo'
    if '--service' in sys.argv:
        service = sys.argv[sys.argv.index('--service') + 1]
    node = railway_service(service)
    assumed = None
    if '--assume-deployed' in sys.argv:       # to see the output, for testing
        assumed = sys.argv[sys.argv.index('--assume-deployed') + 1]
    active = (node.get('activeDeployments') or [{}])[0]
    latest = node.get('latestDeployment') or {}
    deployed = (active.get('meta') or {}).get('commitHash', '')
    latest_commit = (latest.get('meta') or {}).get('commitHash', '')
    if assumed:
        deployed = git('rev-parse', assumed).stdout.strip()
        latest_commit, latest = deployed, {'status': 'SUCCESS'}
    git('fetch', '-q', 'origin', 'main')
    head = git('rev-parse', 'origin/main').stdout.strip()
    print('service        :', service)
    print('running        : %s (%s)' % (deployed[:7], active.get('status')))
    print('latest deploy  : %s (%s, %s)' % (
        latest_commit[:7], latest.get('status'), latest.get('createdAt')))
    print('main           :', head[:7])
    if not deployed:
        sys.exit('no running deployment found')
    if git('cat-file', '-e', deployed + '^{commit}').returncode:
        sys.exit('the running commit %s is not in this clone; git fetch' %
                 deployed[:7])
    if deployed == head:
        print('\nOK: what runs is main.')
        return 0
    rules = load_watch_paths()
    changed = git('diff', '--name-only', deployed, head).stdout.split()
    code = [path for path in changed if deploys(path, rules)]
    skipped = [path for path in changed if not deploys(path, rules)]
    print('\n%s file(s) changed since the running commit: %s code, %s outside '
          'the watch paths (rightly not deployed)' % (
              len(changed), len(code), len(skipped)))
    if not code:
        print('OK: nothing that needs a deploy.')
        return 0
    for path in code:
        print('  CODE', path)
    if latest.get('status') in RUNNING:
        print('\nA deploy of %s is %s: wait for it.' % (
            latest_commit[:7], latest.get('status')))
        return 2
    if latest_commit == head:
        print('\nThe deploy of main %s is %s and the old version is running:'
              ' fix it or redeploy the last SUCCESS.' % (
                  head[:7], latest.get('status')))
        return 1
    print('\nWRONGLY SKIPPED? Code changed on main and no deploy of it exists.'
          '\nCheck the Watch Paths in the dashboard against '
          'scripts/railway_watch_paths.txt, then redeploy.')
    return 1


if __name__ == '__main__':
    sys.exit(main())
