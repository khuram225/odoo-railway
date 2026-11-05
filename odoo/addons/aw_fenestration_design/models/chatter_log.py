# -*- coding: utf-8 -*-
"""The design's chatter records what was done to its glass and hardware.

A save of the configurator REPLACES the rows, so a log written where a row
is created or deleted would say "added" and "removed" on every save. The
log is therefore a DIFF: the glass stacks and hardware rows as they were
when the save started against as they are when it has been applied, row by
row, and one note is posted only when something differs. The author is the
user who saved, and every line names its panel (or the window default).
The price is not logged.
"""
from markupsafe import Markup, escape

from odoo import _, models


def _money(value):
    return '%.2f' % (value or 0.0)


class AwDesign(models.Model):
    _inherit = 'aw.design'

    # -- the snapshot --------------------------------------------------------------
    def _stack_snapshot(self):
        """{'window': [glass dicts], 'panels': {panel_no: {'glass': [...],
        'hardware': [...]}}} as stored right now."""
        self.ensure_one()
        panels = {}
        for leaf in self._all_panels():
            panels[leaf.panel_no or 0] = {
                'glass': [p._as_dict()
                          for p in leaf.glass_part_ids.sorted('sequence')],
                'hardware': [h._as_dict()
                             for h in leaf.hardware_ids.sorted('sequence')],
            }
        return {
            'window': [p._as_dict()
                       for p in self.glass_part_ids.sorted('sequence')],
            'panels': panels,
        }

    # -- the words -------------------------------------------------------------------
    def _glass_text(self, item):
        label = self.env['aw.glass.part']._label_of(item)
        if item.get('kind') == 'gap':
            extras = [x for x in (item.get('spacer_type'),
                                  item.get('spacer_colour')) if x]
            if extras:
                label += ' (%s)' % ', '.join(extras)
        return label

    def _hardware_text(self, row):
        return '%s x%g' % (row.get('name') or _('(no product)'),
                           row.get('qty') or 0)

    @staticmethod
    def _rate_change(old, new, base_word):
        """The line for a typed rate, or a Reset, or nothing."""
        if (old.get('rate_manual'), old.get('manual_rate')) == (
                new.get('rate_manual'), new.get('manual_rate')):
            return ''
        if not new.get('rate_manual'):
            return _("rate reset to the %s", base_word)
        if old.get('rate_manual'):
            return _("typed rate %(old)s → %(new)s",
                     old=_money(old.get('manual_rate')),
                     new=_money(new.get('manual_rate')))
        if not new.get('list_rate'):
            return _("typed rate %s", _money(new.get('manual_rate')))
        return _("typed rate %(new)s (the %(word)s was %(base)s)",
                 new=_money(new.get('manual_rate')), word=base_word,
                 base=_money(new.get('list_rate')))

    def _diff_rows(self, where, kind, old_rows, new_rows):
        """The lines for one list of rows, compared by position."""
        lines = []
        for index in range(max(len(old_rows), len(new_rows))):
            old = old_rows[index] if index < len(old_rows) else None
            new = new_rows[index] if index < len(new_rows) else None
            text = self._glass_text if kind == 'glass' else self._hardware_text
            if old is None:
                lines.append(_("%(where)s: added %(what)s",
                               where=where, what=text(new)))
                continue
            if new is None:
                lines.append(_("%(where)s: removed %(what)s",
                               where=where, what=text(old)))
                continue
            changes = []
            if kind == 'glass':
                before, after = text(old), text(new)
                if before != after:
                    changes.append('%s → %s' % (before, after))
                elif any(old.get(k) != new.get(k) for k in (
                        'spacer_type', 'spacer_colour', 'gas', 'extra',
                        'remark')):
                    changes.append(_("details changed"))
                word = _("list rate")
            else:
                if old.get('product_id') != new.get('product_id'):
                    changes.append('%s → %s' % (
                        old.get('name') or _('(no product)'),
                        new.get('name') or _('(no product)')))
                if (old.get('qty') or 0) != (new.get('qty') or 0):
                    changes.append(_("qty %(old)g → %(new)g",
                                     old=old.get('qty') or 0,
                                     new=new.get('qty') or 0))
                word = _("product cost")
            rate = self._rate_change(old, new, word)
            if rate:
                changes.append(rate)
            if changes:
                lines.append(_("%(where)s, %(what)s: %(changes)s",
                               where=where, what=text(new),
                               changes='; '.join(changes)))
        return lines

    def _stack_changes(self, before, after):
        lines = self._diff_rows(
            _("Window glass"), 'glass', before['window'], after['window'])
        for number in sorted(set(before['panels']) | set(after['panels'])):
            old = before['panels'].get(number, {'glass': [], 'hardware': []})
            new = after['panels'].get(number, {'glass': [], 'hardware': []})
            lines += self._diff_rows(
                _("Panel %s glass", number), 'glass',
                old['glass'], new['glass'])
            lines += self._diff_rows(
                _("Panel %s hardware", number), 'hardware',
                old['hardware'], new['hardware'])
        return lines

    def _log_stack_changes(self, before):
        """Post what changed in the glass and hardware since `before`, as
        one note by the current user. Nothing changed, nothing posted."""
        self.ensure_one()
        lines = self._stack_changes(before, self._stack_snapshot())
        if not lines:
            return False
        body = Markup('<p>%s</p><ul>%s</ul>') % (
            escape(_("Glass and hardware changed:")),
            Markup('').join(Markup('<li>%s</li>') % escape(line)
                            for line in lines))
        self.message_post(body=body, subtype_xmlid='mail.mt_note')
        return True
