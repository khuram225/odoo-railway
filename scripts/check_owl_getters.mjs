#!/usr/bin/env node
/**
 * Instantiate each OWL component's getters against a mocked state and read
 * every one of them once, to catch getter cycles before deploy.
 *
 * Why this exists: the configurator crashed on open with RangeError
 * "Maximum call stack size exceeded" from
 *     scene -> unitsPerPixel -> fitScale -> scene
 * introduced by sizing the panel-number badges inside the scene getter.
 * Nothing caught it. The file is valid XML and valid JS, node --check
 * passes, and the offline tests reimplemented each function standalone --
 * so they exercised the arithmetic but never the real getters, and a
 * cycle only exists between real getters. This runs the actual class.
 *
 * It works by stripping the import lines and the registry registration
 * (neither resolvable outside the Odoo bundle), prepending stubs for what
 * those imports provided, and importing the result. That keeps the class
 * body itself untouched, which is the whole point -- a reimplementation
 * would have the same blind spot as the tests it replaces.
 *
 * Usage: node scripts/check_owl_getters.mjs
 */
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, basename } from "node:path";
import { pathToFileURL } from "node:url";

const TARGETS = [
    {
        file: "odoo/addons/aw_fenestration_design/static/src/design_configurator/design_configurator.js",
        exportName: "DesignConfigurator",
        // Enough shape for the getters to do real work.
        state: () => ({
            loading: false,
            dirty: false,
            zoom: 1,
            canvasW: 900,
            canvasH: 600,
            libraryOpen: true,
            selected: { row: 0, leaf: 1 },
            data: {
                id: 1,
                length_uom: "ftin",
                size_display: "8 ft 0 in x 10 ft 6 in",
                header: {
                    name: "D1",
                    location: "Hall",
                    qty: 1,
                    width_mm: 2438.4,
                    height_mm: 3200.4,
                    window_series_id: 1,
                    window_series_name: "Double Glaze Sliding",
                },
                rows: [
                    {
                        height_mm: 1600.2,
                        is_auto: false,
                        leaves: [
                            { width_mm: 1219.2, leaf_type_id: 1, leaf_type_code: "SLIDER", slide_dir: "left" },
                            { width_mm: 1219.2, leaf_type_id: 3, leaf_type_code: "MESH" },
                        ],
                    },
                    {
                        height_mm: 1600.2,
                        is_auto: false,
                        leaves: [
                            { width_mm: 2438.4, leaf_type_id: 2, leaf_type_code: "CASEMENT", hinge_side: "left", swing: "out" },
                        ],
                    },
                ],
                leaf_types: [
                    { id: 1, code: "SLIDER", name: "Slider", has_hinge_side: false, has_slide_dir: true },
                    { id: 2, code: "CASEMENT", name: "Casement", has_hinge_side: true, has_slide_dir: false },
                    { id: 3, code: "MESH", name: "Mesh", has_hinge_side: false, has_slide_dir: true },
                ],
                presets: [
                    {
                        id: 1,
                        name: "2 Track 2 Panel",
                        category: "Sliding Designs",
                        layout: { rows: [{ h: 1, leaves: [{ w: 1, type: "SLIDER" }, { w: 1, type: "SLIDER" }] }] },
                    },
                ],
            },
        }),
        // Getters that must each evaluate once without recursing.
        getters: [
            "scene",
            "adornments",
            "fitScale",
            "unitsPerPixel",
            "renderedSize",
            "zoomPercent",
            "uom",
            "uomLabel",
            "selectedLeaf",
            "selectedLeafType",
            "selectedPanelLabel",
            "presetsByCategory",
        ],
    },
];

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

function loadable(source) {
    return (
        STUBS +
        source
            .replace(/^\s*import\s[\s\S]*?from\s*["'][^"']+["'];?\s*$/gm, "")
            .replace(/^\s*registry\.category\([\s\S]*?\);\s*$/gm, "")
    );
}

let failures = 0;
const dir = mkdtempSync(join(tmpdir(), "owl-getters-"));

for (const target of TARGETS) {
    const source = readFileSync(target.file, "utf8");
    const tmp = join(dir, basename(target.file, ".js") + ".mjs");
    writeFileSync(tmp, loadable(source), "utf8");

    let mod;
    try {
        mod = await import(pathToFileURL(tmp).href);
    } catch (err) {
        console.log(`  FAIL ${target.file}: could not load -- ${err.message}`);
        failures++;
        continue;
    }

    const Cls = mod[target.exportName];
    if (!Cls) {
        console.log(`  FAIL ${target.file}: no export named ${target.exportName}`);
        failures++;
        continue;
    }

    // Object.create, not new: setup() wants services and lifecycle hooks
    // that only exist inside a mounted component. The getters are on the
    // prototype and only need `state`.
    const instance = Object.create(Cls.prototype);
    instance.state = target.state();
    instance.props = { action: { params: {}, context: {} } };
    instance.canvasRef = { el: null };
    instance.svgRef = { el: null };

    for (const name of target.getters) {
        try {
            void instance[name];
            console.log(`  ok   ${target.exportName}.${name}`);
        } catch (err) {
            const cycle = err instanceof RangeError;
            console.log(
                `  FAIL ${target.exportName}.${name}: ${err.message}` +
                    (cycle ? "  <- looks like a getter cycle" : "")
            );
            failures++;
        }
    }
}

if (failures) {
    console.log(`\n${failures} getter failure(s).`);
    process.exit(1);
}
console.log("\nAll component getters evaluate without cycles.");
