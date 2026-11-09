"""One-time clean-up of the vendor rows Odoo made on profile products.

Run through `odoo shell` on the service, NEVER as a deploy step:

    railway ssh -s odoo -- sh -c 'AW_MODE=list odoo shell -c /etc/odoo/odoo.conf \
        -d odoo --no-http' < scripts/profile_supplierinfo.py

AW_MODE=list    read only: prints the rows (id, vendor, product, price, date).
AW_MODE=note    writes each vendor's rows as a note on the vendor's chatter
                (once; a second run adds nothing).
AW_MODE=delete  removes the rows, and ONLY if every row is (a) written in a
                saved note, (b) untouched since Odoo made it (not edited, no
                variant, min qty 1, lead time 0) and (c) on a profile
                product. Otherwise it removes nothing and says which row
                stopped it. Add AW_CONFIRM=yes to really delete; without it
                the script says what it would delete and rolls back.
"""
import os
import re

from markupsafe import Markup, escape

env = globals()['env']  # noqa: provided by `odoo shell`
MODE = os.environ.get('AW_MODE', 'list')
MARK = 'Vendor rows on profile products, saved before removal'


def rows():
    return env['product.supplierinfo'].sudo().search([], order='id').filtered(
        lambda r: r.product_tmpl_id.aw_is_profile)


def untouched(row):
    return (row.write_date == row.create_date and not row.product_id
            and row.min_qty == 1.0 and not row.delay)


def line(row):
    return '#%s | %s | %s | %.2f %s per %s | created %s' % (
        row.id, row.partner_id.name, row.product_tmpl_id.name, row.price,
        row.currency_id.name, row.product_uom_id.name or '-',
        row.create_date)


def saved_ids(vendor):
    ids = set()
    for message in env['mail.message'].sudo().search([
            ('model', '=', 'res.partner'), ('res_id', '=', vendor.id),
            ('body', 'ilike', MARK)]):
        ids |= {int(n) for n in re.findall(r'#(\d+) \|', str(message.body))}
    return ids


found = rows()
print('RESULT %s row(s) on profile products' % len(found))
for row in found:
    print('RESULT ' + line(row) + (' | untouched' if untouched(row)
                                  else ' | EDITED OR HAS A VARIANT'))

if MODE == 'note':
    for vendor in found.partner_id:
        mine = found.filtered(lambda r: r.partner_id == vendor)
        new = mine.filtered(lambda r: r.id not in saved_ids(vendor))
        if not new:
            print('RESULT %s: already saved' % vendor.name)
            continue
        body = Markup('<p>%s (%s row(s), to be removed once the last purchase '
                      'price table is the only record):</p><ul>%s</ul>') % (
            MARK, len(new), Markup('').join(
                Markup('<li>%s</li>') % escape(line(r)) for r in new))
        vendor.message_post(body=body, subtype_xmlid='mail.mt_note')
        print('RESULT noted %s row(s) on %s' % (len(new), vendor.name))
    env.cr.commit()
elif MODE == 'delete':
    stop = []
    for row in found:
        if row.id not in saved_ids(row.partner_id):
            stop.append('#%s is not in a saved note' % row.id)
        if not untouched(row):
            stop.append('#%s was edited or has a variant' % row.id)
    if stop:
        print('RESULT NOTHING DELETED: ' + '; '.join(stop))
    elif os.environ.get('AW_CONFIRM') != 'yes':
        print('RESULT would delete %s row(s): %s (add AW_CONFIRM=yes)' % (
            len(found), found.ids))
    else:
        ids = found.ids
        found.unlink()
        print('RESULT deleted %s row(s): %s' % (len(ids), ids))
        env.cr.commit()
env.cr.rollback()  # whatever was not committed above is dropped
