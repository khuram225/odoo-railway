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
import { SelectCreateDialog } from "@web/views/view_dialogs/select_create_dialog";
import { FormViewDialog } from "@web/views/view_dialogs/form_view_dialog";
import { presetThumb } from "../preset_thumbnail/preset_thumbnail";

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

const PROFILE_ZOOM_PX = 280; // matches .o_aw_spec_zoom in the scss
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
/**
 * Pane widths and collapsed sections live in localStorage.
 *
 * Per-viewer conveniences, exactly the case browser storage is for:
 * losing them costs a drag, not data. Every read and write is guarded
 * because the accessor itself throws in a private window or with site
 * data blocked, and the configurator has to open regardless.
 */
// Snapping (Part 2, revised). The STEP is in the unit the user is
// working in, because a 1/4 in step is only a round number in inches:
// 6.35mm snapping while the box reads millimetres would look broken.
// MM is 5, which is the smallest division a shop tape actually marks.
const SNAP_STEP_MM = { ftin: 25.4 / 4, in: 25.4 / 4, mm: 5 };
// How close counts as "aligned with the divider above" -- in SCREEN
// pixels, not mm, so the pull is the same at every zoom. A tolerance in
// mm would be unusable zoomed out and twitchy zoomed in.
const SNAP_ALIGN_PX = 6;

const PANE_MIN_PX = 180;
const PANE_MAX_FRACTION = 0.45;
const PANE_DEFAULTS = { left: 220, right: 260 };
const STORE_PANE = "aw_cfg_pane_";
const STORE_COLLAPSED = "aw_cfg_collapsed";
const STORE_RIGHT_TAB = "aw_cfg_right_tab";

/**
 * Collapsible sections WITHIN the Panel tab. The right-hand column used
 * to stack panel, pricing, BOM and checks in one scroller with four
 * collapsibles and a hard max-height on each; four things competing for
 * one column meant none of them had room. They are tabs now, and only
 * the panel's own sub-sections still collapse.
 */
const RIGHT_SECTIONS = ["panel", "infill", "mesh", "grid"];

/** Right-hand tabs, in the order they appear. */
const RIGHT_TABS = ["panel", "spec", "bom", "pricing", "checks"];
const RIGHT_TAB_LABELS = {
    panel: "Panel",
    spec: "Spec",
    bom: "BOM",
    pricing: "Pricing",
    checks: "Checks",
};

function clampPane(value) {
    const max = Math.max(
        PANE_MIN_PX, Math.round(window.innerWidth * PANE_MAX_FRACTION));
    return Math.min(max, Math.max(PANE_MIN_PX, Math.round(value)));
}

function loadPaneWidth(side, fallback) {
    try {
        const raw = window.localStorage.getItem(STORE_PANE + side);
        const value = parseInt(raw, 10);
        return Number.isNaN(value) ? fallback : clampPane(value);
    } catch {
        return fallback;
    }
}

function savePaneWidth(side, value) {
    try {
        window.localStorage.setItem(STORE_PANE + side, String(value));
    } catch {
        // Nothing to do: the width simply resets next time.
    }
}

function loadCollapsed() {
    try {
        return JSON.parse(window.localStorage.getItem(STORE_COLLAPSED)) || {};
    } catch {
        return {};
    }
}

function saveCollapsed(state) {
    try {
        window.localStorage.setItem(STORE_COLLAPSED, JSON.stringify(state));
    } catch {
        // See above.
    }
}

function loadRightTab() {
    try {
        const raw = window.localStorage.getItem(STORE_RIGHT_TAB);
        return RIGHT_TABS.includes(raw) ? raw : "panel";
    } catch {
        return "panel";
    }
}

function saveRightTab(key) {
    try {
        window.localStorage.setItem(STORE_RIGHT_TAB, key);
    } catch {
        // See above.
    }
}

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
            // Panels picked with Ctrl/Shift-click, when more than one.
            // Only honoured while `selected` is one of them, so any
            // code that moves the selection elsewhere drops it.
            multiSel: [],
            // The enlarged profile picture on the Spec tab, or null.
            zoomPic: null,
            // Position picked in each group's "Add component" row,
            // keyed by group.
            addPos: {},
            selectedDivider: null, // divider key
            zoom: 1, // 1 = fitted to the canvas
            paneLeft: loadPaneWidth("left", 220),
            paneRight: loadPaneWidth("right", 260),
            collapsed: loadCollapsed(),
            rightTab: loadRightTab(),
            // The name being typed for "Save as new spec". Not in
            // localStorage: it belongs to one unfinished action, not to
            // the user's preferences.
            specName: "",
            canvasW: 0,
            canvasH: 0,
            // Set while a drag is sitting on an alignment target, so the
            // drawing can show WHY it stopped there. Cleared on every
            // move, which is what makes it flicker off as soon as the
            // pointer leaves the target.
            snapGuide: null,
            // The Grid quick start's pending choice. 2 x 2 rather than
            // 1 x 1, because a 1 x 1 "grid" is what the design already
            // is and the button would appear to do nothing.
            gridCols: 2,
            gridRows: 2,
            libraryOpen: true,
            familyFilter: null, // family id, or null for "All"
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
        this.rightPaneRef = useRef("rightPane");

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
        this.surfaceCheckErrors();
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
    // -- panes -------------------------------------------------------
    // Screen-pixel values, so they belong with the adornments layer's
    // kind of getter, never with `scene`: the drawing must not read a
    // pane width or the cycle scene -> fitScale -> scene comes back.
    get leftPaneStyle() {
        if (!this.state.libraryOpen) {
            return "width: 2.25rem; min-height: 0;";
        }
        return `width: ${this.state.paneLeft}px; min-height: 0;`;
    }

    get rightPaneStyle() {
        return `width: ${this.state.paneRight}px; min-height: 0;`;
    }

    /**
     * Drag a pane border. Widths are read off the pointer's absolute
     * position rather than accumulated deltas, so a fast drag that
     * outruns a few pointermove events still lands where the cursor is.
     */
    onPaneDragStart(side, ev) {
        ev.preventDefault();
        const host = ev.currentTarget.parentElement;
        const bounds = host ? host.getBoundingClientRect() : null;
        const move = (moveEv) => {
            if (!bounds) {
                return;
            }
            const width = side === "left"
                ? moveEv.clientX - bounds.left
                : bounds.right - moveEv.clientX;
            this.state[side === "left" ? "paneLeft" : "paneRight"] =
                clampPane(width);
        };
        const up = () => {
            window.removeEventListener("pointermove", move);
            window.removeEventListener("pointerup", up);
            savePaneWidth(side, side === "left"
                ? this.state.paneLeft : this.state.paneRight);
            // The canvas ResizeObserver has already re-measured, so the
            // drawing re-fits on its own.
        };
        window.addEventListener("pointermove", move);
        window.addEventListener("pointerup", up);
    }

    onPaneReset(side) {
        const value = PANE_DEFAULTS[side];
        this.state[side === "left" ? "paneLeft" : "paneRight"] = value;
        savePaneWidth(side, value);
    }

    onLeftDragStart(ev) {
        this.onPaneDragStart("left", ev);
    }

    onRightDragStart(ev) {
        this.onPaneDragStart("right", ev);
    }

    onLeftDragReset() {
        this.onPaneReset("left");
    }

    onRightDragReset() {
        this.onPaneReset("right");
    }

    // -- collapsible sections ----------------------------------------
    /**
     * Checks used to override the stored state while it had an error,
     * so a collapsed section could never hide the reason a quote
     * cannot be confirmed. It is a tab now and keeps that guarantee a
     * different way -- see surfaceCheckErrors().
     */
    isCollapsed(key) {
        return !!this.state.collapsed[key];
    }

    sectionIcon(key) {
        return this.isCollapsed(key) ? "fa fa-chevron-right" : "fa fa-chevron-down";
    }

    toggleSection(key) {
        this.state.collapsed = {
            ...this.state.collapsed,
            [key]: !this.state.collapsed[key],
        };
        saveCollapsed(this.state.collapsed);
    }

    get leftSectionKeys() {
        return this.presetsByFamily.map((group) => `fam:${group.family}`);
    }

    setAllCollapsed(keys, collapsed) {
        const next = { ...this.state.collapsed };
        for (const key of keys) {
            next[key] = collapsed;
        }
        this.state.collapsed = next;
        saveCollapsed(next);
    }

    expandAllLeft() {
        this.setAllCollapsed(this.leftSectionKeys, false);
    }

    collapseAllLeft() {
        this.setAllCollapsed(this.leftSectionKeys, true);
    }

    expandAllRight() {
        this.setAllCollapsed(RIGHT_SECTIONS, false);
    }

    collapseAllRight() {
        this.setAllCollapsed(RIGHT_SECTIONS, true);
    }

    // -- right-hand tabs ---------------------------------------------
    /**
     * The tab actually showing.
     *
     * Resolved rather than read straight out of state: Pricing is not
     * offered on a design that has none, and a remembered "pricing"
     * would otherwise leave the column blank with no way back.
     */
    get activeRightTab() {
        const key = this.state.rightTab;
        return this.rightTabs.some((tab) => tab.key === key) ? key : "panel";
    }

    /**
     * The tab bar, as data. Built here rather than branched in the
     * template so the badge rules live in one readable place.
     */
    get rightTabs() {
        const errors = this.checkErrors.length;
        const total = errors + this.checkWarnings.length;
        return RIGHT_TABS.filter((key) => key !== "pricing" || this.pricing).map(
            (key) => ({
                key,
                label: RIGHT_TAB_LABELS[key],
                // Only Checks carries a count. A zero badge is noise:
                // the tab body already says "Nothing to report".
                badge: (key === "checks" && total)
                    || (key === "spec" && this.changeCount)
                    || 0,
                danger: key === "checks" && errors > 0,
            })
        );
    }

    setRightTab(key) {
        this.state.rightTab = key;
        saveRightTab(key);
    }

    /**
     * Bring an error to the front, once per set of results.
     *
     * Called after a load and after a save -- NOT from a getter or a
     * render. The collapsible version of Checks forced itself open on
     * every render while an error stood, which is right for a section
     * the user can see past and wrong for a tab: it would take the
     * column hostage and there would be no way to look at the BOM that
     * caused the error. Switching on new results surfaces the problem
     * and still leaves the user in charge afterwards.
     */
    surfaceCheckErrors() {
        if (this.checkErrors.length) {
            this.setRightTab("checks");
        }
    }

    get seriesOptions() {
        return this.state.data?.series_options || [];
    }

    /**
     * Pricing for the right-hand column. Internal only -- the customer
     * PDF deliberately carries none of this.
     */
    get pricing() {
        return this.state.data?.pricing || null;
    }

    get pricingBreakdown() {
        const pricing = this.pricing;
        if (!pricing) {
            return [];
        }
        return (pricing.by_kind || []).filter((row) => row.cost);
    }

    get marginIsThin() {
        const pricing = this.pricing;
        return !!pricing && !!pricing.price
            && Math.round(pricing.margin_pct * 100)
                < Math.round(pricing.min_margin_pct * 100);
    }

    formatMoney(value) {
        const pricing = this.pricing;
        const symbol = pricing ? pricing.currency : "";
        const rounded = Math.round((value || 0) * 100) / 100;
        return `${symbol} ${rounded.toLocaleString()}`;
    }

    // -- glazing family ----------------------------------------------
    get familyOptions() {
        return this.state.data?.family_options || [];
    }

    /**
     * The frame, in the short form.
     *
     * The glazing family is shown right beside it, so "Double Glaze -
     * Openable" repeats half of what the reader has already read.
     * Openable / Sliding / Fixed / Tilt & Turn is the part that is
     * actually news. The server sends both; the long one is the
     * tooltip.
     */
    get systemLabel() {
        return (this.state.data?.system_short
                || this.state.data?.system_label || "");
    }

    get systemLabelFull() {
        return this.state.data?.system_label || "";
    }

    get systemOptions() {
        return this.state.data?.system_options || [];
    }

    /** Only a choice when more than one system could carry the layout. */
    get showSystemPicker() {
        return this.systemOptions.length > 1;
    }

    onFamilyChange(ev) {
        this.onHeaderIdChange("family_id", ev);
    }

    onSystemChange(ev) {
        this.onHeaderIdChange("window_series_id", ev);
    }

    // -- frame type ---------------------------------------------------
    /** The family's roles, offered after "Auto". */
    get frameRoles() {
        return this.state.data?.frame_roles || [];
    }

    get frameRole() {
        return this.state.data?.header?.frame_role || "";
    }

    /**
     * Choose a frame type, or "" for Auto. The server converts panels
     * the new system cannot host, so unsaved edits are saved first: it
     * works on the stored layout, and a conversion on top of a stale
     * one would lose them.
     */
    async onFrameRoleChange(ev) {
        const role = ev.target.value || false;
        if ((role || "") === this.frameRole) {
            return;
        }
        if (this.changeCount) {
            // Same question as a spec change, same answers. The
            // dropdown goes back until one is given.
            const revert = () => {
                ev.target.value = this.frameRole;
            };
            revert();
            this.dialog.add(ConfirmationDialog, {
                title: _t("Changes for this window"),
                body: _t(
                    "This window has %s change(s) of its own. Keep them on " +
                        "top of the new frame type, or discard them and take " +
                        "its specification as it stands?",
                    this.changeCount
                ),
                confirmLabel: _t("Keep the changes"),
                confirm: () => this.applyFrameRole(role, true),
                cancelLabel: _t("Discard them"),
                cancel: () => this.applyFrameRole(role, false),
                dismiss: revert,
            });
            return;
        }
        await this.applyFrameRole(role, true);
    }

    async applyFrameRole(role, keepChanges) {
        if (this.state.dirty) {
            await this.save();
        }
        const data = await this.orm.call(
            "aw.design", "set_frame_role",
            [[this.designId], role, keepChanges]);
        const notice = data.frame_notice;
        this.state.data = data;
        this.state.selected = null;
        this.state.multiSel = [];
        this.state.dirty = false;
        this.surfaceCheckErrors();
        if (notice) {
            this.notification.add(notice, { type: "warning", sticky: true });
        }
    }

    // -- divider options ---------------------------------------------
    get dividerOptions() {
        const entry = this.selectedDividerEntry;
        const options = this.state.data?.divider_options;
        if (!entry || !options) {
            return [];
        }
        return (entry.kind === "h" ? options.horizontal : options.vertical)
            || [];
    }

    get selectedDividerProductId() {
        const entry = this.selectedDividerEntry;
        if (!entry) {
            return false;
        }
        const rows = this.rowsAt(entry.path);
        if (entry.kind === "h") {
            return rows[entry.ri]?.divider_product_id || false;
        }
        return rows[entry.ri]?.leaves[entry.li]?.divider_product_id || false;
    }

    /**
     * Store the choice where the divider lives: a vertical divider
     * belongs to the leaf on its left, a horizontal one to the row
     * above it. The same places the junction type is already kept, so
     * the two cannot drift apart.
     */
    /**
     * Is this the profile the divider is actually built from?
     *
     * Nothing stored means the DEFAULT, so the default has to light up
     * on an untouched divider -- otherwise the toolbar shows a position
     * with no profile selected, which is never the case.
     */
    isDividerOptionActive(option) {
        const chosen = this.selectedDividerProductId;
        return chosen ? option.id === chosen : !!option.is_default;
    }

    setDividerOption(productId) {
        const entry = this.selectedDividerEntry;
        if (!entry) {
            return;
        }
        const rows = this.rowsAt(entry.path);
        // Clicking the chosen one again goes back to the DEFAULT, which
        // is what empty means -- and clicking the default itself stores
        // nothing rather than storing the default explicitly, so a spec
        // that later changes its default carries the design with it.
        const current = this.selectedDividerProductId;
        const option = this.dividerOptions.find((o) => o.id === productId);
        const value =
            current === productId || (option && option.is_default)
                ? false
                : productId;
        if (entry.kind === "h") {
            rows[entry.ri].divider_product_id = value;
        } else {
            rows[entry.ri].leaves[entry.li].divider_product_id = value;
        }
        this.state.dirty = true;
    }

    get glassSpecOptions() {
        return this.state.data?.glass_specs || [];
    }

    // -- specification (phase 7c) ------------------------------------
    get specOptions() {
        return this.state.data?.spec_options || [];
    }

    get specName() {
        return this.state.data?.header?.template_name || "";
    }

    /** A dropdown only when there is more than one to choose from. */
    get showSpecPicker() {
        return this.specOptions.length > 1;
    }

    /**
     * The Spec dropdown itself. Always offered: "Custom (start empty)"
     * is an option on every window, so even a system with one spec has
     * a choice to make. showSpecPicker keeps its old meaning (more than
     * one spec to choose between).
     */
    get showSpecSelect() {
        return !!this.state.data;
    }

    get specProfiles() {
        return this.state.data?.spec_parts?.profiles || [];
    }

    /**
     * The profile rows under their part headings, in the order the
     * server sends them (the position's own group order), with a row's
     * group falling back to "other". A heading with no rows is dropped
     * rather than drawn over nothing.
     */
    get profileGroups() {
        const parts = this.state.data?.spec_parts || {};
        const rows = parts.profiles || [];
        return (parts.groups || [])
            .map((group) => ({
                ...group,
                rows: rows.filter(
                    (row) => (row.part_group || "other") === group.key),
            }))
            .filter((group) => group.rows.length || group.key !== "other"
                    || this.addablePositions("other").length);
    }

    // -- add component --------------------------------------------------
    /** Positions the window could take in this group, from the server. */
    addablePositions(groupKey) {
        return (this.state.data?.spec_parts?.addable || []).filter(
            (p) => p.part_group === groupKey);
    }

    get canCreatePosition() {
        return !!this.state.data?.spec_parts?.can_create_position;
    }

    /** The position chosen for a group, defaulting to its first. */
    addPosition(groupKey) {
        const options = this.addablePositions(groupKey);
        const picked = this.state.addPos[groupKey];
        return options.some((p) => p.id === picked)
            ? picked : (options[0] ? options[0].id : 0);
    }

    onAddPosChange(groupKey, ev) {
        this.state.addPos[groupKey] = parseInt(ev.target.value, 10) || 0;
    }

    /** Pick a profile for the chosen position, then add it as a change. */
    addComponent(group) {
        const positionId = this.addPosition(group.key);
        if (!positionId) {
            return;
        }
        const position = this.addablePositions(group.key).find(
            (p) => p.id === positionId);
        this.dialog.add(SelectCreateDialog, {
            resModel: "product.template",
            title: _t("Choose a profile for %s", position.name),
            noCreate: true,
            multiSelect: false,
            context: {
                list_view_ref: "aw_fenestration_design.view_aw_profile_picker_list",
            },
            domain: [["categ_id", "child_of", this.profileCategoryId]],
            onSelected: (ids) => this.saveAddedComponent(positionId, ids[0]),
        });
    }

    async saveAddedComponent(positionId, templateId) {
        // The server works on the stored layout and hands back a fresh
        // payload, so unsaved edits are saved first rather than lost.
        if (this.state.dirty) {
            await this.save();
        }
        this.state.data = await this.orm.call("aw.design", "set_override", [
            [this.designId],
            {
                kind: "profile",
                position_id: positionId,
                product_tmpl_id: templateId,
                added: true,
            },
        ]);
        this.surfaceCheckErrors();
    }

    /** Create a position when none fits; only offered to those allowed. */
    newPosition(group) {
        this.dialog.add(FormViewDialog, {
            resModel: "aw.profile.position",
            title: _t("New position"),
            context: {
                form_view_ref: "aw_fenestration_design.view_aw_position_quick_form",
                default_part_group: group.key === "other" ? false : group.key,
                // A position made on the spot is not something every
                // spec must have, so it must not warn on all of them.
                default_is_required: false,
            },
            onRecordSaved: async (record) => {
                this.state.addPos[group.key] = record.resId;
                this.state.data = await this.orm.call(
                    "aw.design", "get_configurator_data", [[this.designId]]);
            },
        });
    }

    /**
     * Show the enlarged picture in ONE place: just left of the
     * right-hand panel, level with its top, whichever row is hovered.
     * Clamped to the window so it is never partly off screen.
     */
    showProfileZoom(row) {
        const pane = this.rightPaneRef.el;
        if (!pane) {
            return;
        }
        const size = PROFILE_ZOOM_PX;
        const gap = 12;
        const rect = pane.getBoundingClientRect();
        const left = Math.max(gap, rect.left - size - gap);
        const top = Math.max(
            gap, Math.min(rect.top, window.innerHeight - size - gap));
        this.state.zoomPic = {
            url: this.profileImage(row, 512), left, top,
        };
    }

    hideProfileZoom() {
        this.state.zoomPic = null;
    }

    /** Catalogue picture of a profile, small and large. */
    profileImage(row, size) {
        return `/web/image/product.template/${row.product_tmpl_id}/image_${size}`;
    }

    get specHardware() {
        return this.state.data?.spec_parts?.hardware || [];
    }

    get changeCount() {
        return (
            this.specProfiles.filter((row) => row.changed).length +
            this.specHardware.filter((row) => row.changed).length
        );
    }

    /**
     * Switching spec asks about the per-window changes rather than
     * deciding for the user.
     *
     * A change made for one window ("this one takes the heavier
     * mullion") is usually still wanted after a spec switch; a change
     * that was really a correction to the OLD spec is not. Only the
     * person who made it knows which, and silently picking either way
     * loses work or quotes the wrong thing.
     */
    async onSpecChange(ev) {
        // "custom" is the empty window: the server takes spec 0 as that.
        const custom = ev.target.value === "custom";
        const id = custom ? 0 : parseInt(ev.target.value, 10);
        if (Number.isNaN(id)
            || (custom
                ? this.state.data.header.spec_custom
                : id === this.state.data.header.template_id)) {
            return;
        }
        if (!this.changeCount) {
            await this.applySpec(id, true);
            return;
        }
        // The X (and Escape) CANCELS: nothing is applied and the
        // dropdown goes back. Only the Discard button discards, which is
        // why `dismiss` is given separately from `cancel`.
        const header = this.state.data.header;
        const current = header.spec_custom ? "custom" : String(header.template_id);
        const revert = () => {
            ev.target.value = current;
        };
        revert();
        this.dialog.add(ConfirmationDialog, {
            title: _t("Changes for this window"),
            body: _t(
                "This window has %s change(s) of its own. Keep them on top " +
                    "of the new specification, or discard them and take the " +
                    "new spec as it stands?",
                this.changeCount
            ),
            confirmLabel: _t("Keep the changes"),
            confirm: () => this.applySpec(id, true),
            cancelLabel: _t("Discard them"),
            cancel: () => this.applySpec(id, false),
            dismiss: revert,
        });
    }

    async applySpec(specId, keepChanges) {
        this.state.data = await this.orm.call("aw.design", "set_spec", [
            [this.designId],
            specId,
            keepChanges,
        ]);
        this.surfaceCheckErrors();
    }

    /** Whether a part is showing the spec's answer or this window's. */
    sourceLabel(row) {
        return row.changed ? _t("changed") : _t("spec");
    }

    /**
     * Pick a replacement for one part.
     *
     * The picker is a plain act_window on the product model, filtered to
     * the right category by a domain, rather than a list built into the
     * payload: there are 491 profiles and the point of the change is
     * that it could be any of them. `views` is declared because this
     * action is fetched through orm.call, which does no cleaning -- see
     * check_act_window_views.py.
     */
    changePart(row, kind) {
        const isProfile = kind === "profile";
        this.dialog.add(SelectCreateDialog, {
            resModel: isProfile ? "product.template" : "product.product",
            title: isProfile
                ? _t("Choose a profile for %s", row.position_name)
                : _t("Choose hardware for %s", row.line_name),
            noCreate: true,
            multiSelect: false,
            // Profiles get their own list with the picture and the
            // section size; the domain is what keeps it to Fenestration
            // / Profiles.
            context: isProfile
                ? { list_view_ref: "aw_fenestration_design.view_aw_profile_picker_list" }
                : {},
            domain: isProfile
                ? [["categ_id", "child_of", this.profileCategoryId]]
                : [["categ_id", "child_of", this.hardwareCategoryId]],
            onSelected: (ids) => this.saveOverride(row, kind, ids[0]),
        });
    }

    get profileCategoryId() {
        return this.state.data?.categories?.profiles || 0;
    }

    get hardwareCategoryId() {
        return this.state.data?.categories?.hardware || 0;
    }

    async saveOverride(row, kind, productId) {
        const values =
            kind === "profile"
                ? {
                      kind: "profile",
                      position_id: row.position_id,
                      product_tmpl_id: productId,
                      // No thickness: the server resolves the one the
                      // chosen profile is actually sold in, the same way
                      // the seed does, so a change cannot land on a
                      // thickness that makes no variant.
                  }
                : {
                      kind: "hardware",
                      line_id: row.line_id,
                      product_id: productId,
                      qty: row.qty,
                  };
        this.state.data = await this.orm.call("aw.design", "set_override", [
            [this.designId],
            values,
        ]);
        this.surfaceCheckErrors();
    }

    async resetPart(row, kind) {
        this.state.data = await this.orm.call("aw.design", "clear_override", [
            [this.designId],
            kind === "profile"
                ? { kind: "profile", position_id: row.position_id }
                : { kind: "hardware", line_id: row.line_id },
        ]);
        this.surfaceCheckErrors();
    }

    /** Turn this window's parts, changes included, into a new spec. */
    get canSaveAsSpec() {
        return !!(this.state.specName || "").trim();
    }

    onSpecNameInput(ev) {
        this.state.specName = ev.target.value;
    }

    async saveAsSpec() {
        const name = (this.state.specName || "").trim();
        if (!name) {
            return;
        }
        // The server works on the stored layout and replaces the whole
        // payload, so unsaved edits are saved first.
        if (this.state.dirty) {
            await this.save();
        }
        const data = await this.orm.call("aw.design", "save_as_spec", [
            [this.designId],
            name,
        ]);
        const saved = data.saved_spec;
        this.state.data = data;
        this.state.specName = "";
        this.notification.add(
            _t("Saved to Window Systems > %(system)s > Specifications: %(name)s",
               { system: saved.system, name: saved.name }),
            {
                type: "success",
                buttons: [{
                    name: _t("Open the specification"),
                    primary: true,
                    onClick: () => this.action.doAction({
                        type: "ir.actions.act_window",
                        res_model: "aw.window.template",
                        res_id: saved.id,
                        view_mode: "form",
                        views: [[false, "form"]],
                    }),
                }],
            });
        this.surfaceCheckErrors();
    }

    get finishOptions() {
        return this.state.data?.finish_options || [];
    }

    // Phase 7d removed the Profile Section and Hardware Set
    // dropdowns: both follow the Specification. The getters are gone
    // with them rather than left returning [] -- check_owl_getters.mjs
    // reads every getter on the class, so a dead one is a dead one it
    // keeps exercising.

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
        // The catalogue comes back too, so the library's mesh and infill
        // sections stay in step with whatever the new Series allows.
        for (const key of ["mesh_types", "infill_types", "glass_specs",
                           "grid_patterns", "families", "spec_options",
                           "spec_parts"]) {
            if (context[key]) {
                this.state.data[key] = context[key];
            }
        }

        // The SPEC belongs to the system, so a stale one would point at
        // another system's. Same rule _resolve_spec() applies on the
        // server: keep a choice that still fits, otherwise take the new
        // system's default. The Profile Section and Hardware Set are not
        // here any more -- they follow the spec and are readonly.
        const specs = this.specOptions;
        const spec = this.state.data.header.template_id;
        if (!specs.some((o) => o.id === spec)) {
            const fallback = specs.find((o) => o.is_default) || specs[0];
            this.state.data.header.template_id = fallback
                ? fallback.id : false;
            this.state.data.header.template_name = fallback
                ? fallback.name : "";
        }
        // Default glass FILLS only, matching _compute_glass_spec on the
        // server: switching Series must not replace glass someone chose.
        if (!this.state.data.header.glass_spec_id
                && context.default_glass_spec_id) {
            this.state.data.header.glass_spec_id =
                context.default_glass_spec_id;
        }

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

    /**
     * Event handlers that do their own conversion.
     *
     * A template expression like `parseInt(ev.target.value)` does NOT
     * call the global: OWL compiles every symbol outside its
     * RESERVED_WORDS list into a lookup on the component context, so it
     * becomes ctx['parseInt'], which is undefined, and the handler dies
     * with "vNN is not a function" the moment the field is changed.
     * (Math, Array, Object, Date and console ARE in that list and do
     * work -- parseInt, parseFloat, Number, String, Boolean, isNaN and
     * JSON are not.) Templates call methods; methods do the converting.
     */
    onQtyChange(ev) {
        this.onHeaderChange('qty', parseInt(ev.target.value, 10) || 1);
    }

    /**
     * One converter for every Many2one dropdown in the header. The
     * empty option yields "", which must become false rather than 0 or
     * NaN -- the server writes this straight onto the record.
     */
    onHeaderIdChange(field, ev) {
        const id = parseInt(ev.target.value, 10);
        this.onHeaderChange(field, Number.isNaN(id) ? false : id);
    }

    /**
     * Manual rate, per sqft. An empty box means "go back to the
     * calculated price", which has to reach the server as 0 rather than
     * as nothing: manual_rate is in CONFIGURATOR_PROTECTED_HEADER, where
     * an absent value means "not sent, leave it alone" and would make
     * the override impossible to clear.
     */
    async onManualRateChange(ev) {
        const text = (ev.target.value || "").trim();
        const value = text === "" ? 0 : parseFloat(text);
        const rate = Number.isNaN(value) ? 0 : value;
        this.onHeaderChange("manual_rate", rate);
        // Read-only recompute, so the figures follow the rate on Enter
        // or Tab without a Save. Nothing is written server-side.
        await this.refreshPricingPreview();
    }

    /**
     * Pricing tab figures for the header as it stands (manual rate and
     * finish), computed server-side and rolled back, so nothing is
     * saved. Ignored if the header moved on while the call was out.
     */
    async refreshPricingPreview() {
        const header = this.state.data.header;
        const { manual_rate: rate, finish_id: finish } = header;
        const pricing = await this.orm.call(
            "aw.design", "preview_pricing",
            [[this.designId], rate || 0, finish || false]);
        if (this.state.data.pricing
            && header.manual_rate === rate && header.finish_id === finish) {
            this.state.data.pricing = pricing;
        }
    }

    onGlassSpecChange(ev) {
        this.onHeaderIdChange("glass_spec_id", ev);
    }

    /** The finish dropdown's choice; Finish is required, so no clearing. */
    setFinish(id) {
        this.onHeaderChange("finish_id", id);
        return this.refreshPricingPreview();
    }

    finishStyle(option) {
        const colour = (option && option.color) || "#cccccc";
        return `background-color: ${colour};`;
    }

    get currentFinish() {
        return this.finishOptions.find(
            (opt) => opt.id === this.state.data?.header?.finish_id) || {};
    }

    /**
     * Frame and sash profiles are drawn in the finish's colour. Fill is
     * the colour itself, stroke a darker shade of it; with no colour set
     * (or one that is not a hex code) the old grey applies.
     */
    get finishFill() {
        return /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(this.currentFinish.color || "")
            ? this.currentFinish.color : "#8a9095";
    }

    get finishStroke() {
        const hex = this.finishFill.slice(1);
        const full = hex.length === 3
            ? hex.split("").map((c) => c + c).join("") : hex;
        const channel = (i) => Math.round(
            parseInt(full.slice(i, i + 2), 16) * 0.7);
        return "#" + [0, 2, 4]
            .map((i) => channel(i).toString(16).padStart(2, "0")).join("");
    }

    onBuilderPanelsChange(ev) {
        this.setBuilder("panels", parseInt(ev.target.value, 10) || 2);
    }

    onBuilderTracksChange(ev) {
        this.setBuilder("tracks", parseInt(ev.target.value, 10) || 2);
    }

    onBuilderMeshChange(ev) {
        this.setBuilder("mesh", ev.target.checked);
    }

    onBuilderRoleChange(index, ev) {
        this.setBuilderRole(index, ev.target.value);
    }

    onBuilderSlideChange(index, ev) {
        this.setBuilderSlide(index, ev.target.value);
    }

    onBuilderTrackChange(index, ev) {
        this.setBuilderTrack(index, ev.target.value);
    }

    onSeriesSelectChange(ev) {
        return this.onSeriesChange(ev.target.value);
    }

    onHeaderChange(field, value) {
        this.state.data.header[field] = value;
        this.state.dirty = true;
    }

    /**
     * The overall Width/Height boxes, one in inches and one in mm
     * whatever the unit setting. Typing in either writes the same mm
     * value, so the other box follows.
     */
    formatInchesBox(mm) {
        if (!mm) {
            return "";
        }
        const trim = (v) => String(Math.round(v * 100) / 100);
        const totalIn = mm / MM_PER_IN;
        const ft = Math.floor(totalIn / 12 + 1e-9);
        const rest = totalIn - ft * 12;
        if (!ft) {
            return `${trim(rest)}"`;
        }
        return rest < 0.005 ? `${ft}'` : `${ft}' ${trim(rest)}"`;
    }

    formatMmBox(mm) {
        return mm ? String(Math.round(mm * 100) / 100) : "";
    }

    /**
     * 8' 6" / 8'6 / 8 6 -> feet and inches; 8' -> feet only; a lone
     * number with no foot mark (102) is total inches.
     */
    parseInchesBox(text) {
        const str = String(text || "").trim();
        const nums = str.match(/-?\d+(\.\d+)?/g) || [];
        if (!nums.length) {
            return 0;
        }
        const first = parseFloat(nums[0]);
        const hasFootMark = /['’]|ft|feet|foot/i.test(str);
        if (nums.length >= 2) {
            return (first * 12 + parseFloat(nums[1])) * MM_PER_IN;
        }
        return (hasFootMark ? first * 12 : first) * MM_PER_IN;
    }

    onSizeBoxChange(field, kind, ev) {
        const text = ev.target.value;
        const mm = kind === "mm"
            ? parseFloat(text) || 0
            : this.parseInchesBox(text);
        this.applyDimension(field, mm);
        // Rewrite the box in its normal form: OWL will not, because
        // typed junk leaves the bound value unchanged.
        ev.target.value = kind === "mm"
            ? this.formatMmBox(mm) : this.formatInchesBox(mm);
    }

    onDimensionChange(field, text) {
        this.applyDimension(field, this.parseLength(text));
    }

    applyDimension(field, value) {
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

    /**
     * `n` shares of `total` that sum to exactly `total`.
     *
     * Goes through fitToTotal with every entry at zero and nothing
     * flagged Automatic, which is its "spread evenly" path, so the
     * exact-sum and residue handling is the one already in use rather
     * than a second copy that rounds differently.
     */
    equalShares(total, n) {
        return this.fitToTotal(
            new Array(n).fill(0), new Array(n).fill(false), total);
    }

    // Both recurse: a container's children have to be refitted to the
    // container's NEW size, or a nested split stops adding up as soon as
    // the overall dimensions change.
    // Named methods rather than closures over the whole design, because
    // Equalize needs to refit ONE container's subtree rather than the
    // design's -- same recursion, a different starting point.
    rescaleWidthsIn(rows, total) {
        for (const row of rows) {
            const sizes = this.fitToTotal(
                row.leaves.map((l) => l.width_mm),
                row.leaves.map((l) => l.is_auto),
                total
            );
            row.leaves.forEach((leaf, i) => {
                leaf.width_mm = sizes[i];
                if (leaf.rows && leaf.rows.length) {
                    this.rescaleWidthsIn(leaf.rows, sizes[i]);
                }
            });
        }
    }

    rescaleHeightsIn(rows, total) {
        const sizes = this.fitToTotal(
            rows.map((r) => r.height_mm),
            rows.map((r) => r.is_auto),
            total
        );
        rows.forEach((row, i) => {
            row.height_mm = sizes[i];
            for (const leaf of row.leaves) {
                if (leaf.rows && leaf.rows.length) {
                    this.rescaleHeightsIn(leaf.rows, sizes[i]);
                }
            }
        });
    }

    rescaleWidths(totalWidth) {
        this.rescaleWidthsIn(this.state.data.rows, totalWidth);
    }

    rescaleHeights(totalHeight) {
        this.rescaleHeightsIn(this.state.data.rows, totalHeight);
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

    /**
     * How many parts Split offers. Four is the practical ceiling for a
     * single opening; beyond that the panels are narrower than the
     * profiles framing them.
     */
    get splitCounts() {
        return [2, 3, 4];
    }

    /**
     * The lock bar on the selected panel.
     *
     * Every OPENING sash has one, hinged or sliding; a fixed light has
     * no side for it. The profile comes from the system's own spec, so
     * a system with no Lock Bar line simply produces no piece -- the
     * toggle is still the right place to say whether this sash locks.
     */
    get showLockToggle() {
        const type = this.selectedLeafType;
        return !!type && (type.has_hinge_side || type.has_slide_dir);
    }

    get panelHasLock() {
        // Absent means yes: an opening sash locks unless somebody says
        // otherwise, which is the same default the server holds.
        const panel = this.selectedPanel;
        return !panel || panel.has_lock !== false;
    }

    /**
     * Which side the lock bar lands on, in words, so the toggle says
     * what it will do rather than leaving the reader to derive it.
     */
    get lockEdgeLabel() {
        const panel = this.selectedPanel;
        return (panel && this.lockEdge(panel)) || "lock";
    }

    toggleLock() {
        const panel = this.selectedPanel;
        if (!panel) {
            return;
        }
        panel.has_lock = !this.panelHasLock;
        this.state.dirty = true;
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
        this.state.selectedDivider = null;
        if (ev && (ev.ctrlKey || ev.shiftKey || ev.metaKey)) {
            // Ctrl and Shift both TOGGLE: a panel in or out of the set.
            const set = this.selectionPaths.length
                ? [...this.selectionPaths]
                : (this.state.selected ? [this.state.selected] : []);
            const at = set.findIndex((p) => samePath(p, path));
            if (at >= 0) {
                set.splice(at, 1);
            } else {
                set.push(path);
            }
            this.state.multiSel = set.length > 1 ? set : [];
            this.state.selected = set.length ? set[set.length - 1] : null;
            return;
        }
        this.state.multiSel = [];
        this.state.selected = path;
    }

    /** The picked panels, or [] unless a real multi-selection stands. */
    get selectionPaths() {
        const multi = this.state.multiSel || [];
        const sel = this.state.selected;
        return multi.length > 1 && multi.some((p) => samePath(p, sel))
            ? multi : [];
    }

    isPathSelected(path) {
        return samePath(this.state.selected, path)
            || this.selectionPaths.some((p) => samePath(p, path));
    }

    /**
     * Even out the selected panels, keeping their combined total.
     *
     * Two shapes are understood: panels all in ONE row (equal widths),
     * and exactly one panel per row of ONE stack (equal heights). A
     * selection that spans rows any other way is reported rather than
     * guessed at.
     */
    equalizeSelection() {
        const paths = this.selectionPaths;
        if (paths.length < 2) {
            return;
        }
        const parent = pathKey(paths[0].slice(0, -1));
        const sameParent = paths.every(
            (p) => pathKey(p.slice(0, -1)) === parent);
        const rowIdx = paths.map((p) => p[p.length - 1][0]);
        const rows = sameParent ? this.rowsAt(paths[0].slice(0, -1)) : null;
        if (rows && new Set(rowIdx).size === 1) {
            const row = rows[rowIdx[0]];
            const picked = paths.map((p) => row.leaves[p[p.length - 1][1]]);
            const total = picked.reduce((a, l) => a + (l.width_mm || 0), 0);
            const widths = this.equalShares(total, picked.length);
            picked.forEach((leaf, i) => {
                leaf.width_mm = widths[i];
                leaf.is_auto = false;
                if (leaf.rows && leaf.rows.length) {
                    this.rescaleWidthsIn(leaf.rows, widths[i]);
                }
            });
        } else if (rows && new Set(rowIdx).size === paths.length) {
            const picked = rowIdx.map((i) => rows[i]);
            const total = picked.reduce((a, r) => a + (r.height_mm || 0), 0);
            const heights = this.equalShares(total, picked.length);
            picked.forEach((row, i) => {
                row.height_mm = heights[i];
                row.is_auto = false;
                for (const leaf of row.leaves) {
                    if (leaf.rows && leaf.rows.length) {
                        this.rescaleHeightsIn(leaf.rows, heights[i]);
                    }
                }
            });
        } else {
            this.notification.add(
                _t("The selected panels span more than one row. Select panels in one row (equal widths) or one panel from each row of a stack (equal heights)."),
                { type: "warning" });
            return;
        }
        this.state.dirty = true;
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
     * Turn the selected panel into a container of `parts` equal pieces.
     *
     * "vertical" means vertical dividers, i.e. panels side by side: one
     * sub-row, `parts` leaves. "horizontal" is one leaf per sub-row,
     * stacked. The panel keeps its own width/height; the children split
     * it. Every child inherits the original's type and direction so a
     * split never silently invents a panel type.
     *
     * Two used to be the only option, and a three- or four-light
     * opening meant splitting in two and then splitting one half again,
     * which gives unequal panels and a nesting level nobody wanted.
     */
    splitPanel(direction, parts = 2) {
        const leaf = this.selectedLeaf;
        if (!leaf || !this.canSplit) {
            return;
        }
        const count = Math.max(2, Math.min(4, Math.round(parts) || 2));
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
            // Split exactly, then let fitToTotal place the residue, so
            // the children always add up to the parent however the
            // division falls. See its note on NOT rounding to whole mm.
            const widths = this.equalShares(leaf.width_mm || 0, count);
            leaf.rows = [{
                height_mm: rowHeight,
                is_auto: false,
                leaves: widths.map((w) => ({ ...child(), width_mm: w })),
            }];
        } else {
            leaf.rows = this.equalShares(rowHeight, count).map((h) => ({
                height_mm: h,
                is_auto: false,
                leaves: [{ ...child(), height_mm: h }],
            }));
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
     * The rows and the row index the selected panel sits in.
     *
     * Both Equalize actions work on the selected panel's SIBLINGS
     * rather than on the panel itself, so they share this.
     */
    selectionSiblings() {
        const sel = this.state.selected;
        if (!sel || !sel.length) {
            return null;
        }
        const rows = this.rowsAt(sel.slice(0, -1));
        const [ri] = sel[sel.length - 1];
        return rows[ri] ? { rows, ri } : null;
    }

    /** More than one panel across, so there is something to even out. */
    get canEqualizeWidths() {
        const found = this.selectionSiblings();
        return !!found && found.rows[found.ri].leaves.length > 1;
    }

    /** More than one row in this stack. */
    get canEqualizeHeights() {
        const found = this.selectionSiblings();
        return !!found && found.rows.length > 1;
    }

    /**
     * Give every panel in the selected panel's row the same width.
     *
     * The row's TOTAL is preserved -- this evens out what is already
     * there, it does not resize the opening. A child container is
     * rescaled with its new width, the same rule rescaleWidths follows,
     * or a nested split stops adding up the moment a sibling moves.
     *
     * Automatic is deliberately ignored here: the user asking for equal
     * panels is a more specific instruction than the flag, and
     * honouring both is not possible.
     */
    equalizeWidths() {
        const found = this.selectionSiblings();
        if (!found || !this.canEqualizeWidths) {
            return;
        }
        const row = found.rows[found.ri];
        const total = row.leaves.reduce((a, l) => a + (l.width_mm || 0), 0);
        const widths = this.equalShares(total, row.leaves.length);
        row.leaves.forEach((leaf, i) => {
            leaf.width_mm = widths[i];
            leaf.is_auto = false;
            if (leaf.rows && leaf.rows.length) {
                this.rescaleWidthsIn(leaf.rows, widths[i]);
            }
        });
        this.state.dirty = true;
    }

    /** Give every row in the selected panel's stack the same height. */
    equalizeHeights() {
        const found = this.selectionSiblings();
        if (!found || !this.canEqualizeHeights) {
            return;
        }
        const { rows } = found;
        const total = rows.reduce((a, r) => a + (r.height_mm || 0), 0);
        const heights = this.equalShares(total, rows.length);
        rows.forEach((row, i) => {
            row.height_mm = heights[i];
            row.is_auto = false;
            for (const leaf of row.leaves) {
                if (leaf.rows && leaf.rows.length) {
                    this.rescaleHeightsIn(leaf.rows, heights[i]);
                }
            }
        });
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
    /**
     * The library's four groups, fixed rather than data-driven.
     *
     * Part 2 (revised) retired the mechanism-based families (Openable /
     * Sliding / Tilt & Turn / Twin Sash / Curtain Wall): grouping by
     * mechanism is a fact about the panels, not a way anybody shops for
     * a starting point. An estimator with a 3-across opening and a top
     * light wants "top light over 3 across" and does not care that its
     * panels happen to be casements.
     *
     * Shapes are geometry, Our designs are named layouts, and the two
     * option groups are what can go IN a panel.
     */
    get libraryGroups() {
        const presets = this.state.data?.presets || [];
        return [
            {
                key: "shapes",
                label: _t("Shapes"),
                kind: "preset",
                items: presets.filter((p) => p.kind === "shape"),
            },
            {
                key: "designs",
                label: _t("Our designs"),
                kind: "preset",
                // Anything not marked a shape, so a preset from before
                // the split still appears rather than vanishing.
                items: presets.filter((p) => p.kind !== "shape"),
            },
            {
                key: "screens",
                label: _t("Fly screens"),
                kind: "mesh",
                items: (this.state.data?.mesh_types || []).map(
                    (m) => ({ ...m, attachKind: "mesh" })),
            },
            {
                // Georgian bars are deliberately NOT here: a bar
                // pattern needs a rows x cols to mean anything, so it
                // is set on the Panel tab rather than applied by one
                // click. The library offers what one click can finish.
                key: "addons",
                label: _t("Add-ons"),
                kind: "infill",
                items: (this.state.data?.infill_types || []).map(
                    (i) => ({ ...i, attachKind: "infill" })),
            },
        ].filter((group) => group.items.length);
    }

    get presetsByFamily() {
        const groups = new Map();
        for (const preset of this.state.data?.presets || []) {
            const key = preset.family_name || _t("Other");
            if (!groups.has(key)) {
                groups.set(key, {
                    family: key,
                    familyId: preset.family_id || null,
                    sequence: preset.family_sequence ?? 999,
                    presets: [],
                });
            }
            groups.get(key).presets.push(preset);
        }
        const all = [...groups.values()].sort(
            (a, b) => a.sequence - b.sequence || a.family.localeCompare(b.family)
        );
        const filter = this.state.familyFilter;
        return filter === null || filter === undefined
            ? all
            : all.filter((g) => g.familyId === filter);
    }

    /**
     * Preset thumbnails come from the shared module, so the library and
     * the backend kanban widget draw from one routine rather than two
     * copies that would drift apart.
     */
    presetThumb(layout) {
        return presetThumb(layout);
    }

    // -- family strip ------------------------------------------------------
    get families() {
        return this.state.data?.families || [];
    }

    familyThumb(family) {
        return presetThumb(family.preview);
    }

    familyImageUrl(family) {
        return `/web/image/aw.layout.family/${family.id}/image_128`;
    }

    /**
     * Clicking a tile filters the library to that family and scrolls to
     * it; clicking the same tile again, or "All", clears the filter.
     * Filtering rather than only scrolling keeps the answer visible when
     * the list is long.
     */
    selectFamily(id) {
        this.state.familyFilter =
            this.state.familyFilter === id ? null : id;
        if (this.state.familyFilter !== null) {
            // Scroll after the filtered list has rendered.
            Promise.resolve().then(() => {
                const el = document.querySelector(
                    `[data-aw-family="${this.state.familyFilter}"]`);
                el?.scrollIntoView({ block: "start", behavior: "smooth" });
            });
        }
    }

    toggleLibrary() {
        this.state.libraryOpen = !this.state.libraryOpen;
    }

    /**
     * The library's click handler.
     *
     * Dispatches on the group rather than sniffing the item's fields,
     * and hands anything that is not a preset to the EXISTING
     * applyAttachment -- which already knows about attachKind, the
     * "clicking it again takes it off" behaviour and the selected-panel
     * warning. A second dispatch would have had to reimplement all
     * three.
     */
    applyLibraryItem(group, item) {
        if (group.kind !== "preset") {
            this.applyAttachment(item);
            return;
        }
        if (item.kind === "shape") {
            this.applyShape(item);
        } else {
            this.applyPreset(item);
        }
    }

    /**
     * Apply a SHAPE: the geometry, keeping the panel types already there.
     *
     * A shape is about how the opening is divided, so retyping panels
     * would be doing something the user did not ask for. Types are
     * carried across BY POSITION -- row index, then leaf index -- and
     * anything with no counterpart in the old layout comes out Fixed.
     * That makes "3 across, now make it 4 across" keep the three panels
     * already set up and add one plain light, which is what the words
     * mean.
     */
    applyShape(preset) {
        const before = this.state.data.rows.map((row) =>
            row.leaves.map((leaf) => ({
                leaf_type_id: leaf.leaf_type_id,
                leaf_type_code: leaf.leaf_type_code,
                hinge_side: leaf.hinge_side || "",
                swing: leaf.swing || "",
                slide_dir: leaf.slide_dir || "",
                track_no: leaf.track_no || 0,
                has_lock: leaf.has_lock,
            }))
        );
        this.applyPreset(preset);
        this.state.data.rows.forEach((row, ri) => {
            row.leaves.forEach((leaf, li) => {
                const kept = before[ri]?.[li];
                // Never onto a container: it carries no type of its own,
                // and writing one would make it a panel with children.
                if (!kept || !kept.leaf_type_id || leaf.rows?.length) {
                    return;
                }
                Object.assign(leaf, kept);
            });
        });
        this.recomputeJunctions(this.state.data.rows);
        this.state.dirty = true;
    }

    // -- grid quick start --------------------------------------------
    setGridCols(value) {
        this.state.gridCols = Math.max(1, Math.min(6, parseInt(value, 10) || 1));
    }

    setGridRows(value) {
        this.state.gridRows = Math.max(1, Math.min(6, parseInt(value, 10) || 1));
    }

    applyGridFromState() {
        this.applyGridStart(this.state.gridCols, this.state.gridRows);
    }

    get gridChoices() {
        return [1, 2, 3, 4, 5, 6];
    }

    /**
     * columns x rows of equal Fixed panels.
     *
     * Goes through the same equalShares/fitToTotal path everything else
     * does, so the panels add up to the opening exactly rather than to
     * within a rounding error per cell.
     */
    applyGridStart(cols, rows) {
        const header = this.state.data.header;
        const columns = Math.max(1, Math.min(6, Math.round(cols) || 1));
        const lines = Math.max(1, Math.min(6, Math.round(rows) || 1));
        const fixed = (this.state.data.leaf_types || []).find(
            (t) => t.code === "FIXED");
        const widths = this.equalShares(header.width_mm || 0, columns);
        const heights = this.equalShares(header.height_mm || 0, lines);
        this.state.data.rows = heights.map((h) => ({
            height_mm: h,
            is_auto: false,
            leaves: widths.map((w) => ({
                width_mm: w,
                height_mm: h,
                is_auto: false,
                leaf_type_id: fixed ? fixed.id : false,
                leaf_type_code: fixed ? "FIXED" : "",
                hinge_side: "",
                swing: "",
                slide_dir: "",
                junction_after: "",
                track_no: 0,
                rows: [],
            })),
        }));
        this.state.selected = null;
        this.state.selectedDivider = null;
        this.recomputeJunctions(this.state.data.rows);
        this.state.dirty = true;
    }

    // -- frame-level add row / column --------------------------------
    /** One full-width Fixed panel, sized to `height`. */
    frameRow(height) {
        const fixed = (this.state.data.leaf_types || []).find(
            (t) => t.code === "FIXED");
        return {
            height_mm: height,
            is_auto: false,
            leaves: [{
                width_mm: this.state.data.header.width_mm || 0,
                height_mm: height,
                is_auto: false,
                leaf_type_id: fixed ? fixed.id : false,
                leaf_type_code: fixed ? "FIXED" : "",
                hinge_side: "",
                swing: "",
                slide_dir: "",
                junction_after: "",
                track_no: 0,
                rows: [],
            }],
        };
    }

    /**
     * A full-width row above or below everything.
     *
     * It takes a share of the HEIGHT from what is there rather than
     * growing the opening: the opening is a hole in a wall and its size
     * is not ours to change. A new row gets an equal share, and the
     * existing rows are refitted into what is left.
     */
    addFrameRow(where) {
        const total = this.state.data.header.height_mm || 0;
        const rows = this.state.data.rows;
        const share = total / (rows.length + 1) || 0;
        this.rescaleHeightsIn(rows, Math.max(0, total - share));
        const fresh = this.frameRow(share);
        this.state.data.rows = where === "above"
            ? [fresh, ...rows]
            : [...rows, fresh];
        this.state.selected = null;
        this.recomputeJunctions(this.state.data.rows);
        this.state.dirty = true;
    }

    /**
     * A full-height column left or right of everything.
     *
     * With ONE row this is just another leaf in it. With several, the
     * existing layout has to be wrapped into a container first --
     * a column spanning three rows is not a leaf of any one of them --
     * which is why this is more than the mirror image of addFrameRow.
     */
    addFrameColumn(where) {
        const header = this.state.data.header;
        const total = header.width_mm || 0;
        const rows = this.state.data.rows;
        const fixed = (this.state.data.leaf_types || []).find(
            (t) => t.code === "FIXED");
        const share = total / 2;
        const rest = Math.max(0, total - share);

        const column = {
            width_mm: share,
            height_mm: header.height_mm || 0,
            is_auto: false,
            leaf_type_id: fixed ? fixed.id : false,
            leaf_type_code: fixed ? "FIXED" : "",
            hinge_side: "",
            swing: "",
            slide_dir: "",
            junction_after: "",
            track_no: 0,
            rows: [],
        };

        if (rows.length === 1) {
            const row = rows[0];
            this.rescaleWidthsIn([row], rest);
            row.leaves = where === "left"
                ? [column, ...row.leaves]
                : [...row.leaves, column];
        } else {
            // Wrap what is there into a container leaf, then put the new
            // column beside it.
            this.rescaleWidthsIn(rows, rest);
            const wrapper = {
                width_mm: rest,
                height_mm: header.height_mm || 0,
                is_auto: false,
                leaf_type_id: false,
                leaf_type_code: "",
                hinge_side: "",
                swing: "",
                slide_dir: "",
                junction_after: "",
                track_no: 0,
                rows: rows.map((row) => ({ ...row })),
            };
            this.state.data.rows = [{
                height_mm: header.height_mm || 0,
                is_auto: false,
                leaves: where === "left"
                    ? [column, wrapper]
                    : [wrapper, column],
            }];
        }
        this.state.selected = null;
        this.state.selectedDivider = null;
        this.recomputeJunctions(this.state.data.rows);
        this.state.dirty = true;
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
        const meshByCode = Object.fromEntries(
            (this.state.data.mesh_types || []).map((m) => [m.code, m]));
        const infillByCode = Object.fromEntries(
            (this.state.data.infill_types || []).map((i) => [i.code, i]));
        const gridByCode = Object.fromEntries(
            (this.state.data.grid_patterns || []).map((g) => [g.code, g]));
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
                            // Attachments are named by CODE in a preset,
                            // resolved to ids here against the current
                            // catalogue.
                            mesh_type_id: nested ? false : meshByCode[leaf.mesh]?.id || false,
                            mesh_type_code: nested ? "" : leaf.mesh || "",
                            mesh_hinge_side:
                                !nested && leaf.mesh ? leaf.hinge || "" : "",
                            infill_type_id: nested ? false : infillByCode[leaf.infill]?.id || false,
                            infill_kind: nested ? "glass" : infillByCode[leaf.infill]?.kind || "glass",
                            infill_uses_glass:
                                nested || !leaf.infill
                                    ? true
                                    : !!infillByCode[leaf.infill]?.uses_glass,
                            glass_spec_id: false,
                            grid_pattern_id: nested ? false : gridByCode[leaf.grid?.pattern]?.id || false,
                            grid_rows: nested ? 0 : leaf.grid?.rows || 0,
                            grid_cols: nested ? 0 : leaf.grid?.cols || 0,
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
                            selected: this.isPathSelected(leafPath),
                            glyph: this.leafGlyph(rx, ry, lw, rh, leaf),
                            // Attachments: positions only, no stroke
                            // widths -- those are screen-sized and live
                            // in adornments, per the layering rule.
                            attach: this.leafAttachments(rx, ry, lw, rh, leaf),
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

    /**
     * The edge a sash locks on: the far edge from the way it moves.
     *
     * Hinged, it is opposite the hinge; sliding, it is opposite the
     * slide direction, because a sash that slides left to open shuts
     * to the right. One mapping for both, matching _lock_edge() on the
     * server exactly -- two places drawing different conclusions from
     * one sash would be worse than the duplication.
     */
    lockEdge(leaf) {
        const opposite = {
            left: "right",
            right: "left",
            top: "bottom",
            bottom: "top",
        };
        return (
            opposite[leaf.hinge_side || ""] ||
            opposite[leaf.slide_dir || ""] ||
            ""
        );
    }

    /**
     * The lock mark: a short bar on the sash's lock side.
     *
     * Returns null for anything with no lock side -- a fixed light, a
     * sash whose direction is not set yet, or one whose Lock has been
     * turned off.
     */
    lockMark(x, y, w, h, leaf) {
        if (leaf.has_lock === false) {
            return null;
        }
        const edge = this.lockEdge(leaf);
        if (!edge) {
            return null;
        }
        // A fifth of the edge, centred on it, inset so it reads as
        // fitted to the sash rather than drawn over the frame.
        if (edge === "left" || edge === "right") {
            const cx = edge === "left" ? x : x + w;
            return {
                x1: cx,
                x2: cx,
                y1: y + h * 0.4,
                y2: y + h * 0.6,
            };
        }
        const cy = edge === "top" ? y : y + h;
        return { x1: x + w * 0.4, x2: x + w * 0.6, y1: cy, y2: cy };
    }

    /**
     * Where a panel's mesh, infill and grid are drawn (spec 5.5).
     *
     * Geometry only: every stroke width and font size comes from the
     * adornment layer, so these stay readable at any zoom, and so this
     * never reads fitScale and re-creates the cycle that crashed the
     * configurator once.
     */
    leafAttachments(x, y, w, h, leaf) {
        const out = {
            meshOverlay: null,
            meshBadge: null,
            infill: null,
            grid: null,
            lock: null,
        };

        // A small mark on the lock side, so the drawing shows which
        // edge the lock bar is on rather than leaving the reader to
        // derive "opposite the hinge". Geometry only -- its stroke and
        // size come from the adornment layer, per the layering rule
        // above.
        out.lock = this.lockMark(x, y, w, h, leaf);

        if (leaf.mesh_type_id) {
            out.meshOverlay = { x, y, w, h };
            out.meshBadge = {
                x: x + w - 4,
                y: y + 4,
                label: leaf.mesh_type_code || "MSH",
            };
        }

        const kind = leaf.infill_kind || "glass";
        const cx = x + w / 2;
        const cy = y + h / 2;
        if (kind === "panel") {
            out.infill = { kind, x, y, w, h };
        } else if (kind === "louvre") {
            // Evenly spaced slats across the opening.
            const count = Math.max(3, Math.min(9, Math.round(h / 60)));
            const step = h / (count + 1);
            out.infill = {
                kind,
                slats: Array.from({ length: count }, (_, i) => ({
                    key: i,
                    x1: x + w * 0.12,
                    x2: x + w * 0.88,
                    y: y + step * (i + 1),
                })),
            };
        } else if (kind === "fan") {
            out.infill = {
                kind,
                cx,
                cy,
                r: Math.min(w, h) * 0.26,
            };
        } else if (kind === "ac") {
            const bw = w * 0.5;
            const bh = h * 0.3;
            out.infill = {
                kind,
                x: cx - bw / 2,
                y: cy - bh / 2,
                w: bw,
                h: bh,
            };
        }

        if (leaf.grid_pattern_id) {
            const rows = Math.max(0, leaf.grid_rows || 0);
            const cols = Math.max(0, leaf.grid_cols || 0);
            const bars = [];
            for (let i = 1; i < rows; i++) {
                const gy = y + (h * i) / rows;
                bars.push({ key: `r${i}`, x1: x, y1: gy, x2: x + w, y2: gy });
            }
            for (let i = 1; i < cols; i++) {
                const gx = x + (w * i) / cols;
                bars.push({ key: `c${i}`, x1: gx, y1: y, x2: gx, y2: y + h });
            }
            out.grid = { bars };
        }
        return out;
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
            // Attachment strokes, all screen-constant for the same
            // reason the triangles are.
            meshStroke: 0.8 * upp,
            louvreStroke: 1.1 * upp,
            fanStroke: 1.2 * upp,
            gridStroke: 2 * upp,
            // The lock mark reads as a fitting, so it is the heaviest
            // of the attachment strokes -- still screen-constant.
            lockStroke: 3 * upp,
            badgeFontSmall: 8 * upp,
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
        // The guide belongs to a drag in progress; leaving it behind
        // would draw a line nothing is explaining any more.
        this.state.snapGuide = null;
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

    /**
     * The step a dragged divider rounds to, in mm.
     *
     * Reads the design's own unit, so ft+in and inches both snap to a
     * quarter inch and millimetres snap to 5.
     */
    get snapStepMm() {
        return SNAP_STEP_MM[this.state.data?.length_uom] || SNAP_STEP_MM.mm;
    }

    /**
     * Offsets (from the start of the row or stack) a divider should
     * snap to, besides the step: the equal-split positions, and any
     * divider at the same depth in the row above or below.
     *
     * Equal splits are in here because "make these even" is the single
     * most common thing a drag is trying to do, and hitting it by eye
     * at 1/4 in is luck. Alignment with a neighbouring row is the other
     * one -- a transom lining up across a mullion is what makes an
     * elevation look drawn rather than dragged.
     */
    snapTargets(drag) {
        const rows = this.rowsAt(drag.path);
        const targets = [];
        if (drag.kind === "v") {
            const leaves = rows[drag.ri].leaves;
            const total = leaves.reduce((a, l) => a + (l.width_mm || 0), 0);
            // Equal splits of this row.
            for (let i = 1; i < leaves.length + 1; i++) {
                targets.push((total * i) / (leaves.length + 1));
            }
            for (let n = 2; n <= 4; n++) {
                for (let i = 1; i < n; i++) {
                    targets.push((total * i) / n);
                }
            }
            // Vertical dividers in the sibling rows, measured the same
            // way: cumulative width from the row's left edge.
            rows.forEach((row, ri) => {
                if (ri === drag.ri) {
                    return;
                }
                let at = 0;
                for (const leaf of row.leaves.slice(0, -1)) {
                    at += leaf.width_mm || 0;
                    targets.push(at);
                }
            });
        } else {
            const total = rows.reduce((a, r) => a + (r.height_mm || 0), 0);
            for (let n = 2; n <= 4; n++) {
                for (let i = 1; i < n; i++) {
                    targets.push((total * i) / n);
                }
            }
        }
        return targets;
    }

    /**
     * Round `offset` to the step, then let a nearby target win.
     *
     * Order matters: the step is the floor, and an equal-split or an
     * alignment is a stronger intention than a round number, so it
     * overrides. `tolerance` is converted from screen pixels by the
     * caller, which is what keeps the pull constant across zoom.
     */
    snapOffset(offset, targets, tolerance) {
        const step = this.snapStepMm;
        let best = step > 0 ? Math.round(offset / step) * step : offset;
        let bestGap = tolerance;
        for (const target of targets) {
            const gap = Math.abs(target - offset);
            if (gap <= bestGap) {
                best = target;
                bestGap = gap;
            }
        }
        return best;
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
        // Snapping, unless Alt is held: a step, plus the equal-split and
        // alignment targets. Alt-drag is the escape hatch -- a shop
        // sometimes needs 731mm and no amount of snapping should make
        // that hard to type by dragging.
        let wanted = raw;
        this.state.snapGuide = null;
        if (!ev.altKey) {
            const targets = drag.snapTargets || this.snapTargets(drag);
            // Pixels to mm at the CURRENT zoom, so the pull feels the
            // same whatever the scale.
            const tolerance = SNAP_ALIGN_PX * this.unitsPerPixel
                / (drag.unitsPerMM || 1);
            const snapped = this.snapOffset(
                drag.a + raw, targets, tolerance);
            wanted = snapped - drag.a;
            // A guide is drawn only for a real alignment, not for the
            // step: a line flashing on every quarter inch is noise.
            if (targets.some((t) => Math.abs(t - snapped) < 0.001)) {
                this.state.snapGuide = {
                    kind: drag.kind,
                    path: drag.path,
                    ri: drag.ri,
                    offset: snapped,
                };
            }
        }
        // Clamp so neither side of the divider goes below the minimum leaf
        // size -- straight from the prototype's pointermove handler.
        const delta = Math.max(
            MIN_LEAF_MM - drag.a,
            Math.min(drag.b - MIN_LEAF_MM, wanted)
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

    // -- attachments (spec 5.1-5.4) ----------------------------------------
    get meshTypes() {
        return this.state.data?.mesh_types || [];
    }

    get infillTypes() {
        return this.state.data?.infill_types || [];
    }

    get glassSpecs() {
        return this.state.data?.glass_specs || [];
    }

    get gridPatterns() {
        return this.state.data?.grid_patterns || [];
    }

    /**
     * Mesh and infill grouped by family, so the library lists them the
     * same way it lists layouts and the family strip can jump to them.
     *
     * Mesh and infill are offered on EVERY Series: an attached mesh or a
     * louvre is a property of the panel, not of the system, and nothing
     * in the data ties a mesh type to a Series. Narrowing them would be
     * a guess.
     */
    get attachmentsByFamily() {
        const groups = new Map();
        const add = (item, kind, fallback) => {
            const key = item.family_name || fallback;
            if (!groups.has(key)) {
                groups.set(key, {
                    family: key,
                    familyId: item.family_id || null,
                    sequence: item.family_sequence ?? 999,
                    items: [],
                });
            }
            groups.get(key).items.push({ ...item, attachKind: kind });
        };
        for (const mesh of this.meshTypes) {
            add(mesh, "mesh", _t("Mesh"));
        }
        for (const infill of this.infillTypes) {
            add(infill, "infill", _t("Add-ons"));
        }
        return [...groups.values()].sort(
            (a, b) => a.sequence - b.sequence || a.family.localeCompare(b.family)
        );
    }

    /** Honours the family strip's filter, like the layout list does. */
    get visibleAttachments() {
        const filter = this.state.familyFilter;
        const all = this.attachmentsByFamily;
        return filter === null || filter === undefined
            ? all
            : all.filter((g) => g.familyId === filter);
    }

    /** Is this attachment the one currently on the selected panel? */
    isAttachmentActive(item) {
        const leaf = this.selectedPanel;
        if (!leaf) {
            return false;
        }
        return item.attachKind === "mesh"
            ? leaf.mesh_type_id === item.id
            : leaf.infill_type_id === item.id;
    }

    applyAttachment(item) {
        if (item.attachKind === "mesh") {
            this.applyMesh(item.id);
        } else {
            this.applyInfill(item.id);
        }
    }

    /**
     * A tiny drawing for an attachment chip: a frame plus whatever marks
     * that kind out. Reuses the leaf symbol shapes so a louvre chip and a
     * louvre panel look like the same thing.
     */
    attachmentSymbol(item) {
        const W = 26;
        const H = 20;
        const sym = { viewBox: `0 0 ${W} ${H}`, W, H, kind: "", lines: [],
                      circle: null, box: null, hatch: false };
        if (item.attachKind === "mesh") {
            sym.kind = "mesh";
            sym.hatch = true;
            return sym;
        }
        sym.kind = item.kind || "glass";
        if (sym.kind === "louvre") {
            sym.lines = [0.3, 0.5, 0.7].map((f, i) => ({
                key: i, x1: W * 0.18, x2: W * 0.82, y: H * f,
            }));
        } else if (sym.kind === "fan") {
            sym.circle = { cx: W / 2, cy: H / 2, r: Math.min(W, H) * 0.25 };
        } else if (sym.kind === "ac") {
            sym.box = { x: W * 0.25, y: H * 0.35, w: W * 0.5, h: H * 0.3 };
        } else if (sym.kind === "panel") {
            sym.box = { x: W * 0.15, y: H * 0.2, w: W * 0.7, h: H * 0.6 };
        }
        return sym;
    }

    /**
     * Mesh and infill APPLY TO A PANEL rather than replacing the layout,
     * which is the whole difference between a layout family and a mesh
     * or infill one (spec 4.1). With nothing selected there is nothing
     * to apply them to, so say so rather than doing nothing.
     */
    requireSelectedPanel(what) {
        if (this.selectedPanel) {
            return true;
        }
        this.notification.add(
            _t("Select a panel first, then apply the %s to it.", what),
            { type: "warning" }
        );
        return false;
    }

    applyMesh(meshId) {
        if (!this.requireSelectedPanel(_t("mesh"))) {
            return;
        }
        const leaf = this.selectedPanel;
        const mesh = this.meshTypes.find((m) => m.id === meshId) || null;
        // Clicking the mesh already on the panel takes it off again.
        const clearing = leaf.mesh_type_id === meshId;
        leaf.mesh_type_id = clearing ? false : meshId;
        leaf.mesh_type_code = clearing ? "" : mesh?.code || "";
        // A hinged mesh follows the panel's own hinge unless changed.
        leaf.mesh_hinge_side =
            !clearing && mesh?.mechanism === "hinged"
                ? leaf.hinge_side || "left"
                : "";
        this.state.dirty = true;
    }

    applyInfill(infillId) {
        if (!this.requireSelectedPanel(_t("infill"))) {
            return;
        }
        const leaf = this.selectedPanel;
        const infill = this.infillTypes.find((i) => i.id === infillId) || null;
        leaf.infill_type_id = infillId;
        leaf.infill_kind = infill?.kind || "glass";
        leaf.infill_uses_glass = infill ? !!infill.uses_glass : true;
        // An unglazed infill has no glass to override, so drop any that
        // was set rather than leaving it to be quietly applied later.
        if (!leaf.infill_uses_glass) {
            leaf.glass_spec_id = false;
            leaf.glass_suggested = false;
        }
        this.state.dirty = true;
    }

    setPanelGlass(value) {
        const leaf = this.selectedPanel;
        if (!leaf) {
            return;
        }
        leaf.glass_spec_id = parseInt(value, 10) || false;
        // A choice made here is the user's, not a suggestion --
        // "Design glass" (empty) included, which is a choice too, so
        // later saves never suggest for this panel again.
        leaf.glass_suggested = false;
        leaf.glass_chosen = true;
        this.state.dirty = true;
    }

    setPanelGrid(value) {
        const leaf = this.selectedPanel;
        if (!leaf) {
            return;
        }
        const id = parseInt(value, 10) || false;
        leaf.grid_pattern_id = id;
        if (!id) {
            leaf.grid_rows = 0;
            leaf.grid_cols = 0;
        } else if (!leaf.grid_rows && !leaf.grid_cols) {
            leaf.grid_rows = 2;
            leaf.grid_cols = 2;
        }
        this.state.dirty = true;
    }

    setPanelGridSize(field, value) {
        const leaf = this.selectedPanel;
        if (!leaf) {
            return;
        }
        leaf[field] = Math.max(0, parseInt(value, 10) || 0);
        this.state.dirty = true;
    }

    setMeshHinge(side) {
        const leaf = this.selectedPanel;
        if (!leaf) {
            return;
        }
        leaf.mesh_hinge_side = side;
        this.state.dirty = true;
    }

    onPanelGlassChange(ev) {
        this.setPanelGlass(ev.target.value);
    }

    onPanelGridChange(ev) {
        this.setPanelGrid(ev.target.value);
    }

    onGridRowsChange(ev) {
        this.setPanelGridSize("grid_rows", ev.target.value);
    }

    onGridColsChange(ev) {
        this.setPanelGridSize("grid_cols", ev.target.value);
    }

    get selectedMeshType() {
        const leaf = this.selectedPanel;
        return leaf
            ? this.meshTypes.find((m) => m.id === leaf.mesh_type_id) || null
            : null;
    }

    get selectedPanelUsesGlass() {
        const leaf = this.selectedPanel;
        if (!leaf) {
            return false;
        }
        // No infill chosen means plain glass, which is the default.
        return leaf.infill_type_id ? !!leaf.infill_uses_glass : true;
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

    // -- BOM and checks (spec 6.5, 6.6) ------------------------------------
    get bom() {
        return this.state.data?.bom || {};
    }

    /**
     * Errors the client can see without a round trip.
     *
     * No joints and no couplers, so a frame member longer than one bar
     * can hold is simply not makeable. The server reports it too, on
     * save -- this is here so the person typing the size is told
     * immediately rather than after a save that looked like it worked.
     */
    get dimensionErrors() {
        const limits = this.state.data?.limits;
        const header = this.state.data?.header;
        if (!limits || !header || !limits.max_piece_mm) {
            return [];
        }
        const out = [];
        for (const [field, piece] of [
            ["width_mm", "top and bottom"],
            ["height_mm", "jambs"],
        ]) {
            const value = header[field] || 0;
            if (value > limits.max_piece_mm) {
                out.push({
                    level: "error",
                    message: `The frame ${piece} would be ${this.formatLength(value)}, `
                        + `longer than the ${limits.max_piece_label} that can be cut `
                        + `from one bar. Pieces are never joined — reduce the size.`,
                });
            }
        }
        return out;
    }

    get checks() {
        return [...this.dimensionErrors, ...(this.state.data?.checks || [])];
    }

    get checkErrors() {
        return this.checks.filter((c) => c.level === "error");
    }

    get checkWarnings() {
        return this.checks.filter((c) => c.level === "warning");
    }

    /** BOM sections in a fixed reading order, empty ones dropped. */
    get bomGroups() {
        const titles = {
            profile: _t("Profiles"),
            glass: _t("Glass"),
            hardware: _t("Hardware"),
            mesh: _t("Mesh"),
            infill: _t("Infill"),
            grid: _t("Grid"),
        };
        return ["profile", "glass", "hardware", "mesh", "infill", "grid"]
            .filter((kind) => (this.bom[kind] || []).length)
            .map((kind) => ({
                kind,
                title: titles[kind],
                lines: this.bom[kind],
            }));
    }

    get bomIsEmpty() {
        return !this.bomGroups.length;
    }

    // -- drawing snapshot (spec 7a) -----------------------------------------
    /**
     * Serialise the drawing as a standalone SVG.
     *
     * The live <svg> gets most of its appearance from the module's SCSS
     * (o_aw_divider_line, o_aw_grid_bar, o_aw_junction ...). A plain
     * serialisation carries the class names but not the stylesheet, so
     * it would render with browser defaults -- lines invisible, rects
     * filled black. Computed styles are therefore copied onto each node
     * as presentation attributes, which keeps the SCSS as the single
     * source of truth instead of duplicating it here.
     */
    snapshotSvg() {
        const live = this.svgRef.el;
        if (!live) {
            return null;
        }
        const clone = live.cloneNode(true);
        const liveNodes = [live, ...live.querySelectorAll("*")];
        const cloneNodes = [clone, ...clone.querySelectorAll("*")];
        const props = [
            "fill", "fill-opacity", "stroke", "stroke-width",
            "stroke-dasharray", "stroke-linecap", "stroke-opacity",
            "opacity", "font-size", "font-family", "font-weight",
            "text-anchor", "dominant-baseline",
        ];
        for (let i = 0; i < liveNodes.length; i++) {
            const computed = getComputedStyle(liveNodes[i]);
            for (const prop of props) {
                const value = computed.getPropertyValue(prop);
                if (value) {
                    cloneNodes[i].setAttribute(prop, value);
                }
            }
        }
        // Interaction-only overlays. They are invisible on screen but
        // would print as solid blocks once their computed fill is
        // baked in above.
        for (const node of clone.querySelectorAll(
            ".o_aw_divider_hit, .o_aw_selection"
        )) {
            node.remove();
        }
        clone.removeAttribute("style");
        clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
        const box = (clone.getAttribute("viewBox") || "").split(/\s+/);
        const width = parseFloat(box[2]) || 800;
        const height = parseFloat(box[3]) || 600;
        clone.setAttribute("width", width);
        clone.setAttribute("height", height);
        return { svg: new XMLSerializer().serializeToString(clone), width, height };
    }

    /**
     * Rasterise that SVG to a PNG, because the PDF reports go through
     * wkhtmltopdf and its inline-SVG support is not dependable.
     * Returns base64 with no data: prefix, or null if the browser
     * refuses -- in which case the SVG is still saved and the reports
     * simply have no picture, rather than the save failing.
     */
    async snapshotPng(svg, width, height) {
        try {
            const scale = Math.min(3, Math.max(1, 1400 / width));
            const image = new Image();
            await new Promise((resolve, reject) => {
                image.onload = resolve;
                image.onerror = reject;
                image.src = "data:image/svg+xml;charset=utf-8,"
                    + encodeURIComponent(svg);
            });
            const canvas = document.createElement("canvas");
            canvas.width = Math.round(width * scale);
            canvas.height = Math.round(height * scale);
            const ctx = canvas.getContext("2d");
            // White, not transparent: a transparent PNG prints as a
            // black rectangle in some PDF viewers.
            ctx.fillStyle = "#ffffff";
            ctx.fillRect(0, 0, canvas.width, canvas.height);
            ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
            return canvas.toDataURL("image/png").split(",")[1] || null;
        } catch {
            return null;
        }
    }

    async buildSnapshot() {
        const drawing = this.snapshotSvg();
        if (!drawing) {
            return null;
        }
        return {
            svg: drawing.svg,
            png: await this.snapshotPng(
                drawing.svg, drawing.width, drawing.height),
        };
    }

    // -- save --------------------------------------------------------------
    async save() {
        const data = this.state.data;
        // Taken BEFORE the call: it must describe the layout being sent.
        const snapshot = await this.buildSnapshot();
        this.state.data = await this.orm.call("aw.design", "save_layout", [
            [this.designId],
            { header: data.header, rows: data.rows, snapshot },
        ]);
        this.state.dirty = false;
        this.state.selected = null;
        // The save regenerates the checks, so this is the moment a new
        // error can appear. A success toast over an error nobody sees
        // is worse than no toast at all.
        this.surfaceCheckErrors();
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
