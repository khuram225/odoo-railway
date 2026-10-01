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

   Worth being precise about **where that 500 actually comes from**,
   because it is not this line. Verified in `odoo-src`: when a request
   carries a database, `Application.__call__` routes it through
   `Request._serve_db`, which calls `Registry(self.db)` *before* any
   controller is matched -- it has to, since the routing map itself is
   built from `registry['ir.http']`. A broken module graph raises
   `TypeError: Model 'aw.design' does not exist in registry` there; the
   `except` beside it catches only `AttributeError` and two psycopg2
   errors, so it propagates to the outer handler, is logged, and comes
   back as a 500 (`request.dispatcher` is set to an HTTP one at
   `http.py:1802` precisely so an early failure still has a responder).
   **Every** route 500s in that state, including this one, and this
   handler is never entered. That is the correct outcome and the reason
   the healthcheck works -- but the credit belongs to core, not here.

   What this line does add is the explicit `?db=` case and the guarantee
   that the registry is loaded rather than merely signalled, so the
   meaning of a 200 does not depend on which code path core took.
2. **Reads a real `aw.design` row**, with real column names. **This is
   the part no core route can replace**, and the part the registry load
   above does not cover. A registry loads perfectly well while a column
   is missing -- a new stored field deployed but not yet upgraded is
   exactly that, and it took this instance down once via `res.company`
   and again via nine new columns on `aw.window.template`. Reading named
   fields turns that into a 500 here instead of a surprise on somebody's
   first page load.

Path: **/aw/health** -- set it as Railway's healthcheck.

**One limit to know.** A request with no database at all is served by
`Application._serve_nodb`, whose routing map is built only from
`server_wide_modules` endpoints declaring `nodb_only=True`. This route is
in neither, so in that state it answers **404**, not 500. A 404 still
fails a healthcheck, so the direction is safe, but the reason on screen
would be "not found" rather than "unhealthy". `db_name` is set by
`odoo/entrypoint.sh`, which is what keeps a request from landing there.

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
        name = db or getattr(request, 'db', None) or self._configured_db()
        if not name:
            return self._fail(
                'no single database to check (db_name names none, or more '
                'than one, and the request carries no database)')

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

    def _configured_db(self):
        """The one configured database, or None if that is not a single name.

        **`config['db_name']` is a LIST in Odoo 19**, not a string: `-d`
        is declared `type='comma'` (`odoo/tools/config.py`), and core
        itself writes `config['db_name'][0]` and
        `set(config['db_name']).intersection(dbs)`. The first version of
        this route did `config.get('db_name')` and handed the result
        straight to `Registry()`, so on a perfectly healthy instance it
        would have reported a 500 -- a healthcheck that fails closed on
        working code, which is its own kind of outage.

        `request.db` is preferred over this because it is the database
        the rest of this very request would use, dbfilter included. This
        is only the fallback, and it answers nothing rather than guessing
        when several databases are exposed: health-checking a database
        that is not the one serving traffic is worse than saying so.
        """
        configured = config.get('db_name') or []
        if isinstance(configured, str):  # older/ini-style single value
            configured = [part for part in configured.split(',') if part]
        return configured[0] if len(configured) == 1 else None

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
