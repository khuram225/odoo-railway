"""Pure layout helpers for the print-line engine (no ORM). All sizes in inches."""
import math

CUTS = (1, 2, 3, 4, 6, 8)


def cut_dims(width, height, parts):
    """Size of one part when a paper sheet is cut into `parts` (short side first)."""
    a, b = min(width, height), max(width, height)
    return {1: (a, b), 2: (a, b / 2), 3: (a, b / 3), 4: (a / 2, b / 2), 6: (a / 2, b / 3), 8: (a / 2, b / 4)}.get(parts, (a, b))


def fits(w, h, max_w, max_h):
    eps = 1e-6
    return (w <= max_w + eps and h <= max_h + eps) or (w <= max_h + eps and h <= max_w + eps)


def layout(kind, sheet_w, sheet_h, page_w, page_h, spine, gripper, strip, gap,
           cols=None, rows=None, col_group=1, row_group=1, orientation=None, grip_dir="across", strip_pos="edge"):
    """Fit pages (text), spreads (cover) or pieces (sheet) on a print sheet.

    Across = gripper on the long edge of the print sheet; along = on the short edge.
    Portrait = page height runs away from the gripper; landscape = turned 90 degrees.
    A cover uses two page columns per spread with the spine between them.
    With cols/rows given (an imposition) the layout is checked; otherwise the best fit is searched.
    Returns a dict with n (pages per side, or ups), cols, rows, orientation, need/avail sizes and fits.
    """
    long_side, short_side = max(sheet_w, sheet_h), min(sheet_w, sheet_h)
    edge = short_side if grip_dir == "along" else long_side
    other = long_side if grip_dir == "along" else short_side
    avail_w = edge
    avail_h = other - gripper - (0 if strip_pos == "none" else strip)

    def unit(orient):
        uw = 2 * page_w + spine if kind == "cover" else page_w
        uh = page_h
        return (uw, uh) if orient == "portrait" else (uh, uw)

    def check(orient, c, r, cg, rg):
        uw, uh = unit(orient)
        cols_u = c // 2 if kind == "cover" else c
        groups_w = cols_u if kind == "cover" else math.ceil(c / max(1, cg))
        groups_h = math.ceil(r / max(1, rg))
        need_w = cols_u * uw + max(0, groups_w - 1) * gap
        need_h = r * uh + max(0, groups_h - 1) * gap
        return {
            "orientation": orient, "cols": c, "rows": r, "units_across": cols_u, "n": cols_u * r,
            "need_w": need_w, "need_h": need_h, "avail_w": avail_w, "avail_h": avail_h,
            "unit_w": uw, "unit_h": uh, "fits": need_w <= avail_w + 1e-6 and need_h <= avail_h + 1e-6,
            "grip_dir": grip_dir, "edge": edge, "other": other,
        }

    if cols:
        return check(orientation or "portrait", cols, rows or 1, col_group, row_group)
    best = None
    for orient in ("portrait", "landscape"):
        uw, uh = unit(orient)
        if uw <= 0 or uh <= 0:
            continue
        units = math.floor((avail_w + 1e-6) / uw)
        r = math.floor((avail_h + 1e-6) / uh)
        c = units * 2 if kind == "cover" else units
        res = check(orient, c, r, max(1, c), max(1, r))
        if best is None or res["n"] > best["n"]:
            best = res
    return best
