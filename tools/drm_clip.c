#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <xf86drm.h>
#include <xf86drmMode.h>

// Repo source: x1fold/tools/drm_clip.c

static void die(const char *msg) {
  perror(msg);
  exit(1);
}

static void die_msg(const char *msg) {
  fprintf(stderr, "%s\n", msg);
  exit(1);
}

static const char *default_card_path(void) {
  if (access("/dev/dri/card1", R_OK | W_OK) == 0) {
    return "/dev/dri/card1";
  }
  return "/dev/dri/card0";
}

static void usage(FILE *out) {
  fprintf(out,
          "Usage:\n"
          "  drm_clip [--card /dev/dri/cardN] [--connector eDP-1] [--height 1240] {status|half|full}\n");
}

static const char *connector_name(const drmModeConnector *conn, char *buf, size_t n) {
  snprintf(buf, n, "%s-%u", drmModeGetConnectorTypeName(conn->connector_type), conn->connector_type_id);
  return buf;
}

static drmModeConnector *pick_connector(int fd, drmModeRes *res, const char *want_name) {
  drmModeConnector *fallback = NULL;
  for (int i = 0; i < res->count_connectors; i++) {
    drmModeConnector *conn = drmModeGetConnector(fd, res->connectors[i]);
    if (!conn) {
      continue;
    }
    char name_buf[32];
    const char *name = connector_name(conn, name_buf, sizeof(name_buf));
    bool connected = (conn->connection == DRM_MODE_CONNECTED);
    if (!connected) {
      drmModeFreeConnector(conn);
      continue;
    }
    if (want_name && strcmp(want_name, name) == 0) {
      return conn;
    }
    if (!fallback && strncmp(name, "eDP-", 4) == 0) {
      fallback = conn;
      continue;
    }
    drmModeFreeConnector(conn);
  }
  return fallback;
}

static int crtc_index(drmModeRes *res, uint32_t crtc_id) {
  for (int i = 0; i < res->count_crtcs; i++) {
    if (res->crtcs[i] == crtc_id) {
      return i;
    }
  }
  return -1;
}

static int get_prop_by_name(int fd,
                            uint32_t obj_id,
                            uint32_t obj_type,
                            const char *name,
                            uint32_t *prop_id_out,
                            uint64_t *value_out) {
  drmModeObjectProperties *props = drmModeObjectGetProperties(fd, obj_id, obj_type);
  if (!props) {
    return -1;
  }
  int rc = -1;
  for (uint32_t i = 0; i < props->count_props; i++) {
    drmModePropertyRes *prop = drmModeGetProperty(fd, props->props[i]);
    if (!prop) {
      continue;
    }
    if (strcmp(prop->name, name) == 0) {
      if (prop_id_out) {
        *prop_id_out = prop->prop_id;
      }
      if (value_out) {
        *value_out = props->prop_values[i];
      }
      rc = 0;
      drmModeFreeProperty(prop);
      break;
    }
    drmModeFreeProperty(prop);
  }
  drmModeFreeObjectProperties(props);
  return rc;
}

static drmModePlane *pick_primary_plane(int fd, uint32_t crtc_id, int crtc_idx) {
  drmModePlaneRes *pres = drmModeGetPlaneResources(fd);
  if (!pres) {
    return NULL;
  }
  drmModePlane *best = NULL;
  for (uint32_t i = 0; i < pres->count_planes; i++) {
    drmModePlane *plane = drmModeGetPlane(fd, pres->planes[i]);
    if (!plane) {
      continue;
    }
    if (((plane->possible_crtcs >> crtc_idx) & 0x1) == 0) {
      drmModeFreePlane(plane);
      continue;
    }
    if (plane->crtc_id != crtc_id) {
      drmModeFreePlane(plane);
      continue;
    }
    uint64_t type_val = 0;
    if (get_prop_by_name(fd, plane->plane_id, DRM_MODE_OBJECT_PLANE, "type", NULL, &type_val) != 0) {
      drmModeFreePlane(plane);
      continue;
    }
    if (type_val != 1) {
      drmModeFreePlane(plane);
      continue;
    }
    best = plane;
    break;
  }
  drmModeFreePlaneResources(pres);
  return best;
}

static int set_clip(int fd, drmModePlane *plane, uint32_t crtc_id, uint32_t w, uint32_t h) {
  struct {
    const char *name;
    uint64_t value;
  } props[] = {
      {"FB_ID", plane->fb_id},
      {"CRTC_ID", crtc_id},
      {"CRTC_X", 0},
      {"CRTC_Y", 0},
      {"CRTC_W", w},
      {"CRTC_H", h},
      {"SRC_X", 0},
      {"SRC_Y", 0},
      {"SRC_W", ((uint64_t)w) << 16},
      {"SRC_H", ((uint64_t)h) << 16},
  };

  drmModeAtomicReq *req = drmModeAtomicAlloc();
  if (!req) {
    return -ENOMEM;
  }

  for (size_t i = 0; i < sizeof(props) / sizeof(props[0]); i++) {
    uint32_t prop_id = 0;
    if (get_prop_by_name(fd, plane->plane_id, DRM_MODE_OBJECT_PLANE, props[i].name, &prop_id, NULL) != 0) {
      drmModeAtomicFree(req);
      return -ENOENT;
    }
    if (drmModeAtomicAddProperty(req, plane->plane_id, prop_id, props[i].value) < 0) {
      drmModeAtomicFree(req);
      return -errno;
    }
  }

  int rc = drmModeAtomicCommit(fd, req, 0, NULL);
  drmModeAtomicFree(req);
  if (rc != 0) {
    return -errno;
  }
  return 0;
}

static void print_status_json(int fd,
                              const drmModeConnector *conn,
                              const drmModeCrtc *crtc,
                              const drmModePlane *plane) {
  char name_buf[32];
  const char *name = connector_name(conn, name_buf, sizeof(name_buf));

  uint64_t crtc_x = 0, crtc_y = 0, crtc_w = 0, crtc_h = 0;
  uint64_t src_x = 0, src_y = 0, src_w = 0, src_h = 0;
  get_prop_by_name(fd, plane->plane_id, DRM_MODE_OBJECT_PLANE, "CRTC_X", NULL, &crtc_x);
  get_prop_by_name(fd, plane->plane_id, DRM_MODE_OBJECT_PLANE, "CRTC_Y", NULL, &crtc_y);
  get_prop_by_name(fd, plane->plane_id, DRM_MODE_OBJECT_PLANE, "CRTC_W", NULL, &crtc_w);
  get_prop_by_name(fd, plane->plane_id, DRM_MODE_OBJECT_PLANE, "CRTC_H", NULL, &crtc_h);
  get_prop_by_name(fd, plane->plane_id, DRM_MODE_OBJECT_PLANE, "SRC_X", NULL, &src_x);
  get_prop_by_name(fd, plane->plane_id, DRM_MODE_OBJECT_PLANE, "SRC_Y", NULL, &src_y);
  get_prop_by_name(fd, plane->plane_id, DRM_MODE_OBJECT_PLANE, "SRC_W", NULL, &src_w);
  get_prop_by_name(fd, plane->plane_id, DRM_MODE_OBJECT_PLANE, "SRC_H", NULL, &src_h);

  printf("{\n");
  printf("  \"connector\": {\"name\": \"%s\", \"id\": %" PRIu32 "},\n", name, conn->connector_id);
  printf("  \"crtc\": {\"id\": %" PRIu32 ", \"mode\": \"%ux%u\"},\n", crtc->crtc_id, crtc->mode.hdisplay,
         crtc->mode.vdisplay);
  printf("  \"plane\": {\"id\": %" PRIu32 ", \"fb_id\": %" PRIu32 "},\n", plane->plane_id, plane->fb_id);
  printf("  \"plane_rect\": {\n");
  printf("    \"crtc\": {\"x\": %" PRIu64 ", \"y\": %" PRIu64 ", \"w\": %" PRIu64 ", \"h\": %" PRIu64 "},\n", crtc_x, crtc_y,
         crtc_w, crtc_h);
  printf("    \"src\": {\"x\": %" PRIu64 ", \"y\": %" PRIu64 ", \"w\": %" PRIu64 ", \"h\": %" PRIu64 "}\n", src_x, src_y, src_w,
         src_h);
  printf("  }\n");
  printf("}\n");
}

int main(int argc, char **argv) {
  const char *card = default_card_path();
  const char *connector = NULL;
  uint32_t half_h = 1240;
  const char *cmd = NULL;

  for (int i = 1; i < argc; i++) {
    if (strcmp(argv[i], "--card") == 0 && i + 1 < argc) {
      card = argv[++i];
    } else if (strcmp(argv[i], "--connector") == 0 && i + 1 < argc) {
      connector = argv[++i];
    } else if (strcmp(argv[i], "--height") == 0 && i + 1 < argc) {
      half_h = (uint32_t)strtoul(argv[++i], NULL, 0);
    } else if (strcmp(argv[i], "-h") == 0 || strcmp(argv[i], "--help") == 0) {
      usage(stdout);
      return 0;
    } else if (!cmd) {
      cmd = argv[i];
    } else {
      usage(stderr);
      return 2;
    }
  }

  if (!cmd) {
    usage(stderr);
    return 2;
  }

  int fd = open(card, O_RDWR | O_CLOEXEC);
  if (fd < 0) {
    die(card);
  }
  drmSetMaster(fd);
  bool is_master = drmIsMaster(fd) == 1;
  if (!is_master && strcmp(cmd, "status") != 0) {
    fprintf(stderr, "not DRM master (another compositor may own %s)\n", card);
    close(fd);
    return 1;
  }

  if (drmSetClientCap(fd, DRM_CLIENT_CAP_UNIVERSAL_PLANES, 1) != 0) {
    close(fd);
    die("drmSetClientCap(UNIVERSAL_PLANES)");
  }
  if (drmSetClientCap(fd, DRM_CLIENT_CAP_ATOMIC, 1) != 0) {
    close(fd);
    die("drmSetClientCap(ATOMIC)");
  }

  drmModeRes *res = drmModeGetResources(fd);
  if (!res) {
    close(fd);
    die("drmModeGetResources");
  }

  drmModeConnector *conn = pick_connector(fd, res, connector);
  if (!conn) {
    drmModeFreeResources(res);
    close(fd);
    die_msg("no connected connector found");
  }
  if (conn->encoder_id == 0) {
    drmModeFreeConnector(conn);
    drmModeFreeResources(res);
    close(fd);
    die_msg("connector has no encoder_id");
  }

  drmModeEncoder *enc = drmModeGetEncoder(fd, conn->encoder_id);
  if (!enc) {
    drmModeFreeConnector(conn);
    drmModeFreeResources(res);
    close(fd);
    die("drmModeGetEncoder");
  }
  if (enc->crtc_id == 0) {
    drmModeFreeEncoder(enc);
    drmModeFreeConnector(conn);
    drmModeFreeResources(res);
    close(fd);
    die_msg("encoder has no crtc_id");
  }

  int idx = crtc_index(res, enc->crtc_id);
  if (idx < 0) {
    drmModeFreeEncoder(enc);
    drmModeFreeConnector(conn);
    drmModeFreeResources(res);
    close(fd);
    die_msg("failed to find CRTC index");
  }

  drmModeCrtc *crtc = drmModeGetCrtc(fd, enc->crtc_id);
  if (!crtc) {
    drmModeFreeEncoder(enc);
    drmModeFreeConnector(conn);
    drmModeFreeResources(res);
    close(fd);
    die("drmModeGetCrtc");
  }
  if (crtc->mode_valid == 0) {
    drmModeFreeCrtc(crtc);
    drmModeFreeEncoder(enc);
    drmModeFreeConnector(conn);
    drmModeFreeResources(res);
    close(fd);
    die_msg("CRTC has no valid mode");
  }

  drmModePlane *plane = pick_primary_plane(fd, enc->crtc_id, idx);
  if (!plane) {
    drmModeFreeCrtc(crtc);
    drmModeFreeEncoder(enc);
    drmModeFreeConnector(conn);
    drmModeFreeResources(res);
    close(fd);
    die_msg("failed to find active primary plane");
  }

  int rc = 0;
  if (strcmp(cmd, "status") == 0) {
    print_status_json(fd, conn, crtc, plane);
  } else if (strcmp(cmd, "half") == 0) {
    uint32_t w = crtc->mode.hdisplay;
    uint32_t h = half_h;
    if (h == 0 || h > crtc->mode.vdisplay) {
      die_msg("--height must be in 1..current_vdisplay");
    }
    rc = set_clip(fd, plane, enc->crtc_id, w, h);
    if (rc != 0) {
      fprintf(stderr, "clip failed: %s\n", strerror(-rc));
    }
  } else if (strcmp(cmd, "full") == 0) {
    uint32_t w = crtc->mode.hdisplay;
    uint32_t h = crtc->mode.vdisplay;
    rc = set_clip(fd, plane, enc->crtc_id, w, h);
    if (rc != 0) {
      fprintf(stderr, "clip failed: %s\n", strerror(-rc));
    }
  } else {
    usage(stderr);
    rc = 2;
  }

  drmModeFreePlane(plane);
  drmModeFreeCrtc(crtc);
  drmModeFreeEncoder(enc);
  drmModeFreeConnector(conn);
  drmModeFreeResources(res);
  close(fd);
  return rc == 0 ? 0 : 1;
}
