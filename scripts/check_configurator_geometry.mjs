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
const useRef = () => ({ el: null });
const onWillStart = () => {};
const onMounted = () => {};
const onWillUnmount = () => {};
const useService = () => ({});
const registry = { category: () => ({ add: () => {} }) };
const standardActionServiceProps = {};
const _t = (s) => s;
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
        libraryOpen: true, selected: null, selectedDivider: null,
        toolbar: { show: false, left: 0, top: 0 },
        data: {
            id: 1, length_uom: "ftin", size_display: "",
            header: { name: "D1", location: "", qty: 1, width_mm: W, height_mm: H,
                      window_series_id: 1, window_series_name: "Casement Single Glaze" },
            rows, leaf_types: LEAF_TYPES, presets: [],
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
    // move by +200mm worth of user units
    const delta = 200 * d.unitsPerMM;
    c.onPointerMove({ clientX: 0, clientY: delta });
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

    // These mocks are in ft+in, so sizes are typed that way.
    const c2 = mk();
    c2.notification = { add: () => {} };
    c2.selectLeaf([[0, 0]]);
    const target = 2 * 304.8 + 6 * 25.4; // 2 ft 6 in
    c2.setPanelWidth("2 6");
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
    c4.setPanelWidth("0 1");           // 1 inch, below the 4in minimum
    near(c4.state.data.rows[0].leaves[0].width_mm, 600, "below minimum: refused");
    ok(warned === 1, "and the user was told");

    c4.setPanelWidth("3 10");          // would starve the neighbour
    near(c4.state.data.rows[0].leaves[0].width_mm, 600,
         "no room for the neighbour: refused");
    ok(warned === 2, "and told again");

    // Sole panel in its row can't be resized this way.
    const c5 = make([{ height_mm: 1500, is_auto: false,
                       leaves: [panel(1200, "FIXED")] }], 1200, 1500);
    let told = 0;
    c5.notification = { add: () => { told += 1; } };
    c5.selectLeaf([[0, 0]]);
    c5.setPanelWidth("2 0");
    near(c5.state.data.rows[0].leaves[0].width_mm, 1200, "sole panel unchanged");
    ok(told === 1, "explained rather than silently ignored");

    // Height edits the row, and rows still sum to the design height.
    const c6 = make([
        { height_mm: 750, is_auto: false, leaves: [panel(1200, "FIXED")] },
        { height_mm: 750, is_auto: false, leaves: [panel(1200, "FIXED")] },
    ], 1200, 1500);
    c6.notification = { add: () => {} };
    c6.selectLeaf([[0, 0]]);
    c6.setPanelHeight("3 0");          // 914.4mm
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

console.log(fail ? `\n${fail} FAILURES` : "\nall passed");
process.exit(fail ? 1 : 0);
