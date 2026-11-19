import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { ControllerNotFoundError } from "@web/webclient/actions/action_service";
import { handleStalePage } from "./stale_page_logic";

// "Invalid controller to restore" used to open a traceback. A page that is
// no longer there is not a bug to read: say so, and reload once (see
// stale_page_logic.js for when it does not).
function controllerNotFoundHandler(env, error, originalError) {
    if (!(originalError instanceof ControllerNotFoundError)) {
        return false;
    }
    error.unhandledRejectionEvent?.preventDefault?.();
    handleStalePage({
        storage: browser.sessionStorage,
        now: Date.now(),
        notify: (message, options) => env.services.notification.add(message, options),
        reload: () => browser.location.reload(),
        schedule: (fn, ms) => browser.setTimeout(fn, ms),
        t: _t,
    });
    return true;
}

registry
    .category("error_handlers")
    .add("awControllerNotFound", controllerNotFoundHandler, { sequence: 1 });
