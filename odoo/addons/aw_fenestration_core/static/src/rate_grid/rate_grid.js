import { Component, onWillStart, useEffect, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { SelectCreateDialog } from "@web/views/view_dialogs/select_create_dialog";

const LINE = "aw.vendor.rate.list.line";
const LIST = "aw.vendor.rate.list";
const LINE_FIELDS = [
    "code", "thickness_text", "series", "product_tmpl_id", "thickness_id",
    "problem", "result", "match_source",
    ...Array.from({ length: 10 }, (_, i) => `rate_${i + 1}`),
];

/**
 * The lines of a rate list as a grid whose rate columns come from the
 * vendor's layout: one per rate column, headed with the vendor's own name
 * (DULL) and, under it, our finish (Natural) or "no finish". Nothing about
 * the columns is hard-coded; they are read from the list when it opens.
 *
 * It reads and writes the same lines the form would, so the models, the
 * parser, the matching and Apply are untouched. A column with no finish is
 * read-only until a finish is set on the layout.
 */
export class RateGrid extends Component {
    static template = "aw_fenestration_core.RateGrid";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.root = useRef("root");
        this.state = useState({ lines: [], loaded: false });
        onWillStart(() => this.load());
        // Reload when the form reloads the list (Add pasted rows, Fill from
        // current rates, Apply change these counts or the state).
        useEffect(
            () => {
                // Not on the first run: onWillStart has just loaded.
                if (this.mountedOnce) {
                    this.load();
                }
                this.mountedOnce = true;
            },
            () => [
                this.props.record.data.line_count,
                this.props.record.data.state,
            ]
        );
    }

    get listId() {
        return this.props.record.resId;
    }

    get meta() {
        return this.props.record.data[this.props.name] || {};
    }

    get columns() {
        return this.meta.columns || [];
    }

    get readonly() {
        return this.props.readonly || this.props.record.data.state === "applied";
    }

    async load() {
        if (!this.listId) {
            this.state.lines = [];
            this.state.loaded = true;
            return;
        }
        const rows = await this.orm.searchRead(
            LINE, [["list_id", "=", this.listId]], LINE_FIELDS,
            { order: "sequence, id" });
        this.state.lines = rows;
        this.state.loaded = true;
    }

    cell(line, column) {
        const value = line[`rate_${column.index}`];
        return value ? String(value) : "";
    }

    productName(line) {
        return line.product_tmpl_id ? line.product_tmpl_id[1] : "";
    }

    statusText(line) {
        return line.result || line.problem || "";
    }

    parseNumber(text) {
        const value = parseFloat(String(text || "").replace(/,/g, ""));
        return Number.isFinite(value) && value > 0 ? value : 0;
    }

    async refresh() {
        await this.load();
        // Keep the counts on the form honest; never throw away a form
        // that has unsaved edits of its own.
        if (!this.props.record.dirty) {
            await this.props.record.load();
        }
    }

    async saveText(line, field, text) {
        if ((line[field] || "") === text) {
            return;
        }
        await this.orm.write(LINE, [line.id], { [field]: text });
        await this.refresh();
    }

    async saveRate(line, column, text) {
        const value = this.parseNumber(text);
        if ((line[`rate_${column.index}`] || 0) === value) {
            return;
        }
        await this.orm.write(LINE, [line.id], { [`rate_${column.index}`]: value });
        await this.refresh();
    }

    onKey(ev) {
        if (ev.key !== "Enter") {
            return;
        }
        ev.preventDefault();
        const row = parseInt(ev.target.dataset.row, 10);
        const col = ev.target.dataset.col;
        const next = this.root.el.querySelector(
            `input[data-row="${row + 1}"][data-col="${col}"]:not([readonly])`);
        if (next) {
            next.focus();
            next.select();
        } else {
            ev.target.blur();
        }
    }

    pickProduct(line) {
        this.dialog.add(SelectCreateDialog, {
            resModel: "product.template",
            title: _t("Choose a profile for %s", line.code),
            noCreate: true,
            multiSelect: false,
            domain: [["categ_id", "child_of", this.meta.profile_category_id]],
            onSelected: async (ids) => {
                // Written through the line, so the alias is saved as before.
                await this.orm.write(LINE, [line.id], { product_tmpl_id: ids[0] });
                await this.refresh();
            },
        });
    }

    /**
     * Tab-separated text pasted into any cell goes to the parser as if it
     * had been pasted into the paste box. A single value is left alone, so
     * pasting a number into one cell still works.
     */
    async onPaste(ev) {
        if (this.readonly || !this.listId) {
            return;
        }
        const text = ev.clipboardData ? ev.clipboardData.getData("text") : "";
        if (!/[\t\n\r]/.test(text)) {
            return;
        }
        ev.preventDefault();
        await this.orm.write(LIST, [this.listId], { paste_text: text });
        await this.orm.call(LIST, "action_parse_paste", [[this.listId]]);
        await this.refresh();
    }

    async addLine() {
        const last = this.state.lines.length
            ? this.state.lines[this.state.lines.length - 1] : null;
        await this.orm.create(LINE, [{
            list_id: this.listId, code: "",
            sequence: (last ? 10 : 0) + this.state.lines.length * 10 + 10,
        }]);
        await this.refresh();
    }

    async removeLine(line) {
        await this.orm.unlink(LINE, [line.id]);
        await this.refresh();
    }
}

registry.category("fields").add("aw_rate_grid", {
    component: RateGrid,
    displayName: _t("Rate grid"),
    supportedTypes: ["json"],
});
