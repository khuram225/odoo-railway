import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { _t } from "@web/core/l10n/translation";

const MM_PER_IN = 25.4;
const MM_PER_FT = 304.8;

// Drawing geometry, ported from the prototype's draw() (~783).
const VIEW_W = 700;
const VIEW_H = 460;
const PAD_L = 64;
const PAD_T = 30;
const AREA_W = VIEW_W - PAD_L - 64;
const AREA_H = VIEW_H - PAD_T - 108;
// The prototype reads frameFace off its SERIES table (90-150mm). That
// table is master data we deliberately don't port -- and aw.window.series
// has no equivalent field -- so this is a drawing-only approximation,
// not a number anything is calculated from. If the real face width ever
// matters visually, it wants a field on aw.window.series, not a constant.
const FRAME_FACE_MM = 100;
const MIN_LEAF_MM = 4 * MM_PER_IN; // prototype's IN(4) drag floor

/**
 * Visual design configurator.
 *
 * Stage B: everything except the SVG itself, which is Stage C -- the
 * drawing area below is a placeholder on purpose, so the load/edit/save
 * round trip can be verified before the drawing code exists.
 */
export class DesignConfigurator extends Component {
    static template = "aw_fenestration_design.DesignConfigurator";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");

        this.designId =
            this.props.action.params?.design_id ||
            this.props.action.context?.active_id;

        this.state = useState({
            loading: true,
            dirty: false,
            data: null,
            selected: null, // {row: i, leaf: j}
        });

        // Not in state: a drag in progress isn't rendered directly, it only
        // mutates row/leaf sizes, which are.
        this.dragging = null;

        onWillStart(async () => {
            await this.load();
        });
    }

    async load() {
        this.state.data = await this.orm.call(
            "aw.design",
            "get_configurator_data",
            [[this.designId]]
        );
        this.state.loading = false;
        this.state.dirty = false;
        this.state.selected = null;
    }

    // -- unit rendering ----------------------------------------------------
    // Mirrors aw.design._format_length server-side. The unit is a global
    // setting, shown as a read-only label -- there is deliberately no
    // per-screen toggle.
    get uom() {
        return this.state.data?.length_uom || "ftin";
    }

    get uomLabel() {
        return { ftin: _t("ft + in"), in: _t("in"), mm: _t("mm") }[this.uom];
    }

    formatLength(mm) {
        const trim = (v) => String(Math.round(v * 100) / 100);
        if (this.uom === "mm") {
            return `${trim(mm)} mm`;
        }
        const totalIn = mm / MM_PER_IN;
        if (this.uom === "in") {
            return `${trim(totalIn)} in`;
        }
        const ft = Math.floor(totalIn / 12);
        return `${ft} ft ${trim(totalIn - ft * 12)} in`;
    }

    /** Parse what the user typed back into mm, in whatever unit is active. */
    parseLength(text) {
        const str = String(text || "").trim();
        if (!str) {
            return 0;
        }
        if (this.uom === "mm") {
            return parseFloat(str) || 0;
        }
        if (this.uom === "in") {
            return (parseFloat(str) || 0) * MM_PER_IN;
        }
        // ftin: "8 6" / "8ft 6in" / "8' 6" / plain "8" -> feet
        const nums = str.match(/-?\d+(\.\d+)?/g) || [];
        const ft = parseFloat(nums[0]) || 0;
        const inch = parseFloat(nums[1]) || 0;
        return ft * MM_PER_FT + inch * MM_PER_IN;
    }

    // -- header ------------------------------------------------------------
    onHeaderChange(field, value) {
        this.state.data.header[field] = value;
        this.state.dirty = true;
    }

    onDimensionChange(field, text) {
        this.state.data.header[field] = this.parseLength(text);
        this.state.dirty = true;
    }

    // -- selection ---------------------------------------------------------
    get selectedLeaf() {
        const sel = this.state.selected;
        if (!sel) {
            return null;
        }
        return this.state.data.rows[sel.row]?.leaves[sel.leaf] || null;
    }

    get selectedLeafType() {
        const leaf = this.selectedLeaf;
        if (!leaf) {
            return null;
        }
        return this.state.data.leaf_types.find(
            (lt) => lt.id === leaf.leaf_type_id
        );
    }

    selectLeaf(rowIndex, leafIndex) {
        this.state.selected = { row: rowIndex, leaf: leafIndex };
    }

    setLeafType(leafTypeId) {
        const leaf = this.selectedLeaf;
        if (!leaf) {
            return;
        }
        leaf.leaf_type_id = leafTypeId;
        const type = this.state.data.leaf_types.find(
            (lt) => lt.id === leafTypeId
        );
        leaf.leaf_type_code = type?.code || "";
        // Drop direction values the new type can't carry, so a casement
        // switched to fixed doesn't keep an invisible hinge side.
        if (!type?.has_hinge_side) {
            leaf.hinge_side = "";
            leaf.swing = "";
        }
        if (!type?.has_slide_dir) {
            leaf.slide_dir = "";
        }
        this.state.dirty = true;
    }

    setDirection(field, value) {
        const leaf = this.selectedLeaf;
        if (!leaf) {
            return;
        }
        leaf[field] = leaf[field] === value ? "" : value;
        this.state.dirty = true;
    }

    // -- presets -----------------------------------------------------------
    get presetsByCategory() {
        const groups = {};
        for (const preset of this.state.data?.presets || []) {
            const key = preset.category || _t("Other");
            (groups[key] = groups[key] || []).push(preset);
        }
        return Object.entries(groups).map(([category, presets]) => ({
            category,
            presets,
        }));
    }

    /**
     * Apply a preset's relative weights against this design's own overall
     * size. The prototype splits equally via normaliseRows(); weights
     * generalise that without changing the equal-split case.
     */
    applyPreset(preset) {
        const header = this.state.data.header;
        const layout = preset.layout;
        const totalH = layout.rows.reduce((sum, r) => sum + (r.h || 1), 0);
        const byCode = {};
        for (const lt of this.state.data.leaf_types) {
            byCode[lt.code] = lt;
        }
        this.state.data.rows = layout.rows.map((row) => {
            const totalW = row.leaves.reduce((sum, l) => sum + (l.w || 1), 0);
            return {
                height_mm: (header.height_mm * (row.h || 1)) / totalH,
                is_auto: false,
                leaves: row.leaves.map((leaf) => {
                    const type = byCode[leaf.type];
                    return {
                        width_mm: (header.width_mm * (leaf.w || 1)) / totalW,
                        is_auto: false,
                        leaf_type_id: type?.id || false,
                        leaf_type_code: leaf.type,
                        hinge_side: type?.has_hinge_side
                            ? leaf.hinge || ""
                            : "",
                        swing: type?.has_hinge_side ? leaf.swing || "" : "",
                        slide_dir: type?.has_slide_dir ? leaf.slide || "" : "",
                    };
                }),
            };
        });
        this.state.selected = null;
        this.state.dirty = true;
    }

    // -- drawing -----------------------------------------------------------
    // Port of the prototype's draw() / leafGlyph() / drawDim(). The
    // prototype builds SVG nodes imperatively with createElementNS; here
    // the same geometry is computed into a plain scene object and the
    // template renders it declaratively, so it re-renders reactively
    // whenever state changes instead of being torn down and rebuilt.
    get scene() {
        const data = this.state.data;
        if (!data) {
            return null;
        }
        const W = data.header.width_mm;
        const H = data.header.height_mm;
        // A design starts at 0 x 0 (dimensions are filled in after Add
        // Position), and the prototype's scale factor would be Infinity
        // there, putting NaN into every coordinate. Nothing to draw yet.
        if (!(W > 0) || !(H > 0)) {
            return null;
        }

        const s = Math.min(AREA_W / W, AREA_H / H);
        const w = W * s;
        const h = H * s;
        const x0 = PAD_L + (AREA_W - w) / 2;
        const y0 = PAD_T + (AREA_H - h) / 2;
        const ff = Math.max(4, FRAME_FACE_MM * s * 0.4);

        const leaves = [];
        const dividers = [];
        const dims = [];
        const rows = data.rows;
        const totH = rows.reduce((a, r) => a + (r.height_mm || 0), 0) || 1;

        let ry = y0 + ff;
        rows.forEach((row, ri) => {
            const rh = ((row.height_mm || 0) / totH) * (h - 2 * ff);
            const totW =
                row.leaves.reduce((a, l) => a + (l.width_mm || 0), 0) || 1;
            const iw = w - 2 * ff;
            let rx = x0 + ff;

            row.leaves.forEach((leaf, li) => {
                const lw = ((leaf.width_mm || 0) / totW) * iw;
                const sw = Math.max(3, 7 * s);
                const selected =
                    this.state.selected &&
                    this.state.selected.row === ri &&
                    this.state.selected.leaf === li;
                leaves.push({
                    key: `${ri}-${li}`,
                    ri,
                    li,
                    x: rx,
                    y: ry,
                    w: lw,
                    h: rh,
                    glassX: rx + sw,
                    glassY: ry + sw,
                    glassW: Math.max(1, lw - 2 * sw),
                    glassH: Math.max(1, rh - 2 * sw),
                    isMesh: leaf.leaf_type_code === "MESH",
                    selected,
                    glyph: this.leafGlyph(rx, ry, lw, rh, leaf),
                });

                if (li < row.leaves.length - 1) {
                    dividers.push({
                        key: `v-${ri}-${li}`,
                        kind: "v",
                        ri,
                        li,
                        x1: rx + lw,
                        y1: ry + 3,
                        x2: rx + lw,
                        y2: ry + rh - 3,
                        hitX: rx + lw - 6,
                        hitY: ry,
                        hitW: 12,
                        hitH: rh,
                    });
                }
                rx += lw;
            });

            if (ri < rows.length - 1) {
                dividers.push({
                    key: `h-${ri}`,
                    kind: "h",
                    ri,
                    li: null,
                    x1: x0 + ff + 3,
                    y1: ry + rh,
                    x2: x0 + w - ff - 3,
                    y2: ry + rh,
                    hitX: x0 + ff,
                    hitY: ry + rh - 6,
                    hitW: w - 2 * ff,
                    hitH: 12,
                });
            }
            ry += rh;
        });

        // Dimension lines: per-row leaf widths for any row with more than
        // one leaf, then the overall width; row heights down the left if
        // there's more than one row, else the single overall height.
        let dy = y0 + h + 18;
        rows.forEach((row) => {
            if (row.leaves.length > 1) {
                const totW =
                    row.leaves.reduce((a, l) => a + (l.width_mm || 0), 0) || 1;
                const iw = w - 2 * ff;
                let cx = x0 + ff;
                row.leaves.forEach((leaf, li) => {
                    const lw = ((leaf.width_mm || 0) / totW) * iw;
                    dims.push(
                        this.dim(
                            `w-${dy}-${li}`,
                            cx,
                            dy,
                            cx + lw,
                            dy,
                            this.formatLength(leaf.width_mm || 0),
                            false
                        )
                    );
                    cx += lw;
                });
                dy += 20;
            }
        });
        dims.push(
            this.dim("W", x0, dy, x0 + w, dy, this.formatLength(W), false)
        );

        if (rows.length > 1) {
            let ry2 = y0 + ff;
            rows.forEach((row, ri) => {
                const rh = ((row.height_mm || 0) / totH) * (h - 2 * ff);
                dims.push(
                    this.dim(
                        `h-${ri}`,
                        x0 - 22,
                        ry2,
                        x0 - 22,
                        ry2 + rh,
                        this.formatLength(row.height_mm || 0),
                        true
                    )
                );
                ry2 += rh;
            });
        } else {
            dims.push(
                this.dim(
                    "H",
                    x0 - 22,
                    y0,
                    x0 - 22,
                    y0 + h,
                    this.formatLength(H),
                    true
                )
            );
        }

        return {
            viewBox: `0 0 ${VIEW_W} ${VIEW_H}`,
            frame: { x: x0, y: y0, w, h },
            baseline: {
                x1: x0 - 10,
                y1: y0 + h + 8,
                x2: x0 + w + 10,
                y2: y0 + h + 8,
            },
            leaves,
            dividers,
            dims,
            pxPerMmX: w / W,
            pxPerMmY: h / H,
        };
    }

    /** Port of drawDim(): line, end ticks, and a label on a knock-out box. */
    dim(key, x1, y1, x2, y2, text, vert) {
        const mx = (x1 + x2) / 2;
        const my = (y1 + y2) / 2;
        const bw = String(text).length * 6.1 + 6;
        return {
            key,
            x1,
            y1,
            x2,
            y2,
            vert,
            text,
            ticks: [
                [x1, y1],
                [x2, y2],
            ].map(([x, y], i) => ({
                key: `${key}-t${i}`,
                x1: vert ? x - 3.5 : x,
                y1: vert ? y : y - 3.5,
                x2: vert ? x + 3.5 : x,
                y2: vert ? y : y + 3.5,
            })),
            boxX: vert ? mx - 6 : mx - bw / 2,
            boxY: vert ? my - bw / 2 : my - 7,
            boxW: vert ? 12 : bw,
            boxH: vert ? bw : 14,
            textX: mx,
            textY: my,
            transform: vert ? `rotate(-90 ${mx} ${my})` : "",
        };
    }

    /** Port of leafGlyph(): slide arrow, hinge fan + IN/OUT tag, MESH label. */
    leafGlyph(x, y, w, h, leaf) {
        const type = this.state.data.leaf_types.find(
            (lt) => lt.id === leaf.leaf_type_id
        );
        const glyph = { arrow: null, fan: null, label: null };

        if (type?.has_slide_dir && leaf.leaf_type_code !== "MESH") {
            const dir = leaf.slide_dir === "left" ? -1 : 1;
            const cx = x + w / 2;
            const cy = y + h / 2;
            const aw = Math.min(w * 0.32, 24);
            glyph.arrow = `M${cx - aw * dir},${cy} L${cx + aw * dir},${cy} M${
                cx + aw * dir
            },${cy} l${-5 * dir},-4 M${cx + aw * dir},${cy} l${-5 * dir},4`;
        } else if (type?.has_hinge_side) {
            const points = {
                left: [x, y + h / 2],
                right: [x + w, y + h / 2],
                top: [x + w / 2, y],
                bottom: [x + w / 2, y + h],
            };
            const hp = points[leaf.hinge_side] || points.left;
            glyph.fan = {
                cx: hp[0],
                cy: hp[1],
                lines: [
                    [x + 2, y + 2],
                    [x + w - 2, y + 2],
                    [x + w - 2, y + h - 2],
                    [x + 2, y + h - 2],
                ].map(([cx, cy], i) => ({
                    key: i,
                    x1: hp[0],
                    y1: hp[1],
                    x2: cx,
                    y2: cy,
                })),
                tagX: x + w / 2,
                tagY: y + h - 6,
                tag: (leaf.swing || "out").toUpperCase(),
            };
        }

        if (leaf.leaf_type_code === "MESH") {
            glyph.label = { x: x + w / 2, y: y + 12, text: "MESH" };
        }
        return glyph;
    }

    // -- divider dragging --------------------------------------------------
    onDividerPointerDown(divider, ev) {
        ev.preventDefault();
        ev.target.setPointerCapture(ev.pointerId);
        const rows = this.state.data.rows;
        if (divider.kind === "v") {
            const leaves = rows[divider.ri].leaves;
            this.dragging = {
                kind: "v",
                ri: divider.ri,
                li: divider.li,
                start: ev.clientX,
                a: leaves[divider.li].width_mm,
                b: leaves[divider.li + 1].width_mm,
                pxPerMM: this.scene.pxPerMmX,
            };
        } else {
            this.dragging = {
                kind: "h",
                ri: divider.ri,
                start: ev.clientY,
                a: rows[divider.ri].height_mm,
                b: rows[divider.ri + 1].height_mm,
                pxPerMM: this.scene.pxPerMmY,
            };
        }
    }

    onPointerMove(ev) {
        const drag = this.dragging;
        if (!drag) {
            return;
        }
        const rows = this.state.data.rows;
        const raw =
            ((drag.kind === "v" ? ev.clientX : ev.clientY) - drag.start) /
            drag.pxPerMM;
        // Clamp so neither side of the divider goes below the minimum leaf
        // size -- straight from the prototype's pointermove handler.
        const delta = Math.max(
            MIN_LEAF_MM - drag.a,
            Math.min(drag.b - MIN_LEAF_MM, raw)
        );
        if (drag.kind === "v") {
            const leaves = rows[drag.ri].leaves;
            leaves[drag.li].width_mm = Math.round(drag.a + delta);
            leaves[drag.li + 1].width_mm = Math.round(drag.b - delta);
        } else {
            rows[drag.ri].height_mm = Math.round(drag.a + delta);
            rows[drag.ri + 1].height_mm = Math.round(drag.b - delta);
        }
        this.state.dirty = true;
    }

    onPointerUp() {
        this.dragging = null;
    }

    // -- save --------------------------------------------------------------
    async save() {
        const data = this.state.data;
        this.state.data = await this.orm.call("aw.design", "save_layout", [
            [this.designId],
            { header: data.header, rows: data.rows },
        ]);
        this.state.dirty = false;
        this.state.selected = null;
        this.notification.add(_t("Design saved."), { type: "success" });
    }

    openForm() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "aw.design",
            res_id: this.designId,
            view_mode: "form",
            views: [[false, "form"]],
        });
    }
}

registry.category("actions").add("aw_design_configurator", DesignConfigurator);
