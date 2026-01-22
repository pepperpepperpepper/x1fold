// Repo source: x1fold/tools/x1fold_wl_blank.c
//
// Wayland "halfblank" helper for Lenovo X1 Fold:
// - Creates a wlr-layer-shell surface that covers the "blank" region.
// - Sets exclusive_zone so normal windows avoid that space.
//
// This is the Wayland counterpart to x1fold/tools/x1fold_x11_blank.c.
//
// Notes:
// - Requires compositor support for wlr-layer-shell (wlroots-based compositors).
// - Does not attempt global pointer confinement; Wayland does not offer a
//   compositor-agnostic equivalent to XFixes pointer barriers.

#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#include <wayland-client.h>

#include "wayland/wlr-layer-shell-unstable-v1-client-protocol.h"

static volatile sig_atomic_t g_stop = 0;

static void on_signal(int signo) {
  (void)signo;
  g_stop = 1;
}

static void install_signal_handlers(void) {
  struct sigaction sa;
  memset(&sa, 0, sizeof(sa));
  sa.sa_handler = on_signal;
  sigemptyset(&sa.sa_mask);
  // Do not use SA_RESTART: we want blocking Wayland calls to return so the
  // main loop can observe g_stop and exit promptly.
  sa.sa_flags = 0;
  sigaction(SIGINT, &sa, NULL);
  sigaction(SIGTERM, &sa, NULL);
}

static int pump_events(struct wl_display *display, int timeout_ms) {
  if (wl_display_dispatch_pending(display) < 0) {
    return -1;
  }
  if (wl_display_flush(display) < 0) {
    return -1;
  }

  // Prepare a non-blocking read, poll, then read+dispatch pending events.
  //
  // We intentionally avoid wl_display_dispatch() here: it can block inside
  // libwayland even when we already polled, and it doesn't reliably exit on
  // SIGTERM when Sway is on an inactive VT.
  while (wl_display_prepare_read(display) != 0) {
    if (wl_display_dispatch_pending(display) < 0) {
      return -1;
    }
    if (wl_display_flush(display) < 0) {
      return -1;
    }
  }

  const int fd = wl_display_get_fd(display);
  struct pollfd pfd = {.fd = fd, .events = POLLIN, .revents = 0};
  int rc = poll(&pfd, 1, timeout_ms);
  if (rc < 0) {
    wl_display_cancel_read(display);
    if (errno == EINTR) {
      return 0;
    }
    return -1;
  }
  if (rc == 0) {
    wl_display_cancel_read(display);
    return 0;
  }
  if (pfd.revents & (POLLERR | POLLHUP | POLLNVAL)) {
    wl_display_cancel_read(display);
    return -1;
  }

  if (wl_display_read_events(display) < 0) {
    return -1;
  }
  if (wl_display_dispatch_pending(display) < 0) {
    return -1;
  }
  return 0;
}

static void dief(const char *fmt, ...) {
  va_list ap;
  va_start(ap, fmt);
  vfprintf(stderr, fmt, ap);
  va_end(ap);
  fputc('\n', stderr);
  exit(1);
}

static void usage(FILE *out) {
  fprintf(out,
          "Usage:\n"
          "  x1fold_wl_blank [--side SIDE] [--active-size PX] [--name NAME]\n"
          "\n"
          "Creates a Wayland layer-shell surface covering the 'blank' region and\n"
          "reserves that space via exclusive_zone.\n"
          "\n"
          "SIDE controls which edge is blanked (default: bottom):\n"
          "  bottom  -> blank bottom, active top is PX tall\n"
          "  top     -> blank top, active bottom is PX tall\n"
          "  left    -> blank left, active right is PX wide\n"
          "  right   -> blank right, active left is PX wide\n");
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
  dief("invalid --side (must be one of: bottom, top, left, right)");
  return SIDE_BOTTOM;
}

static int create_tmpfile(off_t size) {
  char template_path[] = "/tmp/x1fold_wl_blank.XXXXXX";
  int fd = mkstemp(template_path);
  if (fd < 0) {
    return -1;
  }
  unlink(template_path);
  if (ftruncate(fd, size) < 0) {
    close(fd);
    return -1;
  }
  return fd;
}

struct output_info {
  struct wl_output *wl_output;
  int32_t width;
  int32_t height;
  int32_t scale;
  bool have_current_mode;
};

struct app {
  struct wl_display *display;
  struct wl_registry *registry;
  struct wl_compositor *compositor;
  struct wl_shm *shm;
  struct zwlr_layer_shell_v1 *layer_shell;

  struct output_info out;
  bool have_output;

  enum Side side;
  int32_t active_size_px;
  const char *name;

  struct wl_surface *surface;
  struct zwlr_layer_surface_v1 *layer_surface;

  struct wl_buffer *buffer;
  void *buf_data;
  size_t buf_len;
  int buf_w;
  int buf_h;
  int buf_stride;

  int32_t desired_w;
  int32_t desired_h;
  int32_t exclusive_zone;
  int32_t scale;
};

static void destroy_buffer(struct app *app) {
  if (app->buffer) {
    wl_buffer_destroy(app->buffer);
    app->buffer = NULL;
  }
  if (app->buf_data && app->buf_len) {
    munmap(app->buf_data, app->buf_len);
  }
  app->buf_data = NULL;
  app->buf_len = 0;
  app->buf_w = 0;
  app->buf_h = 0;
  app->buf_stride = 0;
}

static void ensure_buffer(struct app *app, int32_t width, int32_t height) {
  if (!app->shm) {
    dief("missing wl_shm");
  }
  if (width <= 0 || height <= 0) {
    dief("invalid configured size %dx%d", (int)width, (int)height);
  }

  const int32_t scale = (app->scale > 0) ? app->scale : 1;
  const int buf_w = (int)width * (int)scale;
  const int buf_h = (int)height * (int)scale;
  const int stride = buf_w * 4;
  const size_t size = (size_t)stride * (size_t)buf_h;

  if (app->buffer && app->buf_w == buf_w && app->buf_h == buf_h) {
    return;
  }

  destroy_buffer(app);

  int fd = create_tmpfile((off_t)size);
  if (fd < 0) {
    dief("mkstemp/ftruncate failed: %s", strerror(errno));
  }

  void *data = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
  if (data == MAP_FAILED) {
    close(fd);
    dief("mmap failed: %s", strerror(errno));
  }
  memset(data, 0x00, size);  // XRGB8888 black

  struct wl_shm_pool *pool = wl_shm_create_pool(app->shm, fd, (int)size);
  if (!pool) {
    munmap(data, size);
    close(fd);
    dief("wl_shm_create_pool failed");
  }
  struct wl_buffer *buf =
      wl_shm_pool_create_buffer(pool, 0, buf_w, buf_h, stride, WL_SHM_FORMAT_XRGB8888);
  wl_shm_pool_destroy(pool);
  close(fd);

  if (!buf) {
    munmap(data, size);
    dief("wl_shm_pool_create_buffer failed");
  }

  app->buffer = buf;
  app->buf_data = data;
  app->buf_len = size;
  app->buf_w = buf_w;
  app->buf_h = buf_h;
  app->buf_stride = stride;
}

static void layer_surface_configure(void *data, struct zwlr_layer_surface_v1 *surface,
                                    uint32_t serial, uint32_t width, uint32_t height) {
  (void)serial;
  struct app *app = data;

  const int32_t w = (width > 0) ? (int32_t)width : app->desired_w;
  const int32_t h = (height > 0) ? (int32_t)height : app->desired_h;
  if (w <= 0 || h <= 0) {
    dief("compositor configured invalid size w=%u h=%u", width, height);
  }

  zwlr_layer_surface_v1_ack_configure(surface, serial);

  wl_surface_set_buffer_scale(app->surface, app->scale > 0 ? app->scale : 1);
  ensure_buffer(app, w, h);

  wl_surface_attach(app->surface, app->buffer, 0, 0);
  // wl_surface_damage_buffer requires wl_surface v4; wl_surface_damage is
  // sufficient for our static black buffer.
  wl_surface_damage(app->surface, 0, 0, INT32_MAX, INT32_MAX);
  wl_surface_commit(app->surface);
}

static void layer_surface_closed(void *data, struct zwlr_layer_surface_v1 *surface) {
  (void)data;
  (void)surface;
  g_stop = 1;
}

static const struct zwlr_layer_surface_v1_listener layer_surface_listener = {
    .configure = layer_surface_configure,
    .closed = layer_surface_closed,
};

static void output_geometry(void *data, struct wl_output *wl_output, int32_t x, int32_t y, int32_t phys_w,
                            int32_t phys_h, int32_t subpixel, const char *make, const char *model,
                            int32_t transform) {
  (void)data;
  (void)wl_output;
  (void)x;
  (void)y;
  (void)phys_w;
  (void)phys_h;
  (void)subpixel;
  (void)make;
  (void)model;
  (void)transform;
}

static void output_mode(void *data, struct wl_output *wl_output, uint32_t flags, int32_t width, int32_t height,
                        int32_t refresh) {
  (void)wl_output;
  (void)refresh;
  struct app *app = data;
  if ((flags & WL_OUTPUT_MODE_CURRENT) == 0) {
    return;
  }
  app->out.width = width;
  app->out.height = height;
  app->out.have_current_mode = true;
}

static void output_done(void *data, struct wl_output *wl_output) {
  (void)data;
  (void)wl_output;
}

static void output_scale(void *data, struct wl_output *wl_output, int32_t factor) {
  (void)wl_output;
  struct app *app = data;
  app->out.scale = factor;
}

static const struct wl_output_listener output_listener = {
    .geometry = output_geometry,
    .mode = output_mode,
    .done = output_done,
    .scale = output_scale,
};

static void registry_global(void *data, struct wl_registry *registry, uint32_t name, const char *interface,
                            uint32_t version) {
  struct app *app = data;
  if (strcmp(interface, wl_compositor_interface.name) == 0) {
    uint32_t v = version < 4 ? version : 4;
    app->compositor = wl_registry_bind(registry, name, &wl_compositor_interface, v);
  } else if (strcmp(interface, wl_shm_interface.name) == 0) {
    uint32_t v = version < 1 ? version : 1;
    app->shm = wl_registry_bind(registry, name, &wl_shm_interface, v);
  } else if (strcmp(interface, zwlr_layer_shell_v1_interface.name) == 0) {
    uint32_t v = version < 1 ? version : 1;
    app->layer_shell = wl_registry_bind(registry, name, &zwlr_layer_shell_v1_interface, v);
  } else if (strcmp(interface, wl_output_interface.name) == 0) {
    if (!app->have_output) {
      uint32_t v = version < 2 ? version : 2;
      app->out.wl_output = wl_registry_bind(registry, name, &wl_output_interface, v);
      wl_output_add_listener(app->out.wl_output, &output_listener, app);
      app->have_output = true;
    }
  }
}

static void registry_remove(void *data, struct wl_registry *registry, uint32_t name) {
  (void)data;
  (void)registry;
  (void)name;
}

static const struct wl_registry_listener registry_listener = {
    .global = registry_global,
    .global_remove = registry_remove,
};

static void setup_geometry(struct app *app) {
  if (!app->have_output || !app->out.have_current_mode) {
    dief("no wl_output current mode available (compositor did not report output size)");
  }
  int32_t scale = app->out.scale > 0 ? app->out.scale : 1;
  app->scale = scale;

  // wl_output mode size is in physical pixels; layer-shell surface size and
  // exclusive zone are in surface-local units (logical px). Convert with scale.
  const int32_t full_w = app->out.width / scale;
  const int32_t full_h = app->out.height / scale;
  int32_t active = app->active_size_px / scale;
  if (active <= 0) {
    active = 1;
  }

  int32_t blank_w = full_w;
  int32_t blank_h = full_h;
  int32_t exclusive = 0;

  if (app->side == SIDE_BOTTOM || app->side == SIDE_TOP) {
    if (active >= full_h) {
      dief("--active-size must be in 1..(screen_height-1); full_h=%d active=%d", (int)full_h, (int)active);
    }
    blank_h = full_h - active;
    exclusive = blank_h;
    blank_w = 0;  // fill
  } else {
    if (active >= full_w) {
      dief("--active-size must be in 1..(screen_width-1); full_w=%d active=%d", (int)full_w, (int)active);
    }
    blank_w = full_w - active;
    exclusive = blank_w;
    blank_h = 0;  // fill
  }

  app->desired_w = blank_w;
  app->desired_h = blank_h;
  app->exclusive_zone = exclusive;
}

static void create_surface(struct app *app) {
  if (!app->display || !app->compositor || !app->layer_shell) {
    dief("missing Wayland globals (need wl_compositor + zwlr_layer_shell_v1)");
  }

  setup_geometry(app);

  app->surface = wl_compositor_create_surface(app->compositor);
  if (!app->surface) {
    dief("wl_compositor_create_surface failed");
  }

  const char *ns = app->name ? app->name : "x1fold-halfblank";
  app->layer_surface = zwlr_layer_shell_v1_get_layer_surface(
      app->layer_shell, app->surface, app->out.wl_output, ZWLR_LAYER_SHELL_V1_LAYER_OVERLAY, ns);
  if (!app->layer_surface) {
    dief("zwlr_layer_shell_v1_get_layer_surface failed");
  }

  uint32_t anchors = 0;
  if (app->side == SIDE_BOTTOM) {
    anchors = ZWLR_LAYER_SURFACE_V1_ANCHOR_BOTTOM | ZWLR_LAYER_SURFACE_V1_ANCHOR_LEFT |
              ZWLR_LAYER_SURFACE_V1_ANCHOR_RIGHT;
  } else if (app->side == SIDE_TOP) {
    anchors = ZWLR_LAYER_SURFACE_V1_ANCHOR_TOP | ZWLR_LAYER_SURFACE_V1_ANCHOR_LEFT |
              ZWLR_LAYER_SURFACE_V1_ANCHOR_RIGHT;
  } else if (app->side == SIDE_LEFT) {
    anchors = ZWLR_LAYER_SURFACE_V1_ANCHOR_LEFT | ZWLR_LAYER_SURFACE_V1_ANCHOR_TOP |
              ZWLR_LAYER_SURFACE_V1_ANCHOR_BOTTOM;
  } else if (app->side == SIDE_RIGHT) {
    anchors = ZWLR_LAYER_SURFACE_V1_ANCHOR_RIGHT | ZWLR_LAYER_SURFACE_V1_ANCHOR_TOP |
              ZWLR_LAYER_SURFACE_V1_ANCHOR_BOTTOM;
  }

  zwlr_layer_surface_v1_set_anchor(app->layer_surface, anchors);
  zwlr_layer_surface_v1_set_size(app->layer_surface, (uint32_t)app->desired_w, (uint32_t)app->desired_h);
  zwlr_layer_surface_v1_set_exclusive_zone(app->layer_surface, app->exclusive_zone);
  zwlr_layer_surface_v1_set_keyboard_interactivity(app->layer_surface, 0);

  zwlr_layer_surface_v1_add_listener(app->layer_surface, &layer_surface_listener, app);

  wl_surface_commit(app->surface);
}

int main(int argc, char **argv) {
  const char *name = "X1FOLD_HALFBLANK";
  const char *side_str = "bottom";
  int32_t active_size = 1240;

  for (int i = 1; i < argc; i++) {
    if (strcmp(argv[i], "--side") == 0 && i + 1 < argc) {
      side_str = argv[++i];
    } else if (strcmp(argv[i], "--active-size") == 0 && i + 1 < argc) {
      active_size = (int32_t)strtol(argv[++i], NULL, 0);
    } else if (strcmp(argv[i], "--top-height") == 0 && i + 1 < argc) {
      // Backwards-compatible alias.
      active_size = (int32_t)strtol(argv[++i], NULL, 0);
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

  if (active_size <= 0) {
    dief("--active-size must be >= 1");
  }

  install_signal_handlers();

  struct app app = {0};
  app.side = parse_side(side_str);
  app.active_size_px = active_size;
  app.name = name;

  app.display = wl_display_connect(NULL);
  if (!app.display) {
    dief("wl_display_connect failed (is WAYLAND_DISPLAY set?)");
  }
  app.registry = wl_display_get_registry(app.display);
  if (!app.registry) {
    dief("wl_display_get_registry failed");
  }
  wl_registry_add_listener(app.registry, &registry_listener, &app);

  // Populate globals, then wait for an output current mode.
  //
  // On some compositors (notably Sway when its VT is inactive), wl_output may
  // exist but not report a current mode yet. Rather than exiting and forcing
  // a restart loop, keep the helper alive and wait for the mode to appear.
  bool ready = false;
  while (!g_stop) {
    if (app.compositor && app.shm && app.layer_shell && app.have_output && app.out.have_current_mode) {
      ready = true;
      break;
    }
    if (pump_events(app.display, 1000) < 0) {
      break;
    }
  }
  if (!g_stop && ready) {
    if (!app.layer_shell) {
      dief("compositor missing zwlr_layer_shell_v1 (wlroots layer-shell)");
    }
    create_surface(&app);
  }

  while (!g_stop) {
    if (pump_events(app.display, 1000) < 0) {
      break;
    }
  }

  destroy_buffer(&app);
  if (app.layer_surface) {
    zwlr_layer_surface_v1_destroy(app.layer_surface);
  }
  if (app.surface) {
    wl_surface_destroy(app.surface);
  }
  if (app.out.wl_output) {
    wl_output_destroy(app.out.wl_output);
  }
  if (app.layer_shell) {
    zwlr_layer_shell_v1_destroy(app.layer_shell);
  }
  if (app.shm) {
    wl_shm_destroy(app.shm);
  }
  if (app.compositor) {
    wl_compositor_destroy(app.compositor);
  }
  if (app.registry) {
    wl_registry_destroy(app.registry);
  }
  if (app.display) {
    wl_display_disconnect(app.display);
  }

  return 0;
}
