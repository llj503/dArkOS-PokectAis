/* pocketAis in-game OSD overlay -- pure Wayland client.
 *
 * The dArkOS SDL2 build only ships KMSDRM/offscreen video drivers, so an SDL2
 * window cannot be created inside the Weston session. This uses wl_shm +
 * xdg-shell directly and FreeType for CJK text. Alpha in the ARGB8888 buffer
 * gives the translucent overlay; the game keeps rendering underneath.
 *
 * Navigation reads the gamepad evdev node directly (Wayland keyboard focus is
 * not needed). The hotkey that OPENS the overlay belongs to vita3k-pad.py and
 * is derived from `console-detect -t`.
 *
 * Build (on device):
 *   wayland-scanner client-header xdg-shell.xml xdg-shell-client-protocol.h
 *   wayland-scanner private-code  xdg-shell.xml xdg-shell-protocol.c
 *   gcc -O2 -Wall -o vita3k-osd vita3k-osd-wl.c xdg-shell-protocol.c \
 *       $(pkg-config --cflags --libs wayland-client freetype2) -lrt
 */
#define _POSIX_C_SOURCE 200809L
#include <wayland-client.h>
#include "xdg-shell-client-protocol.h"
#include <ft2build.h>
#include FT_FREETYPE_H

#include <fcntl.h>
#include <linux/input.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/select.h>
#include <unistd.h>

#define ACTIVE_FLAG "/roms/vita3k/.osd-active"
#define PENDING_FILE "/roms/vita3k/.osd-pending"
#define PAD_NAME "rk3562-joystick"
#define OSD_BTN_UP 544
#define OSD_BTN_DOWN 545
#define OSD_BTN_A 304
#define OSD_BTN_B 305

typedef struct { const char *label; const char *key; const char *value; } MenuItem;
static const MenuItem items_zh[] = {
    { "返回游戏  /  Resume", NULL, NULL },
    { "系统语言  简体中文", "sys-lang", "11" },
    { "系统语言  English", "sys-lang", "1" },
    { "画面倍率  1x 流畅", "resolution-multiplier", "1" },
    { "画面倍率  2x 清晰", "resolution-multiplier", "2" },
    { "性能  省电 2 核", "guest-cores", "2" },
    { "性能  平衡 3 核", "guest-cores", "3" },
};
static const MenuItem items_en[] = {
    { "Resume", NULL, NULL },
    { "System language  Chinese (Simplified)", "sys-lang", "11" },
    { "System language  English", "sys-lang", "1" },
    { "Resolution  1x (fast)", "resolution-multiplier", "1" },
    { "Resolution  2x (sharp)", "resolution-multiplier", "2" },
    { "Performance  Power save (2 cores)", "guest-cores", "2" },
    { "Performance  Balanced (3 cores)", "guest-cores", "3" },
};
#define ITEM_COUNT ((int)(sizeof(items_zh) / sizeof(items_zh[0])))
/* Switched at startup from /roms/vita3k/.ui-lang (written by psvita-lang.py,
 * which follows the ES language exactly like the flycast/ps2 launchers). */
static const MenuItem *items = items_zh;
static const char *osd_title = "Vita3K 快捷设置   Quick Settings";
static const char *osd_hint = "方向键选择   A 确认   B 返回   (设置下次启动游戏生效)";

static const char *fonts[] = {
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    NULL
};

typedef struct {
    struct wl_display *display;
    struct wl_compositor *compositor;
    struct wl_shm *shm;
    struct xdg_wm_base *wm_base;
    struct wl_surface *surface;
    struct xdg_surface *xdg_surface;
    struct wl_buffer *buffer;
    uint32_t *pixels;
    int width, height, stride, size;
    int busy;
    FT_Face face;
    int sel;
    int done;
} Osd;

static volatile sig_atomic_t stop_flag = 0;
static void on_signal(int s) { (void)s; stop_flag = 1; }

static int utf8_next(const unsigned char *s, unsigned int *cp) {
    if (!*s) { *cp = 0; return 0; }
    if (s[0] < 0x80) { *cp = s[0]; return 1; }
    if ((s[0] & 0xE0) == 0xC0 && s[1]) { *cp = ((s[0] & 0x1F) << 6) | (s[1] & 0x3F); return 2; }
    if ((s[0] & 0xF0) == 0xE0 && s[1] && s[2]) {
        *cp = ((s[0] & 0x0F) << 12) | ((s[1] & 0x3F) << 6) | (s[2] & 0x3F); return 3;
    }
    if ((s[0] & 0xF8) == 0xF0 && s[1] && s[2] && s[3]) {
        *cp = ((s[0] & 0x07) << 18) | ((s[1] & 0x3F) << 12) |
              ((s[2] & 0x3F) << 6) | (s[3] & 0x3F); return 4;
    }
    *cp = '?'; return 1;
}

static void fill_rect(Osd *o, int x, int y, int w, int h, uint32_t color) {
    if (x < 0) { w += x; x = 0; }
    if (y < 0) { h += y; y = 0; }
    if (x + w > o->width) w = o->width - x;
    if (y + h > o->height) h = o->height - y;
    for (int j = 0; j < h; j++)
        for (int i = 0; i < w; i++)
            o->pixels[(y + j) * o->stride + x + i] = color;
}

/* Blend one FreeType glyph into the ARGB buffer. */
static void draw_text(Osd *o, const char *text, int x, int y, uint32_t color) {
    if (!o->face) return;
    const unsigned char *p = (const unsigned char *)text;
    int pen = 0; unsigned int cp; int n;
    while ((n = utf8_next(p, &cp)) > 0) {
        if (FT_Load_Char(o->face, cp, FT_LOAD_RENDER) == 0) {
            FT_Bitmap *b = &o->face->glyph->bitmap;
            int gx = x + pen + o->face->glyph->bitmap_left;
            int gy = y + 24 - o->face->glyph->bitmap_top;
            for (int j = 0; j < (int)b->rows; j++) {
                for (int i = 0; i < (int)b->width; i++) {
                    int px = gx + i, py = gy + j;
                    if (px < 0 || px >= o->width || py < 0 || py >= o->height) continue;
                    unsigned char a = b->buffer[j * b->pitch + i];
                    if (a < 8) continue;
                    uint32_t dst = o->pixels[py * o->stride + px];
                    uint32_t src = (color & 0x00FFFFFF) | ((uint32_t)a << 24);
                    /* simple source-over on opaque-ish card background */
                    if (a >= 200) o->pixels[py * o->stride + px] = src;
                    else {
                        unsigned int sr = (src >> 16) & 255, sg = (src >> 8) & 255, sb = src & 255;
                        unsigned int dr = (dst >> 16) & 255, dg = (dst >> 8) & 255, db = dst & 255;
                        unsigned int r = (sr * a + dr * (255 - a)) / 255;
                        unsigned int g = (sg * a + dg * (255 - a)) / 255;
                        unsigned int bl = (sb * a + db * (255 - a)) / 255;
                        o->pixels[py * o->stride + px] = 0xFF000000u | (r << 16) | (g << 8) | bl;
                    }
                }
            }
            pen += o->face->glyph->advance.x >> 6;
        } else pen += 12;
        p += n;
    }
}

static void draw(Osd *o) {
    fill_rect(o, 0, 0, o->width, o->height, 0xC0080C14u);   /* translucent dim */
    int card_w = o->width - 80, card_h = 90 + ITEM_COUNT * 46;
    int card_x = 40, card_y = (o->height - card_h) / 2;
    fill_rect(o, card_x, card_y, card_w, card_h, 0xF0181C26u);
    fill_rect(o, card_x, card_y, card_w, 2, 0xFF5082DCu);
    draw_text(o, osd_title, card_x + 28, card_y + 14, 0xFFFFFFFFu);
    for (int i = 0; i < ITEM_COUNT; i++) {
        int ry = card_y + 62 + i * 46;
        if (i == o->sel)
            fill_rect(o, card_x + 16, ry, card_w - 32, 40, 0xFF2D7FF9u);
        draw_text(o, items[i].label, card_x + 32, ry + 4,
                  i == o->sel ? 0xFFFFFFFFu : 0xFFBEC3CDu);
    }
    draw_text(o, osd_hint, card_x + 28, card_y + card_h - 32, 0xFF9AA6BCu);
}

static void buffer_release(void *data, struct wl_buffer *b) {
    (void)b; ((Osd *)data)->busy = 0;
}
static const struct wl_buffer_listener buffer_listener = { .release = buffer_release };

static void xdg_configure(void *data, struct xdg_surface *s, uint32_t serial) {
    Osd *o = data;
    xdg_surface_ack_configure(s, serial);
    if (!o->buffer) return;
    draw(o);
    wl_surface_attach(o->surface, o->buffer, 0, 0);
    wl_surface_damage(o->surface, 0, 0, o->width, o->height);
    wl_surface_commit(o->surface);
    wl_display_flush(o->display);   /* requests generated inside a callback are
                                    * not sent until we flush */
    o->busy = 1;
}
static const struct xdg_surface_listener xdg_surface_listener = { .configure = xdg_configure };

static void toplevel_configure(void *data, struct xdg_toplevel *t,
                               int32_t w, int32_t h, struct wl_array *states) {
    (void)data; (void)t; (void)w; (void)h; (void)states;
}
static void toplevel_close(void *data, struct xdg_toplevel *t) {
    (void)t; ((Osd *)data)->done = 1;
}
static const struct xdg_toplevel_listener toplevel_listener = {
    .configure = toplevel_configure, .close = toplevel_close,
};

static void wm_ping(void *data, struct xdg_wm_base *wm, uint32_t serial) {
    (void)data; xdg_wm_base_pong(wm, serial);
}
static const struct xdg_wm_base_listener wm_listener = { .ping = wm_ping };

static void registry_global(void *data, struct wl_registry *reg, uint32_t name,
                            const char *iface, uint32_t version) {
    Osd *o = data;
    if (!strcmp(iface, "wl_compositor"))
        o->compositor = wl_registry_bind(reg, name, &wl_compositor_interface, 4);
    else if (!strcmp(iface, "wl_shm"))
        o->shm = wl_registry_bind(reg, name, &wl_shm_interface, 1);
    else if (!strcmp(iface, "xdg_wm_base")) {
        o->wm_base = wl_registry_bind(reg, name, &xdg_wm_base_interface, 1);
        xdg_wm_base_add_listener(o->wm_base, &wm_listener, o);
    }
    (void)version;
}
static void registry_remove(void *data, struct wl_registry *r, uint32_t n) {
    (void)data; (void)r; (void)n;
}
static const struct wl_registry_listener registry_listener = {
    .global = registry_global, .global_remove = registry_remove,
};

static int find_pad(void) {
    char path[64], name[128];
    for (int i = 31; i >= 0; i--) {
        snprintf(path, sizeof(path), "/dev/input/event%d", i);
        int fd = open(path, O_RDONLY | O_NONBLOCK);
        if (fd < 0) continue;
        memset(name, 0, sizeof(name));
        if (ioctl(fd, EVIOCGNAME(sizeof(name) - 1), name) >= 0 && !strcmp(name, PAD_NAME))
            return fd;
        close(fd);
    }
    return -1;
}

static void write_pending(const MenuItem *it) {
    if (!it->key) return;
    FILE *f = fopen(PENDING_FILE, "a");
    if (!f) return;
    fprintf(f, "%s=%s\n", it->key, it->value);
    fclose(f);
}

static void recommit(Osd *o) {
    if (o->busy) return;
    draw(o);
    wl_surface_attach(o->surface, o->buffer, 0, 0);
    wl_surface_damage(o->surface, 0, 0, o->width, o->height);
    wl_surface_commit(o->surface);
    wl_display_flush(o->display);
    o->busy = 1;
}

int main(void) {
    signal(SIGTERM, on_signal);
    signal(SIGINT, on_signal);
    FILE *flag = fopen(ACTIVE_FLAG, "w");
    if (flag) { fputs("1\n", flag); fclose(flag); }

    /* Language follows ES via psvita-lang.py (dArkOS flycast/ps2 logic). */
    FILE *lf = fopen("/roms/vita3k/.ui-lang", "r");
    char lang[8] = { 0 };
    if (lf) { (void)fgets(lang, sizeof(lang), lf); fclose(lf); }
    if (strncmp(lang, "en", 2) == 0) {
        items = items_en;
        osd_title = "Vita3K Quick Settings";
        osd_hint = "D-pad select   A confirm   B back   (applies next boot)";
    }

    Osd o; memset(&o, 0, sizeof(o));
    const char *env;
    o.width = (env = getenv("OSD_W")) ? atoi(env) : 1024;
    o.height = (env = getenv("OSD_H")) ? atoi(env) : 768;
    o.stride = o.width;
    o.size = o.stride * o.height * 4;

    o.display = wl_display_connect(NULL);
    if (!o.display) { fprintf(stderr, "osd: no Wayland display\n"); goto fail; }
    struct wl_registry *reg = wl_display_get_registry(o.display);
    wl_registry_add_listener(reg, &registry_listener, &o);
    wl_display_roundtrip(o.display);
    if (!o.compositor || !o.shm || !o.wm_base) {
        fprintf(stderr, "osd: missing compositor/shm/xdg_wm_base\n"); goto fail;
    }

    FT_Library ft;
    if (FT_Init_FreeType(&ft) == 0) {
        for (int i = 0; fonts[i]; i++)
            if (FT_New_Face(ft, fonts[i], 0, &o.face) == 0) break;
        if (o.face) FT_Set_Pixel_Sizes(o.face, 0, 24);
    }

    int shm_fd = shm_open("/vita3k-osd-buffer", O_CREAT | O_RDWR, 0600);
    if (shm_fd < 0) { perror("shm_open"); goto fail; }
    if (ftruncate(shm_fd, o.size) < 0) { perror("ftruncate"); goto fail; }
    o.pixels = mmap(NULL, o.size, PROT_READ | PROT_WRITE, MAP_SHARED, shm_fd, 0);
    if (o.pixels == MAP_FAILED) { perror("mmap"); goto fail; }
    struct wl_shm_pool *pool = wl_shm_create_pool(o.shm, shm_fd, o.size);
    o.buffer = wl_shm_pool_create_buffer(pool, 0, o.width, o.height,
                                         o.stride * 4, WL_SHM_FORMAT_ARGB8888);
    wl_buffer_add_listener(o.buffer, &buffer_listener, &o);
    shm_unlink("/vita3k-osd-buffer");

    o.surface = wl_compositor_create_surface(o.compositor);
    o.xdg_surface = xdg_wm_base_get_xdg_surface(o.wm_base, o.surface);
    xdg_surface_add_listener(o.xdg_surface, &xdg_surface_listener, &o);
    struct xdg_toplevel *top = xdg_surface_get_toplevel(o.xdg_surface);
    xdg_toplevel_add_listener(top, &toplevel_listener, &o);
    xdg_toplevel_set_title(top, "Vita3K OSD");
    xdg_toplevel_set_app_id(top, "vita3k-osd");
    /* kiosk-shell only maps fullscreen toplevels (Vita3K's game window does
     * the same through Qt's showFullScreen()). */
    xdg_toplevel_set_fullscreen(top, NULL);
    wl_surface_commit(o.surface);
    wl_display_roundtrip(o.display);

    int pad = find_pad();
    int wlfd = wl_display_get_fd(o.display);
    int dirty = 1;

    while (!stop_flag && !o.done) {
        fd_set fds; FD_ZERO(&fds);
        FD_SET(wlfd, &fds);
        int maxfd = wlfd;
        if (pad >= 0) { FD_SET(pad, &fds); if (pad > maxfd) maxfd = pad; }
        struct timeval tv = { 0, 40000 };
        int ready = select(maxfd + 1, &fds, NULL, NULL, &tv);
        if (ready < 0) break;
        if (FD_ISSET(wlfd, &fds)) wl_display_dispatch(o.display);
        if (pad >= 0 && FD_ISSET(pad, &fds)) {
            struct input_event ie;
            while (read(pad, &ie, sizeof(ie)) == (ssize_t)sizeof(ie)) {
                if (ie.type != EV_KEY || ie.value != 1) continue;
                if (ie.code == OSD_BTN_DOWN) { o.sel = (o.sel + 1) % ITEM_COUNT; dirty = 1; }
                else if (ie.code == OSD_BTN_UP) { o.sel = (o.sel + ITEM_COUNT - 1) % ITEM_COUNT; dirty = 1; }
                else if (ie.code == OSD_BTN_A) { write_pending(&items[o.sel]); o.done = 1; }
                else if (ie.code == OSD_BTN_B) { o.done = 1; }
            }
        }
        if (dirty) { recommit(&o); if (!o.busy) dirty = 0; }
    }

    if (pad >= 0) close(pad);
    wl_display_flush(o.display);
    wl_display_disconnect(o.display);
    unlink(ACTIVE_FLAG);
    return 0;

fail:
    unlink(ACTIVE_FLAG);
    return 1;
}
