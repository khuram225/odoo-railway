import { Component, useEffect, useRef, useState } from "@odoo/owl";

/**
 * A size box that is a plain display until it is clicked.
 *
 * Selecting the whole value on the first mouse click kept failing in
 * Chrome: the browser places the caret after the focus event and undoes
 * whatever was selected there. So no attempt is made to fight it. A click
 * (or Tab) swaps the display for a FRESH input, mounted with the current
 * value and given focus and select-all as it mounts -- there is no
 * earlier mousedown on that element for the browser to place a caret
 * from. Blur or Enter commits and swaps back to the display; Escape
 * leaves the value alone.
 *
 * A box that was entered and left unchanged commits nothing, which is
 * what the native "change" event gave the inputs this replaces.
 */
export class SizeBox extends Component {
    static template = "aw_fenestration_design.SizeBox";
    static props = {
        value: { type: String, optional: true },
        placeholder: { type: String, optional: true },
        inputmode: { type: String, optional: true },
        class: { type: String, optional: true },
        style: { type: String, optional: true },
        size: { type: String, optional: true },
        kind: { type: String, optional: true },
        onInput: { type: Function, optional: true },
        onCommit: Function,
        onCancel: { type: Function, optional: true },
    };

    setup() {
        this.state = useState({ editing: false, initial: "" });
        this.input = useRef("input");
        useEffect(
            (editing) => {
                const el = this.input.el;
                if (editing && el) {
                    el.focus();
                    el.select();
                }
            },
            () => [this.state.editing]
        );
    }

    start() {
        if (this.state.editing) {
            return;
        }
        this.state.initial = this.props.value || "";
        this.state.editing = true;
    }

    onInput(ev) {
        this.props.onInput?.(ev.target.value);
    }

    commit() {
        // Removing the input can blur it once more; only the first counts.
        if (!this.state.editing) {
            return;
        }
        const text = this.input.el ? this.input.el.value : this.state.initial;
        this.state.editing = false;
        if (text === this.state.initial) {
            this.props.onCancel?.();
            return;
        }
        this.props.onCommit(text);
    }

    cancel() {
        if (!this.state.editing) {
            return;
        }
        this.state.editing = false;
        this.props.onCancel?.();
    }

    onKeydown(ev) {
        if (ev.key === "Enter") {
            this.commit();
        } else if (ev.key === "Escape") {
            this.cancel();
        }
    }
}
