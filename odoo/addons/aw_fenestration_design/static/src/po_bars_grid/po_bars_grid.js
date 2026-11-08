import { Component, onWillStart, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { PurchaseOrderLineProductField } from "@purchase_product_matrix/js/purchase_product_field";

/**
 * The bars grid for one profile on a purchase order: thickness chips (each
 * with the bars entered under it), a row per finish and a column per active
 * bar length. A cell is a whole number of bars. The server does the work:
 * aw_bars_grid_data() loads, aw_bars_grid_apply() writes every cell.
 */
export class BarsGridDialog extends Component {
    static template = "aw_fenestration_design.BarsGridDialog";
    static components = { Dialog };
    static props = {
        orderId: Number,
        templateId: { type: [Number, Boolean], optional: true },
        onApplied: { type: Function, optional: true },
        close: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            loading: true,
            saving: false,
            query: "",
            profiles: [],
            data: null,
            cells: {},
            thicknessId: null,
            error: "",
        });
        onWillStart(async () => {
            if (this.props.templateId) {
                await this.load(this.props.templateId);
            } else {
                await this.search();
            }
            this.state.loading = false;
        });
    }

    async search() {
        this.state.profiles = await this.orm.call(
            "purchase.order",
            "aw_bars_grid_profiles",
            [[this.props.orderId], this.state.query]
        );
    }

    async onQuery(ev) {
        this.state.query = ev.target.value;
        await this.search();
    }

    async pick(templateId) {
        this.state.error = "";
        try {
            await this.load(templateId);
        } catch (error) {
            this.state.error = (error.data && error.data.message) || String(error);
        }
    }

    async load(templateId) {
        const data = await this.orm.call(
            "purchase.order",
            "aw_bars_grid_data",
            [[this.props.orderId], templateId]
        );
        this.state.data = data;
        this.state.cells = Object.assign({}, data.cells);
        this.state.thicknessId = data.thicknesses.length ? data.thicknesses[0].id : null;
    }

    back() {
        this.state.data = null;
        this.state.error = "";
        return this.search();
    }

    // -- the grid --------------------------------------------------------
    cellKey(thicknessId, finishId, length) {
        return `${thicknessId}|${finishId}|${length}`;
    }
    cellValue(finishId, length) {
        return this.state.cells[this.cellKey(this.state.thicknessId, finishId, length)] || 0;
    }
    setCell(finishId, length, ev) {
        const parsed = Math.floor(Number(ev.target.value));
        const bars = Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
        this.state.cells[this.cellKey(this.state.thicknessId, finishId, length)] = bars;
        ev.target.value = bars;
    }
    selectThickness(thicknessId) {
        this.state.thicknessId = thicknessId;
    }
    rate(thicknessId, finishId) {
        return this.state.data.rates[`${thicknessId}|${finishId}`] || 0;
    }
    barsIn(thicknessId, finishId) {
        let total = 0;
        for (const length of this.state.data.lengths) {
            total += this.state.cells[this.cellKey(thicknessId, finishId, length)] || 0;
        }
        return total;
    }
    feetIn(thicknessId, finishId) {
        let total = 0;
        for (const length of this.state.data.lengths) {
            total +=
                (this.state.cells[this.cellKey(thicknessId, finishId, length)] || 0) * length;
        }
        return total;
    }
    thicknessBadge(thicknessId) {
        let total = 0;
        for (const finish of this.state.data.finishes) {
            total += this.barsIn(thicknessId, finish.id);
        }
        return total;
    }
    rowBars(finishId) {
        return this.barsIn(this.state.thicknessId, finishId);
    }
    rowFeet(finishId) {
        return this.feetIn(this.state.thicknessId, finishId);
    }
    rowAmount(finishId) {
        return this.rowFeet(finishId) * this.rate(this.state.thicknessId, finishId);
    }
    isLastPaid(finishId) {
        return this.state.data.sources[`${this.state.thicknessId}|${finishId}`] === "lpp";
    }
    hasRate(finishId) {
        return this.rate(this.state.thicknessId, finishId) > 0;
    }
    get totalBars() {
        let total = 0;
        for (const thickness of this.state.data.thicknesses) {
            total += this.thicknessBadge(thickness.id);
        }
        return total;
    }
    get totalFeet() {
        let total = 0;
        for (const thickness of this.state.data.thicknesses) {
            for (const finish of this.state.data.finishes) {
                total += this.feetIn(thickness.id, finish.id);
            }
        }
        return total;
    }
    get totalAmount() {
        let total = 0;
        for (const thickness of this.state.data.thicknesses) {
            for (const finish of this.state.data.finishes) {
                total +=
                    this.feetIn(thickness.id, finish.id) * this.rate(thickness.id, finish.id);
            }
        }
        return total;
    }
    money(value) {
        return `${this.state.data.currency} ${this.grouped(value)}`;
    }
    feet(value) {
        return this.grouped(value);
    }
    /** Two decimals and thousands separators. */
    grouped(value) {
        return value.toLocaleString("en-US", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }

    // -- confirm -----------------------------------------------------------
    async confirm() {
        const data = this.state.data;
        const cells = [];
        for (const thickness of data.thicknesses) {
            for (const finish of data.finishes) {
                for (const length of data.lengths) {
                    cells.push({
                        thickness_id: thickness.id,
                        finish_id: finish.id,
                        length_ft: length,
                        bars: this.state.cells[this.cellKey(thickness.id, finish.id, length)] || 0,
                    });
                }
            }
        }
        this.state.saving = true;
        this.state.error = "";
        try {
            await this.orm.call(
                "purchase.order",
                "aw_bars_grid_apply",
                [[this.props.orderId], data.template.id, cells]
            );
        } catch (error) {
            this.state.saving = false;
            this.state.error = (error.data && error.data.message) || String(error);
            return;
        }
        this.state.saving = false;
        if (this.props.onApplied) {
            this.props.onApplied();
        }
        this.props.close();
    }
}

/** Opens the dialog; the form is reloaded once the bars are written. */
export function openBarsGrid(env, orderId, templateId) {
    env.services.dialog.add(BarsGridDialog, {
        orderId,
        templateId: templateId || false,
        onApplied: () =>
            env.services.action.doAction({ type: "ir.actions.client", tag: "soft_reload" }),
    });
}

// "Add profile (bars grid)" on the RFQ form returns this client action.
registry.category("actions").add("aw_po_bars_grid", async (env, action) => {
    openBarsGrid(env, action.params.order_id, action.params.template_id);
});

// The pencil on a profile line opens the same dialog instead of Odoo's grid.
patch(PurchaseOrderLineProductField.prototype, {
    setup() {
        super.setup(...arguments);
        this.awDialog = useService("dialog");
        this.awAction = useService("action");
        this.awNotification = useService("notification");
    },
    onEditConfiguration() {
        const record = this.props.record;
        if (!record.data.aw_is_profile) {
            return super.onEditConfiguration(...arguments);
        }
        const orderId = record.model.root.resId;
        if (!orderId) {
            this.awNotification.add("Save the order first.", { type: "warning" });
            return;
        }
        openBarsGrid(
            { services: { dialog: this.awDialog, action: this.awAction } },
            orderId,
            record.data.product_template_id && record.data.product_template_id.id
        );
    },
});
