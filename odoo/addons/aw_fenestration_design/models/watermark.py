# -*- coding: utf-8 -*-
"""The watermark on the Elevation Sheet, the Elevation Schedule and the Quotation.

One switch per report, in Settings (`aw_fenestration.watermark_sheet`, `_schedule`,
`_quotation`; 'on' unless set to 'off', and a Selection rather than a Boolean because
a Boolean that is False deletes its parameter, which would read as the default 'on'
again). No logo means no watermark and no error. The stickers, the cut list and the
cut summary are not in the list of reports that get one (report_chunks.WATERMARKED).
The stamping itself is pdf_watermark.stamp, on the finished PDF.
"""
import base64
import hashlib
import logging

from odoo import api, models

from . import watermark_image

_logger = logging.getLogger(__name__)

KEYS = ('sheet', 'schedule', 'quotation')
_CACHE = {}


class ResCompany(models.Model):
    _inherit = 'res.company'

    @api.model
    def _aw_watermark_on(self, key):
        value = self.env['ir.config_parameter'].sudo().get_param(
            'aw_fenestration.watermark_%s' % key, 'on')
        return value != 'off'

    def _aw_watermark_png(self, key, page_w, page_h):
        """(png, width, height) of the watermark for report `key` on a page of the
        given size (any unit; the answer is in the same unit), or None: switched
        off, no logo, or a logo that is not an image."""
        company = self[:1]
        if not company or not self._aw_watermark_on(key) or not company.logo:
            return None
        logo = base64.b64decode(company.logo)
        cache_key = (hashlib.sha1(logo).hexdigest(), round(page_w), round(page_h))
        made = _CACHE.get(cache_key)
        if made is None:
            try:
                made = watermark_image.watermark(logo, page_w, page_h)
            except Exception:
                _logger.exception("watermark: the logo could not be prepared")
                made = None
            if len(_CACHE) > 16:
                _CACHE.clear()
            _CACHE[cache_key] = made or False
        return made or None
