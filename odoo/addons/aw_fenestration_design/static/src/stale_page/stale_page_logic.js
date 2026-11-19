// What to do when Odoo says "Invalid controller to restore": a breadcrumb or
// a reload asked for a page that is no longer in its stack, which happens
// when a page was updated or removed behind a screen that is still open.
//
// Odoo-free on purpose, so scripts/check_stale_page.mjs runs this very file.
// The rules:
//   * no unsaved changes: say so and reload ONCE;
//   * unsaved changes on the configurator: never reload by itself, show a
//     Reload button;
//   * the error again right after a reload: say so and stop (no loop).

export const RELOAD_KEY = "aw_stale_page_reload";
export const RELOAD_WINDOW_MS = 30000;
export const RELOAD_DELAY_MS = 1500;

let unsavedCheck = null;

/** The configurator registers how to ask it whether it has unsaved changes. */
export function setUnsavedCheck(check) {
    unsavedCheck = check;
}

export function clearUnsavedCheck(check) {
    if (!check || unsavedCheck === check) {
        unsavedCheck = null;
    }
}

export function hasUnsavedChanges() {
    try {
        return !!(unsavedCheck && unsavedCheck());
    } catch {
        return true; // when in doubt, do not throw the user's work away
    }
}

/** 'ask' (unsaved changes), 'stop' (reloaded a moment ago) or 'reload'. */
export function decideStalePage({ unsaved, lastReloadAt, now }) {
    if (unsaved) {
        return "ask";
    }
    if (lastReloadAt && now - lastReloadAt < RELOAD_WINDOW_MS) {
        return "stop";
    }
    return "reload";
}

/**
 * Carries the decision out. `deps`: storage (getItem/setItem), now, notify
 * (message, options), reload, schedule (fn, ms), t (translation).
 * Returns what it decided.
 */
export function handleStalePage(deps) {
    const t = deps.t || ((text) => text);
    const message = t("This page was updated or is no longer available.");
    const lastReloadAt = Number(deps.storage.getItem(RELOAD_KEY)) || 0;
    const decision = decideStalePage({
        unsaved: hasUnsavedChanges(),
        lastReloadAt,
        now: deps.now,
    });
    if (decision === "ask") {
        deps.notify(`${message} ${t("Your changes are not saved.")}`, {
            type: "warning",
            sticky: true,
            buttons: [{ name: t("Reload"), primary: true, onClick: deps.reload }],
        });
    } else if (decision === "stop") {
        deps.notify(
            `${message} ${t("Reload the page by hand if it still does not work.")}`,
            { type: "danger", sticky: true }
        );
    } else {
        deps.storage.setItem(RELOAD_KEY, String(deps.now));
        deps.notify(`${message} ${t("Reloading...")}`, { type: "warning" });
        deps.schedule(deps.reload, RELOAD_DELAY_MS);
    }
    return decision;
}
