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
        data: {
            id: 1, length_uom: "ftin", size_display: "",
            header: { name: "D1", location: "", qty: 1, width_mm: W, height_mm: H,
                      window_series_id: 1, window_series_name: "Casement Single Glaze" },
            rows, leaf_types: LEAF_TYPES, presets: [],
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
    ok(c.adornments.toolbar.show === false,
       "no toolbar anchor when nothing is selected");
    c.selectLeaf([[0, 0]]);
    ok(c.adornments.toolbar.show === true,
       "toolbar anchors to the selected panel");
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
    ok(c.adornments.toolbar.show === true, "and the floating toolbar anchors to it");
    c.endDrag();
    c.setJunction("interlock");
    ok(c.scene.dividers[0].junction === "interlock", "setJunction writes through");
}

console.log(fail ? `\n${fail} FAILURES` : "\nall passed");
process.exit(fail ? 1 : 0);
