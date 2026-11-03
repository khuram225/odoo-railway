import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * The rates in force today for one profile, as a table: a row per
 * thickness, a column per finish any vendor prices. Read-only: rates come
 * only from rate lists.
 *
 * Three views of one payload, chosen here with no further server call:
 * All (one line per vendor under each thickness, the lowest rate in each
 * finish bold), one vendor, and Compare (one line per thickness, each cell
 * the lowest rate with the vendor that offers it).
 */
export class RatesTable extends Component {
    static template = "aw_fenestration_core.RatesTable";
    static props = { ...standardFieldProps };

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        const data = this.table;
        const preferred = data.default_vendor_id;
        this.state = useState({ mode: preferred ? String(preferred) : "all" });
    }

    get table() {
        return this.props.record.data.aw_rates_table || {};
    }

    get vendors() {
        return this.table.vendors || [];
    }

    get finishes() {
        return this.table.finishes || [];
    }

    get modes() {
        const modes = [{ key: "all", label: _t("All") }];
        for (const vendor of this.vendors) {
            modes.push({ key: String(vendor.id), label: vendor.name });
        }
        if (this.vendors.length > 1) {
            modes.push({ key: "compare", label: _t("Compare") });
        }
        return modes;
    }

    get activeMode() {
        // A remembered vendor that no longer has rates falls back to All.
        const known = this.modes.some((mode) => mode.key === this.state.mode);
        return known ? this.state.mode : "all";
    }

    setMode(key) {
        this.state.mode = key;
    }

    cellOf(thicknessId, finishId, vendorId) {
        return (this.table.cells || []).find(
            (cell) => cell.t === thicknessId && cell.f === finishId
                && cell.v === vendorId) || null;
    }

    cellsAt(thicknessId, finishId) {
        return (this.table.cells || []).filter(
            (cell) => cell.t === thicknessId && cell.f === finishId);
    }

    hasVariant(thicknessId, finishId) {
        return (this.table.variants || []).includes(`${thicknessId}-${finishId}`);
    }

    vendorName(vendorId) {
        const vendor = this.vendors.find((item) => item.id === vendorId);
        return vendor ? vendor.name : "";
    }

    fmt(price) {
        return Number.isInteger(price) ? String(price) : price.toFixed(2);
    }

    /** Lines of the table: {key, thickness, vendorId, vendor, date, cells}. */
    get rows() {
        const rows = [];
        const mode = this.activeMode;
        for (const thickness of this.table.thicknesses || []) {
            const vendorIds = mode === "all"
                ? this.vendors.map((vendor) => vendor.id)
                : mode === "compare" ? [0] : [Number(mode)];
            let first = true;
            for (const vendorId of vendorIds) {
                const cells = this.finishes.map((finish) => this.buildCell(
                    mode, thickness.id, finish.id, vendorId));
                if (!cells.some((cell) => cell.price !== null)) {
                    continue;
                }
                const sample = cells.find((cell) => cell.price !== null);
                rows.push({
                    key: `${thickness.id}-${vendorId}`,
                    thickness: first ? thickness.name : "",
                    vendorId: vendorId,
                    vendor: mode === "all" ? this.vendorName(vendorId) : "",
                    date: mode === "all" && sample ? sample.date : "",
                    cells: cells,
                });
                first = false;
            }
        }
        return rows;
    }

    buildCell(mode, thicknessId, finishId, vendorId) {
        const empty = {
            key: finishId, price: null, date: "", vendorId: 0, vendor: "",
            best: false, dot: this.hasVariant(thicknessId, finishId),
            thicknessId: thicknessId, finishId: finishId,
        };
        if (mode === "compare") {
            const all = this.cellsAt(thicknessId, finishId);
            if (!all.length) {
                return empty;
            }
            const lowest = all.reduce(
                (a, b) => (b.price < a.price ? b : a));
            return { ...empty, price: lowest.price, vendorId: lowest.v,
                     vendor: this.vendorName(lowest.v), date: lowest.date };
        }
        const cell = this.cellOf(thicknessId, finishId, vendorId);
        if (!cell) {
            return empty;
        }
        const all = this.cellsAt(thicknessId, finishId);
        const lowest = Math.min(...all.map((item) => item.price));
        return { ...empty, price: cell.price, vendorId: vendorId,
                 date: cell.date,
                 best: mode === "all" && all.length > 1
                     && cell.price === lowest };
    }

    async openCell(cell) {
        if (cell.price === null) {
            return;
        }
        const id = this.props.record.resId;
        const action = await this.orm.call(
            "product.template", "aw_rates_action",
            [[id], cell.thicknessId, cell.finishId, cell.vendorId]);
        await this.action.doAction(action);
    }
}

registry.category("fields").add("aw_rates_table", {
    component: RatesTable,
    displayName: _t("Rates table"),
    supportedTypes: ["json"],
});
