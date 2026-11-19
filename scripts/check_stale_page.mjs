#!/usr/bin/env node
/**
 * "Invalid controller to restore": what the page does about it, and that
 * the configurator says which design it is.
 *
 * Runs the REAL files: stale_page_logic.js (Odoo-free, imported as it is)
 * and the real DesignConfigurator class with its setup() actually run
 * (hooks stubbed to record what was registered). Cases, from the brief:
 *   - the configurator publishes updateActionState({ active_id: designId }),
 *     from params or from the action context, and a second configurator
 *     carries its own id;
 *   - the unsaved-changes check is registered on mount and cleared on
 *     unmount;
 *   - the handler reloads only when there are no unsaved changes, shows a
 *     Reload button instead when there are, and does not loop.
 *
 * Usage: node scripts/check_stale_page.mjs
 */
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const ROOT = "odoo/addons/aw_fenestration_design/static/src";
const dir = mkdtempSync(join(tmpdir(), "stale-page-"));
let failures = 0;
function check(ok, label) {
    console.log(`  ${ok ? "ok  " : "FAIL"} ${label}`);
    if (!ok) failures++;
}
async function load(source, name) {
    const tmp = join(dir, name);
    writeFileSync(tmp, source, "utf8");
    return import(pathToFileURL(tmp).href);
}

// ---- the logic, fresh for every scenario (it keeps one module variable)
const logicSource = readFileSync(`${ROOT}/stale_page/stale_page_logic.js`, "utf8");
let n = 0;
const freshLogic = () => load(logicSource + `\n// ${++n}`, `logic${n}.mjs`);

function deps(logic, over = {}) {
    const sent = { notes: [], reloads: 0, scheduled: [] };
    const store = {};
    const d = {
        storage: {
            getItem: (k) => (k in store ? store[k] : null),
            setItem: (k, v) => { store[k] = v; },
        },
        now: 1_000_000,
        notify: (message, options) => sent.notes.push({ message, options }),
        reload: () => { sent.reloads++; },
        schedule: (fn, ms) => sent.scheduled.push({ fn, ms }),
        ...over,
    };
    return { d, sent, store };
}

console.log("\nNO UNSAVED CHANGES: reload once");
{
    const logic = await freshLogic();
    const { d, sent, store } = deps(logic);
    const result = logic.handleStalePage(d);
    check(result === "reload", "decides to reload");
    check(sent.reloads === 0 && sent.scheduled.length === 1,
        "the reload is scheduled after the message, not done at once");
    sent.scheduled[0].fn();
    check(sent.reloads === 1, "and happens once");
    check(sent.notes[0].message.startsWith("This page was updated or is no longer available."),
        "the message says what happened");
    check(store[logic.RELOAD_KEY] === String(d.now), "it remembers it reloaded");
}

console.log("\nTHE ERROR AGAIN AFTER A RELOAD: say so and stop");
{
    const logic = await freshLogic();
    const { d, sent, store } = deps(logic);
    store[logic.RELOAD_KEY] = String(d.now - 5000);
    const result = logic.handleStalePage(d);
    check(result === "stop", "decides to stop");
    check(sent.scheduled.length === 0 && sent.reloads === 0, "does not reload again");
    check(sent.notes.length === 1 && !sent.notes[0].options.buttons,
        "shows the message only");
    store[logic.RELOAD_KEY] = String(d.now - logic.RELOAD_WINDOW_MS - 1);
    check(logic.handleStalePage(d) === "reload",
        "an error long after the last reload is a new one: reload once more");
}

console.log("\nUNSAVED CHANGES: never by itself, a Reload button");
{
    const logic = await freshLogic();
    logic.setUnsavedCheck(() => true);
    const { d, sent, store } = deps(logic);
    const result = logic.handleStalePage(d);
    check(result === "ask", "decides to ask");
    check(sent.scheduled.length === 0 && sent.reloads === 0, "does not reload");
    const buttons = sent.notes[0].options.buttons || [];
    check(buttons.length === 1 && buttons[0].name === "Reload", "offers a Reload button");
    check(sent.notes[0].options.sticky === true, "and the message stays");
    check(!(logic.RELOAD_KEY in store), "nothing remembered: the user has not reloaded");
    buttons[0].onClick();
    check(sent.reloads === 1, "the button reloads");
    // even right after a reload, unsaved work is never thrown away
    store[logic.RELOAD_KEY] = String(d.now - 1000);
    check(logic.handleStalePage(d) === "ask", "unsaved changes win over the loop guard");
    logic.clearUnsavedCheck();
    check(logic.hasUnsavedChanges() === false, "cleared on unmount: no unsaved changes");
    logic.setUnsavedCheck(() => { throw new Error("broken"); });
    check(logic.hasUnsavedChanges() === true, "a check that fails counts as unsaved");
}

// ---- the real configurator class, setup() run
console.log("\nTHE CONFIGURATOR: which design it is");
const STUBS = `
const window = { innerWidth: 1440, innerHeight: 900, addEventListener() {}, removeEventListener() {},
    localStorage: { getItem() { return null; }, setItem() {}, removeItem() {} } };
const Component = class {};
const SizeBox = class {};
const Many2One = class {};
const ConfirmationDialog = class {};
const useState = (o) => o;
const useRef = () => ({ el: null });
const useService = () => ({});
const registry = { category: () => ({ add: () => {} }) };
const standardActionServiceProps = {};
const _t = (s) => s;
const presetThumb = () => ({});
const onWillStart = () => {};
const onPatched = () => {};
globalThis.__hooks = { mounted: [], unmount: [] };
const onMounted = (fn) => globalThis.__hooks.mounted.push(fn);
const onWillUnmount = (fn) => globalThis.__hooks.unmount.push(fn);
globalThis.ResizeObserver = class { observe() {} disconnect() {} };
let __check = null;
const setUnsavedCheck = (fn) => { __check = fn; globalThis.__check = fn; };
const clearUnsavedCheck = (fn) => { if (__check === fn) { __check = null; globalThis.__check = null; } };
`;
const cfgSource = readFileSync(`${ROOT}/design_configurator/design_configurator.js`, "utf8");
const cfg = await load(
    STUBS + cfgSource
        .replace(/^\s*import\s[\s\S]*?from\s*["'][^"']+["'];?\s*$/gm, "")
        .replace(/^\s*registry\.category\([\s\S]*?\);\s*$/gm, ""),
    "configurator.mjs");
const Cls = cfg.DesignConfigurator;

function open(props) {
    globalThis.__hooks.mounted.length = 0;
    globalThis.__hooks.unmount.length = 0;
    const calls = [];
    const instance = Object.create(Cls.prototype);
    instance.props = { updateActionState: (s) => calls.push(s), ...props };
    instance.setup();
    return { instance, calls };
}

{
    const { instance, calls } = open({ action: { params: { design_id: 7 }, context: {} } });
    check(instance.designId === 7, "the design id comes from the action params");
    check(calls.length === 1 && calls[0].active_id === 7,
        "it publishes updateActionState({ active_id: 7 })");
}
{
    const { calls } = open({ action: { params: {}, context: { active_id: 12 } } });
    check(calls.length === 1 && calls[0].active_id === 12,
        "or from the context the action was opened with");
}
{
    const first = open({ action: { params: { design_id: 3 }, context: {} } });
    const second = open({ action: { params: { design_id: 4 }, context: {} } });
    check(first.calls[0].active_id === 3 && second.calls[0].active_id === 4,
        "a configurator opened on top of another carries its own design id");
}
{
    const { instance } = open({ action: { params: { design_id: 5 }, context: {} } });
    instance.state.dirty = false;
    globalThis.__hooks.mounted.forEach((fn) => fn.call(instance));
    check(typeof globalThis.__check === "function", "the unsaved check is registered on mount");
    check(globalThis.__check() === false, "clean: no unsaved changes");
    instance.state.dirty = true;
    check(globalThis.__check() === true, "after an edit: unsaved changes");
    globalThis.__hooks.unmount.forEach((fn) => fn.call(instance));
    check(!globalThis.__check, "and cleared on unmount");
}
{
    // an action service that gives no updateActionState (a dialog) must
    // not break the page
    const instance = Object.create(Cls.prototype);
    instance.props = { action: { params: { design_id: 9 }, context: {} } };
    let threw = false;
    try { instance.setup(); } catch { threw = true; }
    check(!threw, "no updateActionState prop: setup still works");
}

// ---- the registration itself (needs Odoo's bundle to run, so read)
console.log("\nTHE HANDLER IS REGISTERED");
{
    const wiring = readFileSync(`${ROOT}/stale_page/stale_page.js`, "utf8");
    check(/category\("error_handlers"\)\s*\.add\("awControllerNotFound"/.test(wiring),
        "added to the error_handlers registry");
    check(wiring.includes("originalError instanceof ControllerNotFoundError"),
        "answers only to ControllerNotFoundError (every other error is left alone)");
    check(wiring.includes('from "@web/webclient/actions/action_service"')
        && wiring.includes("handleStalePage"),
        "imports the error class from Odoo and the decision from stale_page_logic");
}

console.log(failures ? `\n${failures} check(s) failed` : "\nall passed");
process.exit(failures ? 1 : 0);
