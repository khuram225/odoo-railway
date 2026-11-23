"""One-time backfill: give a window that has NO stored drawing the drawing of a window
on the same quote that has the same finish and the same layout fingerprint, so a copy
made before copies took their source's drawing prints a picture.

Run through `odoo shell` on the service, NEVER as a deploy step, and take a dump first
(`scripts/rehearse.sh --dump-only`):

    railway ssh -s odoo -- sh -c 'AW_MODE=count odoo shell -c /etc/odoo/odoo.conf \
        -d odoo --no-http' < scripts/backfill_copy_drawings.py

AW_MODE=count   (default) read only: how many windows it would touch, each with the
                window it would take the drawing from. Writes nothing, rolls back.
AW_MODE=apply   copies the drawings. Without AW_CONFIRM=yes it says what it would do
                and rolls back; with it, it writes and commits. A second run finds
                nothing (the windows now have a drawing).

A window is only matched to a window on the SAME quote with the SAME finish (the frame
is painted in the finish's colour and the fingerprint does not cover it), and only when
the source's drawing is current. The copied SVG is marked as copied, so if the size is
changed later the print says "Drawing from the source window: size differs".
"""
import os

env = globals()['env']  # noqa: provided by `odoo shell`
MODE = os.environ.get('AW_MODE', 'count')

Design = env['aw.design']
without = Design.search([('elevation_svg', '=', False)])
print('RESULT %s window(s) have no stored drawing, of %s' % (
    len(without), Design.search_count([])))
found = Design._aw_twin_drawing_report(apply=False)
print('RESULT %s of them match a current drawing on the same quote and finish:' % len(found))
for quote, design, source in found:
    print('RESULT   %s: %s (%s) <- %s' % (
        quote, design.name, design.location or '-', source.name))

if MODE == 'apply':
    if os.environ.get('AW_CONFIRM') == 'yes':
        Design._aw_twin_drawing_report(apply=True)
        env.cr.commit()
        left = Design._aw_twin_drawing_report(apply=False)
        print('RESULT wrote %s drawing(s); %s still to do' % (len(found), len(left)))
    else:
        print('RESULT would copy %s drawing(s); add AW_CONFIRM=yes to write them. '
              'Nothing was written.' % len(found))
        env.cr.rollback()
else:
    env.cr.rollback()
