// Exercises the REAL DesignConfigurator class (same load trick as
// check_owl_getters.mjs), not a reimplementation.
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const SRC =
    "odoo/addons/aw_fenestration_design/static/src/design_configurator/design_configurator.js";
const STUBS = `
const Component = class {};
const useState = (o) => o;
const SizeBox = class {};
const Many2One = class {};
const FormViewDialog = class {};
const useRef = () => ({ el: null });
const onWillStart = () => {};
const onMounted = () => {};
const onWillUnmount = () => {};
const useService = () => ({});
const registry = { category: () => ({ add: () => {} }) };
const standardActionServiceProps = {};
const _t = (s, ...a) => (a[0] && typeof a[0] === "object" ? s.replace(/%\\((\\w+)\\)s/g, (_m, k) => a[0][k]) : a.length ? s.replace(/%s/g, () => String(a.shift())) : s);
const ConfirmationDialog = class {};
const HardwareKitDialog = class {};
const setUnsavedCheck = () => {};
const clearUnsavedCheck = () => {};
`;
const dir = mkdtempSync(join(tmpdir(), "nest-"));
const tmp = join(dir, "cfg.mjs");
writeFileSync(
    tmp,
    STUBS +
        readFileSync(SRC, "utf8")
            .replace(/^\s*import\s[\s\S]*?from\s*["'][^"']+["'];?\s*$/gm, "")
            .replace(/^\s*registry\.category\([\s\S]*?\);\s*$/gm, ""),
    "utf8"
);
// The drag attaches listeners to window (deliberately — see
// onDividerPointerDown), which node has no notion of.
globalThis.window = { addEventListener() {}, removeEventListener() {} };

const { DesignConfigurator } = await import(pathToFileURL(tmp).href);

let fail = 0;
const ok = (c, m) => {
    console.log((c ? "  ok   " : "  FAIL ") + m);
    if (!c) fail++;
};
const near = (a, b, m, e = 0.001) =>
    ok(Math.abs(a - b) < e, `${m} (${Number(a).toFixed(2)} ~ ${Number(b).toFixed(2)})`);

const LEAF_TYPES = [
    { id: 1, code: "FIXED", name: "Fixed", has_hinge_side: false, has_slide_dir: false },
    { id: 2, code: "CASEMENT", name: "Casement", has_hinge_side: true, has_slide_dir: false },
    { id: 3, code: "SLIDER", name: "Slider", has_hinge_side: false, has_slide_dir: true },
    { id: 4, code: "MESH", name: "Mesh", has_hinge_side: false, has_slide_dir: true },
];

function make(rows, W = 2438.4, H = 3200.4) {
    const c = Object.create(DesignConfigurator.prototype);
    c.state = {
        loading: false, dirty: false, zoom: 1, canvasW: 900, canvasH: 600,
        canUndo: false, canRedo: false, groupTarget: {},
        libraryOpen: true, selected: null, selectedDivider: null,
        toolbar: { show: false, left: 0, top: 0 },
        data: {
            id: 1, length_uom: "ftin", size_display: "",
            header: { name: "D1", location: "", qty: 1, width_mm: W, height_mm: H,
                      window_series_id: 1, window_series_name: "Casement Single Glaze",
                      glass_product_id: false, glass_product_name: "",
                      glass_choose: false, glass_spec_product_id: false,
                      glass_spec_product_name: "" },
            rows, leaf_types: LEAF_TYPES, presets: [],
            mesh_types: [
                { id: 11, code: "MSH-FIX", name: "Fixed Mesh", mechanism: "fixed",
                  family_id: 6, family_name: "Add-on Mesh", family_sequence: 60 },
                { id: 12, code: "MSH-HNG", name: "Hinged Mesh", mechanism: "hinged",
                  family_id: 6, family_name: "Add-on Mesh", family_sequence: 60 },
            ],
            infill_types: [
                { id: 21, code: "ADD-GLS", name: "Glass", kind: "glass", uses_glass: true },
                { id: 22, code: "ADD-LOUV-F", name: "Louvre", kind: "louvre", uses_glass: false },
                { id: 23, code: "ADD-FAN", name: "Fan", kind: "fan", uses_glass: false },
            ],
            glass_category_id: 9,
            glass_products: [
                { id: 301, name: "Clear 6 mm", rate: 265.52, rate_date: "2026-01-01", source: "list" },
                { id: 302, name: "6+12+6 Clear sealed unit", rate: 400, rate_date: "2026-11-01", source: "latest" },
            ],
            grid_patterns: [{ id: 41, code: "ADD-GRID-R", name: "Georgian", kind: "rect" }],
            series_options: [
                { id: 1, name: "Casement Single Glaze",
                  leaf_type_codes: ["FIXED", "CASEMENT", "MESH"] },
                { id: 2, name: "Double Glaze Sliding",
                  leaf_type_codes: ["FIXED", "SLIDER", "MESH"] },
            ],
        },
    };
    c.canvasRef = { el: null };
    c.svgRef = { el: null };
    return c;
}
const panel = (w, code = "CASEMENT", extra = {}) => ({
    width_mm: w, is_auto: false,
    leaf_type_id: LEAF_TYPES.find((t) => t.code === code).id,
    leaf_type_code: code, hinge_side: "", swing: "", slide_dir: "",
    junction_after: "", rows: [], ...extra,
});
const labels = (c) => c.scene.leaves.map((l) => l.badge.label).join(",");

// ---------------------------------------------------------------------
console.log("FLAT DESIGN still works (backwards compatibility):");
{
    // Exactly the shape the server sends for an existing flat design:
    // no `rows` key on leaves at all.
    const c = make([{ height_mm: 3200.4, is_auto: false, leaves: [
        { width_mm: 1219.2, is_auto: false, leaf_type_id: 2, leaf_type_code: "CASEMENT", hinge_side: "left", swing: "out" },
        { width_mm: 1219.2, is_auto: false, leaf_type_id: 1, leaf_type_code: "FIXED" },
    ] }]);
    ok(c.scene.leaves.length === 2, "2 panels drawn");
    ok(labels(c) === "1,2", "numbered 1,2");
    ok(c.scene.dividers.length === 1, "one divider");
    near(c.scene.leaves[0].w + c.scene.leaves[1].w,
         c.scene.frame.w - 2 * (c.scene.leaves[0].x - c.scene.frame.x),
         "panels tile the inner frame");
}

console.log("\nTHE BRIEF'S TEST: Casement, 2 panels, split the RIGHT one horizontally");
{
    const c = make([{ height_mm: 3200.4, is_auto: false, leaves: [
        panel(1219.2, "CASEMENT", { hinge_side: "left", swing: "out" }),
        panel(1219.2, "CASEMENT", { hinge_side: "right", swing: "out" }),
    ] }]);
    ok(labels(c) === "1,2", "before: panels 1,2");

    c.selectLeaf([[0, 1]]);
    ok(c.canSplit, "right panel can be split");
    c.splitPanel("horizontal");

    ok(c.scene.leaves.length === 3, "now 3 panels");
    ok(labels(c) === "1,2,3", "renumbered IN PLACE: 1,2,3");
    const container = c.state.data.rows[0].leaves[1];
    ok(container.rows.length === 2, "right panel became a container of 2 rows");
    ok(!container.leaf_type_id, "container carries no leaf type");
    near(container.rows[0].height_mm + container.rows[1].height_mm, 3200.4,
         "sub-rows sum to the container's height");

    // top Fixed, bottom Casement hinge left swing out
    c.selectLeaf([[0, 1], [0, 0]]);
    c.setLeafType(1);
    c.selectLeaf([[0, 1], [1, 0]]);
    c.setLeafType(2);
    c.setDirection("hinge_side", "left");
    c.setDirection("swing", "out");
    const top = c.state.data.rows[0].leaves[1].rows[0].leaves[0];
    const bot = c.state.data.rows[0].leaves[1].rows[1].leaves[0];
    ok(top.leaf_type_code === "FIXED", "top sub-panel is Fixed");
    ok(bot.leaf_type_code === "CASEMENT" && bot.hinge_side === "left" && bot.swing === "out",
       "bottom sub-panel is Casement, hinge left, swing out");
    ok(c.selectedPanelLabel === "Panel 3", `right panel's bottom is Panel 3 (${c.selectedPanelLabel})`);

    console.log("\n  drag the NEW horizontal divider (inside the container):");
    const inner = c.scene.dividers.filter((d) => d.kind === "h" && d.path.length === 1);
    ok(inner.length === 1, "the nested horizontal divider exists");
    const d = inner[0];
    c.clientToUser = (ev) => ({ x: ev.clientX, y: ev.clientY });
    c.onDividerPointerDown(d, { preventDefault() {}, stopPropagation() {},
                                clientX: 0, clientY: 0 });
    ok(!!c.dragging, "drag started");
    ok(c.dragging.path.length === 1, "drag is scoped to the container, not the top level");
    // move by +200mm worth of user units. altKey, because this is
    // testing the drag ARITHMETIC: without it Part 2's snapping rounds
    // to a quarter inch and 200mm is not one. The snapping itself is
    // asserted in its own block, including that Alt bypasses it.
    const delta = 200 * d.unitsPerMM;
    c.onPointerMove({ clientX: 0, clientY: delta, altKey: true });
    const rows = c.state.data.rows[0].leaves[1].rows;
    near(rows[0].height_mm, 1600.2 + 200, "top sub-row grew by exactly 200mm");
    near(rows[1].height_mm, 1600.2 - 200, "bottom sub-row shrank by exactly 200mm");
    near(rows[0].height_mm + rows[1].height_mm, 3200.4, "container height preserved");
    c.endDrag();

    console.log("\n  outer divider still drags the TOP level:");
    const outer = c.scene.dividers.find((x) => x.kind === "v" && x.path.length === 0);
    ok(!!outer, "top-level vertical divider exists");
    c.clientToUser = (ev) => ({ x: ev.clientX, y: ev.clientY });
    c.onDividerPointerDown(outer, { preventDefault() {}, stopPropagation() {}, clientX: 0, clientY: 0 });
    ok(c.dragging.path.length === 0, "scoped to the top level");
    c.endDrag();
}

console.log("\nRESCALE recurses into containers:");
{
    const c = make([{ height_mm: 3200.4, is_auto: false, leaves: [
        panel(1219.2, "FIXED"),
        panel(1219.2, "FIXED"),
    ] }]);
    c.selectLeaf([[0, 1]]);
    c.splitPanel("vertical");
    c.onDimensionChange("width_mm", "10");   // 10 ft
    const W = c.state.data.header.width_mm;
    const top = c.state.data.rows[0].leaves;
    near(top[0].width_mm + top[1].width_mm, W, "top-level widths sum to the new width");
    const sub = top[1].rows[0].leaves;
    near(sub[0].width_mm + sub[1].width_mm, top[1].width_mm,
         "sub-panel widths sum to their container's new width");

    c.onDimensionChange("height_mm", "12");
    const H = c.state.data.header.height_mm;
    near(c.state.data.rows[0].height_mm, H, "row height follows");
    near(top[1].rows[0].height_mm, H, "sub-row height follows the container");
}

console.log("\nDEPTH LIMIT (3):");
{
    const c = make([{ height_mm: 3000, is_auto: false, leaves: [panel(2400, "FIXED")] }]);
    c.selectLeaf([[0, 0]]);
    ok(c.canSplit, "depth 1 can split");
    c.splitPanel("vertical");
    ok(c.state.selected.length === 2, "selection followed into the child");
    ok(c.canSplit, "depth 2 can split");
    c.splitPanel("vertical");
    ok(c.state.selected.length === 3, "now at depth 3");
    ok(!c.canSplit, "depth 3 CANNOT split further");
}

console.log("\nREMOVE collapses a container back to a panel:");
{
    const c = make([{ height_mm: 3000, is_auto: false, leaves: [
        panel(1200, "FIXED"), panel(1200, "CASEMENT"),
    ] }]);
    c.selectLeaf([[0, 1]]);
    c.splitPanel("horizontal");
    ok(c.scene.leaves.length === 3, "3 panels after split");
    c.selectLeaf([[0, 1], [1, 0]]);
    c.removePanel();
    ok(c.scene.leaves.length === 2, "back to 2 panels");
    ok(!c.state.data.rows[0].leaves[1].rows.length,
       "container collapsed back into a plain panel");
    ok(labels(c) === "1,2", "renumbered 1,2");
}

console.log("\nJUNCTION defaults (spec 3.3):");
{
    const french = make([{ height_mm: 3000, is_auto: false, leaves: [
        panel(1200, "CASEMENT", { hinge_side: "left" }),
        panel(1200, "CASEMENT", { hinge_side: "right" }),
    ] }]);
    french.recomputeJunctions(french.state.data.rows);
    ok(french.state.data.rows[0].leaves[0].junction_after === "meeting",
       "casement L + casement R -> meeting");

    const sliders = make([{ height_mm: 3000, is_auto: false, leaves: [
        panel(1200, "SLIDER"), panel(1200, "SLIDER"),
    ] }]);
    sliders.recomputeJunctions(sliders.state.data.rows);
    ok(sliders.state.data.rows[0].leaves[0].junction_after === "interlock",
       "slider + slider -> interlock");

    const mixed = make([{ height_mm: 3000, is_auto: false, leaves: [
        panel(1200, "FIXED"), panel(1200, "CASEMENT", { hinge_side: "right" }),
    ] }]);
    mixed.recomputeJunctions(mixed.state.data.rows);
    ok(mixed.state.data.rows[0].leaves[0].junction_after === "mullion",
       "fixed + casement -> mullion");
    ok(mixed.state.data.rows[0].leaves[1].junction_after === "",
       "last panel in the row has no junction");

    const backwards = make([{ height_mm: 3000, is_auto: false, leaves: [
        panel(1200, "CASEMENT", { hinge_side: "right" }),
        panel(1200, "CASEMENT", { hinge_side: "left" }),
    ] }]);
    backwards.recomputeJunctions(backwards.state.data.rows);
    ok(backwards.state.data.rows[0].leaves[0].junction_after === "mullion",
       "casements hinged TOWARDS each other -> mullion, not meeting");
}

console.log("\nOPENING TRIANGLES (spec 3.4): apex at the hinge side");
{
    const c = make([{ height_mm: 1000, is_auto: false, leaves: [
        panel(1000, "CASEMENT", { hinge_side: "left", swing: "out" }),
    ] }]);
    const g = c.scene.leaves[0].glyph;
    ok(!!g.triangles && g.triangles.length === 1, "one triangle for a casement");
    const leaf = c.scene.leaves[0];
    const pts = g.triangles[0].points.split(" ").map((s) => s.split(",").map(Number));
    const apex = pts[1];
    near(apex[0], leaf.x, "apex sits on the LEFT edge for hinge left");
    near(apex[1], leaf.y + leaf.h / 2, "apex is vertically centred");
    ok(g.fan.tag === "OUT", "IN/OUT tag kept");

    const tt = make([{ height_mm: 1000, is_auto: false, leaves: [
        { ...panel(1000, "CASEMENT", { hinge_side: "left" }), leaf_type_code: "TILTTURN" },
    ] }]);
    // leaf_type_id still points at CASEMENT (has_hinge_side), code says TILTTURN
    ok(tt.scene.leaves[0].glyph.triangles.length === 2,
       "tilt & turn draws two triangles");
}

console.log("\nREGRESSIONS from the Phase 1 browser test:");
{
    // A design exactly as the SERVER sends it: junction_after empty,
    // because existing designs pre-date the field. This is what made
    // every boundary draw as a mullion however its panels were hinged.
    const c = make([{ height_mm: 1500, is_auto: false, leaves: [
        { width_mm: 600, is_auto: false, panel_no: 1, is_container: false,
          leaf_type_id: 2, leaf_type_code: "CASEMENT",
          hinge_side: "left", swing: "out", slide_dir: "",
          junction_after: "", rows: [] },
        { width_mm: 600, is_auto: false, panel_no: 2, is_container: false,
          leaf_type_id: 2, leaf_type_code: "CASEMENT",
          hinge_side: "right", swing: "out", slide_dir: "",
          junction_after: "", rows: [] },
    ] }], 1200, 1500);
    ok(c.scene.dividers[0].junction === "mullion",
       "unfilled junction falls back to mullion (this was the bug)");
    c.fillMissingJunctions(c.state.data.rows);
    ok(c.scene.dividers[0].junction === "meeting",
       "filled on load: casement L | casement R -> meeting");

    c.state.data.rows[0].leaves[0].junction_after = "mullion";
    c.fillMissingJunctions(c.state.data.rows);
    ok(c.scene.dividers[0].junction === "mullion",
       "a junction chosen by hand is never overwritten by the fill");

    c.selectLeaf([[0, 1]]);
    c.setDirection("hinge_side", "left");
    ok(c.scene.dividers[0].junction === "mullion",
       "both hinged left -> mullion, re-derived when a hinge changes");
    c.setDirection("hinge_side", "right");
    ok(c.scene.dividers[0].junction === "meeting",
       "hinged back to right -> meeting again");
}

console.log("\n  glyph sizes constant in CSS pixels, not viewBox units:");
{
    const c = make([{ height_mm: 1500, is_auto: false, leaves: [
        panel(1200, "CASEMENT", { hinge_side: "left", swing: "out" }),
    ] }], 1200, 1500);
    for (const z of [0.25, 1, 4]) {
        c.state.zoom = z;
        const px = c.adornments.glyphStroke * c.fitScale * z;
        ok(Math.abs(px - 1.2) < 1e-9,
           `zoom ${z * 100}%: triangle stroke = ${px.toFixed(2)}px`);
    }
    c.state.zoom = 1;
    // The toolbar's screen position is measured from the DOM, which node
    // has none of; what IS testable here is the anchor it measures from.
    ok(c.toolbarAnchorUnits() === null,
       "no toolbar anchor when nothing is selected");
    c.selectLeaf([[0, 0]]);
    const a = c.toolbarAnchorUnits();
    ok(!!a, "toolbar anchors to the selected panel");
    const p0 = c.scene.leaves[0];
    near(a.x, p0.badge.cx, "anchored on the panel's centre line");
    near(a.yTop, p0.y, "anchored at the panel's TOP edge");
    near(a.yBottom, p0.y + p0.h, "and knows its bottom edge, to flip below");
}

console.log("\n  a divider is selected on pointerdown, not by a click:");
{
    const c = make([{ height_mm: 1500, is_auto: false, leaves: [
        panel(600, "CASEMENT", { hinge_side: "left" }),
        panel(600, "CASEMENT", { hinge_side: "right" }),
    ] }], 1200, 1500);
    c.clientToUser = (ev) => ({ x: ev.clientX, y: ev.clientY });
    const d = c.scene.dividers[0];
    c.onDividerPointerDown(d, { preventDefault() {}, stopPropagation() {},
                                clientX: 0, clientY: 0 });
    ok(c.state.selectedDivider === d.key, "pointerdown selected it");
    ok(!!c.selectedDividerEntry, "so the junction toolbar has something to show");
    const da = c.toolbarAnchorUnits();
    ok(!!da, "and the floating toolbar anchors to the divider");
    near(da.x, (d.x1 + d.x2) / 2, "anchored on the divider's mid-line");
    c.endDrag();
    // interlock is invalid between two casements now, so this asserts on a
    // junction that IS offered there -- the refusal is covered separately.
    c.setJunction("mullion");
    ok(c.scene.dividers[0].junction === "mullion", "setJunction writes through");
}

console.log("\nSELECTION STATES (the Phase 1 crash):");
{
    const c = make([{ height_mm: 1500, is_auto: false, leaves: [
        panel(600, "CASEMENT", { hinge_side: "left" }),
        panel(600, "CASEMENT", { hinge_side: "right" }),
    ] }], 1200, 1500);

    ok(c.selectionMode === "none", "nothing selected -> 'none'");
    ok(c.selectedPanel === null, "no panel");
    ok(c.selectedPanelSize === "", "no size text");
    ok(c.selectedPanelLabel === "", "no label");

    c.selectLeaf([[0, 0]]);
    ok(c.selectionMode === "panel", "panel selected -> 'panel'");
    ok(!!c.selectedPanel, "selectedPanel resolves");
    ok(c.selectedPanelLabel === "Panel 1", `label is "${c.selectedPanelLabel}"`);
    ok(/×/.test(c.selectedPanelSize),
       `size reads "${c.selectedPanelSize}" -- width x height, no NaN`);
    ok(!/NaN/.test(c.selectedPanelSize), "and contains no NaN");
    ok(!!c.selectedLeafType, "leaf type resolves, so hinge chips render");
    ok(c.selectedLeafType.has_hinge_side === true,
       "casement reports has_hinge_side, so hinge/swing appear");

    c.clientToUser = (ev) => ({ x: ev.clientX, y: ev.clientY });
    c.onDividerPointerDown(c.scene.dividers[0], {
        preventDefault() {}, stopPropagation() {}, clientX: 0, clientY: 0 });
    c.endDrag();
    ok(c.selectionMode === "divider", "divider selected -> 'divider'");
    ok(c.selectedPanel === null, "no panel while a divider is selected");
    ok(c.selectedPanelSize === "", "size text empty, not a crash");
    ok(c.selectedPanelLabel === "", "label empty, not a crash");

    // The crash was a re-render with a divider selected: zooming did it.
    for (const z of [0.25, 1, 3]) {
        c.state.zoom = z;
        let threw = null;
        try {
            void c.scene; void c.adornments; void c.selectedPanelSize;
            void c.selectedPanelLabel; void c.selectionMode;
        } catch (e) { threw = e; }
        ok(!threw, `zoom ${z * 100}% with a divider selected: no crash`);
    }

    // A selection pointing at something that no longer exists.
    c.state.selected = [[9, 9]];
    c.state.selectedDivider = null;
    let threw = null;
    try {
        void c.selectionMode; void c.selectedPanelSize; void c.selectedPanelLabel;
    } catch (e) { threw = e; }
    ok(!threw, "a stale selection path degrades quietly");
}

console.log("\nJUNCTION VALIDITY (only what makes sense):");
{
    const two = (a, b, extraA = {}, extraB = {}) => make([{
        height_mm: 1500, is_auto: false,
        leaves: [panel(600, a, extraA), panel(600, b, extraB)],
    }], 1200, 1500);

    const select = (c) => {
        c.clientToUser = (ev) => ({ x: ev.clientX, y: ev.clientY });
        c.onDividerPointerDown(c.scene.dividers[0], {
            preventDefault() {}, stopPropagation() {}, clientX: 0, clientY: 0 });
        c.endDrag();
        return Object.fromEntries(c.junctionOptions.map((o) => [o.value, o]));
    };

    const sashes = select(two("CASEMENT", "CASEMENT",
                              { hinge_side: "left" }, { hinge_side: "right" }));
    ok(sashes.mullion.enabled, "two sashes: mullion allowed");
    ok(sashes.meeting.enabled, "two sashes: meeting allowed");
    ok(!sashes.interlock.enabled, "two sashes: interlock NOT allowed");
    ok(/two sliding/i.test(sashes.interlock.title),
       `and says why: "${sashes.interlock.title}"`);

    const sliders = select(two("SLIDER", "SLIDER"));
    ok(sliders.interlock.enabled, "two sliders: interlock allowed");
    ok(!sliders.meeting.enabled, "two sliders: meeting NOT allowed");
    ok(/two opening sashes/i.test(sliders.meeting.title),
       `and says why: "${sliders.meeting.title}"`);
    ok(sliders.mullion.enabled, "two sliders: mullion still allowed");

    const mixed = select(two("FIXED", "CASEMENT", {}, { hinge_side: "right" }));
    ok(mixed.mullion.enabled, "fixed + casement: only mullion");
    ok(!mixed.meeting.enabled && !mixed.interlock.enabled,
       "fixed + casement: meeting and interlock both refused");
    ok(mixed.mullion.title.length > 0 && mixed.meeting.title.length > 0,
       "every option carries a tooltip");

    // A disabled option must not be settable, even programmatically.
    const c = two("FIXED", "CASEMENT", {}, { hinge_side: "right" });
    select(c);
    c.setJunction("interlock");
    ok(c.scene.dividers[0].junction !== "interlock",
       "setJunction refuses a disabled option");
}

console.log("\n  and the drawing differs per junction type:");
{
    const c = make([{ height_mm: 1500, is_auto: false, leaves: [
        panel(600, "CASEMENT", { hinge_side: "left" }),
        panel(600, "CASEMENT", { hinge_side: "right" }),
    ] }], 1200, 1500);
    const shapeFor = (j) => {
        c.state.data.rows[0].leaves[0].junction_after = j;
        return c.adornments.dividers[0].shape;
    };
    const mull = shapeFor("mullion");
    const meet = shapeFor("meeting");
    const lock = shapeFor("interlock");

    ok(mull.kind === "mullion" && mull.bars.length === 1 && !mull.lines.length,
       "mullion: one solid bar, no lines");
    ok(meet.kind === "meeting" && !meet.bars.length && meet.lines.length === 2,
       "meeting: two lines and NO bar");
    ok(lock.kind === "interlock" && lock.bars.length === 2,
       "interlock: two bars, overlapping");
    const [a, b] = lock.bars;
    ok(a.x < b.x && a.x + a.w > b.x, "and they genuinely overlap");
    ok(JSON.stringify(mull) !== JSON.stringify(meet) &&
       JSON.stringify(meet) !== JSON.stringify(lock) &&
       JSON.stringify(mull) !== JSON.stringify(lock),
       "all three shapes are distinct in the scene");

    // The mullion is now sized in DRAWING units (~60mm), so unlike the
    // other adornments it SHOULD grow with zoom -- that is the point.
    shapeFor("mullion");
    const d0 = c.adornments.dividers[0];
    near(d0.shape.bars[0].w, 60 * d0.unitsPerMM, "mullion bar is 60mm wide");
    const widthAt = (z) => {
        c.state.zoom = z;
        return c.adornments.dividers[0].shape.bars[0].w * c.fitScale * z;
    };
    const wide = widthAt(4), narrow = widthAt(0.25);
    ok(wide > narrow, `grows with zoom: ${narrow.toFixed(1)}px -> ${wide.toFixed(1)}px`);
    ok(narrow >= 4 - 1e-9,
       `and never thinner than 4px on screen (${narrow.toFixed(1)}px)`);
    c.state.zoom = 1;
    c.state.zoom = 1;
}

console.log("\nEXACT PANEL SIZES by typing:");
{
    const mk = () => make([{ height_mm: 1500, is_auto: false, leaves: [
        panel(600, "FIXED"), panel(600, "FIXED"),
    ] }], 1200, 1500);

    // Sizes are typed in inches (the old ft+in unit is retired).
    const c2 = mk();
    c2.notification = { add: () => {} };
    c2.selectLeaf([[0, 0]]);
    const target = 2 * 304.8 + 6 * 25.4; // 2 ft 6 in
    c2.setPanelWidth("30");
    const lv = c2.state.data.rows[0].leaves;
    near(lv[0].width_mm, target, "typed width applied exactly");
    near(lv[0].width_mm + lv[1].width_mm, 1200, "total width unchanged");

    // Automatic sibling absorbs in preference to the neighbour.
    const c3 = make([{ height_mm: 1500, is_auto: false, leaves: [
        panel(400, "FIXED"), panel(400, "FIXED", { is_auto: true }),
        panel(400, "FIXED"),
    ] }], 1200, 1500);
    c3.notification = { add: () => {} };
    c3.selectLeaf([[0, 0]]);
    c3.setPanelWidth("2 0");
    const l3 = c3.state.data.rows[0].leaves;
    near(l3[2].width_mm, 400, "non-auto neighbour untouched");
    near(l3[0].width_mm + l3[1].width_mm + l3[2].width_mm, 1200,
         "total still exact, the Automatic panel absorbed it");

    // Refusals keep the old value.
    const c4 = mk();
    let warned = 0;
    c4.notification = { add: () => { warned += 1; } };
    c4.selectLeaf([[0, 0]]);
    c4.setPanelWidth("1");             // 1 inch, below the 4in minimum
    near(c4.state.data.rows[0].leaves[0].width_mm, 600, "below minimum: refused");
    ok(warned === 1, "and the user was told");

    c4.setPanelWidth("46");            // would starve the neighbour
    near(c4.state.data.rows[0].leaves[0].width_mm, 600,
         "no room for the neighbour: refused");
    ok(warned === 2, "and told again");

    // Sole panel in its row can't be resized this way.
    const c5 = make([{ height_mm: 1500, is_auto: false,
                       leaves: [panel(1200, "FIXED")] }], 1200, 1500);
    let told = 0;
    c5.notification = { add: () => { told += 1; } };
    c5.selectLeaf([[0, 0]]);
    c5.setPanelWidth("24");
    near(c5.state.data.rows[0].leaves[0].width_mm, 1200, "sole panel unchanged");
    ok(told === 1, "explained rather than silently ignored");

    // Height edits the row, and rows still sum to the design height.
    const c6 = make([
        { height_mm: 750, is_auto: false, leaves: [panel(1200, "FIXED")] },
        { height_mm: 750, is_auto: false, leaves: [panel(1200, "FIXED")] },
    ], 1200, 1500);
    c6.notification = { add: () => {} };
    c6.selectLeaf([[0, 0]]);
    c6.setPanelHeight("36");           // 914.4mm
    near(c6.state.data.rows[0].height_mm, 914.4, "typed height applied");
    near(c6.state.data.rows[0].height_mm + c6.state.data.rows[1].height_mm, 1500,
         "rows still sum to the design height");
}

console.log("\nSERIES SWITCH:");
{
    const c = make([{ height_mm: 1500, is_auto: false, leaves: [
        panel(600, "SLIDER"), panel(600, "SLIDER"),
    ] }], 1200, 1500);
    const used = c.usedLeafTypeCodes(c.state.data.rows);
    ok(used.has("SLIDER") && used.size === 1, "collects the codes actually used");

    const casement = c.seriesOptions.find((o) => o.name === "Casement Single Glaze");
    const unsupported = [...used].filter(
        (x) => !casement.leaf_type_codes.includes(x));
    ok(unsupported.length === 1 && unsupported[0] === "SLIDER",
       "switching a slider design to Casement would strand SLIDER -> prompts");

    const sliding = c.seriesOptions.find((o) => o.name === "Double Glaze Sliding");
    ok([...used].every((x) => sliding.leaf_type_codes.includes(x)),
       "switching to another sliding Series keeps the layout, no prompt");

    // Containers are skipped -- they have no type of their own.
    const nested = make([{ height_mm: 1500, is_auto: false, leaves: [
        panel(600, "FIXED"),
        { width_mm: 600, is_auto: false, leaf_type_id: false, leaf_type_code: "",
          hinge_side: "", swing: "", slide_dir: "", junction_after: "",
          rows: [{ height_mm: 1500, is_auto: false,
                   leaves: [panel(600, "CASEMENT", { hinge_side: "left" })] }] },
    ] }], 1200, 1500);
    const nestedUsed = nested.usedLeafTypeCodes(nested.state.data.rows);
    ok(nestedUsed.has("FIXED") && nestedUsed.has("CASEMENT") && nestedUsed.size === 2,
       "recurses into containers and ignores the container itself");
}

console.log("\nSLIDING BUILDER (spec 4.2):");
{
    const SLIDE_TYPES = [
        { id: 1, code: "FIXED", name: "Fixed", has_hinge_side: false, has_slide_dir: false },
        { id: 3, code: "SLIDER", name: "Slider", has_hinge_side: false, has_slide_dir: true },
        { id: 4, code: "MESH", name: "Mesh", has_hinge_side: false, has_slide_dir: true },
    ];
    const c = make([{ height_mm: 1500, is_auto: false,
                      leaves: [panel(2400, "FIXED")] }], 2400, 1500);
    c.state.data.leaf_types = SLIDE_TYPES;
    c.state.builderOpen = false;
    c.state.builder = { panels: 2, tracks: 2, mesh: false, roles: [] };

    ok(c.canUseSlidingBuilder, "offered when the Series allows sliders");
    c.state.data.leaf_types = SLIDE_TYPES.filter((t) => t.code !== "SLIDER");
    ok(!c.canUseSlidingBuilder, "hidden when it doesn't");
    c.state.data.leaf_types = SLIDE_TYPES;

    c.setBuilder("panels", 4);
    c.setBuilder("tracks", 2);
    ok(c.slidingBuilderErrors.length === 0,
       "4 panels / 2 tracks defaults are valid: " +
       c.state.builder.roles.map((r) => r.role[0].toUpperCase() + "T" + r.track).join(" "));

    c.state.builder.roles[1].role = "slider";
    c.state.builder.roles[2].role = "slider";
    c.state.builder.roles[1].track = 1;
    c.state.builder.roles[2].track = 1;
    ok(c.slidingBuilderErrors.some((e) => /both slide on track/.test(e)),
       "adjacent sliders sharing a track: refused");

    c.state.builder.roles[2].track = 2;
    ok(!c.slidingBuilderErrors.some((e) => /both slide on track/.test(e)),
       "different tracks: allowed");

    c.state.builder.roles[0].role = "fixed";
    c.state.builder.roles[0].track = 1;
    ok(c.slidingBuilderErrors.some((e) => /belongs on the outer track/.test(e)),
       "fixed panel on an inner track: refused");
    c.setBuilderRole(0, "fixed");
    ok(c.state.builder.roles[0].track === c.state.builder.tracks,
       "choosing Fixed moves it to the outer track automatically");

    c.setBuilder("panels", 4);
    c.setBuilder("tracks", 2);
    c.setBuilder("mesh", true);
    ok(c.slidingBuilderErrors.length === 0, "with a mesh track: still valid");
    c.applySlidingBuilder();
    const lv = c.state.data.rows[0].leaves;
    ok(lv.length === 5, "4 panels + mesh = 5 leaves");
    ok(lv[4].leaf_type_code === "MESH", "mesh is last");
    ok(lv[4].track_no === 3, "mesh on the outermost track (" + lv[4].track_no + ")");
    ok(lv.every((l) => l.track_no >= 1), "every leaf has a track");
    near(lv.reduce((a, l) => a + l.width_mm, 0), 2400,
         "widths sum to the design width");
    ok(lv.some((l) => l.junction_after === "interlock"),
       "junctions derived: sliders interlock");
    ok(!c.state.builderOpen, "builder closes after applying");
    ok(c.state.dirty, "and the design is dirty");
}

console.log("\n  library grouped by family:");
{
    const one = { rows: [{ h: 1, leaves: [{ w: 1, type: "FIXED" }] }] };
    const c = make([{ height_mm: 1500, is_auto: false,
                      leaves: [panel(1200, "FIXED")] }], 1200, 1500);
    c.state.data.presets = [
        { id: 1, name: "B", family_name: "Sliding Designs", family_sequence: 40, layout: one },
        { id: 2, name: "A", family_name: "Openable Designs", family_sequence: 10, layout: one },
        { id: 3, name: "C", family_name: "Openable Designs", family_sequence: 10, layout: one },
    ];
    const groups = c.presetsByFamily;
    ok(groups.length === 2, "two families");
    ok(groups[0].family === "Openable Designs", "ordered by family sequence");
    ok(groups[0].presets.length === 2, "presets grouped under their family");

    c.state.data.presets.push({ id: 4, name: "D", layout: one });
    ok(c.presetsByFamily.length === 3,
       "a preset with no family still lands in a group");
}

console.log("\nATTACHMENTS (spec 5.1-5.5):");
{
    const mk = () => {
        const c = make([{ height_mm: 1500, is_auto: false, leaves: [
            panel(600, "CASEMENT", { hinge_side: "left", swing: "out" }),
            panel(600, "FIXED"),
        ] }], 1200, 1500);
        c.notification = { add: (m) => { c._warned = (c._warned || 0) + 1; } };
        return c;
    };

    console.log("  applying with nothing selected:");
    const none = mk();
    none.applyMesh(11);
    ok(none._warned === 1, "mesh with no panel selected warns");
    none.applyInfill(22);
    ok(none._warned === 2, "infill with no panel selected warns");
    ok(!none.state.dirty, "and nothing was changed");

    console.log("\n  mesh on a panel:");
    const c = mk();
    c.selectLeaf([[0, 0]]);
    c.applyMesh(12); // hinged
    const leaf = c.state.data.rows[0].leaves[0];
    ok(leaf.mesh_type_id === 12, "mesh applied to the selected panel");
    ok(leaf.mesh_hinge_side === "left",
       "hinged mesh defaults to the panel's own hinge side");
    ok(!!c.scene.leaves[0].attach.meshOverlay, "drawing gets a hatch overlay");
    ok(c.scene.leaves[0].attach.meshBadge.label === "MSH-HNG",
       "and a badge with the code");
    c.applyMesh(12);
    ok(!c.state.data.rows[0].leaves[0].mesh_type_id,
       "clicking the same mesh again takes it off");

    console.log("\n  infill hides the glass override when unglazed:");
    const g = mk();
    g.selectLeaf([[0, 1]]);
    ok(g.selectedPanelUsesGlass, "no infill set means glass, so override shown");
    g.setPanelGlassProduct({ id: 301, display_name: "Clear 6 mm" });
    ok(g.selectedPanel.glass_product_id === 301, "a glass product for the panel");
    g.applyInfill(22); // louvre, uses_glass false
    ok(!g.selectedPanelUsesGlass, "louvre is not glazed, so no override offered");
    ok(!g.selectedPanel.glass_product_id,
       "and the product that was set is cleared, not left to apply silently");
    g.applyInfill(21); // back to glass
    ok(g.selectedPanelUsesGlass, "back to Glass, override offered again");

    console.log("\nGLASS: one product per panel:");
    {
        const stk = mk();
        stk.state.data.header.glass_product_id = 301;
        stk.state.data.header.glass_product_name = "Clear 6 mm";
        stk.selectLeaf([[0, 0]]);
        ok(stk.panelFollowsWindow, "a panel starts by following the window");
        ok(stk.panelGlass.id === 301 && stk.headerGlassName === "Clear 6 mm",
           "and the window's product is what it is glazed with");
        const other = stk.state.data.rows[0].leaves[1];

        stk.setPanelGlassProduct({ id: 302, display_name: "6+12+6 Clear sealed unit" });
        ok(!stk.panelFollowsWindow && stk.selectedPanel.glass_product_id === 302,
           "choosing a product gives the panel its own");
        ok(stk.state.data.header.glass_product_id === 301 && !other.glass_product_id,
           "the window and the other panel did not move");
        ok(stk.selectedPanel.glass_chosen === true, "a hand choice is a choice, not a suggestion");
        ok(stk.panelGlassRateText.includes("latest rate 400"), "the rate source is named");

        // rate: the product's, then a typed one (manual), then Reset
        ok(stk.glassRateUsed(stk.selectedPanel) === 400, "the rate used is the product's");
        stk.setGlassRate("350");
        ok(stk.selectedPanel.glass_rate_manual && stk.glassRateUsed(stk.selectedPanel) === 350,
           "a typed rate is manual");
        stk.resetGlassRate();
        ok(!stk.selectedPanel.glass_rate_manual && stk.glassRateUsed(stk.selectedPanel) === 400,
           "Reset returns to the product's rate");
        stk.setGlassRate("350");
        stk.setPanelGlassProduct({ id: 301, display_name: "Clear 6 mm" });
        ok(!stk.selectedPanel.glass_rate_manual, "a different product drops the typed rate");

        // size: the rule's until typed, typed is flagged, Use the rule undoes it
        const leaf = stk.selectedPanel;
        leaf.glass_rule_w = 600; leaf.glass_rule_h = 1500;
        ok(stk.panelGlassSize(leaf).w === 600, "the size is the rule's");
        stk.setGlassSizeManual(true);
        ok(leaf.glass_size_manual && leaf.glass_w_mm === 600 && leaf.glass_h_mm === 1500,
           "typing a size starts from the rule's");
        stk.setGlassSize("w", "500", "mm");
        ok(stk.panelGlassSize(leaf).w === 500 && leaf.glass_size_manual, "a typed size is used and flagged");
        stk.setGlassSizeManual(false);
        ok(stk.panelGlassSize(leaf).w === 600, "Use the rule returns to it");
        stk.setGlassRate("100");
        ok(Math.abs(stk.glassAreaSqft(leaf) - (600 * 1500) / (304.8 * 304.8)) < 1e-9
           && Math.abs(stk.panelGlassCost - stk.glassAreaSqft(leaf) * 100) < 1e-9,
           "cost is the area in sqft times the rate");

        // Copy from panel, Follow the window
        stk.selectLeaf([[0, 1]]);
        stk.copyGlassFromPanel({ target: { value: "1" } });
        ok(other.glass_product_id === 301 && other.glass_rate_manual && other.glass_manual_rate === 100,
           "Copy from panel takes the product, size and rate");
        stk.followWindowGlass();
        ok(stk.panelFollowsWindow && !other.glass_rate_manual, "Follow the window drops the panel's own");

        // a panel whose glass has to be chosen
        stk.state.data.header.glass_product_id = false;
        stk.state.data.header.glass_product_name = "";
        other.glass_choose = true;
        ok(stk.panelGlass === null, "no product: nothing to glaze with");
        const header = stk.state.data.header;
        stk.setHeaderGlassProduct({ id: 302, display_name: "6+12+6 Clear sealed unit" });
        stk.state.data.rows[0].leaves[0].glass_product_id = false;
        ok(header.glass_product_id === 302 && stk.headerGlassName.startsWith("6+12+6"),
           "the window's product is set from the top bar");
        ok(stk.panelGlass === null && stk.panelGlassOf(stk.state.data.rows[0].leaves[0]).id === 302,
           "a panel flagged to choose does not follow it; the others do");
        const xml = readFileSync(
            "odoo/addons/aw_fenestration_design/static/src/design_configurator/design_configurator.xml",
            "utf8");
        ok(!xml.includes("Apply to all panels"), "the header has no Apply to all panels");
    }

    console.log("\n  infill symbols differ per kind:");
    const sym = mk();
    sym.selectLeaf([[0, 1]]);
    sym.applyInfill(22);
    const louvre = sym.scene.leaves[1].attach.infill;
    ok(louvre.kind === "louvre" && louvre.slats.length >= 3,
       `louvre drawn as ${louvre.slats.length} slats`);
    sym.applyInfill(23);
    const fan = sym.scene.leaves[1].attach.infill;
    ok(fan.kind === "fan" && fan.r > 0, "fan drawn as a circle");
    ok(JSON.stringify(louvre) !== JSON.stringify(fan),
       "the two symbols are genuinely different");

    console.log("\n  Georgian bars:");
    const grid = mk();
    grid.selectLeaf([[0, 1]]);
    grid.setPanelGrid("41");
    ok(grid.selectedPanel.grid_rows === 2 && grid.selectedPanel.grid_cols === 2,
       "picking a pattern seeds a sensible 2x2");
    grid.setPanelGridSize("grid_rows", "2");
    grid.setPanelGridSize("grid_cols", "3");
    const bars = grid.scene.leaves[1].attach.grid.bars;
    ok(bars.length === 1 + 2, `2 rows x 3 cols -> ${bars.length} bars (1 horizontal, 2 vertical)`);
    grid.setPanelGrid("");
    ok(!grid.scene.leaves[1].attach.grid, "clearing the pattern removes the bars");

    console.log("\n  attachment strokes are screen-constant:");
    const z = mk();
    for (const zoom of [0.25, 1, 4]) {
        z.state.zoom = zoom;
        const px = z.adornments.gridStroke * z.fitScale * zoom;
        near(px, 2, `zoom ${zoom * 100}%: grid bar = ${px.toFixed(2)}px`);
    }
    z.state.zoom = 1;
}

console.log("\n  TWN presets carry mesh through applyPreset:");
{
    const c = make([{ height_mm: 1500, is_auto: false,
                      leaves: [panel(1200, "FIXED")] }], 1200, 1500);
    c.notification = { add: () => {} };
    c.applyPreset({
        id: 99, name: "Twin Sash: Casement left + Mesh",
        family_name: "Twin Sash Designs", family_sequence: 30,
        layout: { rows: [{ h: 1, leaves: [
            { w: 1, type: "CASEMENT", hinge: "left", swing: "out", mesh: "MSH-HNG" },
        ] }] },
    });
    const leaf = c.state.data.rows[0].leaves[0];
    ok(leaf.leaf_type_code === "CASEMENT", "panel type applied");
    ok(leaf.mesh_type_id === 12, "mesh code resolved to its id");
    ok(leaf.mesh_hinge_side === "left", "mesh hinge follows the panel");
}

// ---------------------------------------------------------------------
console.log("\nSPLIT into 2, 3 or 4 equal parts:");
{
    // 3 and 4 exist because splitting twice is NOT the same thing:
    // halving a half gives 50/25/25, plus a nesting level nobody asked
    // for. These have to come out equal and add up in one step.
    for (const n of [2, 3, 4]) {
        const c = make([{ height_mm: 3000, is_auto: false,
                          leaves: [panel(2400, "FIXED")] }], 2400, 3000);
        c.selectLeaf([[0, 0]]);
        c.splitPanel("vertical", n);
        const kids = c.state.data.rows[0].leaves[0].rows[0].leaves;
        ok(kids.length === n, `vertical ${n} -> ${n} panels`);
        near(kids.reduce((a, l) => a + l.width_mm, 0), 2400,
             `vertical ${n} widths sum to the parent`);
        ok(kids.every((l) => Math.abs(l.width_mm - 2400 / n) < 0.001),
           `vertical ${n} panels are equal`);
    }
    for (const n of [2, 3, 4]) {
        const c = make([{ height_mm: 3000, is_auto: false,
                          leaves: [panel(2400, "FIXED")] }], 2400, 3000);
        c.selectLeaf([[0, 0]]);
        c.splitPanel("horizontal", n);
        const rows = c.state.data.rows[0].leaves[0].rows;
        ok(rows.length === n, `horizontal ${n} -> ${n} rows`);
        near(rows.reduce((a, r) => a + r.height_mm, 0), 3000,
             `horizontal ${n} heights sum to the parent`);
    }
    // The count is clamped, not trusted: it reaches splitPanel from a
    // template expression.
    const c = make([{ height_mm: 3000, is_auto: false,
                      leaves: [panel(2400, "FIXED")] }], 2400, 3000);
    c.selectLeaf([[0, 0]]);
    c.splitPanel("vertical", 99);
    ok(c.state.data.rows[0].leaves[0].rows[0].leaves.length === 4,
       "a silly count clamps to 4 rather than drawing 99 panels");
}

console.log("\nEQUALIZE evens out what is there, keeping the total:");
{
    const c = make([{ height_mm: 3000, is_auto: false, leaves: [
        panel(1800, "FIXED"), panel(400, "FIXED"), panel(200, "FIXED"),
    ] }], 2400, 3000);
    c.selectLeaf([[0, 1]]);
    ok(c.canEqualizeWidths, "three panels across can be equalized");
    ok(!c.canEqualizeHeights, "one row has no stack to equalize");
    c.equalizeWidths();
    const leaves = c.state.data.rows[0].leaves;
    near(leaves.reduce((a, l) => a + l.width_mm, 0), 2400,
         "the opening is NOT resized, only redistributed");
    ok(leaves.every((l) => Math.abs(l.width_mm - 800) < 0.001),
       "all three are 800 wide");
}

console.log("\n  Equalize refits a container's children:");
{
    const c = make([{ height_mm: 3000, is_auto: false, leaves: [
        panel(1800, "FIXED"), panel(600, "FIXED"),
    ] }], 2400, 3000);
    c.selectLeaf([[0, 0]]);
    c.splitPanel("vertical", 2);       // 1800 -> 900 + 900
    c.selectLeaf([[0, 1]]);
    c.equalizeWidths();                // top level -> 1200 + 1200
    const top = c.state.data.rows[0].leaves;
    near(top[0].width_mm, 1200, "container evened out");
    const kids = top[0].rows[0].leaves;
    near(kids.reduce((a, l) => a + l.width_mm, 0), 1200,
         "its children were refitted to its new width");
}

console.log("\n  Equalize heights across a stack:");
{
    const c = make([
        { height_mm: 2400, is_auto: false, leaves: [panel(2400, "FIXED")] },
        { height_mm: 600, is_auto: false, leaves: [panel(2400, "FIXED")] },
    ], 2400, 3000);
    c.selectLeaf([[1, 0]]);
    ok(c.canEqualizeHeights, "two rows can be equalized");
    c.equalizeHeights();
    const rows = c.state.data.rows;
    near(rows[0].height_mm, 1500, "top row halved the stack");
    near(rows[0].height_mm + rows[1].height_mm, 3000,
         "the design's height is unchanged");
}

console.log("\nRIGHT-HAND TABS:");
{
    const c = make([{ height_mm: 3000, is_auto: false,
                      leaves: [panel(2400, "FIXED")] }], 2400, 3000);
    c.state.rightTab = "panel";
    ok(c.rightTabs.map((t) => t.key).join(",") === "panel,spec,checks",
       "Pricing is not offered on a design that has none");
    ok(c.activeRightTab === "panel", "panel is the active tab");

    // A remembered tab that no longer exists must not leave the column
    // blank with no way back.
    c.state.rightTab = "pricing";
    ok(c.activeRightTab === "panel", "an unavailable tab falls back to Panel");

    c.state.data.checks = [
        { level: "warning", message: "one" },
        { level: "warning", message: "two" },
    ];
    const warned = c.rightTabs.find((t) => t.key === "checks");
    ok(warned.badge === 2 && !warned.danger, "warnings badge, not red");

    c.state.data.checks.push({ level: "error", message: "three" });
    const bad = c.rightTabs.find((t) => t.key === "checks");
    ok(bad.badge === 3 && bad.danger, "an error makes the badge red");

    // Opens itself on new results, and ONLY then -- a tab that forced
    // itself open every render would take the column hostage.
    c.state.rightTab = "spec";
    c.surfaceCheckErrors();
    ok(c.activeRightTab === "checks", "an error brings Checks to the front");
    c.setRightTab("spec");
    ok(c.activeRightTab === "spec",
       "the user can still look away from a standing error");
}

// ---------------------------------------------------------------------
console.log("\nLOCK BAR (phase 7d): the far edge from the way the sash moves");
{
    const c = make([{ height_mm: 3000, is_auto: false, leaves: [
        panel(800, "CASEMENT", { hinge_side: "left", swing: "out" }),
        panel(800, "CASEMENT", { hinge_side: "top", swing: "out" }),
        panel(800, "FIXED"),
    ] }], 2400, 3000);

    const marks = c.scene.leaves.map((l) => l.attach.lock);
    ok(!!marks[0], "a hinged sash gets a lock mark");
    ok(marks[0].x1 === marks[0].x2, "hinge left -> a VERTICAL mark");
    near(marks[0].x1, c.scene.leaves[0].x + c.scene.leaves[0].w,
         "hinge left -> the mark is on the RIGHT edge");

    ok(!!marks[1], "a top-hung sash gets one too");
    ok(marks[1].y1 === marks[1].y2, "top-hung -> a HORIZONTAL mark");
    near(marks[1].y1, c.scene.leaves[1].y + c.scene.leaves[1].h,
         "top-hung -> the mark is along the BOTTOM edge");

    ok(marks[2] === null, "a fixed light has no lock side, so no mark");

    // A SLIDING sash locks on the edge it closes towards, which is
    // opposite its slide direction: slides left to open -> shuts to the
    // right -> lock bar on its right edge. The PROFILE differs (the
    // sliding systems use their own), but that comes from the system's
    // spec, not from the geometry.
    const slider = make([{ height_mm: 3000, is_auto: false,
                           leaves: [panel(2400, "SLIDER", { slide_dir: "left" })] }],
                        2400, 3000);
    const sm = slider.scene.leaves[0].attach.lock;
    ok(!!sm, "a sliding sash gets a lock mark too");
    ok(sm.x1 === sm.x2, "slide left -> a VERTICAL mark");
    near(sm.x1, slider.scene.leaves[0].x + slider.scene.leaves[0].w,
         "slides left to open -> the mark is on the RIGHT edge");

    const right = make([{ height_mm: 3000, is_auto: false,
                          leaves: [panel(2400, "SLIDER", { slide_dir: "right" })] }],
                       2400, 3000);
    near(right.scene.leaves[0].attach.lock.x1, right.scene.leaves[0].x,
         "slides right to open -> the mark is on the LEFT edge");

    // Direction not set yet: no side to put it on, and nothing invented.
    const undecided = make([{ height_mm: 3000, is_auto: false,
                              leaves: [panel(2400, "SLIDER")] }], 2400, 3000);
    ok(undecided.scene.leaves[0].attach.lock === null,
       "a sash with no direction set yet gets no mark");
}

console.log("\n  the Lock toggle:");
{
    const c = make([{ height_mm: 3000, is_auto: false,
                      leaves: [panel(2400, "CASEMENT", { hinge_side: "left" })] }],
                   2400, 3000);
    c.selectLeaf([[0, 0]]);
    ok(c.showLockToggle, "offered on a hinged sash");
    ok(c.panelHasLock, "an absent has_lock reads as ON, as the server holds");
    ok(c.lockEdgeLabel === "right", "and it says which side: right");

    c.toggleLock();
    ok(c.state.data.rows[0].leaves[0].has_lock === false, "toggled off");
    ok(c.scene.leaves[0].attach.lock === null, "so the mark goes");
    ok(c.state.dirty, "and the design is dirty");
    c.toggleLock();
    ok(c.panelHasLock, "and back on again");

    const fixed = make([{ height_mm: 3000, is_auto: false,
                          leaves: [panel(2400, "FIXED")] }], 2400, 3000);
    fixed.selectLeaf([[0, 0]]);
    ok(!fixed.showLockToggle, "not offered on a fixed light");

    const slider = make([{ height_mm: 3000, is_auto: false,
                           leaves: [panel(2400, "SLIDER", { slide_dir: "left" })] }],
                        2400, 3000);
    slider.selectLeaf([[0, 0]]);
    ok(slider.showLockToggle, "offered on a sliding sash as well");
    ok(slider.lockEdgeLabel === "right",
       "and names the edge it closes towards: right");
}

console.log("\nSPEC TAB (phase 7c):");
{
    const c = make([{ height_mm: 3000, is_auto: false,
                      leaves: [panel(2400, "CASEMENT")] }], 2400, 3000);
    c.state.data.spec_options = [{ id: 7, name: "RE spec", is_default: true }];
    c.state.data.header.template_id = 7;
    c.state.data.header.template_name = "RE spec";
    c.state.data.spec_parts = {
        profiles: [
            { position_id: 1, position_name: "Outer Frame - Top",
              product_name: "RE-8", spec_name: "RE-8", changed: false },
            { position_id: 2, position_name: "Lock Bar",
              product_name: "RE-27", spec_name: "RE-13", changed: true },
        ],
        hardware: [
            { line_id: 5, line_name: "Handle", product_name: "Handle",
              spec_name: "Handle", qty: 1, changed: false },
        ],
    };

    ok(c.specName === "RE spec", "the header names the spec");
    ok(!c.showSpecPicker, "one spec is not a choice, so no dropdown");
    c.state.data.spec_options.push({ id: 8, name: "Heavy duty" });
    ok(c.showSpecPicker, "two specs -> a dropdown");

    ok(c.changeCount === 1, "one part differs from the spec");
    const tab = c.rightTabs.find((t) => t.key === "spec");
    ok(tab.badge === 1, "the Spec tab badges the change count");
    ok(!tab.danger, "a change is not an error, so the badge is not red");

    ok(c.sourceLabel(c.specProfiles[0]) === "spec", "unchanged part: spec");
    ok(c.sourceLabel(c.specProfiles[1]) === "changed", "changed part: changed");

    ok(!c.canSaveAsSpec, "no name typed, so Save as new spec is disabled");
    c.state.specName = "  RE heavy  ";
    ok(c.canSaveAsSpec, "a name enables it");
    c.state.specName = "   ";
    ok(!c.canSaveAsSpec, "whitespace is not a name");
}

// ---------------------------------------------------------------------
console.log("\nLIBRARY GROUPS (Part 2 revised): Shapes | Our designs | ...");
{
    const c = make([{ height_mm: 3000, is_auto: false,
                      leaves: [panel(2400, "FIXED")] }], 2400, 3000);
    c.state.data.presets = [
        { id: 1, name: "3 across", kind: "shape",
          layout: { rows: [{ h: 1, leaves: [
              { w: 1, type: "FIXED" }, { w: 1, type: "FIXED" },
              { w: 1, type: "FIXED" }] }] } },
        { id: 2, name: "Openable + Fixed + Openable", kind: "design",
          layout: { rows: [{ h: 1, leaves: [
              { w: 1, type: "CASEMENT", hinge: "left" },
              { w: 2, type: "FIXED" },
              { w: 1, type: "CASEMENT", hinge: "right" }] }] } },
        // No kind at all: a preset from before the split must still
        // appear, not vanish.
        { id: 3, name: "Legacy", layout: { rows: [{ h: 1, leaves: [
            { w: 1, type: "FIXED" }] }] } },
    ];
    const keys = c.libraryGroups.map((g) => g.key);
    ok(keys.includes("shapes") && keys.includes("designs"),
       "Shapes and Our designs are both offered");
    ok(keys.includes("screens"), "Fly screens group present");
    ok(keys.includes("addons"), "Add-ons group present");
    ok(!keys.includes("families"), "no mechanism families any more");

    const shapes = c.libraryGroups.find((g) => g.key === "shapes");
    const designs = c.libraryGroups.find((g) => g.key === "designs");
    ok(shapes.items.length === 1, "one shape");
    ok(designs.items.length === 2,
       "a preset with no kind falls in with the designs, not nowhere");

    // Georgian bars are NOT in the library: a pattern needs rows x cols
    // to mean anything, so it is set on the Panel tab.
    const addons = c.libraryGroups.find((g) => g.key === "addons");
    ok(addons.items.every((i) => i.attachKind === "infill"),
       "Add-ons holds infills only, each tagged for applyAttachment");

    // An empty group is dropped rather than drawn as a heading over
    // nothing.
    c.state.data.mesh_types = [];
    ok(!c.libraryGroups.some((g) => g.key === "screens"),
       "a group with nothing in it is not shown");
}

console.log("\nAPPLYING A SHAPE keeps the panel types that still fit:");
{
    const c = make([{ height_mm: 3000, is_auto: false, leaves: [
        panel(1200, "CASEMENT", { hinge_side: "left", swing: "out" }),
        panel(1200, "FIXED"),
    ] }], 2400, 3000);
    c.notification = { add: () => {} };
    c.applyShape({
        id: 1, name: "3 across", kind: "shape",
        layout: { rows: [{ h: 1, leaves: [
            { w: 1, type: "FIXED" }, { w: 1, type: "FIXED" },
            { w: 1, type: "FIXED" }] }] },
    });
    const leaves = c.state.data.rows[0].leaves;
    ok(leaves.length === 3, "3 panels after the shape");
    ok(leaves[0].leaf_type_code === "CASEMENT" && leaves[0].hinge_side === "left",
       "panel 1 kept its casement AND its hinge");
    ok(leaves[1].leaf_type_code === "FIXED", "panel 2 kept Fixed");
    ok(leaves[2].leaf_type_code === "FIXED",
       "the NEW panel is Fixed, not a copy of anything");
    near(leaves.reduce((a, l) => a + l.width_mm, 0), 2400,
         "the opening is unchanged");
}

console.log("\nGRID QUICK START:");
{
    const c = make([{ height_mm: 3000, is_auto: false,
                      leaves: [panel(2400, "CASEMENT")] }], 2400, 3000);
    c.applyGridStart(2, 2);
    const rows = c.state.data.rows;
    ok(rows.length === 2, "2 rows");
    ok(rows.every((r) => r.leaves.length === 2), "2 columns each");
    ok(rows.every((r) => r.leaves.every((l) => l.leaf_type_code === "FIXED")),
       "every panel Fixed");
    near(rows.reduce((a, r) => a + r.height_mm, 0), 3000, "heights sum");
    near(rows[0].leaves.reduce((a, l) => a + l.width_mm, 0), 2400,
         "widths sum");
    // Clamped: the control offers 1 to 6 and the method is reachable
    // from a template expression.
    c.applyGridStart(99, 0);
    ok(c.state.data.rows.length === 1
       && c.state.data.rows[0].leaves.length === 6,
       "out-of-range counts clamp to 1..6");
}

console.log("\nFRAME-LEVEL add row / column:");
{
    const c = make([{ height_mm: 3000, is_auto: false, leaves: [
        panel(800, "FIXED"), panel(800, "FIXED"), panel(800, "FIXED"),
    ] }], 2400, 3000);
    c.addFrameRow("above");
    const rows = c.state.data.rows;
    ok(rows.length === 2, "a row was added");
    ok(rows[0].leaves.length === 1,
       "the new row spans the whole width as ONE panel");
    ok(rows[1].leaves.length === 3, "the original three are untouched");
    near(rows.reduce((a, r) => a + r.height_mm, 0), 3000,
         "the opening's height did NOT grow");

    // A column across several rows cannot be a leaf of one of them, so
    // the existing layout has to be wrapped.
    const d = make([
        { height_mm: 1500, is_auto: false, leaves: [panel(2400, "FIXED")] },
        { height_mm: 1500, is_auto: false, leaves: [panel(2400, "FIXED")] },
    ], 2400, 3000);
    d.addFrameColumn("left");
    ok(d.state.data.rows.length === 1,
       "the two rows were wrapped into one");
    const top = d.state.data.rows[0].leaves;
    ok(top.length === 2, "column plus wrapper");
    ok(!top[0].rows.length && top[1].rows.length === 2,
       "the column is a panel; the wrapper holds the old rows");
    near(top[0].width_mm + top[1].width_mm, 2400,
         "the opening's width did NOT grow");

    // With one row it is simply another leaf, no wrapper.
    const e = make([{ height_mm: 3000, is_auto: false,
                      leaves: [panel(2400, "FIXED")] }], 2400, 3000);
    e.addFrameColumn("right");
    ok(e.state.data.rows.length === 1, "still one row");
    ok(e.state.data.rows[0].leaves.length === 2,
       "one row: the column is just another leaf");
    ok(e.state.data.rows[0].leaves.every((l) => !l.rows.length),
       "and nothing was wrapped");
}

console.log("\nSNAPPING:");
{
    const c = make([{ height_mm: 3000, is_auto: false, leaves: [
        panel(1000, "FIXED"), panel(1400, "FIXED"),
    ] }], 2400, 3000);
    c.state.data.length_uom = "mm";
    near(c.snapStepMm, 5, "mm snaps to 5mm");
    c.state.data.length_uom = "ftin";
    near(c.snapStepMm, 6.35, "ft+in snaps to a quarter inch");
    c.state.data.length_uom = "in";
    near(c.snapStepMm, 6.35, "inches snap to a quarter inch too");

    // The step is the floor; an equal split beats it.
    const drag = { kind: "v", path: [], ri: 0, li: 0 };
    const targets = c.snapTargets(drag);
    ok(targets.some((t) => Math.abs(t - 1200) < 0.001),
       "the halfway point is a snap target");
    ok(targets.some((t) => Math.abs(t - 800) < 0.001),
       "so is the one-third point");

    c.state.data.length_uom = "mm";
    near(c.snapOffset(1003, [], 0), 1005, "with no targets it rounds to 5mm");
    near(c.snapOffset(1197, targets, 10), 1200,
         "a nearby equal split wins over the step");
    near(c.snapOffset(1150, targets, 10), 1150,
         "a target out of tolerance does NOT pull");

    // End to end through a real drag: snapped by default, exact with Alt.
    const d = make([{ height_mm: 3000, is_auto: false, leaves: [
        panel(1000, "FIXED"), panel(1400, "FIXED"),
    ] }], 2400, 3000);
    d.state.data.length_uom = "mm";
    d.clientToUser = (ev) => ({ x: ev.clientX, y: ev.clientY });
    const div = d.scene.dividers[0];
    const move = 37 * div.unitsPerMM;   // 37mm: not a multiple of 5

    d.onDividerPointerDown(div, { preventDefault() {}, stopPropagation() {},
                                  clientX: 0, clientY: 0 });
    d.onPointerMove({ clientX: move, clientY: 0 });
    near(d.state.data.rows[0].leaves[0].width_mm, 1035,
         "a 37mm drag lands on 1035, the nearest 5mm");
    near(d.state.data.rows[0].leaves[0].width_mm
         + d.state.data.rows[0].leaves[1].width_mm, 2400,
         "and the two sides still sum to the row");

    d.onPointerMove({ clientX: move, clientY: 0, altKey: true });
    near(d.state.data.rows[0].leaves[0].width_mm, 1037,
         "Alt-drag goes exactly where it is put");
    ok(d.state.snapGuide === null, "and draws no guide");
    d.endDrag();
    ok(d.state.snapGuide === null, "the guide is cleared when the drag ends");
}

// ---------------------------------------------------------------------
console.log("\nDIVIDER ALTERNATES (phase 7d): a profile, not a line");
{
    const c = make([{ height_mm: 3000, is_auto: false, leaves: [
        panel(1200, "FIXED"), panel(1200, "FIXED"),
    ] }], 2400, 3000);
    // RE-1 is the position's default, RE-3 its heavier alternate.
    c.state.data.divider_options = {
        vertical: [
            { id: 101, name: "RE-1", is_default: true, max_span_mm: 1500 },
            { id: 103, name: "RE-3", is_default: false, max_span_mm: 0 },
        ],
        horizontal: [],
    };
    const div = c.scene.dividers[0];
    c.onDividerPointerDown(div, { preventDefault() {}, stopPropagation() {},
                                 clientX: 0, clientY: 0 });
    c.endDrag();

    ok(c.dividerOptions.length === 2, "both profiles offered");
    ok(c.selectedDividerProductId === false, "nothing stored to begin with");
    ok(c.isDividerOptionActive(c.dividerOptions[0]),
       "the DEFAULT lights up on an untouched divider");
    ok(!c.isDividerOptionActive(c.dividerOptions[1]),
       "and the alternate does not");

    c.setDividerOption(103);
    ok(c.state.data.rows[0].leaves[0].divider_product_id === 103,
       "choosing the alternate stores the PRODUCT");
    ok(c.isDividerOptionActive(c.dividerOptions[1]), "and it lights up");

    // Back to the default stores NOTHING, so a spec that later changes
    // its default carries the design with it.
    c.setDividerOption(101);
    ok(c.state.data.rows[0].leaves[0].divider_product_id === false,
       "choosing the default stores nothing, not the default's id");

    c.setDividerOption(103);
    c.setDividerOption(103);
    ok(c.state.data.rows[0].leaves[0].divider_product_id === false,
       "clicking the chosen one again goes back to the default");
}

console.log("\n  the Frame label is the SHORT name:");
{
    const c = make([{ height_mm: 3000, is_auto: false,
                      leaves: [panel(2400, "FIXED")] }], 2400, 3000);
    c.state.data.system_label = "Double Glaze - Openable";
    c.state.data.system_short = "Openable";
    ok(c.systemLabel === "Openable",
       "the header shows the short form, since Glazing is beside it");
    ok(c.systemLabelFull === "Double Glaze - Openable",
       "and the full name is the tooltip");

    // A system with no role still has to read as something.
    c.state.data.system_short = "";
    ok(c.systemLabel === "Double Glaze - Openable",
       "no short form falls back to the full name rather than going blank");
}

{
    // The Panel tab's unit switch: display only, mm stays the stored value.
    const c = make([{ height_mm: 1500, is_auto: false, leaves: [
        panel(600, "FIXED"), panel(600, "FIXED"),
    ] }], 1200, 1500);
    c.notification = { add: () => {} };
    c.selectLeaf([[0, 0]]);
    c.setUnitMode("mm");
    ok(c.state.unitMode === "mm" && !c.showIn && c.showMm, "mm shows only the mm boxes");
    c.setUnitMode("in");
    ok(c.showIn && !c.showMm, "in shows only the inch boxes");
    c.setUnitMode("both");
    ok(c.showIn && c.showMm, "both shows both");
    c.setUnitMode("feet");
    ok(c.state.unitMode === "both", "an unknown mode is ignored");
    ok(c.panelWidthBox("mm") === "600", "the mm box shows the stored 600");
    c.setPanelWidth("700", "mm");
    near(c.state.data.rows[0].leaves[0].width_mm, 700, "typing mm stores exactly that");
    c.setPanelWidth("24", "in");
    near(c.state.data.rows[0].leaves[0].width_mm, 24 * 25.4, "typing inches stores mm");
    const both = c.modeLengthPair(1829, 1791);
    ok(both.includes(" mm") && both.includes(" in"), "both shows inches and mm");
    c.setUnitMode("mm");
    ok(c.modeLengthPair(1829, 1791) === "1829 \u00d7 1791 mm", "mm only reads in mm");
    ok(c.profileText({ profile_code: "HD-14", profile_name: "Frame" }) === "HD-14 Frame",
       "a piece reads as code and name");
    ok(c.profileText({ profile_code: "HD-14", profile_name: "HD-14 Frame" }) === "HD-14 Frame",
       "a name that already starts with the code is not doubled");
}

{
    // Hardware per panel: own rows, the rate used, copying.
    const c = make([{ height_mm: 1500, is_auto: false, leaves: [
        panel(600, "CASEMENT"), panel(600, "CASEMENT"),
    ] }], 1200, 1500);
    c.notification = { add: () => {} };
    c.state.data.hardware_products = [{ id: 7, name: "Roller", cost: 50 }];
    c.selectLeaf([[0, 0]]);
    ok(c.panelFollowsSpecHardware, "a panel with no rows follows the spec");
    c.addHardware();
    ok(!c.panelFollowsSpecHardware && c.panelHardware.length === 1,
       "adding a row makes the panel use its own");
    c.setHardwareProduct(0, "7");
    c.setHardwareQty(0, "3");
    const row = c.panelHardware[0];
    ok(row.product_id === 7 && row.name === "Roller", "the product is picked by id");
    ok(c.hardwareRateUsed(row) === 50, "the rate used defaults to the product cost");
    near(c.hardwareCost(row), 150, "cost is qty x rate");
    c.setHardwareRate(0, "70");
    ok(row.rate_manual && c.hardwareRateUsed(row) === 70, "a typed rate is manual");
    near(c.panelHardwareCost, 210, "the panel total follows the typed rate");
    c.resetHardwareRate(0);
    ok(!row.rate_manual && c.hardwareRateUsed(row) === 50, "Reset returns the product cost");
    ok(!("copyHardwareToOthers" in c) && !("followSpecHardware" in c),
       "Copy to other panels and Follow the spec are gone");
    c.selectLeaf([[0, 1]]);
    c.copyHardwareFromPanel({ target: { value: "1" } });
    const other = c.state.data.rows[0].leaves[1];
    ok((other.hardware || []).length === 1 && other.hardware[0] !== row
       && other.hardware[0].qty === 3, "Copy from panel gives the panel its own row");
    other.hardware[0].qty = 9;
    ok(row.qty === 3, "the copy is independent of the original");
    other.hardware = [];
    ok(c.panelFollowsSpecHardware, "taking every row off follows the spec again");
    c.selectLeaf([[0, 0]]);
    c.removeHardware(0);
    c.selectLeaf([[0, 1]]);
    c.selectLeaf([[0, 1]]);
    c.copyHardwareFromPanel({ target: { value: "1" } });
    ok(c.panelHardware.length === 0, "copying from a panel with none leaves none");
}

{
    // Checks as links: a click selects the panel, opens the tab, opens the
    // section; a record opens in a dialog.
    const c = make([{ height_mm: 1500, is_auto: false, leaves: [
        panel(600, "CASEMENT"), panel(600, "CASEMENT"),
    ] }], 1200, 1500);
    c.notification = { add: () => {} };
    c.state.collapsed = { hardware: true };
    c.state.rightTab = "checks";
    c.goToCheck({ target_kind: "hardware", panel_no: 2 });
    ok(JSON.stringify(c.state.selected) === JSON.stringify([[0, 1]]),
       "a hardware check selects panel 2");
    ok(c.state.rightTab === "panel", "and opens the Panel tab");
    ok(c.state.collapsed.hardware === false, "and opens the Hardware section");
    ok(c.checkTargetName({ target_kind: "hardware" }) === "hardware"
       && c.checkTargetName({ target_kind: "glass" }) === "glass",
       "the row to flash is named by the check");
    ok(c.checkTargetName({ target_kind: "piece", target_key: "5|1|1|1" })
       === "piece:5|1|1|1", "a piece is found by its stable key");
    c.goToCheck({ target_kind: "panel", panel_no: 0 });
    ok(c.state.selected === null, "panel 0 is the frame: nothing selected");
    let warned = 0;
    c.notification = { add: () => { warned += 1; } };
    c.goToCheck({ target_kind: "glass", panel_no: 9 });
    ok(warned === 1, "a panel that is gone says so rather than doing nothing");
    let opened = null;
    c.dialog = { add: (component, props) => { opened = props; } };
    c.goToCheck({ target_kind: "record", target_model: "product.product",
                  target_res_id: 42, message: "Roller has no cost price" });
    ok(opened && opened.resModel === "product.product" && opened.resId === 42
       && opened.canExpand === true, "a record opens in a dialog with Expand");
    ok(c.checkHasTarget({ target_kind: "panel" }) && !c.checkHasTarget({ target_kind: "" }),
       "only a check with a target is a link");
}

{
    // Mesh cloth: the rate used, a typed rate, Reset, the quantity text.
    const c = make([{ height_mm: 1500, is_auto: false, leaves: [
        panel(600, "CASEMENT"),
    ] }], 600, 1500);
    c.notification = { add: () => {} };
    c.state.data.mesh_types = [{
        id: 9, name: "Zig-zag mesh", mechanism: "zigzag", cloth_cost: 40,
        cloth_name: "Mesh cloth - Zig-zag",
    }];
    c.selectLeaf([[0, 0]]);
    const leaf = c.state.data.rows[0].leaves[0];
    leaf.mesh_type_id = 9;
    ok(c.meshClothListRate === 40 && c.meshClothRateUsed === 40,
       "the cloth rate used defaults to the product cost");
    c.setMeshRate("50");
    ok(leaf.mesh_rate_manual && c.meshClothRateUsed === 50, "a typed cloth rate is manual");
    c.resetMeshRate();
    ok(!leaf.mesh_rate_manual && c.meshClothRateUsed === 40, "Reset returns the product cost");
    ok(c.meshQtyText({ area_sqft: 19.654, unit_cost: 40, line_cost: 786.16 })
       === "19.65 sqft \u00d7 40.00 = 786.16", "the quantity reads in sqft with the unit");
    c.setMeshRate("50");
    c.applyMesh(9);                 // takes the mesh off again
    ok(!leaf.mesh_rate_manual, "a rate typed for one cloth is not the next one's");
}

{
    // Money and quantities: two decimals, thousands separators; lengths keep inches.
    const c = make([{ height_mm: 1500, is_auto: false, leaves: [
        panel(600, "FIXED"),
    ] }], 600, 1500);
    ok(c.costText(1234.5) === "1,234.50", "an amount shows two decimals and a separator");
    ok(c.costText(0) === "0.00" && c.costText(undefined) === "0.00", "zero and nothing show 0.00");
    ok(c.costText(1234567.891) === "1,234,567.89", "millions are grouped");
    ok(c.costText(-5) === "-5.00", "a negative amount keeps its sign");
    ok(c.costText(786.155) === "786.16" || c.costText(786.155) === "786.15",
       "rounded to two decimals only for display");
    c.state.data.pricing = { currency: "Rs." };
    ok(c.formatMoney(151218.5125) === "Rs. 151,218.51", "formatMoney: symbol, grouping, 2 decimals");
    ok(c.formatMoney(40) === "Rs. 40.00", "a whole amount still shows .00");
    ok(c.meshQtyText({ area_sqft: 19.654, unit_cost: 1200, line_cost: 23584.8 })
       === "19.65 sqft \u00d7 1,200.00 = 23,584.80", "sqft and the amounts use the same rule");
    ok(c.rightTabs.find((t) => t.key === "spec").label === "Parts", "the spec tab reads Parts");
}

{
    // Price build-up: the rows come from the server; the client only formats them.
    const c = make([{ height_mm: 1500, is_auto: false, leaves: [
        panel(600, "FIXED"),
    ] }], 600, 1500);
    c.state.data.pricing = { currency: "Rs.", margin_pct: 20, min_margin_pct: 15,
        build_up: [{ key: "profiles", label: "Profiles", amount: 100, kind: "base" }] };
    ok(c.pricingBuildUp.length === 1, "the Pricing tab reads the server's rows");
    ok(c.buildUpRate({ percent: 8, unit: "%" }) === "8.00%", "a percentage row shows 8.00%");
    ok(c.buildUpRate({ percent: 0, unit: "%" }) === "0.00%", "a 0% row still shows 0.00%");
    ok(c.buildUpRate({ percent: null, rate: 450, unit: "per m\u00b2" }).endsWith("per m\u00b2"),
       "a rate row shows its unit");
    ok(c.buildUpRate({ percent: null, rate: 0, unit: "" }) === "", "a plain row shows no rate");
    ok(c.buildUpClass({ kind: "total" }).includes("fw-bold"), "the price row is bold");
}

{
    // The Glass section collapses by its heading, remembers it, and is a
    // section of its own beside Mesh and Hardware (not inside Infill).
    const c = make([{ height_mm: 1500, is_auto: false, leaves: [
        panel(600, "CASEMENT"),
    ] }], 600, 1500);
    const store = {};
    const saved = globalThis.window.localStorage;
    globalThis.window.localStorage = {
        setItem: (k, v) => { store[k] = v; },
        getItem: (k) => (k in store ? store[k] : null),
    };
    c.state.collapsed = {};
    ok(!c.isCollapsed("glass"), "Glass starts open");
    c.toggleSection("glass");
    ok(c.isCollapsed("glass") && c.sectionIcon("glass") === "fa fa-chevron-right",
       "clicking the heading closes it and turns the arrow");
    ok(JSON.parse(store.aw_cfg_collapsed).glass === true, "and the state is kept");
    c.toggleSection("glass");
    ok(!c.isCollapsed("glass") && c.sectionIcon("glass") === "fa fa-chevron-down",
       "clicking again opens it");
    ok(JSON.parse(store.aw_cfg_collapsed).glass === false, "open is kept too");
    c.toggleSection("glass");
    c.toggleSection("infill");
    ok(c.isCollapsed("glass"), "closing Infill does not touch Glass");
    c.toggleSection("infill");
    c.state.collapsed = { glass: true };
    c.selectLeaf([[0, 0]]);
    c.goToCheck({ target_kind: "glass", panel_no: 1 });
    ok(c.state.collapsed.glass === false, "a Checks link to glass opens the section");
    c.toggleSection("glass");
    c.setAllCollapsed(["panel", "infill", "mesh", "glass", "hardware", "grid"], false);
    ok(["panel", "infill", "mesh", "glass", "hardware", "grid"].every((k) => !c.isCollapsed(k)),
       "Expand all opens Glass too");
    globalThis.window.localStorage = saved;

    // the markup: the heading's handler, and not nested inside Infill's content
    const xml = readFileSync(
        "odoo/addons/aw_fenestration_design/static/src/design_configurator/design_configurator.xml",
        "utf8");
    const head = xml.indexOf("toggleSection('glass')");
    const infill = xml.indexOf("<t t-if=\"!isCollapsed('infill')\">");
    ok(head > 0 && infill > 0 && head > infill, "the Glass heading is bound to toggleSection('glass')");
    let depth = 0;
    for (const m of xml.slice(infill, head).matchAll(/<t(?=[\s>])[^>]*?(\/?)>|<\/t>/g)) {
        if (m[0] === "</t>") {
            depth -= 1;
        } else if (m[1] !== "/") {
            depth += 1;
        }
    }
    ok(depth === 1, "and the heading sits outside Infill's content, inside only its own glazed-panel test (depth " + depth + ")");
    ok(xml.includes("isCollapsed('glass')"), "the stack hides when the section is closed");
    ok(xml.includes("toggleSection('grid')") && xml.includes("toggleSection('hardware')")
       && xml.includes("toggleSection('mesh')"),
       "Mesh, Hardware and the Georgian bars have their arrows too");
}

{
    // The Form is the History page: its button, its method, and no text that
    // sends the user to "the form".
    const xml = readFileSync(
        "odoo/addons/aw_fenestration_design/static/src/design_configurator/design_configurator.xml",
        "utf8");
    ok(/t-on-click="openHistory"[^>]*>\s*History\s*</.test(xml), "the top-bar button reads History");
    ok(!/t-on-click="openForm"/.test(xml), "and nothing calls openForm any more");
    ok(typeof DesignConfigurator.prototype.openHistory === "function"
       && typeof DesignConfigurator.prototype.openForm === "undefined", "openHistory replaced openForm");
    ok(!/from the form/i.test(xml), "no text says to generate the cut list from the form");
}

{
    // Parts tab: glass (window default), glass on panels, hardware on panels.
    const c = make([{ height_mm: 1500, is_auto: false, leaves: [
        panel(600, "CASEMENT"), panel(600, "FIXED"), panel(600, "CASEMENT"),
    ] }], 1800, 1500);
    c.notification = { add: () => {} };
    c.state.data.hardware_products = [{ id: 7, name: "Roller", cost: 50 }];
    c.state.data.header.glass_product_id = 301;
    c.state.data.header.glass_product_name = "Clear 6 mm";
    const leaves = c.state.data.rows[0].leaves;
    leaves[2].glass_product_id = 302;
    leaves[2].glass_product_name = "6+12+6 Clear sealed unit";
    leaves[0].hardware = [
        { product_id: 7, name: "Roller", qty: 2, rate_manual: false, manual_rate: 0, list_rate: 50 },
        { product_id: 7, name: "Roller", qty: 1, rate_manual: true, manual_rate: 70, list_rate: 50 }];

    // the window default is a collapsed section like Outer frame
    c.state.collapsed = {};
    ok(c.isCollapsed("prof:glass"), "Glass (window default) starts collapsed");
    const store = {};
    const saved = globalThis.window.localStorage;
    globalThis.window.localStorage = {
        setItem: (k, v) => { store[k] = v; }, getItem: (k) => (k in store ? store[k] : null) };
    c.toggleSection("prof:glass");
    ok(!c.isCollapsed("prof:glass") && JSON.parse(store.aw_cfg_collapsed)["prof:glass"] === false,
       "its heading opens it and the state is kept");
    globalThis.window.localStorage = saved;
    ok(c.headerGlassName === "Clear 6 mm", "the window default names its product");

    // glass on panels: one row per panel that takes glass
    const rows = c.panelGlassRows;
    ok(rows.map((r) => r.no).join() === "1,2,3", "a row per panel");
    ok(rows[0].follows && rows[0].summary === "Clear 6 mm",
       "a panel that follows shows the window's product");
    ok(!rows[2].follows && rows[2].summary === "6+12+6 Clear sealed unit",
       "a panel with its own shows its own");
    leaves[1].glass_choose = true;
    ok(c.panelGlassRows[1].summary === "Choose a glass product",
       "a panel with nothing to glaze with says so");

    // hardware on panels: one row per hardware row, and the badge is the total
    const hw = c.panelHardwareRows;
    ok(hw.length === 2 && hw[0].no === 1 && hw[0].name === "Roller", "a row per hardware row, with its panel");
    ok(hw[0].rate === 50 && hw[0].cost === 100 && !hw[0].manual, "list rate and cost");
    ok(hw[1].rate === 70 && hw[1].cost === 70 && hw[1].manual, "a typed rate is shown as manual");
    c.state.data.spec_parts = { hardware: [{ line_id: 1 }, { line_id: 2 }, { line_id: 3 }] };
    ok(c.partsHardwareCount === 5, "the badge is the series set plus the panel rows");

    // a click selects the panel and opens its section
    c.state.collapsed = {};
    c.state.rightTab = "spec";
    c.goToPanelGlass(3);
    ok(JSON.stringify(c.state.selected) === JSON.stringify([[0, 2]]) && c.state.rightTab === "panel"
       && c.state.collapsed.glass === false, "a glass row selects the panel and opens Glass");
    c.state.rightTab = "spec";
    c.goToPanelHardware(1);
    ok(JSON.stringify(c.state.selected) === JSON.stringify([[0, 0]]) && c.state.rightTab === "panel"
       && c.state.collapsed.hardware === false, "a hardware row selects the panel and opens Hardware");
    // Checks links still go the same way
    c.goToCheck({ target_kind: "hardware", panel_no: 3 });
    ok(JSON.stringify(c.state.selected) === JSON.stringify([[0, 2]]), "Checks links keep working");

    // the markup
    const xml = readFileSync(
        "odoo/addons/aw_fenestration_design/static/src/design_configurator/design_configurator.xml",
        "utf8");
    ok(xml.includes("Glass (window default)") && !xml.includes("Window glass (new panels start from this)"),
       "the window glass section is renamed");
    ok(xml.includes("toggleSection('prof:glass')") && xml.includes("toggleSection('prof:panelglass')"),
       "both glass sections have an arrow");
    ok(xml.includes('data-aw-parts="series-set"') && xml.includes('data-aw-parts="on-panels"'),
       "Hardware has Series set and On panels");
    ok(xml.includes("No hardware yet. Select a panel and use + Hardware in the Panel tab."),
       "the empty text says what to do");
}

// ---------------------------------------------------------------------
console.log("\nUNDO / REDO (the layout since the last save):");
{
    const c = make([{ height_mm: 3200.4, is_auto: false,
                      leaves: [panel(1219.2), panel(1219.2)] }]);
    c.resetHistory();
    ok(!c.state.canUndo && !c.state.canRedo, "nothing to undo at the start");
    c.state.data.header.location = "Hall";
    c.touch();
    ok(c.state.dirty && c.state.canUndo, "an edit is a step");
    c.state.data.header.location = "Hall 2";
    c.touch();
    ok(c.history.undo.length === 1, "a burst of typing is one step");
    c.undo();
    ok(c.state.data.header.location === "", "undo steps back the whole burst");
    ok(!c.state.dirty, "back at the saved layout there are no unsaved changes");
    ok(c.state.canRedo && !c.state.canUndo, "redo is offered");
    c.redo();
    ok(c.state.data.header.location === "Hall 2" && c.state.dirty, "redo steps forward");
    c.history.at = 0;
    c.state.data.rows[0].leaves[0].width_mm = 1000;
    c.touch();
    ok(c.history.undo.length === 2, "a later edit is a step of its own");
    c.undo();
    ok(c.state.data.rows[0].leaves[0].width_mm === 1219.2
       && c.state.data.header.location === "Hall 2" && c.state.dirty,
       "one undo steps back one change, not all of them");
    c.history.at = 0;
    c.state.data.header.location = "Hall 3";
    c.touch();
    ok(!c.state.canRedo, "a new edit drops the redo steps");
    c.state.selected = [[0, 0]];
    c.undo();
    ok(c.state.selected === null, "the selection is cleared by a step (it may no longer exist)");
    c.resetHistory();
    ok(!c.state.canUndo && !c.state.canRedo, "a save or reload starts the history afresh");
}
{
    const c = make([{ height_mm: 3200.4, is_auto: false, leaves: [panel(1219.2)] }]);
    c.resetHistory();
    c.state.data.header.location = "A";
    c.touch();
    let prevented = 0;
    const key = (k, extra = {}) => ({
        key: k, ctrlKey: true, shiftKey: false, altKey: false,
        target: { tagName: "DIV" }, preventDefault() { prevented++; }, ...extra,
    });
    c.keyDown(key("z", { target: { tagName: "INPUT" } }));
    ok(c.state.data.header.location === "A" && !prevented,
       "Ctrl+Z inside a field is the field's own undo");
    c.keyDown(key("z"));
    ok(c.state.data.header.location === "" && prevented === 1, "Ctrl+Z undoes");
    c.keyDown(key("y"));
    ok(c.state.data.header.location === "A", "Ctrl+Y redoes");
    c.keyDown(key("z"));
    c.keyDown(key("z", { shiftKey: true }));
    ok(c.state.data.header.location === "A", "Ctrl+Shift+Z redoes");
    c.keyDown(key("z", { ctrlKey: false }));
    ok(c.state.data.header.location === "A", "Z alone does nothing");
}

console.log("\nDISCARD (the X):");
{
    const c = make([{ height_mm: 3200.4, is_auto: false, leaves: [panel(1219.2)] }]);
    const shown = [];
    let back = 0;
    let loaded = 0;
    c.dialog = { add: (_cls, props) => shown.push(props) };
    c.env = { config: { historyBack: () => { back++; } } };
    c.load = async () => { loaded++; };
    c.state.dirty = false;
    c.discard();
    ok(back === 1 && shown.length === 0, "with nothing to lose it just leaves");
    c.state.dirty = true;
    c.discard();
    ok(shown.length === 1 && back === 1, "with changes it asks first");
    ok(loaded === 0, "and has not thrown anything away yet");
    shown[0].confirm();
    ok(loaded === 1, "Discard reloads the saved window");
    ok(typeof shown[0].cancel === "function", "Keep editing leaves everything as it was");
}

console.log("\nDIVIDERS ARE NAMED BY PLACE:");
{
    const three = make([{ height_mm: 3200.4, is_auto: false,
                          leaves: [panel(800), panel(800), panel(800)] }]);
    const labelsV = three.scene.dividers.filter((d) => d.kind === "v").map((d) => d.label);
    ok(labelsV.join("|") === "Divider after P1|Divider after P2",
       "a 3-across window has Divider after P1 and Divider after P2");
    ok(three.dividersOfKind("h").length === 0, "and no horizontal divider");
    ok(three.partPlaces({ scope: "junction_mullion" }) === "Divider after P1, Divider after P2",
       "the Parts tab lists where the vertical dividers are");
    const stacked = make([
        { height_mm: 1600, is_auto: false, leaves: [panel(1200), panel(1200)] },
        { height_mm: 1600, is_auto: false, leaves: [panel(2400)] },
    ]);
    const h = stacked.scene.dividers.filter((d) => d.kind === "h").map((d) => d.label);
    ok(h.join("|") === "Divider below P1-P2", "a horizontal divider: below the panels above it");
    three.state.selectedDivider = three.scene.dividers[1].key;
    ok(three.selectedDividerLabel === "Divider after P2", "the selected divider shows its name");
}

console.log("\nPARTS TAB: parts with no piece are not listed:");
{
    const c = make([{ height_mm: 3200.4, is_auto: false,
                      leaves: [panel(800), panel(800), panel(800)] }]);
    const row = (extra) => ({ position_id: 1, scope: "", changed: false, added: false,
                              needs_thickness: false, pieces: 0, ...extra });
    c.state.data.spec_parts = { has_pieces: true, profiles: [], addable: [] };
    ok(!c.partRowVisible(row({})), "a part that made no piece is hidden");
    ok(c.partRowVisible(row({ pieces: 2 })), "a part that made pieces is shown");
    ok(c.partRowVisible(row({ changed: true })), "a part changed for this window is shown");
    ok(c.partRowVisible(row({ needs_thickness: true })), "a part waiting for a thickness is shown");
    ok(c.partRowVisible(row({ scope: "junction_mullion" })),
       "vertical dividers drawn since the last save are shown");
    ok(!c.partRowVisible(row({ scope: "transom" })),
       "Divider - Horizontal is hidden on a 3-across window: it has no horizontal divider");
    c.state.data.spec_parts.has_pieces = false;
    ok(c.partRowVisible(row({})), "before the window has any piece every part is shown");
}

console.log("\nPARTS TAB: thickness is chosen on the group heading:");
{
    const c = make([{ height_mm: 3200.4, is_auto: false,
                      leaves: [panel(1200), panel(1200)] }]);
    const A = { position_id: 10, scope_key: "outer", part_key: "frame", code: "RE-8",
                scope: "frame", pieces: 1, changed: false, added: false, needs_thickness: false,
                thickness_id: 2, thickness_name: "1.6MM",
                thickness_options: [{ id: 1, name: "1.2MM" }, { id: 2, name: "1.6MM" }] };
    const B = { ...A, position_id: 11, code: "RE-9", thickness_id: 1, thickness_name: "1.2MM",
                thickness_options: [{ id: 1, name: "1.2MM" }] };
    c.state.data.spec_parts = { has_pieces: true, profiles: [A, B], addable: [] };
    const group = { gkey: "outer:frame", rows: [A, B] };
    const info = c.groupThickness(group);
    ok(info.options.map((o) => o.name).join(",") === "1.2MM,1.6MM", "the heading offers every thickness its lines offer");
    ok(info.mixed && info.current === 0, "different thicknesses show as mixed");
    const calls = [];
    c.partCall = async (method, args) => { calls.push([method, args]); };
    c.applyGroupThickness(group, 2);
    ok(calls.length === 1 && calls[0][0] === "apply_thickness_rows"
       && calls[0][1][0] === 2 && calls[0][1][1].join() === "10",
       "applying a thickness sends only the lines whose profile is sold in it");
    ok(c.rowThicknessWarning(group, B).includes("RE-9") && c.rowThicknessWarning(group, B).includes("1.6MM"),
       "a line whose profile lacks that thickness gets a warning");
    ok(c.rowThicknessWarning(group, A) === "", "a line that has it has none");
    const same = c.groupThickness({ gkey: "x", rows: [A, { ...A, position_id: 12 }] });
    ok(!same.mixed && same.current === 2, "the same thickness on every line is not mixed");
}

console.log("\nPART C: selection, frame hardware, the drawing's unit:");
{
    const c = make([{ height_mm: 3200.4, is_auto: false,
                      leaves: [panel(1219.2), panel(1219.2)] }]);
    ok(c.selectionMode === "none", "nothing is selected at the start");
    c.selectFrame();
    ok(c.selectionMode === "frame" && c.state.selected === null, "a click on the frame selects the frame");
    c.selectLeaf([[0, 0]]);
    ok(c.selectionMode === "panel" && !c.state.selectedFrame, "selecting a panel lets the frame go");
    c.selectFrame();
    ok(c.state.selected === null, "selecting the frame lets the panel go");
    c.keyDown({ key: "Escape", target: { tagName: "DIV" } });
    ok(c.selectionMode === "none", "Esc clears the selection");
    c.selectFrame();
    c.keyDown({ key: "Escape", target: { tagName: "INPUT" } });
    ok(c.selectionMode === "frame", "Esc inside a field is the field's own");
    c.onCanvasClick({ clientX: 5, clientY: 5, target: { closest: () => null } });
    ok(c.selectionMode === "none", "a click outside the window clears the selection");
    c.selectFrame();
    c.onCanvasClick({ clientX: 5, clientY: 5, target: { closest: () => ({}) } });
    ok(c.selectionMode === "frame", "a click on a control does not");
    c._canvasDown = { x: 0, y: 0 };
    c.onCanvasClick({ clientX: 50, clientY: 0, target: { closest: () => null } });
    ok(c.selectionMode === "frame", "a click that ended a drag does not");

    // the frame's hardware
    c.state.data.header.hardware = [];
    c.state.data.hardware_products = [{ id: 7, name: "Corner key", cost: 12 }];
    c.selectFrame();
    c.addHardware();
    ok(c.state.data.header.hardware.length === 1 && c.panelHardware.length === 1,
       "a row added with the frame selected is the frame's");
    c.setHardwareProduct(0, "7");
    c.setHardwareQty(0, "4");
    ok(c.panelHardwareCost === 48, "the frame's rows are costed like a panel's");
    ok(c.panelHardwareRows[0].no === 0 && c.panelHardwareRows[0].cost === 48,
       "the Parts list shows the frame's rows");
    ok(c.hardwareOwnerLabel === "the frame", "the section names its owner");
    c.selectLeaf([[0, 0]]);
    ok(c.panelHardware.length === 0, "a panel does not see the frame's rows");
    c.selectFrame();
    c.copyHardwareFromPanel({ target: { value: "1" } });
    ok(c.state.data.header.hardware.length === 0,
       "Copy from panel replaces the frame's rows with that panel's");
    ok("hardware" in JSON.parse(c.layoutSnapshot()).header,
       "the frame's rows travel in the saved header");

    // hardware sets: saved lists, COPIED onto the rows
    {
        const dialogs = [];
        c.dialog = { add: (cls, props) => dialogs.push({ cls, props }) };
        c.notification = { add: () => {} };
        const slider = c.state.data.leaf_types[0].id;
        const other = c.state.data.leaf_types.find((t) => t.id !== slider)?.id || 999;
        c.state.data.can_edit_hardware_kits = true;
        c.state.data.hardware_kits = [
            { id: 1, name: "Zeta any", leaf_type_id: false, leaf_type_name: "",
              rows: [{ product_id: 7, name: "Corner key", qty: 2, rate_manual: false,
                       manual_rate: 0, list_rate: 12 }] },
            { id: 2, name: "Beta other", leaf_type_id: other, leaf_type_name: "Other",
              rows: [{ product_id: 7, name: "Corner key", qty: 1, rate_manual: false,
                       manual_rate: 0, list_rate: 12 }] },
            { id: 3, name: "Alpha own", leaf_type_id: slider, leaf_type_name: "Own",
              rows: [{ product_id: 7, name: "Corner key", qty: 3, rate_manual: true,
                       manual_rate: 9, list_rate: 12 },
                     { product_id: 7, name: "Corner key", qty: 4, rate_manual: false,
                       manual_rate: 0, list_rate: 12 }] },
        ];
        // a panel: its own type first, then the rest by name
        c.selectLeaf([[0, 0]]);
        c.selectedPanel.leaf_type_id = slider;
        ok(c.hardwareKits.map((k) => k.id).join() === "3,2,1",
           "sets of the panel's type come first, then by name");
        // the frame: sets with no panel type first
        c.selectFrame();
        ok(c.hardwareKits[0].id === 1, "for the frame the sets with no type come first");

        // picking onto an empty panel adds the rows, a rate only if saved with one
        c.selectLeaf([[0, 0]]);
        c.selectedPanel.hardware = [];
        c.pickHardwareKit({ target: { value: "3" } });
        const rows = c.selectedPanel.hardware;
        ok(rows.length === 2 && rows[0].qty === 3 && rows[0].rate_manual
           && rows[0].manual_rate === 9 && !rows[1].rate_manual,
           "an empty panel takes the rows; a rate is kept only where it was saved");
        ok(dialogs.length === 0, "nothing is asked of an empty panel");
        ok(rows[0] !== c.state.data.hardware_kits[2].rows[0],
           "the rows are copies, not the set's own");
        rows[0].qty = 99;
        ok(c.state.data.hardware_kits[2].rows[0].qty === 3,
           "editing the panel does not touch the set");

        // a panel with rows is asked: Add (default) or Replace, then a second question
        c.pickHardwareKit({ target: { value: "1" } });
        ok(dialogs.length === 1 && dialogs[0].props.confirmLabel === "Add"
           && dialogs[0].props.cancelLabel === "Replace",
           "a panel with rows is asked add or replace, Add being the default");
        ok(dialogs[0].props.dismiss() === undefined && c.selectedPanel.hardware.length === 2,
           "closing the question changes nothing");
        dialogs[0].props.cancel();
        ok(dialogs.length === 2 && dialogs[1].props.body.includes("2 row(s)")
           && dialogs[1].props.confirmLabel.includes("2"),
           "Replace asks again and names the number of rows to be removed");
        ok(c.selectedPanel.hardware.length === 2, "nothing is removed before the second answer");
        dialogs[1].props.confirm();
        ok(c.selectedPanel.hardware.length === 1 && c.selectedPanel.hardware[0].qty === 2,
           "the second answer replaces the rows with the set's");
        c.selectedPanel.hardware = [{ product_id: 7, name: "Corner key", qty: 1,
                                      rate_manual: false, manual_rate: 0, list_rate: 12 }];
        c.pickHardwareKit({ target: { value: "1" } });
        dialogs[dialogs.length - 1].props.confirm();
        ok(c.selectedPanel.hardware.length === 2, "Add keeps the rows and adds the set's");

        // Save as set: only managers, only with a product row
        ok(c.canSaveHardwareKit, "a manager can save the rows as a set");
        c.state.data.can_edit_hardware_kits = false;
        ok(!c.canSaveHardwareKit, "nobody else is offered Save as set");
        c.state.data.can_edit_hardware_kits = true;
        c.selectedPanel.hardware = [];
        ok(!c.canSaveHardwareKit, "and not with no hardware");
        c.selectedPanel.hardware = [{ product_id: 7, name: "Corner key", qty: 1,
                                      rate_manual: true, manual_rate: 5, list_rate: 12 }];
        c.saveHardwareKit();
        const dlg = dialogs[dialogs.length - 1];
        ok(dlg.props.rows.length === 1 && dlg.props.leafTypeId === slider,
           "the dialog gets the rows and defaults to the panel's type");
        c.orm = { call: async (_m, _f, args) => ({
            id: 9, name: args[0], leaf_type_id: args[1], leaf_type_name: "",
            rows: args[2] }) };
        await dlg.props.onSave({ name: "New set", leafTypeId: slider, withRates: true });
        ok(c.state.data.hardware_kits.some((k) => k.id === 9),
           "the saved set is in the list at once");
    }

    // the drawing follows In / mm / Both
    c.setUnitMode("mm");
    ok(c.drawingLength(1219.2) === "1219.2", "mm mode draws millimetres");
    c.setUnitMode("in");
    ok(!c.drawingLength(1219.2).includes("|") && c.drawingLength(1219.2) !== "1219.2",
       "in mode draws inches");
    c.setUnitMode("both");
    ok(c.drawingLength(1219.2).includes("|") && c.drawingLength(1219.2).includes("1219.2"),
       "Both draws both");
    ok(c.scene.dims.some((d) => d.text.includes("1219.2")),
       "the dimension lines on the drawing follow the switch");
    ok(c.drawingUnitLabel.length > 0, "the caption names the unit");
    const r = c.renderedSize;
    ok(Number.isInteger(r.w) && Number.isInteger(r.h), "the drawing is sized in whole pixels");
}

console.log("\nMESH never takes the finish colour:");
{
    const c = make([{ height_mm: 1500, is_auto: false, leaves: [panel(600, "FIXED")] }]);
    c.state.data.header.finish_id = 5;
    c.state.data.finish_options = [{ id: 5, name: "Black", color: "#1e1e1e" }];
    ok(c.meshFrameFill === "#e6eaec" && c.meshOutline !== c.meshFrameFill,
       "the mesh is a light neutral with an outline");
    ok(c.meshFrameFill !== c.finishFill, "and not the finish colour");
    const xml = readFileSync(
        "odoo/addons/aw_fenestration_design/static/src/design_configurator/design_configurator.xml",
        "utf8");
    const strips = xml.slice(xml.indexOf('t-foreach="leaf.attach.meshStrips"'));
    ok(strips.slice(0, 700).includes("meshFrameFill") && !strips.slice(0, 700).includes("finishFill"),
       "the attached mesh frame uses the neutral colour");
    ok(xml.includes("leaf.isMesh ? meshFrameFill : finishFill"),
       "a mesh panel's frame uses it too; other panels keep the finish");
}

console.log("\nPHONE LAYOUT SHELL (under 768 px):");
{
    const xml = readFileSync(
        "odoo/addons/aw_fenestration_design/static/src/design_configurator/design_configurator.xml",
        "utf8");
    const scss = readFileSync(
        "odoo/addons/aw_fenestration_design/static/src/design_configurator/design_configurator.scss",
        "utf8");

    // -- the switch itself: one media query, read once and followed ----
    const c = make([{ height_mm: 1500, is_auto: false, leaves: [panel(600, "FIXED")] }]);
    const realWindow = globalThis.window;
    globalThis.window = { ...realWindow };
    ok(c.readPhone() === false, "no matchMedia (a test, an old browser) is not a phone");
    globalThis.window.matchMedia = (q) => ({ matches: q.includes("767.98") });
    ok(c.readPhone() === true, "a 390 px screen matches the phone query");
    globalThis.window.matchMedia = () => ({ matches: false });
    ok(c.readPhone() === false, "a desktop screen does not");
    globalThis.window.matchMedia = () => { throw new Error("blocked"); };
    ok(c.readPhone() === false, "a browser that refuses the query is not a phone");
    globalThis.window = realWindow;

    // -- desktop: exactly as it was ----------------------------------
    c.state.paneLeft = 220;
    c.state.paneRight = 260;
    c.state.phone = false;
    c.state.phoneLibrary = false;
    c.state.libraryOpen = true;
    ok(c.libraryShown === true, "desktop: the library column is shown when open");
    ok(/width: \d+px/.test(c.leftPaneStyle) && /width: \d+px/.test(c.rightPaneStyle),
       "desktop: the panes keep their pixel widths");
    c.state.libraryOpen = false;
    ok(c.libraryShown === false && c.leftPaneStyle.includes("2.25rem"),
       "desktop: a closed library is the narrow bar");
    c.toggleLibrary();
    ok(c.state.libraryOpen === true && c.state.phoneLibrary === false,
       "desktop: the toggle works the column, not the drawer");

    // -- phone ---------------------------------------------------------
    c.state.phone = true;
    c.state.libraryOpen = true;           // the desktop's remembered choice
    c.state.phoneLibrary = false;
    ok(c.libraryShown === false, "phone: the drawer is closed whatever the desktop remembered");
    ok(!/width/.test(c.leftPaneStyle) && !/width/.test(c.rightPaneStyle),
       "phone: no inline pane widths (full width is the stylesheet's)");
    c.toggleLibrary();
    ok(c.state.phoneLibrary === true && c.libraryShown === true,
       "phone: Layouts opens the drawer");
    ok(c.state.libraryOpen === true, "phone: and leaves the desktop's choice alone");
    c.closePhoneLibrary();
    ok(c.libraryShown === false, "phone: the backdrop and the X close it");

    c.state.phoneLibrary = true;
    c.keyDown({ key: "Escape", target: { tagName: "DIV" } });
    ok(c.state.phoneLibrary === false, "phone: Escape closes the drawer first");

    c.state.phoneLibrary = true;
    c.applyShape = () => {};
    c.applyPreset = () => {};
    c.applyAttachment = () => {};
    c.applyLibraryItem({ kind: "preset" }, { kind: "design" });
    ok(c.state.phoneLibrary === false, "phone: choosing a layout closes the drawer");
    c.state.phoneLibrary = true;
    c.applyLibraryItem({ kind: "fly" }, {});
    ok(c.state.phoneLibrary === false, "phone: so does choosing an add-on");
    c.state.phone = false;
    c.state.phoneLibrary = true;
    c.applyLibraryItem({ kind: "preset" }, { kind: "shape" });
    ok(c.state.phoneLibrary === true, "desktop: choosing does not touch the drawer flag");

    // -- Details ---------------------------------------------------------
    c.state.phoneDetails = false;
    c.togglePhoneDetails();
    ok(c.state.phoneDetails === true, "Details opens the rest of the header");
    c.togglePhoneDetails();
    ok(c.state.phoneDetails === false, "and closes it again");

    // -- turning the device ----------------------------------------------
    c.state.phone = true;
    c.state.phoneLibrary = true;
    c.state.phoneDetails = true;
    c.onPhoneChange({ matches: false });
    ok(c.state.phone === false && c.state.phoneLibrary === false
       && c.state.phoneDetails === false,
       "leaving the phone width resets the drawer and the details");
    c.onPhoneChange({ matches: true });
    ok(c.state.phone === true, "entering it switches the layout on");

    // -- the template and the stylesheet agree ----------------------------
    ok(xml.includes("state.phone ? 'o_aw_phone' : ''"), "the root carries o_aw_phone on a phone");
    ok(/<div t-if="!state\.phone" class="ms-auto d-flex gap-2">/.test(xml),
       "the desktop button bar is not rendered on a phone");
    ok(/<div t-if="state\.phone"\s+class="o_aw_phone_bar/.test(xml),
       "the phone bar is rendered only on a phone");
    // every action of the desktop bar is reachable from the phone's menu
    const desktop = xml.slice(xml.indexOf('<div t-if="!state.phone" class="ms-auto d-flex gap-2">'));
    const desktopBar = desktop.slice(0, desktop.indexOf("</div>"));
    const phoneBar = xml.slice(xml.indexOf("o_aw_phone_bar"),
                               xml.indexOf("<!-- Family first"));
    for (const handler of [...desktopBar.matchAll(/t-on-click="(\w+)"/g)].map((m) => m[1])) {
        ok(phoneBar.includes(`t-on-click="${handler}"`),
           `the phone bar or its menu reaches ${handler}`);
    }
    ok(/class="o_aw_hdr_core"/.test(xml) && (xml.match(/o_aw_hdr_core/g) || []).length === 4,
       "the four size boxes stay in the header on a phone");
    ok(xml.includes('t-if="libraryShown and !state.phone"'), "no pane resizer on a phone");
    ok(xml.includes("o_aw_drawer_backdrop"), "a backdrop sits behind the drawer");
    for (const rule of [".o_aw_phone {", ".o_aw_cfg_main {", "flex-direction: column",
                        ".o_aw_drawer.o_aw_drawer_open", ".o_aw_hdr_collapsed",
                        ".o_aw_cfg_center {", ".o_aw_cfg_side {"]) {
        ok(scss.includes(rule), `the stylesheet has ${rule}`);
    }
    // the phone rules are all inside .o_aw_phone: nothing leaks to the desktop
    const phoneStart = scss.indexOf(".o_aw_phone {");
    ok(phoneStart > 0 && !/o_aw_drawer|o_aw_hdr_collapsed|o_aw_cfg_center/.test(scss.slice(0, phoneStart)),
       "the drawer, the collapsed header and the stacked centre exist only under .o_aw_phone");
    // the desktop's full-width tabs and pane rules were not touched
    ok(scss.includes(".o_aw_cfg_tabs {") && scss.includes(".o_aw_cfg_resizer {"),
       "the desktop rules are still there");
}

console.log("\nTOUCH (mobile b): pinch, tap instead of hover, 44 px:");
{
    const xml = readFileSync(
        "odoo/addons/aw_fenestration_design/static/src/design_configurator/design_configurator.xml",
        "utf8");
    const scss = readFileSync(
        "odoo/addons/aw_fenestration_design/static/src/design_configurator/design_configurator.scss",
        "utf8");
    const D = DesignConfigurator;

    // -- the pinch arithmetic ------------------------------------------
    near(D.pinchZoom(1, 100, 200), 2, "fingers twice as far apart: twice the zoom");
    near(D.pinchZoom(2, 100, 50), 1, "half as far apart: half the zoom");
    near(D.pinchZoom(1, 100, 100000), 4, "capped at the largest zoom");
    near(D.pinchZoom(1, 100, 1), 0.25, "and at the smallest");
    near(D.pinchZoom(1.5, 0, 80), 1.5, "no start distance: unchanged");
    near(D.pinchZoom(1.5, 80, 0), 1.5, "no distance: unchanged");
    near(D.pinchScroll(0.5, 2000, 200), 800, "the point under the fingers stays under them");
    near(D.pinchScroll(0, 2000, 200), 0, "and the scroll never goes negative");

    // -- the gesture ----------------------------------------------------
    const c = make([{ height_mm: 1500, is_auto: false, leaves: [panel(600, "FIXED"), panel(600, "FIXED")] }]);
    c.touches = new Map();
    c.pinch = null;
    c._onTouchMove = (ev) => c.onTouchMove(ev);
    c._onTouchEnd = (ev) => c.onTouchEnd(ev);
    const el = {
        scrollLeft: 100, scrollTop: 50, scrollWidth: 1800, scrollHeight: 1200,
        style: {}, getBoundingClientRect: () => ({ left: 10, top: 20 }),
    };
    c.canvasRef = { el };
    const down = (id, x, y, type = "touch") =>
        c.trackTouch({ pointerType: type, pointerId: id, clientX: x, clientY: y });

    down(1, 100, 100, "mouse");
    ok(c.touches.size === 0, "a mouse is not a finger");
    down(1, 100, 100);
    ok(c.touches.size === 1 && !c.pinch, "one finger is tracked, and is not a pinch");

    c.dragging = { kind: "v" };
    c.panning = { x: 0, y: 0, left: 0, top: 0 };
    c.state.zoom = 1;
    down(2, 300, 100);
    ok(c.pinch && c.touches.size === 2, "the second finger starts the pinch");
    ok(c.dragging === null && c.panning === null,
       "a drag or a pan in progress is dropped for the gesture");
    near(c.pinch.dist, 200, "the start distance is measured");
    near(c.pinch.fx, (100 + 200 - 10) / 1800, "the content under the fingers is remembered");

    c.onTouchMove({ pointerId: 2, clientX: 500, clientY: 100 });   // 400 apart
    near(c.state.zoom, 2, "fingers apart: zoom doubles");
    near(el.scrollLeft, Math.max(0, c.pinch.fx * 1800 - (300 - 10)),
         "and the scroll puts the same content under the fingers' midpoint");
    c.onTouchMove({ pointerId: 2, clientX: 140, clientY: 100 });   // 40 apart
    near(c.state.zoom, 0.25, "fingers together: zoom out, to the limit");

    // while pinching, nothing else reads the pointer
    const before = el.scrollLeft;
    c.onCanvasPointerDown({ clientX: 5, clientY: 5 });
    c.onPointerMove({ clientX: 900, clientY: 900 });
    ok(c.panning === null && el.scrollLeft === before,
       "a pinch is not also a pan of one finger");

    let cleared = 0;
    c.clearSelection = () => { cleared++; };
    c.onTouchEnd({ pointerId: 2 });
    ok(c.pinch === null && c.touches.size === 1, "lifting one finger ends the pinch");
    c._canvasDown = null;
    c.onCanvasClick({ clientX: 100, clientY: 100, target: null });
    ok(cleared === 0, "the click after a pinch is not a tap on the background");
    c._pinchEndedAt = Date.now() - 1000;
    c.onCanvasClick({ clientX: 100, clientY: 100, target: null });
    ok(cleared === 1, "a tap a moment later is");
    c.onTouchEnd({ pointerId: 1 });
    ok(c.touches.size === 0, "all fingers up: nothing is tracked");

    // -- the divider is wide enough for a finger ---------------------------
    c.state.phone = false;
    const mouseHit = c.adornments.dividers[0].hitW;
    c.state.phone = true;
    const fingerHit = c.adornments.dividers[0].hitW;
    near(fingerHit / mouseHit, 44 / 14, "a divider's grab width is 44 px on a phone, 14 for a mouse", 0.01);

    // -- tap instead of hover for the profile picture ------------------------
    const realWindow = globalThis.window;
    globalThis.window = { ...realWindow, innerWidth: 390, innerHeight: 800 };
    const t = make([]);
    t.rightPaneRef = { el: { getBoundingClientRect: () => ({ left: 0, top: 120 }) } };
    t.profileImage = () => "/img";
    t.state.zoomPic = null;
    const row = { position_id: 7 };
    t.state.phone = false;
    t.hoverProfileZoom(row);
    ok(t.state.zoomPic && t.state.zoomPic.url === "/img", "a mouse resting on a thumbnail shows the picture");
    t.hideProfileZoom();
    t._touchAt = Date.now();
    t.hoverProfileZoom(row);
    ok(!t.state.zoomPic, "the emulated hover right after a touch does not");
    t._touchAt = 0;
    t.tapProfileZoom(row, { pointerType: "mouse" });
    ok(!t.state.zoomPic, "a mouse click is not a tap");
    t.state.phone = true;
    t.tapProfileZoom(row, { pointerType: "touch" });
    ok(t.state.zoomPic && t.state.zoomPic.rowId === 7, "a tap shows the picture");
    near(t.state.zoomPic.left, (390 - 280) / 2, "centred across a phone screen", 40);
    t.hoverProfileZoom(row);
    ok(t.state.zoomPic !== null, "(the emulated hover does not undo the tap)");
    t.tapProfileZoom(row, { pointerType: "touch" });
    ok(t.state.zoomPic === null, "a second tap puts it away");
    t.tapProfileZoom(row, { pointerType: "touch" });
    t.tapProfileZoom({ position_id: 8 }, { pointerType: "touch" });
    ok(t.state.zoomPic && t.state.zoomPic.rowId === 8, "a tap on another thumbnail shows that one");
    globalThis.window = realWindow;

    // -- the template and the stylesheet --------------------------------------
    ok(xml.includes('t-on-pointerdown.capture="trackTouch"'),
       "the canvas counts fingers before a divider can swallow the event");
    ok(xml.includes("hoverProfileZoom(row)") && xml.includes("tapProfileZoom(row, ev)"),
       "the thumbnail works by hover with a mouse and by tap with a finger");
    ok(!/t-on-mouseenter="\(\) => this\.showProfileZoom/.test(xml),
       "no thumbnail action is hover only");
    ok(/class="o_aw_spec_zoom"[\s\S]{0,80}t-on-click="hideProfileZoom"/.test(xml),
       "the enlarged picture closes on a tap");
    ok(/\.o_aw_phone \.o_aw_cfg_canvas \{\s*touch-action: none;/.test(scss)
       && /@media \(pointer: coarse\)[\s\S]{0,80}touch-action: none/.test(scss),
       "touch-action: none on the canvas, on a phone and on any touch screen");
    ok(/\.nav-link,\s*\.dropdown-item \{\s*min-height: 44px;/.test(scss)
       && /\.btn \{\s*min-width: 44px;/.test(scss),
       "44 px targets for buttons, fields, tabs and menu items on a phone");
    const phoneAt = scss.indexOf(".o_aw_phone {");
    const touchAt = scss.indexOf("Touch (mobile PR b)");
    const touchPart = scss.slice(touchAt);
    ok(touchPart.indexOf("min-height: 44px") > touchPart.indexOf(".o_aw_phone {"),
       "the 44 px rules are inside the phone layout, not outside it");
    const hovers = scss.match(/&:hover/g) || [];
    const guarded = scss.match(/@media \(hover: hover\) \{\s*&:hover/g) || [];
    ok(hovers.length > 0 && hovers.length === guarded.length,
       `every :hover rule is guarded by (hover: hover) (${guarded.length} of ${hovers.length})`);
    ok(!/ontouch|touchstart|touchmove/.test(xml),
       "pointer events only, no second event family to keep in step");
    ok(phoneAt > 0, "(the phone shell is still there)");
}

console.log("\nPIECE ADJUSTMENT (+/-) in the Pieces row:");
{
    const xml = readFileSync(
        "odoo/addons/aw_fenestration_design/static/src/design_configurator/design_configurator.xml",
        "utf8");
    const c = make([{ height_mm: 1500, is_auto: false, leaves: [panel(600, "FIXED")] }]);
    const calls = [];
    const notes = [];
    c.designId = 5;
    c.orm = { call: async (model, method, args) => { calls.push([method, args]); return c.state.data; } };
    c.notification = { add: (m) => notes.push(m) };
    c.surfaceCheckErrors = () => {};
    c.save = async () => { calls.push(["save"]); c.state.dirty = false; };

    // -- what the box shows ------------------------------------------------
    c.state.unitMode = "in";
    ok(c.adjustBoxValue({ adjust_mm: null }) === "", "no adjustment of its own: the box is empty");
    ok(c.adjustBoxValue({}) === "", "(and so is a piece the server sent none for)");
    ok(c.adjustBoxValue({ adjust_mm: 0 }) === "0", "a typed 0 shows 0: it is the piece's own, final adjustment");
    ok(c.adjustBoxValue({ adjust_mm: 25.4 }) === "+1", "+1 inch shows +1");
    ok(c.adjustBoxValue({ adjust_mm: -6.35 }) === "-0-2", "two soot short shows -0-2");
    ok(c.adjustBoxValue({ adjust_mm: 3.175 }) === "+0-1", "one soot long shows +0-1");
    c.state.unitMode = "mm";
    ok(c.adjustBoxValue({ adjust_mm: -6.35 }) === "-6.35", "mm mode shows signed mm");
    ok(c.adjustBoxValue({ adjust_mm: 3 }) === "+3", "and +3 for 3 mm");
    c.state.unitMode = "both";
    ok(c.adjustBoxValue({ adjust_mm: 25.4 }) === "+1", "Both shows inches in the box");

    // -- what is typed, in the box's unit -----------------------------------
    c.state.unitMode = "in";
    near(c.parseAdjust("+1"), 25.4, "+1 is one inch");
    near(c.parseAdjust("-0-2"), -6.35, "-0-2 is two soot short");
    near(c.parseAdjust("-1/2"), -12.7, "-1/2 is half an inch short");
    near(c.parseAdjust("+0-1"), 3.18, "+0-1 is one soot long", 0.01);
    ok(c.parseAdjust("abc") === null, "words are not an adjustment");
    c.state.unitMode = "mm";
    near(c.parseAdjust("+3"), 3, "in mm, +3 is 3 mm");
    near(c.parseAdjust("-2.5"), -2.5, "and -2.5 is 2.5 mm short");
    ok(c.parseAdjust("3mm") === null && c.parseAdjust("x") === null,
       "mm mode takes a plain number only");
    c.state.unitMode = "in";

    // -- committing -------------------------------------------------------
    const piece = { piece_key: "7|1|1|2", adjust_mm: null };
    calls.length = 0;
    await c.commitAdjust(piece, "-0-2");
    ok(calls.length === 1 && calls[0][0] === "set_piece_adjustment"
       && calls[0][1][0][0] === 5 && calls[0][1][1] === "7|1|1|2"
       && Math.abs(calls[0][1][2] + 6.35) < 0.001,
       "a typed value is sent as this piece's own adjustment, in mm");
    calls.length = 0;
    await c.commitAdjust(piece, "   ");
    ok(calls.length === 0, "blank on a piece that has none changes nothing");
    calls.length = 0;
    await c.commitAdjust({ piece_key: "7|1|1|2", adjust_mm: -6.35 }, "");
    ok(calls.length === 1 && calls[0][0] === "reset_piece_adjustment",
       "blank on a piece that has one resets it to the series default");
    calls.length = 0;
    await c.commitAdjust(piece, "banana");
    ok(calls.length === 0 && notes.length === 1,
       "something unreadable is refused with a message, never stored as 0");
    calls.length = 0;
    await c.commitAdjust(piece, "0");
    ok(calls.length === 1 && calls[0][1][2] === 0,
       "a typed 0 is stored: it overrides the series default");
    calls.length = 0;
    await c.resetAdjust(piece);
    ok(calls.length === 1 && calls[0][0] === "reset_piece_adjustment", "Reset deletes the row");
    c.state.dirty = true;
    calls.length = 0;
    await c.commitAdjust(piece, "+1");
    ok(calls[0][0] === "save" && calls[1][0] === "set_piece_adjustment",
       "unsaved layout changes are saved first: the server works on what is stored");

    // -- the row ----------------------------------------------------------
    ok(/piece\.adjustable/.test(xml) && xml.includes('onCommit="(text) => this.commitAdjust(piece, text)"'),
       "the Pieces row has an adjustment box for an adjustable piece");
    ok(xml.includes("rule_length_mm") && xml.includes("Final"),
       "and shows the rule length and the final length");
    ok(/piece\.adjust_mm !== null and piece\.adjust_mm !== undefined[\s\S]{0,600}resetAdjust\(piece\)/.test(xml),
       "Reset is offered only to a piece that has its own adjustment");
}

console.log(fail ? `\n${fail} FAILURES` : "\nall passed");
process.exit(fail ? 1 : 0);
