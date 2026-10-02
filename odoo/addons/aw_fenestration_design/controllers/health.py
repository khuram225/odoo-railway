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

**Two routes, because those two checks must not be the same one.**

- **`/aw/health/registry`** -- registry builds, `aw.design` resolves, NO
  columns read. **This is Railway's healthcheck.**
- **`/aw/health`** -- the above plus a real read of named columns. Run by
  hand after an Upgrade; CI runs it against a database it just installed.

Splitting them is not tidiness, it is the difference between deploying
and deadlocking. Railway holds the old container until the new one is
healthy, and the Upgrade is run FROM the new one. Make the healthcheck
demand upgraded columns and every schema-changing release wedges: the new
container cannot go healthy until it is upgraded, and cannot be upgraded
until it is healthy. The column probe is therefore the one you run after,
not the gate you pass through.

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

    @http.route('/aw/health/registry', type='http', auth='none',
                save_session=False)
    def aw_health_registry(self, db=None, **kwargs):
        """**This is Railway's healthcheck.** Registry only, no columns.

        It answers 200 for a deploy that has new code and has NOT been
        upgraded yet, and that is the entire point. Railway keeps the old
        container until the new one reports healthy, and the Upgrade is
        run FROM the new one -- so a healthcheck that demands upgraded
        columns can never go green on the deploy that would create them.
        Every schema-changing release would deadlock: the new container
        never becomes healthy, so it never serves the Upgrade, so the
        columns never appear.

        So this proves only what must be true before anyone can upgrade:
        the module graph builds and `aw.design` is in the registry. The
        lookup is `registry['aw.design']`, a dict access raising KeyError
        (`odoo/orm/registry.py:342`) -- no cursor, no SELECT, not one
        column named. A missing column cannot fail it.

        Database connectivity is still covered, by core rather than here:
        a request carrying a database reaches this through `_serve_db`,
        which has already opened a readonly cursor and run
        `check_signaling` before any controller is matched.

        `/aw/health` is the deeper probe, for after the Upgrade.
        """
        name = self._target_db(db)
        if not name:
            return self._fail(self._NO_DB)

        try:
            # A failed registry is never cached, so a broken deploy keeps
            # failing rather than answering from a stale one.
            registry = Registry(name)
        except Exception as exc:
            return self._fail('registry would not load: %s' % exc)

        try:
            registry['aw.design']
        except KeyError:
            # The 7549098 shape: the graph built but our model is not in
            # it. Worth distinguishing from a registry that would not
            # build at all, since the remedy is different.
            return self._fail("'aw.design' is not in the registry")

        return self._respond(200, 'pass: registry loaded, aw.design resolves')

    @http.route('/aw/health', type='http', auth='none', save_session=False)
    def aw_health(self, db=None, **kwargs):
        """The full probe: registry, plus real columns. **Not** the
        healthcheck -- see `/aw/health/registry` for why.

        Run this by hand after an Upgrade, where "the columns are there
        now" is exactly the question. CI runs it too, on a database it
        has just installed.
        """
        name = self._target_db(db)
        if not name:
            return self._fail(self._NO_DB)

        try:
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

    _NO_DB = ('no single database to check (db_name names none, or more '
              'than one, and the request carries no database)')

    def _target_db(self, db=None):
        return db or getattr(request, 'db', None) or self._configured_db()

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
