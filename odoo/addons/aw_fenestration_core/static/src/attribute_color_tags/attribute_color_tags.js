/** @odoo-module **/

/**
 * Attribute-value tags painted with their own html_color.
 *
 * Odoo's many2many_tags colours tags from the INTEGER `color` index, a
 * 12-entry palette. For Finish that reads as random: the tag for
 * "Brown PC Sahara" is whatever index it happened to get, not brown.
 * The values already carry an accurate `html_color` (they have to, for
 * the sale configurator's swatches), so this uses it.
 *
 * Verified before building on it: `many2ManyTagsField.relatedFields`
 * is what tells the ORM to load extra fields on the tag records, and
 * it hardcodes the colour field as `type: "integer"` --
 * web/static/src/views/fields/many2many_tags/many2many_tags_field.js.
 * So `html_color` needs its own entry declared as `char`; reusing
 * `color_field` would load it as an integer and hand back nothing
 * useful.
 *
 * The template is a PRIMARY inherit that replaces only the <TagsList/>
 * node. Extending `web.TagsList` itself would have been less code but
 * would alter every tag list in the system; a broken xpath there takes
 * the whole backend with it, and this project has already lost a
 * deploy to each of three different view-inheritance assumptions.
 * Primary inherit fails alone.
 */
import { registry } from "@web/core/registry";
import {
    Many2ManyTagsField,
    many2ManyTagsField,
} from "@web/views/fields/many2many_tags/many2many_tags_field";

/**
 * Black or white, whichever stays readable on this background.
 *
 * Perceived brightness (ITU-R BT.601 weighting) rather than a plain
 * average: the eye is far more sensitive to green than to blue, so an
 * average calls #0000FF light and puts black text on navy.
 */
export function readableTextOn(hex) {
    const match = /^#?([0-9a-fA-F]{6})$/.exec((hex || "").trim());
    if (!match) {
        return "";
    }
    const value = parseInt(match[1], 16);
    const red = (value >> 16) & 255;
    const green = (value >> 8) & 255;
    const blue = value & 255;
    const brightness = (red * 299 + green * 587 + blue * 114) / 1000;
    return brightness > 140 ? "#111111" : "#ffffff";
}

export class AttributeColorTagsField extends Many2ManyTagsField {
    static template = "aw_fenestration_core.AttributeColorTagsField";

    getTagProps(record) {
        const props = super.getTagProps(record);
        const colour = record.data.html_color;
        const text = readableTextOn(colour);
        // No colour, or one we cannot parse, leaves `style` undefined
        // and the tag renders exactly as it does everywhere else.
        if (colour && text) {
            props.style =
                `background-color:${colour};color:${text};` +
                `border:1px solid rgba(0,0,0,.25);`;
        }
        return props;
    }
}

export const attributeColorTagsField = {
    ...many2ManyTagsField,
    component: AttributeColorTagsField,
    relatedFields: (fieldInfo) => [
        ...many2ManyTagsField.relatedFields(fieldInfo),
        { name: "html_color", type: "char", readonly: true },
    ],
};

registry
    .category("fields")
    .add("aw_attribute_color_tags", attributeColorTagsField);
