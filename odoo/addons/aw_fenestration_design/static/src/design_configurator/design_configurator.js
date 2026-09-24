import {
    Component,
    onMounted,
    onWillStart,
    onWillUnmount,
    useRef,
    useState,
} from "@odoo/owl";
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

const ZOOM_MIN = 0.25;
const ZOOM_MAX = 4;
const ZOOM_STEP = 1.25;

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
            zoom: 1, // 1 = fitted to the canvas
            canvasW: 0,
            canvasH: 0,
            libraryOpen: true,
        });

        // Not in state: a drag in progress isn't rendered directly, it only
        // mutates row/leaf sizes, which are.
        this.dragging = null;
        this.panning = null;

        this.canvasRef = useRef("canvas");
        this.svgRef = useRef("svg");

        onWillStart(async () => {
            await this.load();
        });

        // The fitted size depends on the canvas's real pixel size, which
        // isn't known until it's laid out and changes with the window, the
        // sidebar, or anything else that reflows around it.
        onMounted(() => {
            this.resizeObserver = new ResizeObserver(() => this.measure());
            if (this.canvasRef.el) {
                this.resizeObserver.observe(this.canvasRef.el);
                this.measure();
            }
        });
        onWillUnmount(() => {
            this.resizeObserver?.disconnect();
            this.endDrag(); // never leave window listeners behind
        });
    }

    measure() {
        const el = this.canvasRef.el;
        if (!el) {
            return;
        }
        this.state.canvasW = el.clientWidth;
        this.state.canvasH = el.clientHeight;
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
        this.state.zoom = 1; // a freshly opened design starts fitted
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
    /**
     * Bound to input, separately from the change handlers below. "change"
     * only fires on blur, and clicking Save is what causes that blur, so
     * the click could land while Save was still disabled from the edit
     * that was never committed. Marking dirty on the first keystroke
     * makes the button available regardless of event ordering.
     */
    markDirty() {
        this.state.dirty = true;
    }

    onHeaderChange(field, value) {
        this.state.data.header[field] = value;
        this.state.dirty = true;
    }

    onDimensionChange(field, text) {
        const value = this.parseLength(text);
        this.state.data.header[field] = value;
        if (field === "width_mm") {
            this.rescaleWidths(value);
        } else {
            this.rescaleHeights(value);
        }
        this.state.dirty = true;
    }

    /**
     * Fit a list of current sizes to a new total.
     *
     * Without this, changing the overall width left the leaves at their
     * old sizes, so the drawing's proportions silently stopped matching
     * the dimensions printed on it.
     *
     * If exactly one entry is flagged Automatic it absorbs the whole
     * difference, which is what that flag means -- the others keep the
     * exact sizes someone deliberately set. Otherwise everything scales
     * proportionally.
     *
     * Sizes are NOT rounded to whole mm. Rounding 8 ft split in two gives
     * 1219mm a side, which renders as "3 ft 11.99 in" -- arithmetically
     * fine and obviously wrong to anyone reading it. The exact 1219.2
     * shows as "4 ft 0 in".
     */
    fitToTotal(sizes, autoFlags, total) {
        const n = sizes.length;
        if (!n || !(total > 0)) {
            return sizes;
        }
        const current = sizes.reduce((a, b) => a + (b || 0), 0);
        const autoIndex = autoFlags.reduce(
            (found, isAuto, i) =>
                isAuto ? (found === -1 ? i : -2) : found,
            -1
        );

        let next;
        if (autoIndex >= 0) {
            const others = sizes.reduce(
                (sum, v, i) => (i === autoIndex ? sum : sum + (v || 0)),
                0
            );
            next = sizes.slice();
            next[autoIndex] = Math.max(MIN_LEAF_MM, total - others);
        } else if (current > 0) {
            next = sizes.map((v) => ((v || 0) * total) / current);
        } else {
            next = sizes.map(() => total / n);
        }

        // Force an exact sum. The residue goes on the LARGEST entry, not
        // the last one: the last one may be the auto entry that was just
        // clamped up to the minimum, and subtracting the residue from it
        // would silently undo that clamp (it drove one to zero in
        // testing). The largest entry can absorb a fraction of a mm.
        const residue = total - next.reduce((a, b) => a + b, 0);
        if (residue) {
            let big = 0;
            for (let i = 1; i < n; i++) {
                if (next[i] > next[big]) {
                    big = i;
                }
            }
            next[big] += residue;
        }
        return next;
    }

    rescaleWidths(totalWidth) {
        for (const row of this.state.data.rows) {
            const sizes = this.fitToTotal(
                row.leaves.map((l) => l.width_mm),
                row.leaves.map((l) => l.is_auto),
                totalWidth
            );
            row.leaves.forEach((leaf, i) => {
                leaf.width_mm = sizes[i];
            });
        }
    }

    rescaleHeights(totalHeight) {
        const rows = this.state.data.rows;
        const sizes = this.fitToTotal(
            rows.map((r) => r.height_mm),
            rows.map((r) => r.is_auto),
            totalHeight
        );
        rows.forEach((row, i) => {
            row.height_mm = sizes[i];
        });
    }

    // -- selection ---------------------------------------------------------
    get selectedLeaf() {
        const sel = this.state.selected;
        if (!sel) {
            return null;
        }
        return this.state.data.rows[sel.row]?.leaves[sel.leaf] || null;
    }

    /** "Panel 2" / "Panel M3" — the same label the badge shows. */
    get selectedPanelLabel() {
        const sel = this.state.selected;
        if (!sel) {
            return "";
        }
        const entry = this.scene?.leaves.find(
            (l) => l.ri === sel.row && l.li === sel.leaf
        );
        return entry ? `Panel ${entry.badge.label}` : "";
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

    selectLeaf(rowIndex, leafIndex, ev) {
        // A click that ended a pan shouldn't also change the selection.
        ev?.stopPropagation();
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
     * A preset's layout drawn small: frame plus one rect per leaf, no
     * glyphs, dimensions or selection. Same tiling arithmetic as scene(),
     * against a fixed box instead of the design's real size -- a preset
     * has only relative weights, so there's nothing else it could use.
     */
    presetThumb(layout) {
        const W = 58;
        const H = 42;
        const ff = 2.5;
        const rects = [];
        const totH = layout.rows.reduce((a, r) => a + (r.h || 1), 0) || 1;
        let y = ff;
        for (const row of layout.rows) {
            const rh = ((row.h || 1) / totH) * (H - 2 * ff);
            const totW =
                row.leaves.reduce((a, l) => a + (l.w || 1), 0) || 1;
            let x = ff;
            for (const leaf of row.leaves) {
                const lw = ((leaf.w || 1) / totW) * (W - 2 * ff);
                rects.push({
                    key: `${rects.length}`,
                    x: x + 1,
                    y: y + 1,
                    w: Math.max(1, lw - 2),
                    h: Math.max(1, rh - 2),
                    isMesh: leaf.type === "MESH",
                });
                x += lw;
            }
            y += rh;
        }
        return { viewBox: `0 0 ${W} ${H}`, frame: { W, H }, rects };
    }

    toggleLibrary() {
        this.state.libraryOpen = !this.state.libraryOpen;
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
    //
    // THE DRAWING IS TWO LAYERS, AND THE ORDER MATTERS:
    //
    //   scene       pure drawing units. Frame, panels, divider positions,
    //               dimension lines, viewBox. Must NOT read unitsPerPixel,
    //               fitScale, zoom or canvas size -- including the viewBox
    //               margins, which is why M below is a plain constant.
    //   adornments  everything sized in screen pixels (badge radius and
    //               font, divider stroke and hit width), derived from
    //               scene AFTER the fact.
    //
    // fitScale reads scene.vbW/vbH, so anything scene reads back from
    // fitScale is a cycle. Sizing the panel badges inside scene() did
    // exactly that and crashed the configurator on open with
    // "Maximum call stack size exceeded":
    //     scene -> unitsPerPixel -> fitScale -> scene
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

        // Panel numbering mirrors aw.design._renumber_panels() exactly, so
        // numbers appear the moment a preset is applied rather than only
        // after a save. The server still renumbers authoritatively on save.
        let panelNo = 0;

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
                panelNo += 1;
                const isMesh = leaf.leaf_type_code === "MESH";
                leaves.push({
                    key: `${ri}-${li}`,
                    ri,
                    li,
                    panelNo,
                    // Position and label only -- the badge's RADIUS and FONT
                    // are screen-sized and live in `adornments`, which is
                    // computed after this. See the layering note on scene().
                    badge: {
                        cx: rx + lw / 2,
                        cy: ry + rh / 2,
                        // EvA marks mesh sashes M<n>; the counter is shared,
                        // so panel 3 being a mesh reads "M3".
                        label: isMesh ? `M${panelNo}` : String(panelNo),
                    },
                    x: rx,
                    y: ry,
                    w: lw,
                    h: rh,
                    glassX: rx + sw,
                    glassY: ry + sw,
                    glassW: Math.max(1, lw - 2 * sw),
                    glassH: Math.max(1, rh - 2 * sw),
                    isMesh,
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

        const baseline = {
            x1: x0 - 10,
            y1: y0 + h + 8,
            x2: x0 + w + 10,
            y2: y0 + h + 8,
        };

        // The viewBox is derived from what's actually drawn rather than
        // being a fixed 700x460. The frame is centred in a fixed area, but
        // dimension lines and their labels are placed OUTSIDE it -- below
        // the frame, and to the left for row heights -- so with a tall or
        // wide design they fell outside the fixed box and were clipped.
        // Measuring the content guarantees everything fits, whatever the
        // aspect ratio.
        let minX = Math.min(x0, baseline.x1);
        let minY = Math.min(y0, baseline.y1);
        let maxX = Math.max(x0 + w, baseline.x2);
        let maxY = Math.max(y0 + h, baseline.y2);
        for (const d of dims) {
            minX = Math.min(minX, d.x1, d.x2, d.boxX);
            minY = Math.min(minY, d.y1, d.y2, d.boxY);
            maxX = Math.max(maxX, d.x1, d.x2, d.boxX + d.boxW);
            maxY = Math.max(maxY, d.y1, d.y2, d.boxY + d.boxH);
            for (const t of d.ticks) {
                minX = Math.min(minX, t.x1, t.x2);
                minY = Math.min(minY, t.y1, t.y2);
                maxX = Math.max(maxX, t.x1, t.x2);
                maxY = Math.max(maxY, t.y1, t.y2);
            }
        }
        const M = 12;
        const vbW = maxX - minX + 2 * M;
        const vbH = maxY - minY + 2 * M;
        return {
            viewBox: `${minX - M} ${minY - M} ${vbW} ${vbH}`,
            vbW,
            vbH,
            frame: { x: x0, y: y0, w, h },
            baseline,
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

    // -- zoom / fit --------------------------------------------------------
    /** Canvas pixels per viewBox unit at which the drawing exactly fits. */
    get fitScale() {
        const scene = this.scene;
        if (!scene || !this.state.canvasW || !this.state.canvasH) {
            return 1;
        }
        // min(), not max(): the drawing is letterboxed inside the canvas so
        // BOTH dimensions fit. Fitting width alone is what let a tall
        // design run off the bottom.
        return Math.min(
            this.state.canvasW / scene.vbW,
            this.state.canvasH / scene.vbH
        );
    }

    /** Rendered CSS size. At zoom 1 this fits exactly; above it, the
     *  container scrolls, which is what makes panning work. */
    get renderedSize() {
        const scene = this.scene;
        if (!scene) {
            return { w: 0, h: 0 };
        }
        const k = this.fitScale * this.state.zoom;
        return { w: scene.vbW * k, h: scene.vbH * k };
    }

    get zoomPercent() {
        return Math.round(this.state.zoom * 100);
    }

    setZoom(value) {
        this.state.zoom = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, value));
    }

    zoomIn() {
        this.setZoom(this.state.zoom * ZOOM_STEP);
    }

    zoomOut() {
        this.setZoom(this.state.zoom / ZOOM_STEP);
    }

    zoomFit() {
        this.setZoom(1);
    }

    onWheel(ev) {
        // Only with Ctrl held, so ordinary wheel scrolling still pans a
        // zoomed-in drawing instead of being hijacked.
        if (!ev.ctrlKey) {
            return;
        }
        ev.preventDefault();
        if (ev.deltaY < 0) {
            this.zoomIn();
        } else {
            this.zoomOut();
        }
    }

    // -- dragging ----------------------------------------------------------
    /**
     * Client (CSS pixel) coordinates -> SVG user-space coordinates.
     *
     * The drag maths used to divide a clientX delta by the scene's
     * units-per-mm, which silently assumed one viewBox unit rendered as
     * exactly one CSS pixel. That was already wrong whenever the drawing
     * was scaled to fit, and zoom would have multiplied the error.
     * getScreenCTM() is the actual current mapping, so it accounts for
     * fit scale, zoom and scroll position together.
     */
    clientToUser(ev) {
        const svg = this.svgRef.el;
        const ctm = svg?.getScreenCTM();
        if (!ctm) {
            return null;
        }
        return new DOMPoint(ev.clientX, ev.clientY).matrixTransform(
            ctm.inverse()
        );
    }

    /**
     * One viewBox unit in CSS pixels, for the adornment layer only.
     *
     * A divider drawn 1.2 units wide with a 12-unit hit area looked fine
     * at one particular scale and became a near-invisible sliver once the
     * drawing was scaled down to fit. Dividing by the live scale keeps
     * such things constant in CSS pixels at any fit or zoom level.
     *
     * Reads fitScale, therefore scene. Nothing scene touches may call it.
     */
    get unitsPerPixel() {
        const k = this.fitScale * this.state.zoom;
        return k > 0 ? 1 / k : 1;
    }

    /**
     * The screen-sized layer: everything that must stay the same physical
     * size however the drawing is scaled. Computed from scene, never the
     * other way round.
     */
    get adornments() {
        const scene = this.scene;
        if (!scene) {
            return { badgeR: 0, badgeFont: 0, dividers: [] };
        }
        const upp = this.unitsPerPixel;
        const hit = 14 * upp; // ~14 CSS px, comfortably grabbable
        const stroke = 2 * upp;
        return {
            badgeR: 11 * upp,
            badgeFont: 11 * upp,
            dividers: scene.dividers.map((d) => ({
                ...d,
                stroke,
                hitX: d.kind === "v" ? d.x1 - hit / 2 : d.x1,
                hitY: d.kind === "v" ? d.y1 : d.y1 - hit / 2,
                hitW: d.kind === "v" ? hit : d.x2 - d.x1,
                hitH: d.kind === "v" ? d.y2 - d.y1 : hit,
            })),
        };
    }

    onDividerPointerDown(divider, ev) {
        ev.preventDefault();
        ev.stopPropagation(); // don't also start a background pan
        const point = this.clientToUser(ev);
        if (!point) {
            return;
        }
        // Listen on window for the duration of the drag, exactly as the
        // prototype does. Relying on the events bubbling back to the
        // canvas was the bug: the canvas also had a pointerleave handler
        // that ended the drag, so the first move outside the element -- or
        // any boundary event produced by pointer capture -- killed it
        // immediately. Window listeners also mean a release anywhere on
        // the page still ends the drag cleanly.
        this._onWindowMove = (e) => this.onPointerMove(e);
        this._onWindowUp = () => this.endDrag();
        window.addEventListener("pointermove", this._onWindowMove);
        window.addEventListener("pointerup", this._onWindowUp);
        window.addEventListener("pointercancel", this._onWindowUp);

        const rows = this.state.data.rows;
        if (divider.kind === "v") {
            const leaves = rows[divider.ri].leaves;
            this.dragging = {
                kind: "v",
                ri: divider.ri,
                li: divider.li,
                start: point.x,
                a: leaves[divider.li].width_mm,
                b: leaves[divider.li + 1].width_mm,
                unitsPerMM: this.scene.pxPerMmX,
            };
        } else {
            this.dragging = {
                kind: "h",
                ri: divider.ri,
                start: point.y,
                a: rows[divider.ri].height_mm,
                b: rows[divider.ri + 1].height_mm,
                unitsPerMM: this.scene.pxPerMmY,
            };
        }
    }

    endDrag() {
        this.dragging = null;
        window.removeEventListener("pointermove", this._onWindowMove);
        window.removeEventListener("pointerup", this._onWindowUp);
        window.removeEventListener("pointercancel", this._onWindowUp);
    }

    // -- panning -----------------------------------------------------------
    onCanvasPointerDown(ev) {
        // Only from empty background, and only when there's somewhere to
        // pan to. Leaves and dividers stop propagation before this.
        const el = this.canvasRef.el;
        if (
            !el ||
            (el.scrollWidth <= el.clientWidth &&
                el.scrollHeight <= el.clientHeight)
        ) {
            return;
        }
        this.panning = {
            x: ev.clientX,
            y: ev.clientY,
            left: el.scrollLeft,
            top: el.scrollTop,
        };
        el.style.cursor = "grabbing";
    }

    onPointerMove(ev) {
        if (this.panning) {
            const el = this.canvasRef.el;
            el.scrollLeft = this.panning.left - (ev.clientX - this.panning.x);
            el.scrollTop = this.panning.top - (ev.clientY - this.panning.y);
            return;
        }
        const drag = this.dragging;
        if (!drag) {
            return;
        }
        const point = this.clientToUser(ev);
        if (!point) {
            return;
        }
        const rows = this.state.data.rows;
        const raw =
            ((drag.kind === "v" ? point.x : point.y) - drag.start) /
            drag.unitsPerMM;
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
        // Only ends a pan. A divider drag is ended by endDrag(), via the
        // window listeners, so releasing outside the canvas still works.
        if (this.panning) {
            this.panning = null;
            if (this.canvasRef.el) {
                this.canvasRef.el.style.cursor = "";
            }
        }
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
