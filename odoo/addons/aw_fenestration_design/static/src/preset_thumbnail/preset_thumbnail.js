import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * One drawing routine for preset thumbnails, shared by the configurator's
 * library and the backend field widget.
 *
 * It lived as a method on DesignConfigurator; the kanban views need the
 * same picture, and a second copy would drift from the first the moment
 * either changed.
 */
export const THUMB_W = 58;
export const THUMB_H = 42;
const FRAME_FACE = 2.5;

export function presetThumb(layout, width = THUMB_W, height = THUMB_H) {
    const rects = [];
    if (!layout || !Array.isArray(layout.rows) || !layout.rows.length) {
        return {
            viewBox: `0 0 ${width} ${height}`,
            frame: { W: width, H: height },
            rects,
            empty: true,
        };
    }

    // Recurses, so a preset containing a nested split shows that split
    // rather than a single flat panel.
    const tile = (rowList, box) => {
        const totH = rowList.reduce((a, r) => a + (r.h || 1), 0) || 1;
        let y = box.y;
        for (const row of rowList) {
            const rh = ((row.h || 1) / totH) * box.h;
            const leaves = row.leaves || [];
            const totW = leaves.reduce((a, l) => a + (l.w || 1), 0) || 1;
            let x = box.x;
            for (const leaf of leaves) {
                const lw = ((leaf.w || 1) / totW) * box.w;
                if (leaf.rows && leaf.rows.length) {
                    tile(leaf.rows, { x, y, w: lw, h: rh });
                } else {
                    rects.push({
                        key: `${rects.length}`,
                        x: x + 1,
                        y: y + 1,
                        w: Math.max(1, lw - 2),
                        h: Math.max(1, rh - 2),
                        isMesh: leaf.type === "MESH",
                    });
                }
                x += lw;
            }
            y += rh;
        }
    };

    tile(layout.rows, {
        x: FRAME_FACE,
        y: FRAME_FACE,
        w: width - 2 * FRAME_FACE,
        h: height - 2 * FRAME_FACE,
    });
    return {
        viewBox: `0 0 ${width} ${height}`,
        frame: { W: width, H: height },
        rects,
        empty: false,
    };
}

/**
 * Backend field widget: draws a preset's layout_json.
 *
 * Registered as `preset_thumbnail`, used on the Layout Presets kanban
 * and on the family kanban's fallback picture.
 */
export class PresetThumbnailField extends Component {
    static template = "aw_fenestration_design.PresetThumbnailField";
    static props = { ...standardFieldProps };

    get thumb() {
        const raw = this.props.record.data[this.props.name];
        let layout = null;
        try {
            layout = raw ? JSON.parse(raw) : null;
        } catch {
            // A malformed layout is a data problem, not a rendering one:
            // show the empty frame rather than breaking the whole kanban.
            layout = null;
        }
        return presetThumb(layout);
    }
}

registry.category("fields").add("preset_thumbnail", {
    component: PresetThumbnailField,
    supportedTypes: ["text", "char"],
});
