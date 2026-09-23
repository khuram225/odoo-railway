import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { _t } from "@web/core/l10n/translation";

const MM_PER_IN = 25.4;
const MM_PER_FT = 304.8;

/**
 * Visual design configurator.
 *
 * Stage B: everything except the SVG itself, which is Stage C -- the
 * drawing area below is a placeholder on purpose, so the load/edit/save
 * round trip can be verified before the drawing code exists.
 */
export class DesignConfigurator extends Component {
    static template = "aw_fenestration_design.DesignConfigurator";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");

        this.designId =
            this.props.action.params?.design_id ||
            this.props.action.context?.active_id;

        this.state = useState({
            loading: true,
            dirty: false,
            data: null,
            selected: null, // {row: i, leaf: j}
        });

        onWillStart(async () => {
            await this.load();
        });
    }

    async load() {
        this.state.data = await this.orm.call(
            "aw.design",
            "get_configurator_data",
            [[this.designId]]
        );
        this.state.loading = false;
        this.state.dirty = false;
        this.state.selected = null;
    }

    // -- unit rendering ----------------------------------------------------
    // Mirrors aw.design._format_length server-side. The unit is a global
    // setting, shown as a read-only label -- there is deliberately no
    // per-screen toggle.
    get uom() {
        return this.state.data?.length_uom || "ftin";
    }

    get uomLabel() {
        return { ftin: _t("ft + in"), in: _t("in"), mm: _t("mm") }[this.uom];
    }

    formatLength(mm) {
        const trim = (v) => String(Math.round(v * 100) / 100);
        if (this.uom === "mm") {
            return `${trim(mm)} mm`;
        }
        const totalIn = mm / MM_PER_IN;
        if (this.uom === "in") {
            return `${trim(totalIn)} in`;
        }
        const ft = Math.floor(totalIn / 12);
        return `${ft} ft ${trim(totalIn - ft * 12)} in`;
    }

    /** Parse what the user typed back into mm, in whatever unit is active. */
    parseLength(text) {
        const str = String(text || "").trim();
        if (!str) {
            return 0;
        }
        if (this.uom === "mm") {
            return parseFloat(str) || 0;
        }
        if (this.uom === "in") {
            return (parseFloat(str) || 0) * MM_PER_IN;
        }
        // ftin: "8 6" / "8ft 6in" / "8' 6" / plain "8" -> feet
        const nums = str.match(/-?\d+(\.\d+)?/g) || [];
        const ft = parseFloat(nums[0]) || 0;
        const inch = parseFloat(nums[1]) || 0;
        return ft * MM_PER_FT + inch * MM_PER_IN;
    }

    // -- header ------------------------------------------------------------
    onHeaderChange(field, value) {
        this.state.data.header[field] = value;
        this.state.dirty = true;
    }

    onDimensionChange(field, text) {
        this.state.data.header[field] = this.parseLength(text);
        this.state.dirty = true;
    }

    // -- selection ---------------------------------------------------------
    get selectedLeaf() {
        const sel = this.state.selected;
        if (!sel) {
            return null;
        }
        return this.state.data.rows[sel.row]?.leaves[sel.leaf] || null;
    }

    get selectedLeafType() {
        const leaf = this.selectedLeaf;
        if (!leaf) {
            return null;
        }
        return this.state.data.leaf_types.find(
            (lt) => lt.id === leaf.leaf_type_id
        );
    }

    selectLeaf(rowIndex, leafIndex) {
        this.state.selected = { row: rowIndex, leaf: leafIndex };
    }

    setLeafType(leafTypeId) {
        const leaf = this.selectedLeaf;
        if (!leaf) {
            return;
        }
        leaf.leaf_type_id = leafTypeId;
        const type = this.state.data.leaf_types.find(
            (lt) => lt.id === leafTypeId
        );
        leaf.leaf_type_code = type?.code || "";
        // Drop direction values the new type can't carry, so a casement
        // switched to fixed doesn't keep an invisible hinge side.
        if (!type?.has_hinge_side) {
            leaf.hinge_side = "";
            leaf.swing = "";
        }
        if (!type?.has_slide_dir) {
            leaf.slide_dir = "";
        }
        this.state.dirty = true;
    }

    setDirection(field, value) {
        const leaf = this.selectedLeaf;
        if (!leaf) {
            return;
        }
        leaf[field] = leaf[field] === value ? "" : value;
        this.state.dirty = true;
    }

    // -- presets -----------------------------------------------------------
    get presetsByCategory() {
        const groups = {};
        for (const preset of this.state.data?.presets || []) {
            const key = preset.category || _t("Other");
            (groups[key] = groups[key] || []).push(preset);
        }
        return Object.entries(groups).map(([category, presets]) => ({
            category,
            presets,
        }));
    }

    /**
     * Apply a preset's relative weights against this design's own overall
     * size. The prototype splits equally via normaliseRows(); weights
     * generalise that without changing the equal-split case.
     */
    applyPreset(preset) {
        const header = this.state.data.header;
        const layout = preset.layout;
        const totalH = layout.rows.reduce((sum, r) => sum + (r.h || 1), 0);
        const byCode = {};
        for (const lt of this.state.data.leaf_types) {
            byCode[lt.code] = lt;
        }
        this.state.data.rows = layout.rows.map((row) => {
            const totalW = row.leaves.reduce((sum, l) => sum + (l.w || 1), 0);
            return {
                height_mm: (header.height_mm * (row.h || 1)) / totalH,
                is_auto: false,
                leaves: row.leaves.map((leaf) => {
                    const type = byCode[leaf.type];
                    return {
                        width_mm: (header.width_mm * (leaf.w || 1)) / totalW,
                        is_auto: false,
                        leaf_type_id: type?.id || false,
                        leaf_type_code: leaf.type,
                        hinge_side: type?.has_hinge_side
                            ? leaf.hinge || ""
                            : "",
                        swing: type?.has_hinge_side ? leaf.swing || "" : "",
                        slide_dir: type?.has_slide_dir ? leaf.slide || "" : "",
                    };
                }),
            };
        });
        this.state.selected = null;
        this.state.dirty = true;
    }

    // -- save --------------------------------------------------------------
    async save() {
        const data = this.state.data;
        this.state.data = await this.orm.call("aw.design", "save_layout", [
            [this.designId],
            { header: data.header, rows: data.rows },
        ]);
        this.state.dirty = false;
        this.state.selected = null;
        this.notification.add(_t("Design saved."), { type: "success" });
    }

    openForm() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "aw.design",
            res_id: this.designId,
            view_mode: "form",
            views: [[false, "form"]],
        });
    }
}

registry.category("actions").add("aw_design_configurator", DesignConfigurator);
