// The one inch display rule, held to the same vectors in JavaScript as in
// aw_fenestration_core's units.py: inches to the nearest 1/16, a reduced
// ASCII fraction, no decimals, no feet, no glyphs.
//
// The two functions are pulled out of design_configurator.js as TEXT and
// evaluated here, so what is checked is the shipped code, not a copy.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(
    join(here, "..", "odoo", "addons", "aw_fenestration_design", "static",
         "src", "design_configurator", "design_configurator.js"),
    "utf8");

const start = source.indexOf("const MM_PER_IN = 25.4;");
const end = source.indexOf("// Drawing geometry");
if (start < 0 || end < start) {
    console.error("FAIL: cannot find formatInches / parseInches in the component");
    process.exit(1);
}
const { formatInches, parseInches } = new Function(
    `${source.slice(start, end)}\nreturn { formatInches, parseInches };`)();

let failures = 0;
const check = (ok, message) => {
    if (!ok) {
        failures += 1;
    }
    console.log(`  ${ok ? "ok  " : "FAIL"} ${message}`);
};

// mm -> text
const DISPLAY = [
    [1828.8, "72"], [1790.7, "70 1/2"], [866.8, "34 1/8"],
    [846.1, "33 5/16"], [304.79999999999995, "12"], [600, "23 5/8"],
    [1200, "47 1/4"], [731, "28 3/4"], [-38.1, "-1 1/2"], [0, "0"],
];
for (const [mm, want] of DISPLAY) {
    const got = formatInches(mm);
    check(got === want, `${mm} mm -> "${got}" (want "${want}")`);
}
check(!/[^\x20-\x7e]/.test(DISPLAY.map(([mm]) => formatInches(mm)).join("")),
      "display is plain ASCII: no glyphs");

// the workshop style: inches, a dash, soot (half soot as .5)
const SOOT = [
    [1209.2, "47-5"], [3647.6, "143-5"], [1179.2, "46-3.5"],
    [3617.6, "142-3.5"], [3657.6, "144"], [866.8, "34-1"],
    [857.25, "33-6"], [0, "0"], [12.7, "0-4"], [-38.1, "-1-4"],
];
for (const [mm, want] of SOOT) {
    const got = formatInches(mm, "soot");
    check(got === want, `soot ${mm} mm -> "${got}" (want "${want}")`);
}

// what people type -> mm (to 0.02 mm; the Python twin rounds to 0.01)
const PARSE = [
    ["72", 1828.8], ["34.125", 866.78], ["34 1/8", 866.78],
    ["34-1/8", 866.78], ["33 5/16", 846.14], ["33-5/16", 846.14],
    ["33-6", 857.25], ["33-6.5", 858.84], ["3s", 9.53], ["+3s", 9.53],
    ["-1 1/2", -38.1], ["1829mm", 1829.0], ["", 0],
    ["47-5", 1209.675], ["47 5/8", 1209.675], ["47.625", 1209.675],
    ["1209mm", 1209.0], ["46-3.5", 1179.51],
];
for (const [text, want] of PARSE) {
    const got = parseInches(text);
    check(Math.abs(got - want) < 0.02, `"${text}" -> ${got} mm (want ${want})`);
}
check(parseInches("33-6") === 857.25, '"33-6" is exactly 857.25 (the workshop rule)');
check(Number.isNaN(parseInches("seven")), "unreadable input is NaN, not 0");

// Round trip: what is displayed reads back to the same sixteenth of an
// inch, in both styles, for a spread of lengths and their negatives.
const sixteenths = (mm) => Math.round((mm / 25.4) * 16);
let broken = 0;
let tried = 0;
for (let value = 0; value < 6000; value += 7.31) {
    for (const sign of [1, -1]) {
        const mm = sign * value;
        for (const style of ["fraction", "soot"]) {
            const back = parseInches(formatInches(mm, style));
            tried += 1;
            if (sixteenths(back) !== sixteenths(mm)) {
                broken += 1;
                console.log(`    round trip broke: ${style} ${mm} -> "${formatInches(mm, style)}" -> ${back}`);
            }
        }
    }
}
check(!broken, `round trip holds to 1/16 in (${tried} lengths, both styles, both signs)`);

if (failures) {
    console.error(`${failures} FAILURES`);
    process.exit(1);
}
console.log("Inch display: every vector holds.");
