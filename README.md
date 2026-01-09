# X1 Fold (halfblank) tooling

This directory contains the Linux-side implementation of the Lenovo X1 Fold “halfblank” behavior:

- `tools/`: helpers (`x1fold_mode.py`, `x1fold_dock.py`, `x1fold_halfblankd.py`, `x1fold_halfblank_ui.py`, `x1fold_x11_blank.c`, `drm_clip.c`)
- `scripts/`: install + regression wrappers
- `systemd/`: system and user units

See `docs/linux_halfblank_plan.md` and `plan.md` for architecture (including the Wayland plan).
See `docs/linux_halfblank_plan.md` for architecture (including the Wayland plan).
