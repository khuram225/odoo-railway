import { onMounted } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { patch } from "@web/core/utils/patch";
import { Chatter } from "@mail/chatter/web_portal/chatter";

const CLASS = "o-aw-chatter-collapsed";
const KEY = "aw_web_chatter_collapsed";

function stored() {
    try {
        return browser.localStorage.getItem(KEY) === "1";
    } catch {
        return false; // private window, blocked storage...
    }
}

/**
 * One switch for every form's chatter. The state is a class on <body>, so
 * it holds across views without any component keeping it, and it is
 * remembered in localStorage so a refresh keeps it. Collapsing is done in
 * CSS: the chatter's content is hidden and only the toggle stays, as a
 * narrow bar. The chatter itself is not touched.
 */
patch(Chatter.prototype, {
    setup() {
        super.setup(...arguments);
        onMounted(() => {
            document.body.classList.toggle(CLASS, stored());
        });
    },

    toggleAwChatterCollapsed() {
        const collapsed = !document.body.classList.contains(CLASS);
        document.body.classList.toggle(CLASS, collapsed);
        try {
            browser.localStorage.setItem(KEY, collapsed ? "1" : "0");
        } catch {
            // The toggle still works for this page.
        }
    },
});
