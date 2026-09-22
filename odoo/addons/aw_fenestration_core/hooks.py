# -*- coding: utf-8 -*-
"""Seeds the Box Series Profile Section from the Chawla import.

aw.profile.section.line.product_id points at a specific product.product
variant, not a product.template. Thickness/Finish are Dynamic attributes
(see data/chawla_attributes_data.xml), so no variants exist for the 491
imported templates until a combination is actually requested. This hook
materializes exactly the 5 variants the Box Series section needs -- each
pinned to Thickness=Normal, Finish=Natural, since every one of these 5
profiles has a priced Nor/natural row in the source pricelist -- and then
creates the section and its 5 lines.

Idempotent: safe to re-run on module upgrade.
"""

import logging

_logger = logging.getLogger(__name__)

BOX_SECTION_LINES = [
    ('aw_profile_tmpl_dc_30_ba_100mm', 'frame'),
    ('aw_profile_tmpl_m_23', 'sash'),
    ('aw_profile_tmpl_m_28', 'interlock'),
    ('aw_profile_tmpl_d_29', 'bead'),
    ('aw_profile_tmpl_em_29', 'mesh'),
]


def _get_variant(env, template_xmlid, thickness_value, finish_value):
    template = env.ref(f'aw_fenestration_core.{template_xmlid}')
    ptav = env['product.template.attribute.value']
    combination = ptav.browse()
    for line in template.attribute_line_ids:
        if line.attribute_id == thickness_value.attribute_id:
            wanted = thickness_value
        elif line.attribute_id == finish_value.attribute_id:
            wanted = finish_value
        else:
            continue
        combination |= line.product_template_value_ids.filtered(
            lambda v, wanted=wanted: v.product_attribute_value_id == wanted
        )
    return template._create_product_variant(combination, log_warning=True)


def post_init_hook(env):
    thickness_value = env.ref('aw_fenestration_core.aw_attr_val_thickness_normal')
    finish_value = env.ref('aw_fenestration_core.aw_attr_val_finish_natural')

    section = env['aw.profile.section'].search([
        ('name', '=', 'Box Series - Standard'),
        ('window_type_id', '=', env.ref('aw_fenestration_core.window_type_box').id),
    ], limit=1)
    if section:
        return

    window_type_box = env.ref('aw_fenestration_core.window_type_box')
    line_vals = []
    for template_xmlid, role in BOX_SECTION_LINES:
        variant = _get_variant(env, template_xmlid, thickness_value, finish_value)
        if not variant:
            _logger.warning(
                "aw_fenestration_core: could not create/find the Normal/"
                "Natural variant for template '%s' (role=%s) -- skipping "
                "this line in the Box Series - Standard profile section. "
                "The section will be created with fewer than 5 lines.",
                template_xmlid, role,
            )
            continue
        line_vals.append((0, 0, {
            'role': role,
            'product_id': variant.id,
        }))

    env['aw.profile.section'].create({
        'name': 'Box Series - Standard',
        'window_type_id': window_type_box.id,
        'notes': (
            "Seeded from the Chawla 2026-01-01 pricelist import. Each line's "
            "variant is pinned to Thickness=Normal, Finish=Natural as a "
            "default -- not a business decision about what to actually "
            "fabricate, just the combination confirmed present in the "
            "source pricelist for all 5 roles. Revisit before using this "
            "section for real quotes."
        ),
        'line_ids': line_vals,
    })
