import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

/**
 * "Save as set": names the hardware on screen and saves it as a Hardware
 * Set. With "Save rates" ticked the rates that will be saved are listed:
 * only a rate TYPED on a row is carried; a row on the product's cost has
 * no rate to save and follows the product's cost when the set is used.
 */
export class HardwareKitDialog extends Component {
    static template = "aw_fenestration_design.HardwareKitDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        rows: Array,
        leafTypes: Array,
        leafTypeId: { type: [Number, Boolean], optional: true },
        onSave: Function,
    };

    setup() {
        this.state = useState({
            name: "",
            leafTypeId: this.props.leafTypeId || "",
            withRates: false,
            busy: false,
        });
    }

    get typedRates() {
        return this.props.rows.filter((row) => row.rate_manual);
    }

    get canSave() {
        return !this.state.busy && this.state.name.trim().length > 0;
    }

    async save() {
        if (!this.canSave) {
            return;
        }
        this.state.busy = true;
        try {
            const done = await this.props.onSave({
                name: this.state.name.trim(),
                leafTypeId: parseInt(this.state.leafTypeId, 10) || false,
                withRates: this.state.withRates,
            });
            if (done !== false) {
                this.props.close();
            }
        } finally {
            this.state.busy = false;
        }
    }
}
