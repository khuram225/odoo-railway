# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AwProfileSection(models.Model):
    """A named set of profile products covering every position needed for
    one Window Series -- e.g. frame/sash/mesh/bead pieces, each tagged
    with where in the frame it sits (aw.profile.position).

    This is the Odoo-native equivalent of the prototype's
    SERIES.roles / ROLE_VARIANTS: instead of a hard-coded JS object, each
    position -> product mapping is a real, editable line, and a Series can
    have several sections (Standard / Heavy Duty / Economy) to choose from.
    aw.profile.position is open-ended (add a row, no schema change) --
    replaces the earlier fixed 5-value role Selection, which couldn't
    express e.g. a different drainage profile on the sill vs. head/jambs.
    """
    _name = 'aw.profile.section'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Fenestration Profile Section'
    _order = 'window_type_id, name'

    name = fields.Char(required=True, tracking=True)
    # Field name kept: renaming it would need a migration and break
    # every stored reference. Only the LABEL was ever wrong -- the
    # Window Type layer was folded into Series long ago.
    window_type_id = fields.Many2one(
        'aw.window.series', string='Series', required=True,
        ondelete='restrict', index=True, tracking=True)
    active = fields.Boolean(default=True)
    notes = fields.Text()

    line_ids = fields.One2many(
        'aw.profile.section.line', 'section_id', string='Profile Lines')

    _sql_constraints = [
        ('name_type_uniq', 'unique(name, window_type_id)',
         'A profile section name must be unique per Series.'),
    ]


class AwProfileSectionLine(models.Model):
    _name = 'aw.profile.section.line'
    _description = 'Fenestration Profile Section Line'
    _order = 'sequence, id'

    # Phase 7d: a line belongs to a SPECIFICATION now. section_id is
    # kept and no longer required so the migration can re-point existing
    # lines without deleting and recreating them -- that is what keeps a
    # quoted design's BOM identical across the upgrade, since the BOM is
    # costed from these very records. Exactly one owner is set; see
    # _check_one_owner.
    section_id = fields.Many2one(
        'aw.profile.section', ondelete='cascade',
        help="Legacy owner, kept until Profile Sections are dropped.")
    spec_id = fields.Many2one(
        'aw.window.template', string='Specification',
        ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    position_id = fields.Many2one('aw.profile.position', required=True)
    # Stored so a spec can list its lines group by group with a plain
    # domain. Display only.
    part_group = fields.Selection(
        related='position_id.part_group', store=True, readonly=True)

    product_tmpl_id = fields.Many2one(
        'product.template', required=True, ondelete='restrict',
        domain=lambda self: [(
            'categ_id', 'child_of',
            self.env.ref('aw_fenestration_core.product_category_profiles').id,
        )],
        help="The profile filling this position. Pick a Thickness and "
             "Finish below to resolve (or create) the exact variant.")
    # The profile again, only so the list can show its catalogue picture
    # (a many2one with widget="image" is the way to show another
    # record's image) and its printed section size beside it.
    picture_tmpl_id = fields.Many2one(
        related='product_tmpl_id', string='Picture', readonly=True)
    section_dims = fields.Char(
        related='product_tmpl_id.aw_section_dims', string='Section (mm)',
        readonly=True)
    thickness_attribute_value_ids = fields.Many2many(
        'product.attribute.value', compute='_compute_available_attribute_values')
    thickness_id = fields.Many2one(
        'product.attribute.value', required=True,
        domain="[('id', 'in', thickness_attribute_value_ids)]")

    # Phase 7e: FINISH AND THE VARIANT ARE GONE FROM HERE. A spec says
    # what a window is MADE OF -- which profile, in which wall thickness
    # -- and the colour is a property of the window being quoted, not of
    # the specification it is built to. A finish here made every spec
    # implicitly one colour, so quoting the same window in brown needed
    # either a second spec or a per-window change on every profile line.
    #
    # The variant went with it: profile + thickness + finish is what
    # names a variant and the line now holds two of the three. The BOM
    # resolves it per design, in _profile_variant(), from the design's
    # own finish -- which is also what makes the Checks able to say
    # "this profile is not sold in this colour" about a real window
    # rather than about a spec.

    # -- overrides of the position's defaults (spec 6.2) -------------------
    # Empty means "use the position's rule", which is the common case; a
    # line only needs these when this particular profile behaves
    # differently from the position it sits in.
    length_formula = fields.Char(
        string='Length Override',
        help="Empty means the position's own Length Formula.")
    length_formula_h = fields.Char(
        string='Height-edge Length Override')
    cut_angle = fields.Selection([
        ('45', '45 deg'), ('90', '90 deg'),
    ], string='Angle Override')
    qty_formula = fields.Char(
        string='Quantity Override',
        help="Empty means the position's own Quantity Formula.")

    # ONE line per position, with the alternatives on it (phase 7d).
    # They used to be separate lines distinguished by sequence and named
    # by an option_label, which meant a position's choices were spread
    # across rows that only a sort order tied together -- and the label
    # was a third name for a profile that already has a code and a name.
    # The alternatives are products now, so a divider's choice is "which
    # profile", which is what it always meant.
    alternate_product_ids = fields.Many2many(
        'product.template', string='Alternates',
        domain=lambda self: [(
            'categ_id', 'child_of',
            self.env.ref('aw_fenestration_core.product_category_profiles').id,
        )],
        help="Other profiles a design may use in this position, e.g. a "
             "heavier mullion for a wide opening. The default above is "
             "always offered and is never listed here.")

    is_optional = fields.Boolean(
        default=False,
        help="If checked, a sales user may drop this position from a "
             "design (e.g. an interlock on a single-slider + fixed "
             "layout, or mesh when no screen is wanted).")

    _sql_constraints = [
        ('section_position_uniq', 'unique(section_id, position_id)',
         'Each position can only appear once per Profile Section.'),
    ]

    @api.constrains('spec_id', 'position_id')
    def _check_one_line_per_position(self):
        """One line per position, per spec.

        The alternatives live ON the line now, so a second line for the
        same position is not a second option -- it is two rows claiming
        the same slot, and which one the explosion picked would come
        down to a sort order. Python rather than SQL because every
        `_sql_constraints` in this repo is dead (Odoo 19 ignores the
        attribute), and because the rule has to skip the legacy
        section-owned rows, which are allowed to be duplicated until
        they are dropped.
        """
        for line in self:
            if not (line.spec_id and line.position_id):
                continue
            clash = self.search([
                ('id', '!=', line.id),
                ('spec_id', '=', line.spec_id.id),
                ('position_id', '=', line.position_id.id),
            ], limit=1)
            if clash:
                raise ValidationError(_(
                    "'%(spec)s' already has a line for %(position)s. Add "
                    "the other profile to its Alternates instead of a "
                    "second line.",
                    spec=line.spec_id.display_name,
                    position=line.position_id.display_name))

    @api.constrains('product_tmpl_id', 'alternate_product_ids')
    def _check_default_not_an_alternate(self):
        """The default is always offered, so listing it again would
        show the same profile twice in the divider toolbar."""
        for line in self:
            if line.product_tmpl_id in line.alternate_product_ids:
                raise ValidationError(_(
                    "%s is the default for this position, so it does not "
                    "also belong in Alternates.",
                    line.product_tmpl_id.display_name))

    def _profile_choices(self):
        """Every profile this line offers: the default, then alternates.

        Default FIRST and always present -- the order is what the
        divider toolbar shows, and "no choice made" means the default.
        """
        self.ensure_one()
        return self.product_tmpl_id | self.alternate_product_ids

    @api.constrains('section_id', 'spec_id')
    def _check_one_owner(self):
        """A line belongs to a spec, or to a legacy section, not both
        and not neither.

        An orphan line is invisible everywhere and still costs money if
        anything ever walks it; one owned twice would appear in two
        BOMs. Python rather than SQL, because every `_sql_constraints`
        in this repo is dead -- Odoo 19 ignores the attribute and only
        logs that it does.
        """
        for line in self:
            if bool(line.section_id) == bool(line.spec_id):
                raise ValidationError(_(
                    "A profile line must belong to exactly one "
                    "Specification (or, until they are dropped, one "
                    "Profile Section)."))

    @api.onchange('product_tmpl_id')
    def _onchange_product_tmpl_id(self):
        # thickness_id's domain only restricts NEW picks -- it doesn't
        # retroactively clear an already-set value that no longer belongs
        # to the newly chosen template's own attribute lines. Left stale,
        # the BOM would resolve to no variant instead of erroring, since
        # the combination would name a thickness this profile is not sold
        # in.
        self.thickness_id = False

    @api.model
    def _template_values(self, product_tmpl, attribute):
        """The values of `attribute` this TEMPLATE actually offers.

        Thickness and Finish are Dynamic-creation attributes, so what
        exists as an attribute value globally is not what any one
        profile is sold in -- every RE- profile in the price list is
        sold only in 'Standard', while 'Normal' exists and is offered
        by other profiles. Asking a template for a value it does not
        carry yields no variant at all, silently.
        """
        values = self.env['product.attribute.value']
        for attr_line in product_tmpl.attribute_line_ids:
            if attr_line.attribute_id == attribute:
                values |= attr_line.value_ids
        return values

    @api.depends('product_tmpl_id')
    def _compute_available_attribute_values(self):
        thickness_attr = self.env.ref('aw_fenestration_core.aw_attribute_thickness')
        for line in self:
            line.thickness_attribute_value_ids = self._template_values(
                line.product_tmpl_id, thickness_attr)

    @api.model
    def _variant_problem(self, product_tmpl, thickness, finish):
        """Why a template + thickness + finish resolves to no variant.

        "No product for 'P1 Outer Frame - Top'" is true and useless: it
        says the line produced nothing, not which of its three parts is
        at fault. This names it -- "RE-8 has no 'Normal' thickness;
        available: Standard" -- which is the difference between a
        warning somebody can act on and one they learn to ignore.

        Returns '' when the combination is fine, so a caller can use it
        as the reason a product is missing and nothing more.
        """
        if not product_tmpl:
            return _("A Profile Section line has no profile product set.")
        thickness_attr = self.env.ref('aw_fenestration_core.aw_attribute_thickness')
        finish_attr = self.env.ref('aw_fenestration_core.aw_attribute_finish')
        for value, attribute, label in (
                (thickness, thickness_attr, _("thickness")),
                (finish, finish_attr, _("finish"))):
            options = self._template_values(product_tmpl, attribute)
            if not value:
                return _(
                    "No %(what)s is chosen for %(product)s.",
                    what=label, product=product_tmpl.display_name)
            if not options:
                return _(
                    "%(product)s has no %(what)s to choose from, so no "
                    "variant of it can be made.",
                    product=product_tmpl.display_name, what=label)
            if value not in options:
                return _(
                    "%(product)s has no '%(wanted)s' %(what)s; "
                    "available: %(options)s.",
                    product=product_tmpl.display_name, wanted=value.name,
                    what=label,
                    options=', '.join(sorted(options.mapped('name'))))
        return ''

    @api.model
    def _variant_for(self, product_tmpl, thickness, finish):
        """Get-or-create the variant for a template + thickness + finish.

        Pulled out of _compute_product_id so the explosion engine can ask
        for the SAME combination with a different finish -- the design's
        -- without a second copy of the mapping from product.attribute.value
        to the template-scoped product.template.attribute.value, which is
        the part that is easy to get subtly wrong.
        """
        if not (product_tmpl and thickness and finish):
            return self.env['product.product']
        combination = self.env['product.template.attribute.value']
        for attribute_value in (thickness, finish):
            combination |= product_tmpl.attribute_line_ids.product_template_value_ids.filtered(
                lambda v, attribute_value=attribute_value: v.product_attribute_value_id == attribute_value
            )
        variant = product_tmpl._create_product_variant(combination)
        # A variant that has just come into existence has no cost yet,
        # and the rate for it is already known. Only ever fills; a
        # variant with no rate is left alone.
        if variant and not variant.standard_price:
            variant._aw_sync_cost_from_rate()
        return variant

