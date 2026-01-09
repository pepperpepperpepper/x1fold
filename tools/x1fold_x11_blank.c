#include <X11/Xatom.h>
#include <X11/Xlib.h>
#include <X11/extensions/Xfixes.h>
#include <errno.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

// Repo source: x1fold/tools/x1fold_x11_blank.c

static volatile sig_atomic_t g_stop = 0;
static volatile sig_atomic_t g_xerr = 0;

static void on_signal(int signo) {
  (void)signo;
  g_stop = 1;
}

static void die_msg(const char *msg) {
  fprintf(stderr, "%s\n", msg);
  exit(1);
}

static void usage(FILE *out) {
  fprintf(out,
          "Usage:\n"
          "  x1fold_x11_blank [--display :N] [--side SIDE] [--active-size PX] [--name NAME]\n"
          "\n"
          "Creates a black DOCK window that covers the 'blank' region of the screen and\n"
          "reserves that space via _NET_WM_STRUT(_PARTIAL). It also installs an XFixes\n"
          "pointer barrier to prevent the cursor entering the blank region.\n"
          "\n"
          "This emulates the X1 Fold 'halfblank' behavior under X11 without requiring\n"
          "DRM master.\n"
          "\n"
          "SIDE controls which edge is blanked (default: bottom):\n"
          "  bottom  -> blank bottom, active top is PX tall\n"
          "  top     -> blank top, active bottom is PX tall\n"
          "  left    -> blank left, active right is PX wide\n"
          "  right   -> blank right, active left is PX wide\n");
}

static int on_xerror(Display *dpy, XErrorEvent *ev) {
  (void)dpy;
  if (ev) {
    g_xerr = (sig_atomic_t)ev->error_code;
  } else {
    g_xerr = 1;
  }
  return 0;
}

static Atom intern(Display *dpy, const char *name) {
  return XInternAtom(dpy, name, False);
}

static void set_atoms(Display *dpy, Window win, Atom prop, Atom *atoms, int natoms) {
  XChangeProperty(dpy, win, prop, XA_ATOM, 32, PropModeReplace, (unsigned char *)atoms, natoms);
}

static void set_cardinals(Display *dpy, Window win, Atom prop, long *vals, int nvals) {
  Atom cardinal = intern(dpy, "CARDINAL");
  XChangeProperty(dpy, win, prop, cardinal, 32, PropModeReplace, (unsigned char *)vals, nvals);
}

enum Side { SIDE_BOTTOM = 0, SIDE_TOP = 1, SIDE_LEFT = 2, SIDE_RIGHT = 3 };

static enum Side parse_side(const char *s) {
  if (!s || s[0] == '\0') {
    return SIDE_BOTTOM;
  }
  if (strcmp(s, "bottom") == 0) {
    return SIDE_BOTTOM;
  }
  if (strcmp(s, "top") == 0) {
    return SIDE_TOP;
  }
  if (strcmp(s, "left") == 0) {
    return SIDE_LEFT;
  }
  if (strcmp(s, "right") == 0) {
    return SIDE_RIGHT;
  }
  die_msg("invalid --side (must be one of: bottom, top, left, right)");
  return SIDE_BOTTOM;
}

static void clamp_pointer_to_active(Display *dpy, Window root, enum Side side, unsigned long w, unsigned long h,
                                    unsigned long active_size) {
  Window rr = 0, cr = 0;
  int rx = 0, ry = 0;
  int wx = 0, wy = 0;
  unsigned int mask = 0;
  if (!XQueryPointer(dpy, root, &rr, &cr, &rx, &ry, &wx, &wy, &mask)) {
    return;
  }

  int nx = rx;
  int ny = ry;
  bool need = false;

  if (side == SIDE_BOTTOM) {
    if (ry >= (int)active_size) {
      ny = (int)active_size - 1;
      if (ny < 0) {
        ny = 0;
      }
      need = true;
    }
  } else if (side == SIDE_TOP) {
    unsigned long blank_h = h - active_size;
    if (ry < (int)blank_h) {
      ny = (int)blank_h;
      if (ny >= (int)h) {
        ny = (int)h - 1;
      }
      need = true;
    }
  } else if (side == SIDE_LEFT) {
    unsigned long blank_w = w - active_size;
    if (rx < (int)blank_w) {
      nx = (int)blank_w;
      if (nx >= (int)w) {
        nx = (int)w - 1;
      }
      need = true;
    }
  } else if (side == SIDE_RIGHT) {
    if (rx >= (int)active_size) {
      nx = (int)active_size - 1;
      if (nx < 0) {
        nx = 0;
      }
      need = true;
    }
  }

  if (need) {
    XWarpPointer(dpy, None, root, 0, 0, 0, 0, nx, ny);
    XFlush(dpy);
  }
}

int main(int argc, char **argv) {
  const char *display = NULL;
  const char *name = "X1FOLD_HALFBLANK";
  const char *side_str = "bottom";
  unsigned long active_size = 1240;

  for (int i = 1; i < argc; i++) {
    if (strcmp(argv[i], "--display") == 0 && i + 1 < argc) {
      display = argv[++i];
    } else if (strcmp(argv[i], "--side") == 0 && i + 1 < argc) {
      side_str = argv[++i];
    } else if (strcmp(argv[i], "--active-size") == 0 && i + 1 < argc) {
      active_size = strtoul(argv[++i], NULL, 0);
    } else if (strcmp(argv[i], "--top-height") == 0 && i + 1 < argc) {
      // Backwards-compatible alias.
      active_size = strtoul(argv[++i], NULL, 0);
    } else if (strcmp(argv[i], "--name") == 0 && i + 1 < argc) {
      name = argv[++i];
    } else if (strcmp(argv[i], "-h") == 0 || strcmp(argv[i], "--help") == 0) {
      usage(stdout);
      return 0;
    } else {
      usage(stderr);
      return 2;
    }
  }

  signal(SIGINT, on_signal);
  signal(SIGTERM, on_signal);

  Display *dpy = XOpenDisplay(display);
  if (!dpy) {
    die_msg("XOpenDisplay failed (check DISPLAY or --display)");
  }

  int screen = DefaultScreen(dpy);
  Window root = RootWindow(dpy, screen);
  unsigned long w = (unsigned long)DisplayWidth(dpy, screen);
  unsigned long h = (unsigned long)DisplayHeight(dpy, screen);
  if (w == 0 || h == 0) {
    die_msg("DisplayWidth/DisplayHeight returned 0");
  }

  enum Side side = parse_side(side_str);
  if (active_size == 0) {
    die_msg("--active-size must be >= 1");
  }
  if ((side == SIDE_BOTTOM || side == SIDE_TOP) && active_size >= h) {
    die_msg("--active-size must be in 1..(screen_height-1) for top/bottom");
  }
  if ((side == SIDE_LEFT || side == SIDE_RIGHT) && active_size >= w) {
    die_msg("--active-size must be in 1..(screen_width-1) for left/right");
  }

  unsigned long blank_x = 0;
  unsigned long blank_y = 0;
  unsigned long blank_w = w;
  unsigned long blank_h = h;
  int barrier_x1 = 0, barrier_y1 = 0, barrier_x2 = 0, barrier_y2 = 0;
  int barrier_dir = 0;

  if (side == SIDE_BOTTOM) {
    blank_y = active_size;
    blank_h = h - active_size;
    barrier_x1 = 0;
    barrier_x2 = (w > 0) ? (int)(w - 1U) : 0;
    barrier_y1 = barrier_y2 = (int)active_size;
    barrier_dir = BarrierPositiveY;
  } else if (side == SIDE_TOP) {
    blank_y = 0;
    blank_h = h - active_size;
    unsigned long active_y = h - active_size;
    barrier_x1 = 0;
    barrier_x2 = (w > 0) ? (int)(w - 1U) : 0;
    barrier_y1 = barrier_y2 = (int)active_y;
    barrier_dir = BarrierNegativeY;
  } else if (side == SIDE_LEFT) {
    blank_x = 0;
    blank_w = w - active_size;
    unsigned long active_x = w - active_size;
    barrier_y1 = 0;
    barrier_y2 = (h > 0) ? (int)(h - 1U) : 0;
    barrier_x1 = barrier_x2 = (int)active_x;
    barrier_dir = BarrierNegativeX;
  } else if (side == SIDE_RIGHT) {
    blank_x = active_size;
    blank_w = w - active_size;
    barrier_y1 = 0;
    barrier_y2 = (h > 0) ? (int)(h - 1U) : 0;
    barrier_x1 = barrier_x2 = (int)active_size;
    barrier_dir = BarrierPositiveX;
  }

  XSetWindowAttributes attrs = {0};
  attrs.background_pixel = BlackPixel(dpy, screen);
  attrs.event_mask = ExposureMask | StructureNotifyMask;

  Window win = XCreateWindow(dpy, root, (int)blank_x, (int)blank_y, (unsigned int)blank_w, (unsigned int)blank_h, 0,
                             CopyFromParent,
                             InputOutput, CopyFromParent, CWBackPixel | CWEventMask, &attrs);
  if (!win) {
    die_msg("XCreateWindow failed");
  }

  XStoreName(dpy, win, name);

  // EWMH properties: window type, state, and struts.
  Atom net_wm_window_type = intern(dpy, "_NET_WM_WINDOW_TYPE");
  Atom net_wm_window_type_dock = intern(dpy, "_NET_WM_WINDOW_TYPE_DOCK");
  Atom win_type = net_wm_window_type_dock;
  set_atoms(dpy, win, net_wm_window_type, &win_type, 1);

  Atom net_wm_state = intern(dpy, "_NET_WM_STATE");
  Atom states[4];
  int nstates = 0;
  states[nstates++] = intern(dpy, "_NET_WM_STATE_ABOVE");
  states[nstates++] = intern(dpy, "_NET_WM_STATE_STICKY");
  states[nstates++] = intern(dpy, "_NET_WM_STATE_SKIP_TASKBAR");
  states[nstates++] = intern(dpy, "_NET_WM_STATE_SKIP_PAGER");
  set_atoms(dpy, win, net_wm_state, states, nstates);

  Atom net_wm_strut = intern(dpy, "_NET_WM_STRUT");
  long strut[4] = {0, 0, 0, 0};  // left, right, top, bottom
  if (side == SIDE_BOTTOM) {
    strut[3] = (long)blank_h;
  } else if (side == SIDE_TOP) {
    strut[2] = (long)blank_h;
  } else if (side == SIDE_LEFT) {
    strut[0] = (long)blank_w;
  } else if (side == SIDE_RIGHT) {
    strut[1] = (long)blank_w;
  }
  set_cardinals(dpy, win, net_wm_strut, strut, 4);

  Atom net_wm_strut_partial = intern(dpy, "_NET_WM_STRUT_PARTIAL");
  long sp[12] = {0};
  if (side == SIDE_BOTTOM) {
    sp[3] = (long)blank_h;     // bottom
    sp[10] = 0;               // bottom_start_x
    sp[11] = (long)(w - 1U);  // bottom_end_x
  } else if (side == SIDE_TOP) {
    sp[2] = (long)blank_h;    // top
    sp[8] = 0;               // top_start_x
    sp[9] = (long)(w - 1U);  // top_end_x
  } else if (side == SIDE_LEFT) {
    sp[0] = (long)blank_w;    // left
    sp[4] = 0;               // left_start_y
    sp[5] = (long)(h - 1U);  // left_end_y
  } else if (side == SIDE_RIGHT) {
    sp[1] = (long)blank_w;    // right
    sp[6] = 0;               // right_start_y
    sp[7] = (long)(h - 1U);  // right_end_y
  }
  set_cardinals(dpy, win, net_wm_strut_partial, sp, 12);

  XMapRaised(dpy, win);
  XFlush(dpy);

  // Prevent pointer entering the blank region. If the extension is missing,
  // keep going (blank window + strut still provide the core behavior).
  int xfixes_event_base = 0;
  int xfixes_error_base = 0;
  PointerBarrier barrier = 0;
  if (XFixesQueryExtension(dpy, &xfixes_event_base, &xfixes_error_base)) {
    int (*old_handler)(Display *, XErrorEvent *) = XSetErrorHandler(on_xerror);
    g_xerr = 0;
    barrier = XFixesCreatePointerBarrier(dpy, root, barrier_x1, barrier_y1, barrier_x2, barrier_y2, barrier_dir, 0, NULL);
    XSync(dpy, False);
    if (g_xerr != 0) {
      char errtxt[256];
      XGetErrorText(dpy, (int)g_xerr, errtxt, (int)sizeof(errtxt));
      fprintf(stderr, "warning: failed to create pointer barrier (X error %d: %s)\n", (int)g_xerr, errtxt);
      barrier = 0;
      g_xerr = 0;
    }
    XSetErrorHandler(old_handler);
  } else {
    fprintf(stderr, "warning: XFixes extension missing; cursor will not be constrained\n");
  }

  // In practice the pointer can still end up in the blank region (e.g. large
  // accumulated deltas against the barrier, client-side warps, or races when
  // enabling halfblank). Always clamp it back into the active top region to
  // avoid "stuck cursor says it's in the blank area" UX.
  clamp_pointer_to_active(dpy, root, side, w, h, active_size);

  // Minimal event loop: keep the window alive until killed by systemd/UI helper.
  while (!g_stop) {
    while (XPending(dpy) > 0) {
      XEvent ev;
      XNextEvent(dpy, &ev);
      if (ev.type == Expose) {
        // Repaint is handled by background_pixel; nothing to draw.
      }
    }
    clamp_pointer_to_active(dpy, root, side, w, h, active_size);
    usleep(100 * 1000);
  }

  if (barrier) {
    XFixesDestroyPointerBarrier(dpy, barrier);
  }
  XDestroyWindow(dpy, win);
  XCloseDisplay(dpy);
  return 0;
}
