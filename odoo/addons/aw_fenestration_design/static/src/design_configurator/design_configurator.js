import {
    Component,
    onMounted,
    onPatched,
    onWillStart,
    onWillUnmount,
    useRef,
    useState,
} from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { _t } from "@web/core/l10n/translation";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

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
// Drawn width of a mullion. A constant for now; it properly belongs to
// the mullion profile's section size, which arrives with the BOM rules in
// spec section 6.2.
const MULLION_WIDTH_MM = 60;

const MAX_DEPTH = 3; // matches aw.design.MAX_NESTING_DEPTH

// A panel is addressed by its PATH: [[rowIndex, leafIndex], ...] from the
// top of the tree. ri/li alone stopped being unique once panels could be
// subdivided.
const pathKey = (path) => path.map((p) => p.join("-")).join("/");
const samePath = (a, b) =>
    !!a && !!b && a.length === b.length && pathKey(a) === pathKey(b);

const HINGED_CODES = ["CASEMENT", "TILTTURN"];

/** Mirror of aw.design.leaf._default_junction. Keep the two in step. */
function defaultJunction(left, right) {
    if (!right) {
        return false;
    }
    if (left.leaf_type_code === "SLIDER" && right.leaf_type_code === "SLIDER") {
        return "interlock";
    }
    if (
        HINGED_CODES.includes(left.leaf_type_code) &&
        HINGED_CODES.includes(right.leaf_type_code) &&
        left.hinge_side === "left" &&
        right.hinge_side === "right"
    ) {
        return "meeting";
    }
    return "mullion";
}

const ZOOM_MIN = 0.25;
const ZOOM_MAX = 4;
const ZOOM_STEP = 1.25;

/**
 * Visual design configurator: the everyday editing screen for a design.
 *
 * Reads and writes the existing aw.design / row / leaf records through
 * two server methods -- get_configurator_data() to load and
 * save_layout() to store the whole tree in one transaction.
 */
export class DesignConfigurator extends Component {
    static template = "aw_fenestration_design.DesignConfigurator";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");
        this.dialog = useService("dialog");

        this.designId =
            this.props.action.params?.design_id ||
            this.props.action.context?.active_id;

        this.state = useState({
            loading: true,
            dirty: false,
            data: null,
            selected: null, // path: [[rowIdx, leafIdx], ...]
            selectedDivider: null, // divider key
            zoom: 1, // 1 = fitted to the canvas
            canvasW: 0,
            canvasH: 0,
            libraryOpen: true,
            builderOpen: false,
            builder: { panels: 2, tracks: 2, mesh: false, roles: [] },
            // Screen-space position of the floating toolbar, in CSS
            // pixels relative to the canvas viewport. Measured from the
            // DOM rather than derived, so it survives zoom and scroll.
            toolbar: { show: false, left: 0, top: 0 },
        });

        // Not in state: a drag in progress isn't rendered directly, it only
        // mutates row/leaf sizes, which are.
        this.dragging = null;
        this.panning = null;

        this.canvasRef = useRef("canvas");
        this.svgRef = useRef("svg");
        this.toolbarRef = useRef("toolbar");

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
        // After every render: the drawing may have moved (zoom, resize,
        // a split) and the toolbar has to follow it.
        onPatched(() => this.updateToolbar());

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
        this.state.selectedDivider = null;
        this.state.zoom = 1; // a freshly opened design starts fitted
        // Derive any junction the stored data doesn't have. Existing
        // designs pre-date junction_after entirely, so without this every
        // boundary drew as a mullion however its panels were hinged.
        // Only fills blanks -- a junction someone chose is left alone.
        this.fillMissingJunctions(this.state.data.rows);
    }

    /** Set junction_after only where it is empty. */
    fillMissingJunctions(rows) {
        for (const row of rows) {
            row.leaves.forEach((leaf, i) => {
                const next = row.leaves[i + 1] || null;
                if (!next) {
                    leaf.junction_after = "";
                } else if (!leaf.junction_after) {
                    leaf.junction_after = defaultJunction(leaf, next);
                }
                if (leaf.rows && leaf.rows.length) {
                    this.fillMissingJunctions(leaf.rows);
                }
            });
        }
    }

    /**
     * Re-derive the junctions in the row holding `path`, after something
     * that feeds the rule changed. Scoped to that row so a junction
     * chosen by hand elsewhere in the design survives.
     */
    refreshJunctionsAround(path) {
        if (!path || !path.length) {
            return;
        }
        const rows = this.rowsAt(path.slice(0, -1));
        const row = rows[path[path.length - 1][0]];
        if (!row) {
            return;
        }
        row.leaves.forEach((leaf, i) => {
            const next = row.leaves[i + 1] || null;
            leaf.junction_after = next ? defaultJunction(leaf, next) : "";
        });
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

    // -- Series -------------------------------------------------------------
    get seriesOptions() {
        return this.state.data?.series_options || [];
    }

    /** Leaf type codes used anywhere in the layout, containers skipped. */
    usedLeafTypeCodes(rows) {
        const codes = new Set();
        const walk = (list) => {
            for (const row of list) {
                for (const leaf of row.leaves) {
                    if (leaf.rows && leaf.rows.length) {
                        walk(leaf.rows);
                    } else if (leaf.leaf_type_code) {
                        codes.add(leaf.leaf_type_code);
                    }
                }
            }
        };
        walk(rows);
        return codes;
    }

    async onSeriesChange(seriesId) {
        const id = parseInt(seriesId, 10);
        const option = this.seriesOptions.find((o) => o.id === id);
        if (!option) {
            return;
        }
        const allowed = new Set(option.leaf_type_codes);
        const used = this.usedLeafTypeCodes(this.state.data.rows);
        const unsupported = [...used].filter((c) => !allowed.has(c));

        if (!unsupported.length) {
            await this.applySeries(id, { reset: false });
            return;
        }
        // The layout can't survive the switch. Ask rather than silently
        // discarding work, and leave the old Series in place on cancel.
        this.dialog.add(ConfirmationDialog, {
            title: _t("Change Window Series"),
            body: _t(
                "%(series)s does not allow %(types)s, which this design " +
                    "uses. Reset layout to a single panel?",
                { series: option.name, types: unsupported.join(", ") }
            ),
            confirmLabel: _t("Reset layout"),
            confirm: () => this.applySeries(id, { reset: true }),
            cancel: () => {},
        });
    }

    async applySeries(seriesId, { reset }) {
        const context = await this.orm.call(
            "aw.design",
            "get_series_context",
            [seriesId]
        );
        const option = this.seriesOptions.find((o) => o.id === seriesId);
        this.state.data.header.window_series_id = seriesId;
        this.state.data.header.window_series_name = option ? option.name : "";
        this.state.data.leaf_types = context.leaf_types;
        this.state.data.presets = context.presets;

        if (reset) {
            const first = context.leaf_types[0];
            this.state.data.rows = [{
                height_mm: this.state.data.header.height_mm,
                is_auto: false,
                leaves: [{
                    width_mm: this.state.data.header.width_mm,
                    is_auto: false,
                    leaf_type_id: first ? first.id : false,
                    leaf_type_code: first ? first.code : "",
                    hinge_side: "",
                    swing: "",
                    slide_dir: "",
                    junction_after: "",
                    rows: [],
                }],
            }];
        }
        this.state.selected = null;
        this.state.selectedDivider = null;
        this.state.dirty = true;
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

    // Both recurse: a container's children have to be refitted to the
    // container's NEW size, or a nested split stops adding up as soon as
    // the overall dimensions change.
    rescaleWidths(totalWidth) {
        const walk = (rows, total) => {
            for (const row of rows) {
                const sizes = this.fitToTotal(
                    row.leaves.map((l) => l.width_mm),
                    row.leaves.map((l) => l.is_auto),
                    total
                );
                row.leaves.forEach((leaf, i) => {
                    leaf.width_mm = sizes[i];
                    if (leaf.rows && leaf.rows.length) {
                        walk(leaf.rows, sizes[i]);
                    }
                });
            }
        };
        walk(this.state.data.rows, totalWidth);
    }

    rescaleHeights(totalHeight) {
        const walk = (rows, total) => {
            const sizes = this.fitToTotal(
                rows.map((r) => r.height_mm),
                rows.map((r) => r.is_auto),
                total
            );
            rows.forEach((row, i) => {
                row.height_mm = sizes[i];
                for (const leaf of row.leaves) {
                    if (leaf.rows && leaf.rows.length) {
                        walk(leaf.rows, sizes[i]);
                    }
                }
            });
        };
        walk(this.state.data.rows, totalHeight);
    }

    // -- tree navigation ---------------------------------------------------
    /** The row list a path points INTO (i.e. the container's rows). */
    rowsAt(path) {
        let rows = this.state.data.rows;
        for (const [ri, li] of path) {
            rows = rows[ri]?.leaves[li]?.rows || [];
        }
        return rows;
    }

    /** The leaf a path points AT. */
    leafAt(path) {
        if (!path || !path.length) {
            return null;
        }
        let rows = this.state.data.rows;
        let leaf = null;
        for (const [ri, li] of path) {
            leaf = rows[ri]?.leaves[li] || null;
            if (!leaf) {
                return null;
            }
            rows = leaf.rows || [];
        }
        return leaf;
    }

    // -- selection ---------------------------------------------------------
    //
    // Exactly three states, and the template branches on selectionMode
    // rather than poking at state.selected. The template must NOT read
    // state.selected directly: it is a PATH now, so the old
    // state.selected.row read undefined for a panel (rendering "Row NaN")
    // and threw outright for a divider, where it is null -- which is what
    // crashed on zoom, since any re-render hit it.
    get selectionMode() {
        if (this.selectedPanel) {
            return "panel";
        }
        if (this.selectedDividerEntry) {
            return "divider";
        }
        return "none";
    }

    /** The selected panel's data, or null. */
    get selectedPanel() {
        return this.leafAt(this.state.selected);
    }

    /** Kept as an alias: plenty of internal callers still say leaf. */
    get selectedLeaf() {
        return this.selectedPanel;
    }

    /**
     * The selected panel's size as text. A leaf carries only its width --
     * height belongs to the row holding it -- so this reads both from the
     * tree rather than from the leaf alone.
     */
    get selectedPanelSize() {
        const path = this.state.selected;
        const leaf = this.selectedPanel;
        if (!leaf || !path || !path.length) {
            return "";
        }
        const rows = this.rowsAt(path.slice(0, -1));
        const row = rows[path[path.length - 1][0]];
        if (!row) {
            return "";
        }
        return `${this.formatLength(leaf.width_mm || 0)} \u00d7 ${this.formatLength(
            row.height_mm || 0
        )}`;
    }

    get canSplit() {
        // Splitting a leaf at depth d creates rows at depth d+1, so a leaf
        // already at the limit can't be split again.
        return !!this.state.selected && this.state.selected.length < MAX_DEPTH;
    }

    get canRemove() {
        // Never leave a design with nothing in it.
        const sel = this.state.selected;
        if (!sel) {
            return false;
        }
        if (sel.length > 1) {
            return true;
        }
        return this.scene ? this.scene.leaves.length > 1 : false;
    }

    /** "Panel 2" / "Panel M3" — the same label the badge shows. */
    get selectedPanelLabel() {
        const entry = this.selectedSceneLeaf;
        return entry ? `Panel ${entry.badge.label}` : "";
    }

    get selectedSceneLeaf() {
        const sel = this.state.selected;
        if (!sel || !this.scene) {
            return null;
        }
        return (
            this.scene.leaves.find((l) => samePath(l.path, sel)) || null
        );
    }

    get selectedDividerEntry() {
        const key = this.state.selectedDivider;
        if (!key || !this.scene) {
            return null;
        }
        return this.scene.dividers.find((d) => d.key === key) || null;
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

    selectLeaf(path, ev) {
        // A click that ended a pan shouldn't also change the selection.
        ev?.stopPropagation();
        this.state.selected = path;
        this.state.selectedDivider = null;
    }

    selectDivider(divider, ev) {
        ev?.stopPropagation();
        // Only vertical junctions are editable; horizontal boundaries are
        // always transoms, per the spec.
        if (divider.kind !== "v") {
            return;
        }
        this.state.selectedDivider = divider.key;
        this.state.selected = null;
    }

    /**
     * Which junctions make sense at the selected boundary.
     *
     * A mullion always works. Meeting means the two sashes close against
     * each other, so both sides have to open. Interlock is how two
     * sliding sashes hook together where they overlap, so both sides have
     * to slide. Invalid ones are offered but disabled, with the reason as
     * the tooltip, rather than hidden -- hiding them makes the rule
     * invisible.
     */
    get junctionOptions() {
        const entry = this.selectedDividerEntry;
        if (!entry) {
            return [];
        }
        const types = this.state.data.leaf_types || [];
        const typeOf = (code) => types.find((t) => t.code === code);
        const opens = (code) => !!typeOf(code)?.has_hinge_side;
        const slides = (code) => code === "SLIDER";
        const bothSashes = opens(entry.leftCode) && opens(entry.rightCode);
        const bothSliders = slides(entry.leftCode) && slides(entry.rightCode);
        return [
            {
                value: "mullion",
                label: _t("Mullion"),
                enabled: true,
                title: _t("Fixed bar between the panels; both close against it."),
            },
            {
                value: "meeting",
                label: _t("Meeting"),
                enabled: bothSashes,
                title: bothSashes
                    ? _t("No bar; the two sashes close against each other.")
                    : _t("Only between two opening sashes."),
            },
            {
                value: "interlock",
                label: _t("Interlock"),
                enabled: bothSliders,
                title: bothSliders
                    ? _t("Sliding sashes hook together where they overlap.")
                    : _t("Only between two sliding sashes."),
            },
        ];
    }

    setJunction(value) {
        const entry = this.selectedDividerEntry;
        if (!entry) {
            return;
        }
        const option = this.junctionOptions.find((o) => o.value === value);
        if (option && !option.enabled) {
            return;
        }
        const rows = this.rowsAt(entry.path);
        rows[entry.ri].leaves[entry.li].junction_after = value;
        this.state.dirty = true;
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
        this.refreshJunctionsAround(this.state.selected);
        this.state.dirty = true;
    }

    /**
     * Turn the selected panel into a container of two.
     *
     * "vertical" means a vertical divider, i.e. two panels side by side:
     * one sub-row, two leaves. "horizontal" is one leaf per sub-row,
     * stacked. The panel keeps its own width/height; the children split it.
     * Both children inherit the original's type and direction so a split
     * never silently invents a panel type.
     */
    splitPanel(direction) {
        const leaf = this.selectedLeaf;
        if (!leaf || !this.canSplit) {
            return;
        }
        // A leaf has no height of its own -- height belongs to the row that
        // holds it. Server-loaded leaves therefore have no height_mm at
        // all, and using it directly put NaN into every nested coordinate.
        const sel = this.state.selected;
        const parentRows = this.rowsAt(sel.slice(0, -1));
        const rowHeight = parentRows[sel[sel.length - 1][0]].height_mm || 0;

        const child = () => ({
            width_mm: leaf.width_mm,
            height_mm: rowHeight,
            is_auto: false,
            leaf_type_id: leaf.leaf_type_id,
            leaf_type_code: leaf.leaf_type_code,
            hinge_side: leaf.hinge_side || "",
            swing: leaf.swing || "",
            slide_dir: leaf.slide_dir || "",
            track_no: leaf.track_no || 0,
            junction_after: "",
            rows: [],
        });

        if (direction === "vertical") {
            const half = (leaf.width_mm || 0) / 2;
            const a = { ...child(), width_mm: half };
            const b = { ...child(), width_mm: half };
            leaf.rows = [{ height_mm: rowHeight, is_auto: false, leaves: [a, b] }];
        } else {
            const half = rowHeight / 2;
            leaf.rows = [
                { height_mm: half, is_auto: false, leaves: [child()] },
                { height_mm: half, is_auto: false, leaves: [child()] },
            ];
        }
        // A container is not a panel: it carries no type of its own.
        leaf.leaf_type_id = false;
        leaf.leaf_type_code = "";
        leaf.hinge_side = "";
        leaf.swing = "";
        leaf.slide_dir = "";

        this.recomputeJunctions(this.state.data.rows);
        // Select the first child, so the toolbar stays on something real.
        this.state.selected = [...this.state.selected, [0, 0]];
        this.state.dirty = true;
    }

    /**
     * Remove the selected panel from its row, collapsing what's left.
     *
     * A row emptied of leaves goes; a container emptied of rows stops
     * being a container; and a container left holding exactly one panel
     * collapses back into that panel, which is what makes a split
     * reversible by removing one of its halves.
     */
    removePanel() {
        const sel = this.state.selected;
        if (!sel || !this.canRemove) {
            return;
        }
        const parentPath = sel.slice(0, -1);
        const [ri, li] = sel[sel.length - 1];
        const rows = this.rowsAt(parentPath);

        rows[ri].leaves.splice(li, 1);
        if (!rows[ri].leaves.length) {
            rows.splice(ri, 1);
        }

        const container = this.leafAt(parentPath);
        if (container) {
            if (!rows.length) {
                container.rows = [];
            } else if (rows.length === 1 && rows[0].leaves.length === 1) {
                const only = rows[0].leaves[0];
                Object.assign(container, {
                    leaf_type_id: only.leaf_type_id,
                    leaf_type_code: only.leaf_type_code,
                    hinge_side: only.hinge_side,
                    swing: only.swing,
                    slide_dir: only.slide_dir,
                    rows: only.rows || [],
                });
            }
        }

        this.recomputeJunctions(this.state.data.rows);
        this.state.selected = parentPath.length ? parentPath : null;
        this.state.dirty = true;
    }

    /** Keep a preset's explicit junctions, derive the rest. */
    applyJunctionDefaults(rows, presetRows) {
        rows.forEach((row, ri) => {
            row.leaves.forEach((leaf, li) => {
                const next = row.leaves[li + 1] || null;
                const stated = presetRows?.[ri]?.leaves?.[li]?.junction;
                leaf.junction_after = next
                    ? stated || defaultJunction(leaf, next)
                    : "";
                if (leaf.rows && leaf.rows.length) {
                    this.applyJunctionDefaults(
                        leaf.rows, presetRows?.[ri]?.leaves?.[li]?.rows);
                }
            });
        });
    }

    /** Re-apply the default junction wherever one isn't set explicitly. */
    recomputeJunctions(rows) {
        for (const row of rows) {
            row.leaves.forEach((leaf, i) => {
                const next = row.leaves[i + 1] || null;
                leaf.junction_after = next ? defaultJunction(leaf, next) : "";
                if (leaf.rows && leaf.rows.length) {
                    this.recomputeJunctions(leaf.rows);
                }
            });
        }
    }

    setDirection(field, value) {
        const leaf = this.selectedLeaf;
        if (!leaf) {
            return;
        }
        // Plain set, NOT a toggle. A split panel inherits its parent's
        // direction, so clicking the value you want would clear it when it
        // happened to already be set -- clicking "out" on a panel that is
        // already "out" left it with no swing at all.
        leaf[field] = value;
        // Hinge side feeds the junction rule: two sashes hinged away from
        // each other meet, hinged towards each other they need a mullion.
        this.refreshJunctionsAround(this.state.selected);
        this.state.dirty = true;
    }

    // -- presets -----------------------------------------------------------
    /** The library, grouped by family and ordered by family sequence. */
    get presetsByFamily() {
        const groups = new Map();
        for (const preset of this.state.data?.presets || []) {
            const key = preset.family_name || _t("Other");
            if (!groups.has(key)) {
                groups.set(key, {
                    family: key,
                    sequence: preset.family_sequence ?? 999,
                    presets: [],
                });
            }
            groups.get(key).presets.push(preset);
        }
        return [...groups.values()].sort(
            (a, b) => a.sequence - b.sequence || a.family.localeCompare(b.family)
        );
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
        // Recurses, so a preset containing a nested split shows that split
        // in its thumbnail rather than a single flat panel.
        const tile = (rowList, box) => {
            const totH = rowList.reduce((a, r) => a + (r.h || 1), 0) || 1;
            let y = box.y;
            for (const row of rowList) {
                const rh = ((row.h || 1) / totH) * box.h;
                const totW =
                    row.leaves.reduce((a, l) => a + (l.w || 1), 0) || 1;
                let x = box.x;
                for (const leaf of row.leaves) {
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
        tile(layout.rows, { x: ff, y: ff, w: W - 2 * ff, h: H - 2 * ff });
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
        // Recursive: a preset row's leaf may itself carry `rows`, which
        // become a nested container sized against that leaf's share.
        const build = (rowList, boxW, boxH) => {
            const totH = rowList.reduce((a, r) => a + (r.h || 1), 0) || 1;
            return rowList.map((row) => {
                const rowH = (boxH * (row.h || 1)) / totH;
                const totW =
                    row.leaves.reduce((a, l) => a + (l.w || 1), 0) || 1;
                return {
                    height_mm: rowH,
                    is_auto: false,
                    leaves: row.leaves.map((leaf) => {
                        const leafW = (boxW * (leaf.w || 1)) / totW;
                        const nested = leaf.rows && leaf.rows.length;
                        const type = byCode[leaf.type];
                        return {
                            width_mm: leafW,
                            height_mm: rowH,
                            is_auto: false,
                            leaf_type_id: nested ? false : type?.id || false,
                            leaf_type_code: nested ? "" : leaf.type || "",
                            hinge_side:
                                !nested && type?.has_hinge_side
                                    ? leaf.hinge || ""
                                    : "",
                            swing:
                                !nested && type?.has_hinge_side
                                    ? leaf.swing || ""
                                    : "",
                            slide_dir:
                                !nested && type?.has_slide_dir
                                    ? leaf.slide || ""
                                    : "",
                            junction_after: leaf.junction || "",
                            track_no: nested ? 0 : leaf.track || 0,
                            rows: nested ? build(leaf.rows, leafW, rowH) : [],
                        };
                    }),
                };
            });
        };
        this.state.data.rows = build(
            layout.rows, header.width_mm, header.height_mm);
        // A preset may state junctions explicitly; anything it leaves out
        // falls back to the default rule.
        this.applyJunctionDefaults(this.state.data.rows, layout.rows);
        this.state.selected = null;
        this.state.selectedDivider = null;
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

        // Panel numbering mirrors aw.design._renumber_panels() exactly, so
        // numbers appear the moment a panel is split rather than only after
        // a save. The server still renumbers authoritatively on save.
        let panelNo = 0;

        // Recursive tiling. A leaf that carries its own `rows` is a
        // CONTAINER: nothing is drawn for it, its box is handed straight to
        // the next level down. Everything is addressed by PATH -- an array
        // of [rowIndex, leafIndex] pairs from the top -- because ri/li
        // alone stop being unique the moment anything nests.
        const tile = (rowList, box, path) => {
            const totH =
                rowList.reduce((a, r) => a + (r.height_mm || 0), 0) || 1;
            let ry = box.y;
            rowList.forEach((row, ri) => {
                const rh = ((row.height_mm || 0) / totH) * box.h;
                const totW =
                    row.leaves.reduce((a, l) => a + (l.width_mm || 0), 0) || 1;
                let rx = box.x;

                row.leaves.forEach((leaf, li) => {
                    const lw = ((leaf.width_mm || 0) / totW) * box.w;
                    const leafPath = [...path, [ri, li]];
                    const nested = leaf.rows && leaf.rows.length;

                    if (nested) {
                        tile(leaf.rows, { x: rx, y: ry, w: lw, h: rh }, leafPath);
                    } else {
                        const sw = Math.max(3, 7 * s);
                        panelNo += 1;
                        const isMesh = leaf.leaf_type_code === "MESH";
                        leaves.push({
                            key: pathKey(leafPath),
                            path: leafPath,
                            panelNo,
                            // Position and label only -- the badge's RADIUS
                            // and FONT are screen-sized and live in
                            // `adornments`. See the layering note above.
                            badge: {
                                cx: rx + lw / 2,
                                cy: ry + rh / 2,
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
                            selected: samePath(this.state.selected, leafPath),
                            glyph: this.leafGlyph(rx, ry, lw, rh, leaf),
                        });
                    }

                    if (li < row.leaves.length - 1) {
                        const key = `v:${pathKey(path)}:${ri}:${li}`;
                        dividers.push({
                            key,
                            kind: "v",
                            path,
                            ri,
                            li,
                            // Per-container, not global: a nested divider
                            // converts pixels to mm against ITS OWN box, so
                            // dragging inside a sub-panel moves by the amount
                            // dragged rather than by the top level's scale.
                            unitsPerMM: box.w / totW,
                            junction: leaf.junction_after || "mullion",
                            leftCode: leaf.leaf_type_code || "",
                            rightCode:
                                row.leaves[li + 1]?.leaf_type_code || "",
                            selected: this.state.selectedDivider === key,
                            x1: rx + lw,
                            y1: ry + 3,
                            x2: rx + lw,
                            y2: ry + rh - 3,
                        });
                    }
                    rx += lw;
                });

                if (ri < rowList.length - 1) {
                    const key = `h:${pathKey(path)}:${ri}`;
                    dividers.push({
                        key,
                        kind: "h",
                        path,
                        ri,
                        li: null,
                        unitsPerMM: box.h / totH,
                        junction: null, // horizontal boundaries are transoms
                        selected: this.state.selectedDivider === key,
                        x1: box.x + 3,
                        y1: ry + rh,
                        x2: box.x + box.w - 3,
                        y2: ry + rh,
                    });
                }
                ry += rh;
            });
        };

        tile(rows, { x: x0 + ff, y: y0 + ff, w: w - 2 * ff, h: h - 2 * ff }, []);

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
            // Recomputed here rather than shared with the tiling above: the
            // tiling now carries its own total per container, so there is
            // no single outer one to borrow. Dimension lines stay TOP-LEVEL
            // only -- stacking a line per nested sub-panel would be
            // unreadable, and the panel numbers already identify them.
            const totalH =
                rows.reduce((a, r) => a + (r.height_mm || 0), 0) || 1;
            let ry2 = y0 + ff;
            rows.forEach((row, ri) => {
                const rh = ((row.height_mm || 0) / totalH) * (h - 2 * ff);
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
            vbX: minX - M,
            vbY: minY - M,
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

    /**
     * Apex at the midpoint of the hinge side, base at the two corners
     * opposite it. Returned as a polyline so the two dashed legs are one
     * element.
     */
    openingTriangle(x, y, w, h, side) {
        const inset = 2;
        const pts = {
            left: [
                [x + w - inset, y + inset],
                [x, y + h / 2],
                [x + w - inset, y + h - inset],
            ],
            right: [
                [x + inset, y + inset],
                [x + w, y + h / 2],
                [x + inset, y + h - inset],
            ],
            top: [
                [x + inset, y + h - inset],
                [x + w / 2, y],
                [x + w - inset, y + h - inset],
            ],
            bottom: [
                [x + inset, y + inset],
                [x + w / 2, y + h],
                [x + w - inset, y + inset],
            ],
        }[side];
        return {
            key: side,
            points: pts.map((pt) => pt.join(",")).join(" "),
        };
    }

    /** Port of leafGlyph(): slide arrow, opening triangle + IN/OUT tag. */
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
            // Standard convention (spec 3.4), replacing the prototype's
            // hinge dot with fans to all four corners: two dashed lines
            // from the corners OPPOSITE the hinge meeting at the midpoint
            // of the hinge side, so the triangle's apex is the hinge.
            const side = leaf.hinge_side || "left";
            glyph.triangles = [this.openingTriangle(x, y, w, h, side)];
            // Tilt & turn opens two ways: side hinge plus a bottom tilt.
            if (leaf.leaf_type_code === "TILTTURN") {
                glyph.triangles.push(
                    this.openingTriangle(x, y, w, h, "bottom"));
            }
            glyph.fan = {
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

    /**
     * Where the floating toolbar goes, in CSS pixels relative to the
     * canvas viewport.
     *
     * Measured through svg.getScreenCTM() rather than computed from the
     * viewBox, because that matrix already accounts for fit scale, zoom
     * AND scroll offset together -- the previous version positioned
     * itself inside the scrolled wrapper and ended up pinned near the top
     * of the screen. Sits just above the selection, flips below when
     * there is no room, and is clamped inside the visible canvas so it is
     * always reachable.
     */
    updateToolbar() {
        const svg = this.svgRef.el;
        const canvas = this.canvasRef.el;
        const anchor = this.toolbarAnchorUnits();
        if (!svg || !canvas || !anchor) {
            this.setToolbar({ show: false, left: 0, top: 0 });
            return;
        }
        const ctm = svg.getScreenCTM();
        if (!ctm) {
            this.setToolbar({ show: false, left: 0, top: 0 });
            return;
        }
        const toScreen = (x, y) =>
            new DOMPoint(x, y).matrixTransform(ctm);
        const rect = canvas.getBoundingClientRect();
        const topPt = toScreen(anchor.x, anchor.yTop);
        const bottomPt = toScreen(anchor.x, anchor.yBottom);

        const el = this.toolbarRef.el;
        const w = el ? el.offsetWidth : 140;
        const h = el ? el.offsetHeight : 34;
        const GAP = 8;

        let left = topPt.x - rect.left - w / 2;
        let top = topPt.y - rect.top - GAP - h;
        if (top < 4) {
            // No room above: put it just below the selection instead.
            top = bottomPt.y - rect.top + GAP;
        }
        left = Math.min(Math.max(left, 4), Math.max(4, rect.width - w - 4));
        top = Math.min(Math.max(top, 4), Math.max(4, rect.height - h - 4));
        this.setToolbar({ show: true, left, top });
    }

    /**
     * The three junctions have to LOOK different, not just be stored
     * differently: a solid bar, two thin lines with a gap and no bar, or
     * two bars overlapping. Sized from the adornment stroke so they stay
     * constant on screen at any zoom.
     */
    junctionShape(d, stroke) {
        const y = Math.min(d.y1, d.y2);
        const h = Math.abs(d.y2 - d.y1);
        if (d.kind !== "v") {
            return {
                kind: "transom",
                bars: [{ key: "t", x: d.x1, y: y - stroke / 2,
                         w: Math.abs(d.x2 - d.x1), h: stroke }],
                lines: [],
            };
        }
        const x = d.x1;
        if (d.junction === "meeting") {
            const gap = stroke * 0.9;
            return {
                kind: "meeting",
                bars: [],
                lines: [
                    { key: "a", x: x - gap, y1: y, y2: y + h, w: stroke * 0.45 },
                    { key: "b", x: x + gap, y1: y, y2: y + h, w: stroke * 0.45 },
                ],
            };
        }
        if (d.junction === "interlock") {
            return {
                kind: "interlock",
                bars: [
                    { key: "a", x: x - stroke * 1.5, y, w: stroke * 2, h },
                    { key: "b", x: x - stroke * 0.5, y, w: stroke * 2, h },
                ],
                lines: [],
            };
        }
        // A mullion is a real profile, so it is drawn at its real width in
        // DRAWING units -- it grows and shrinks with the window like the
        // frame does, instead of being a fixed number of screen pixels.
        // The floor keeps it visible when zoomed right out.
        const barW = Math.max(
            MULLION_WIDTH_MM * (d.unitsPerMM || 0),
            4 * (stroke / 2)
        );
        return {
            kind: "mullion",
            bars: [{ key: "m", x: x - barW / 2, y, w: barW, h }],
            lines: [],
        };
    }

    /** The point the toolbar should point at, in SVG user units. */
    toolbarAnchorUnits() {
        const scene = this.scene;
        if (!scene) {
            return null;
        }
        const panel = this.selectedSceneLeaf;
        if (panel) {
            return {
                x: panel.badge.cx,
                yTop: panel.y,
                yBottom: panel.y + panel.h,
            };
        }
        const divider = this.selectedDividerEntry;
        if (divider) {
            return {
                x: (divider.x1 + divider.x2) / 2,
                yTop: Math.min(divider.y1, divider.y2),
                yBottom: Math.max(divider.y1, divider.y2),
            };
        }
        return null;
    }

    /** Only write when it actually moved: onPatched would otherwise
     *  re-render forever. */
    setToolbar(next) {
        const cur = this.state.toolbar;
        if (
            cur.show === next.show &&
            Math.abs(cur.left - next.left) < 0.5 &&
            Math.abs(cur.top - next.top) < 0.5
        ) {
            return;
        }
        this.state.toolbar = next;
    }

    onCanvasScroll() {
        this.updateToolbar();
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
            // Opening triangles, IN/OUT tag and MESH label. Left in viewBox
            // units these were drawn under a pixel wide at normal fit,
            // which is why the triangles looked absent rather than thin.
            glyphStroke: 1.2 * upp,
            glyphDash: `${4 * upp} ${3 * upp}`,
            glyphFont: 10 * upp,
            arrowStroke: 1.6 * upp,
            dividers: scene.dividers.map((d) => ({
                ...d,
                stroke,
                shape: this.junctionShape(d, stroke),
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
        // Select HERE, not from a click handler: preventDefault() above is
        // needed to stop the browser starting a text/image drag, and it
        // also suppresses the click that would otherwise follow, so a
        // click-to-select never fired. Selecting on pointerdown is also
        // simply more responsive.
        this.selectDivider(divider);
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

        // rowsAt(divider.path) is the container the divider lives in, so a
        // nested divider resizes its own sub-panels and nothing else. The
        // scale comes from the divider too, because a container's
        // units-per-mm is its own box, not the whole drawing's.
        const rows = this.rowsAt(divider.path);
        if (divider.kind === "v") {
            const leaves = rows[divider.ri].leaves;
            this.dragging = {
                kind: "v",
                path: divider.path,
                ri: divider.ri,
                li: divider.li,
                start: point.x,
                a: leaves[divider.li].width_mm,
                b: leaves[divider.li + 1].width_mm,
                unitsPerMM: divider.unitsPerMM,
            };
        } else {
            this.dragging = {
                kind: "h",
                path: divider.path,
                ri: divider.ri,
                start: point.y,
                a: rows[divider.ri].height_mm,
                b: rows[divider.ri + 1].height_mm,
                unitsPerMM: divider.unitsPerMM,
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
        const rows = this.rowsAt(drag.path);
        const raw =
            ((drag.kind === "v" ? point.x : point.y) - drag.start) /
            drag.unitsPerMM;
        // Clamp so neither side of the divider goes below the minimum leaf
        // size -- straight from the prototype's pointermove handler.
        const delta = Math.max(
            MIN_LEAF_MM - drag.a,
            Math.min(drag.b - MIN_LEAF_MM, raw)
        );
        // NOT rounded to whole mm, though the prototype rounds here. The
        // two sides must go on summing to exactly what they summed to
        // before, and rounding each independently loses up to half a mm
        // per drag -- which inside a container means the sub-panels stop
        // adding up to the container and the drawing drifts. Display
        // trims to 2dp, so exact floats cost nothing on screen.
        if (drag.kind === "v") {
            const leaves = rows[drag.ri].leaves;
            leaves[drag.li].width_mm = drag.a + delta;
            leaves[drag.li + 1].width_mm = drag.b - delta;
        } else {
            rows[drag.ri].height_mm = drag.a + delta;
            rows[drag.ri + 1].height_mm = drag.b - delta;
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

    // -- exact sizes by typing ---------------------------------------------
    /**
     * Move a size change onto a neighbour so the total never drifts.
     *
     * The sibling marked Automatic absorbs it if there is one -- that is
     * what the flag means. Otherwise the right-hand neighbour does, or
     * the left-hand one when the edited item is last. Refused outright if
     * either side would end up below the minimum, leaving the old value
     * in place, because silently clamping would show a number the user
     * did not type.
     */
    resizeWithin(items, index, target, key, what) {
        if (items.length < 2) {
            this.notification.add(
                _t("This is the only %s in its row, so its size follows the " +
                   "design. Split it, or change the overall size.", what),
                { type: "warning" }
            );
            return false;
        }
        if (!(target >= MIN_LEAF_MM)) {
            this.notification.add(
                _t("Minimum %(what)s is %(min)s.",
                   { what, min: this.formatLength(MIN_LEAF_MM) }),
                { type: "warning" }
            );
            return false;
        }
        let absorber = items.findIndex((it, i) => i !== index && it.is_auto);
        if (absorber === -1) {
            absorber = index + 1 < items.length ? index + 1 : index - 1;
        }
        const delta = target - (items[index][key] || 0);
        const absorbed = (items[absorber][key] || 0) - delta;
        if (absorbed < MIN_LEAF_MM) {
            this.notification.add(
                _t("There is not enough room: the neighbouring %(what)s would " +
                   "fall below the minimum of %(min)s.",
                   { what, min: this.formatLength(MIN_LEAF_MM) }),
                { type: "warning" }
            );
            return false;
        }
        items[index][key] = target;
        items[absorber][key] = absorbed;
        this.state.dirty = true;
        return true;
    }

    setPanelWidth(text) {
        const path = this.state.selected;
        if (!this.selectedPanel || !path || !path.length) {
            return;
        }
        const rows = this.rowsAt(path.slice(0, -1));
        const [ri, li] = path[path.length - 1];
        this.resizeWithin(
            rows[ri].leaves, li, this.parseLength(text), "width_mm",
            _t("panel"));
    }

    setPanelHeight(text) {
        const path = this.state.selected;
        if (!this.selectedPanel || !path || !path.length) {
            return;
        }
        const rows = this.rowsAt(path.slice(0, -1));
        const ri = path[path.length - 1][0];
        this.resizeWithin(
            rows, ri, this.parseLength(text), "height_mm", _t("row"));
    }

    get selectedPanelWidthText() {
        const leaf = this.selectedPanel;
        return leaf ? this.formatLength(leaf.width_mm || 0) : "";
    }

    get selectedPanelHeightText() {
        const path = this.state.selected;
        if (!this.selectedPanel || !path || !path.length) {
            return "";
        }
        const rows = this.rowsAt(path.slice(0, -1));
        const row = rows[path[path.length - 1][0]];
        return row ? this.formatLength(row.height_mm || 0) : "";
    }

    // -- sliding builder (spec 4.2) ----------------------------------------
    get canUseSlidingBuilder() {
        return (this.state.data?.leaf_types || []).some(
            (t) => t.code === "SLIDER"
        );
    }

    toggleSlidingBuilder() {
        this.state.builderOpen = !this.state.builderOpen;
        if (this.state.builderOpen) {
            this.state.builder = this.defaultSlidingPattern(
                this.state.builder.panels, this.state.builder.tracks,
                this.state.builder.mesh);
        }
    }

    /**
     * A sensible starting pattern for a panel/track count.
     *
     * Sliding panels alternate tracks so neighbours never share one --
     * two sashes on the same track would collide. With more panels than
     * tracks the outermost pair is fixed, which is the usual way a wide
     * opening is made with few tracks.
     */
    defaultSlidingPattern(panels, tracks, mesh) {
        const roles = [];
        const fixedEnds = panels > tracks * 2 - 1 && panels >= 4;
        for (let i = 0; i < panels; i++) {
            const isEnd = i === 0 || i === panels - 1;
            roles.push({
                role: fixedEnds && isEnd ? "fixed" : "slider",
                slide: i < panels / 2 ? "right" : "left",
                track: 1,
            });
        }
        // Sliders alternate across the available tracks; a fixed panel
        // sits on the outermost of them.
        let t = 1;
        for (const entry of roles) {
            if (entry.role === "slider") {
                entry.track = t;
                t = t >= tracks ? 1 : t + 1;
            } else {
                entry.track = tracks;
            }
        }
        return { panels, tracks, mesh, roles };
    }

    setBuilder(key, value) {
        const b = this.state.builder;
        const panels = key === "panels" ? value : b.panels;
        const tracks = key === "tracks" ? value : b.tracks;
        const mesh = key === "mesh" ? value : b.mesh;
        this.state.builder = this.defaultSlidingPattern(panels, tracks, mesh);
    }

    setBuilderRole(index, role) {
        this.state.builder.roles[index].role = role;
        if (role === "fixed") {
            this.state.builder.roles[index].track = this.state.builder.tracks;
        }
    }

    setBuilderSlide(index, slide) {
        this.state.builder.roles[index].slide = slide;
    }

    setBuilderTrack(index, track) {
        this.state.builder.roles[index].track = parseInt(track, 10) || 1;
    }

    /**
     * Spec 4.2's rules, checked before the layout is applied rather than
     * after: adjacent sliding panels must be on different tracks, a fixed
     * panel sits on the outer track, and the mesh track is outermost.
     */
    get slidingBuilderErrors() {
        const b = this.state.builder;
        const errors = [];
        const meshTrack = b.mesh ? b.tracks + 1 : null;
        b.roles.forEach((entry, i) => {
            const next = b.roles[i + 1];
            if (
                entry.role === "slider" &&
                next &&
                next.role === "slider" &&
                entry.track === next.track
            ) {
                errors.push(
                    _t("Panels %(a)s and %(b)s both slide on track %(t)s.",
                       { a: i + 1, b: i + 2, t: entry.track })
                );
            }
            if (entry.role === "fixed" && entry.track !== b.tracks) {
                errors.push(
                    _t("Panel %(n)s is fixed, so it belongs on the outer " +
                       "track (%(t)s).", { n: i + 1, t: b.tracks })
                );
            }
            if (entry.track > b.tracks) {
                errors.push(
                    _t("Panel %(n)s is on track %(t)s, beyond the %(max)s " +
                       "available.",
                       { n: i + 1, t: entry.track, max: b.tracks })
                );
            }
        });
        if (b.mesh && meshTrack <= b.tracks) {
            errors.push(_t("The mesh track must be the outermost."));
        }
        return errors;
    }

    applySlidingBuilder() {
        if (this.slidingBuilderErrors.length) {
            return;
        }
        const b = this.state.builder;
        const types = this.state.data.leaf_types;
        const byCode = Object.fromEntries(types.map((t) => [t.code, t]));
        const width = this.state.data.header.width_mm;
        const height = this.state.data.header.height_mm;
        const count = b.panels + (b.mesh ? 1 : 0);
        const each = count ? width / count : width;

        const leaves = b.roles.map((entry) => {
            const code = entry.role === "fixed" ? "FIXED" : "SLIDER";
            const type = byCode[code];
            return {
                width_mm: each,
                is_auto: false,
                leaf_type_id: type ? type.id : false,
                leaf_type_code: code,
                hinge_side: "",
                swing: "",
                slide_dir: entry.role === "slider" ? entry.slide : "",
                track_no: entry.track,
                junction_after: "",
                rows: [],
            };
        });
        if (b.mesh && byCode.MESH) {
            leaves.push({
                width_mm: each,
                is_auto: false,
                leaf_type_id: byCode.MESH.id,
                leaf_type_code: "MESH",
                hinge_side: "",
                swing: "",
                slide_dir: "left",
                // Outermost, per 4.2.
                track_no: b.tracks + 1,
                junction_after: "",
                rows: [],
            });
        }

        this.state.data.rows = [
            { height_mm: height, is_auto: false, leaves },
        ];
        this.recomputeJunctions(this.state.data.rows);
        this.state.selected = null;
        this.state.selectedDivider = null;
        this.state.builderOpen = false;
        this.state.dirty = true;
    }

    // -- catalog actions ----------------------------------------------------
    async saveAsPreset() {
        // Saved first, so the wizard reads the layout from the record
        // rather than needing the whole tree passed through a context.
        if (this.state.dirty) {
            await this.save();
        }
        const action = await this.orm.call(
            "aw.design", "action_save_as_preset", [[this.designId]]);
        this.action.doAction(action);
    }

    async duplicatePosition() {
        if (this.state.dirty) {
            await this.save();
        }
        const action = await this.orm.call(
            "aw.design", "action_duplicate_position", [[this.designId]]);
        this.action.doAction(action);
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
