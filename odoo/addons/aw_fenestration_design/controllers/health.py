# -*- coding: utf-8 -*-
"""A healthcheck that actually loads the registry.

`/web/health` does NOT, and that is the whole reason this exists. Core's
route answers 200 as long as the HTTP worker is alive; its only optional
extra is a ping to the Postgres *server* (`db_server_status=1`), never a
registry load. Phase 7e shipped an `_inherit = 'aw.design'` inside
`aw_fenestration_core`, the registry failed with "Model 'aw.design' does
not exist in registry", **every real request returned 500 — and
`/web/health` went on answering 200, so Railway reported the deploy
healthy.**

So this route does the two things that were broken while the old one was
happy:

1. **Loads the registry** of the target database. `Registry(name)` raises
   if the module graph will not build, which covers a bad `_inherit`, an
   undefined name at import, a broken view in a data file -- the whole
   class of "the code deployed but the application does not exist".
2. **Reads a real `aw.design` row**, with real column names. A registry
   can load while a column is missing: a new stored field deployed but
   not yet upgraded is exactly that, and it took this instance down once
   via `res.company`. Reading named fields makes that a 500 here instead
   of a surprise on somebody's first page load.

Path: **/aw/health** -- set it as Railway's healthcheck.

`auth='none'` because a healthcheck has no session, and `save_session`
is off so it never writes one. The response is deliberately
uncacheable: a proxy that cached a 200 would hide the next failure.
"""
import logging

from odoo import SUPERUSER_ID, api, http
from odoo.http import request
from odoo.modules.registry import Registry
from odoo.tools import config

_logger = logging.getLogger(__name__)

# Read by name, so a stored field whose column has not been created yet
# fails HERE rather than on a user's first page load. Deliberately a few
# columns across the parts of the model that move most.
PROBE_FIELDS = ['name', 'window_series_id', 'template_id', 'finish_id']


class AwHealth(http.Controller):

    @http.route('/aw/health', type='http', auth='none', save_session=False)
    def aw_health(self, db=None, **kwargs):
        """200 when the application is really there, 500 otherwise."""
        name = db or config.get('db_name') or getattr(request, 'db', None)
        if not name:
            return self._fail('no database configured (db_name is unset)')

        try:
            # THE point of this route. Raises on a module graph that will
            # not build; a failed registry is never cached, so a broken
            # deploy keeps failing rather than answering from a stale one.
            registry = Registry(name)
        except Exception as exc:
            return self._fail('registry would not load: %s' % exc)

        try:
            with registry.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                design = env['aw.design'].with_context(
                    active_test=False).search([], limit=1)
                if design:
                    design.read(PROBE_FIELDS)
                    detail = 'read design %s' % design.id
                else:
                    # An empty table is not a failure -- a fresh database
                    # has no designs. The model resolving and the SELECT
                    # running is what was being proved.
                    env['aw.design'].search_count([])
                    detail = 'no designs yet'
        except Exception as exc:
            return self._fail('aw.design is not readable: %s' % exc)

        return self._respond(200, 'pass: %s' % detail)

    def _fail(self, message):
        # Logged as well as returned: Railway shows the status code, the
        # log is where the reason has to be findable afterwards.
        _logger.error('aw health check FAILED -- %s', message)
        return self._respond(500, 'fail: %s' % message)

    def _respond(self, status, body):
        return request.make_response(
            body + '\n',
            headers=[
                ('Content-Type', 'text/plain; charset=utf-8'),
                # A cached 200 would hide the next failure, which is the
                # one thing a healthcheck must never do.
                ('Cache-Control', 'no-store, max-age=0'),
            ],
            status=status,
        )
