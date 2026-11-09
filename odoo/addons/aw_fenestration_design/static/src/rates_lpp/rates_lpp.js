import { patch } from "@web/core/utils/patch";
import { RatesTable } from "@aw_fenestration_core/rates_table/rates_table";

// The last purchase price under the list rate it belongs to.
patch(RatesTable.prototype, {
    buildCell(mode, thicknessId, finishId, vendorId) {
        const cell = super.buildCell(...arguments);
        cell.cur = cell.price === null
            ? null
            : this.curFor(thicknessId, finishId, cell.vendorId || vendorId);
        cell.lpp = cell.price === null
            ? null
            : this.lppFor(thicknessId, finishId, cell.vendorId || vendorId);
        return cell;
    },

    lppFor(thicknessId, finishId, vendorId) {
        return (this.table.lpp || []).find(
            (item) => item.t === thicknessId && item.f === finishId
                && item.v === vendorId) || null;
    },

    curFor(thicknessId, finishId, vendorId) {
        return (this.table.current || []).find(
            (item) => item.t === thicknessId && item.f === finishId
                && item.v === vendorId) || null;
    },

    curText(cur) {
        return `cost ${this.fmt(cur.cost)}: ${cur.text}`;
    },

    lppText(lpp) {
        const pct = lpp.pct === null || lpp.pct === undefined
            ? ""
            : ` ${lpp.pct >= 0 ? "+" : ""}${lpp.pct.toFixed(1)}% vs list today`;
        return `last ${this.fmt(lpp.price)} ${lpp.date} ${lpp.po}${pct}`;
    },
});
