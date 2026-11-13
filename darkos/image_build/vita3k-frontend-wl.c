/* pocketAis handheld frontend for Vita3K-Plus -- pure Wayland client.
 *
 * Replaces the desktop Qt app-list window when Vita3K is opened without a ROM
 * (ES -> Ports -> Vita3K). The Qt window is a table with a menu bar, toolbar
 * and log dock; this is a full-screen grid of large game cards driven directly
 * by the gamepad evdev node, so no Weston keyboard focus or mouse is needed.
 *
 *   d-pad / left stick  move selection
 *   A (304)             launch the selected title  -> exec Vita3K -F -r TITLEID
 *   Home (316)          open the native Qt GUI for advanced settings
 *   B (305)             return to EmulationStation
 *   Select+Start        return to EmulationStation
 *
 * The frontend is started by psvita-launch.sh in place of Vita3K's GUI, so it
 * inherits the whole session environment (LD_PRELOAD, WSI layer, Wayland
 * socket). vita3k-pad.py stands down while .frontend-active exists; the flag is
 * removed just before exec, so the in-game OSD and Select+Start work again.
 *
 * Build (on device):
 *   wayland-scanner client-header xdg-shell.xml xdg-shell-client-protocol.h
 *   wayland-scanner private-code  xdg-shell.xml xdg-shell-protocol.c
 *   gcc -O2 -Wall -o vita3k-frontend vita3k-frontend-wl.c xdg-shell-protocol.c \
 *       -I. $(pkg-config --cflags --libs wayland-client freetype2 libpng) -lrt -lm
 */
#define _POSIX_C_SOURCE 200809L
#include <wayland-client.h>
#include "xdg-shell-client-protocol.h"
#include <ft2build.h>
#include FT_FREETYPE_H
#include <png.h>

#include <ctype.h>
#include <dirent.h>
#include <fcntl.h>
#include <linux/input.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/select.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define APP_ROOT "/roms/vita3k/fs/ux0/app"
#define FRONTEND_FLAG "/roms/vita3k/.frontend-active"
#define UI_LANG_FILE "/roms/vita3k/.ui-lang"
#define VITA3K_SH "/opt/vita3k/vita3k.sh"
#define PAD_NAME "rk3562-joystick"

#define PAD_A 304
#define PAD_B 305
#define PAD_SELECT 314
#define PAD_START 315
#define BTN_HOME 316
#define DP_UP 544
#define DP_DOWN 545
#define DP_LEFT 546
#define DP_RIGHT 547
#define STICK_DEAD 12000
#define STICK_RESET 6000
#define NAV_COOLDOWN_MS 150
#define STICK_COOLDOWN_MS 240

#define ICON_SIZE 128
#define MAX_GAMES 64
#define COLS 3
#define ROWS 2
#define PER_PAGE (COLS * ROWS)
#define CARD_W 300
#define CARD_H 240
#define CARD_GAP 16
#define GRID_X 46
#define GRID_Y 108

static const char *fonts[] = {
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    NULL
};

typedef struct {
    char id[24];
    char title[128];
    uint32_t icon[ICON_SIZE * ICON_SIZE];
    int has_icon;
    int special;
} Game;

typedef enum { ACT_NONE = 0, ACT_GAME, ACT_NATIVE, ACT_EXIT } Action;

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
    Action action;
    char launch_id[24];
} Ui;

static Game games[MAX_GAMES];
static int ngames = 0;
static int english = 0;
static volatile sig_atomic_t stop_flag = 0;
static void on_signal(int s) { (void)s; stop_flag = 1; }

static const char *title_text(void) { return english ? "Vita3K games" : "Vita3K 游戏库"; }
static const char *hint_text(void) {
    return english
        ? "D-pad / stick  select      A  launch      B  back      Home  settings      Select+Start  quit"
        : "方向键 / 摇杆 选择     A 启动     B 返回     Home 高级设置     Select+Start 退出";
}
static const char *settings_title(void) { return english ? "Advanced settings" : "高级设置"; }
static const char *settings_sub(void) {
    return english ? "Native Vita3K interface" : "原生 Vita3K 界面";
}
static const char *empty_text(void) {
    return english ? "No installed games yet" : "还没有已安装的游戏";
}
static const char *empty_sub(void) {
    return english
        ? "Put a .zip / .vpk in /roms/psvita and launch it once from ES"
        : "把 .zip / .vpk 放到 /roms/psvita，在 ES 里启动一次即可安装";
}

/* ---------------------------------------------------------------- helpers */
static double now_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec * 1000.0 + (double)ts.tv_nsec / 1e6;
}

static uint16_t le16(const unsigned char *p) { return (uint16_t)(p[0] | (p[1] << 8)); }
static uint32_t le32(const unsigned char *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

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

/* ------------------------------------------------------------- game scan */
static int read_sfo_title(const char *path, char *out, size_t cap) {
    FILE *f = fopen(path, "rb");
    if (!f) return 0;
    unsigned char buf[65536];
    memset(buf, 0, sizeof(buf));
    size_t n = fread(buf, 1, sizeof(buf), f);
    fclose(f);
    if (n < 20 || buf[1] != 'P' || buf[2] != 'S' || buf[3] != 'F') return 0;
    uint32_t koff = le32(buf + 8), doff = le32(buf + 12), entries = le32(buf + 16);
    if (koff >= n || doff >= n || entries > 512) return 0;
    for (uint32_t i = 0; i < entries; i++) {
        size_t pos = 20 + (size_t)i * 16;
        if (pos + 16 > n) break;
        uint16_t key_off = le16(buf + pos);
        uint32_t used = le32(buf + pos + 4);
        uint32_t data_off = le32(buf + pos + 12);
        size_t kp = koff + key_off, dp = doff + data_off;
        if (kp >= n || dp >= n || dp + used > n) continue;
        if (strcmp((const char *)buf + kp, "TITLE") != 0) continue;
        size_t len = used < cap - 1 ? used : cap - 1;
        memcpy(out, buf + dp, len);
        out[len] = 0;
        return 1;
    }
    return 0;
}

static int load_png_scaled(const char *path, uint32_t *out, int ow, int oh) {
    png_image img;
    memset(&img, 0, sizeof(img));
    img.version = PNG_IMAGE_VERSION;
    if (!png_image_begin_read_from_file(&img, path)) return 0;
    img.format = PNG_FORMAT_RGBA;
    size_t sz = PNG_IMAGE_SIZE(img);
    unsigned char *tmp = malloc(sz);
    if (!tmp) { png_image_free(&img); return 0; }
    if (!png_image_finish_read(&img, NULL, tmp, 0, NULL)) {
        free(tmp); png_image_free(&img); return 0;
    }
    int w = (int)img.width, h = (int)img.height;
    if (w > 0 && h > 0) {
        for (int y = 0; y < oh; y++) {
            int sy = y * h / oh;
            for (int x = 0; x < ow; x++) {
                int sx = x * w / ow;
                const unsigned char *p = tmp + ((size_t)sy * w + sx) * 4;
                out[y * ow + x] = ((uint32_t)p[3] << 24) |
                                 ((uint32_t)p[0] << 16) |
                                 ((uint32_t)p[1] << 8) | p[2];
            }
        }
    }
    free(tmp);
    png_image_free(&img);
    return 1;
}

static int cmp_game(const void *a, const void *b) {
    const Game *x = a, *y = b;
    if (x->special != y->special) return x->special - y->special;
    return strcmp(x->title, y->title);
}

static void scan_games(void) {
    DIR *d = opendir(APP_ROOT);
    if (!d) return;
    struct dirent *de;
    while ((de = readdir(d)) != NULL && ngames < MAX_GAMES - 1) {
        const char *name = de->d_name;
        if (strlen(name) != 9 || strchr(name, '.')) continue;
        int valid = 1;
        for (int i = 0; i < 9; i++)
            if (!isalnum((unsigned char)name[i])) { valid = 0; break; }
        if (!valid) continue;
        char path[512];
        snprintf(path, sizeof(path), "%s/%s/sce_sys/param.sfo", APP_ROOT, name);
        Game *g = &games[ngames];
        memset(g, 0, sizeof(*g));
        snprintf(g->id, sizeof(g->id), "%s", name);
        if (!read_sfo_title(path, g->title, sizeof(g->title)) || !g->title[0])
            snprintf(g->title, sizeof(g->title), "%s", name);
        snprintf(path, sizeof(path), "%s/%s/sce_sys/icon0.png", APP_ROOT, name);
        g->has_icon = load_png_scaled(path, g->icon, ICON_SIZE, ICON_SIZE);
        ngames++;
    }
    closedir(d);
    qsort(games, ngames, sizeof(Game), cmp_game);
    Game *g = &games[ngames++];
    memset(g, 0, sizeof(*g));
    g->special = 1;
    snprintf(g->title, sizeof(g->title), "%s", settings_title());
    snprintf(g->id, sizeof(g->id), "native-gui");
}

/* ------------------------------------------------------------- rendering */
static void fill_rect(Ui *o, int x, int y, int w, int h, uint32_t color) {
    if (x < 0) { w += x; x = 0; }
    if (y < 0) { h += y; y = 0; }
    if (x + w > o->width) w = o->width - x;
    if (y + h > o->height) h = o->height - y;
    for (int j = 0; j < h; j++)
        for (int i = 0; i < w; i++)
            o->pixels[(y + j) * o->stride + x + i] = color;
}

static void blend_pixel(Ui *o, int x, int y, uint32_t src) {
    if (x < 0 || x >= o->width || y < 0 || y >= o->height) return;
    uint32_t a = src >> 24;
    if (!a) return;
    uint32_t *dst = &o->pixels[y * o->stride + x];
    if (a >= 250) { *dst = 0xFF000000u | (src & 0x00FFFFFFu); return; }
    unsigned int sr = (src >> 16) & 255, sg = (src >> 8) & 255, sb = src & 255;
    unsigned int dr = (*dst >> 16) & 255, dg = (*dst >> 8) & 255, db = *dst & 255;
    unsigned int r = (sr * a + dr * (255 - a)) / 255;
    unsigned int g = (sg * a + dg * (255 - a)) / 255;
    unsigned int b = (sb * a + db * (255 - a)) / 255;
    *dst = 0xFF000000u | (r << 16) | (g << 8) | b;
}

static void draw_text(Ui *o, const char *text, int x, int y, int size,
                      uint32_t color, int maxw) {
    if (!o->face) return;
    FT_Set_Pixel_Sizes(o->face, 0, size);
    const unsigned char *p = (const unsigned char *)text;
    int pen = 0; unsigned int cp; int n;
    while ((n = utf8_next(p, &cp)) > 0) {
        if (maxw > 0 && pen > maxw) break;
        if (FT_Load_Char(o->face, cp, FT_LOAD_RENDER) == 0) {
            FT_Bitmap *b = &o->face->glyph->bitmap;
            int gx = x + pen + o->face->glyph->bitmap_left;
            int gy = y + size - o->face->glyph->bitmap_top;
            for (int j = 0; j < (int)b->rows; j++) {
                for (int i = 0; i < (int)b->width; i++) {
                    unsigned char a = b->buffer[j * b->pitch + i];
                    if (a < 8) continue;
                    uint32_t src = (color & 0x00FFFFFFu) | ((uint32_t)a << 24);
                    blend_pixel(o, gx + i, gy + j, src);
                }
            }
            pen += o->face->glyph->advance.x >> 6;
        } else pen += size / 2;
        p += n;
    }
}

static void draw_icon(Ui *o, const uint32_t *icon, int x, int y, int w, int h) {
    for (int j = 0; j < h; j++)
        for (int i = 0; i < w; i++)
            blend_pixel(o, x + i, y + j, icon[j * ICON_SIZE + i]);
}

static void draw_card(Ui *o, int idx, int cx, int cy) {
    Game *g = &games[idx];
    int selected = (idx == o->sel);
    if (selected) {
        fill_rect(o, cx - 3, cy - 3, CARD_W + 6, CARD_H + 6, 0xFF2D7FF9u);
        fill_rect(o, cx, cy, CARD_W, CARD_H, 0xFF243A5Eu);
    } else {
        fill_rect(o, cx, cy, CARD_W, CARD_H, 0xFF1B2130u);
        fill_rect(o, cx, cy, CARD_W, 2, 0xFF2B3446u);
    }
    uint32_t fg = selected ? 0xFFFFFFFFu : 0xFFE8ECF4u;
    uint32_t sub = selected ? 0xFFCFE0FFu : 0xFF8E9AB0u;
    if (g->special) {
        draw_text(o, settings_title(), cx + 24, cy + 78, 30, fg, CARD_W - 48);
        draw_text(o, settings_sub(), cx + 24, cy + 130, 18, sub, CARD_W - 48);
        draw_text(o, "Vita3K", cx + 24, cy + 178, 20, sub, CARD_W - 48);
        return;
    }
    if (g->has_icon)
        draw_icon(o, g->icon, cx + (CARD_W - ICON_SIZE) / 2, cy + 14,
                  ICON_SIZE, ICON_SIZE);
    else
        draw_text(o, g->id, cx + 24, cy + 60, 24, fg, CARD_W - 48);
    draw_text(o, g->title, cx + 16, cy + 156, 22, fg, CARD_W - 32);
    draw_text(o, g->id, cx + 16, cy + 194, 17, sub, CARD_W - 32);
}

static void draw(Ui *o) {
    fill_rect(o, 0, 0, o->width, o->height, 0xFF0E1220u);
    fill_rect(o, 0, 0, o->width, 92, 0xFF151C2Cu);
    fill_rect(o, 0, 90, o->width, 2, 0xFF2D7FF9u);
    draw_text(o, title_text(), 46, 16, 36, 0xFFFFFFFFu, 0);
    char count[96];
    int installed = ngames - 1;
    if (english) snprintf(count, sizeof(count), "%d installed", installed);
    else snprintf(count, sizeof(count), "已安装 %d 个游戏", installed);
    draw_text(o, count, 46, 58, 20, 0xFF9AA6BCu, 0);

    int page = o->sel / PER_PAGE;
    int pages = (ngames + PER_PAGE - 1) / PER_PAGE;
    char pgbuf[32];
    snprintf(pgbuf, sizeof(pgbuf), "%d / %d", page + 1, pages);
    draw_text(o, pgbuf, o->width - 130, 30, 22, 0xFF9AA6BCu, 0);

    if (installed == 0) {
        draw_text(o, empty_text(), 46, 200, 30, 0xFFFFFFFFu, 0);
        draw_text(o, empty_sub(), 46, 250, 20, 0xFF9AA6BCu, 0);
    }
    for (int k = 0; k < PER_PAGE; k++) {
        int idx = page * PER_PAGE + k;
        if (idx >= ngames) break;
        int col = k % COLS, row = k / COLS;
        int cx = GRID_X + col * (CARD_W + CARD_GAP);
        int cy = GRID_Y + row * (CARD_H + CARD_GAP);
        draw_card(o, idx, cx, cy);
    }

    fill_rect(o, 0, o->height - 84, o->width, 84, 0xFF151C2Cu);
    fill_rect(o, 0, o->height - 84, o->width, 2, 0xFF2B3446u);
    draw_text(o, hint_text(), 46, o->height - 62, 20, 0xFFBEC8DAu, 0);
}

/* --------------------------------------------------------------- wayland */
static void buffer_release(void *data, struct wl_buffer *b) {
    (void)b; ((Ui *)data)->busy = 0;
}
static const struct wl_buffer_listener buffer_listener = { .release = buffer_release };

static void xdg_configure(void *data, struct xdg_surface *s, uint32_t serial) {
    Ui *o = data;
    xdg_surface_ack_configure(s, serial);
    if (!o->buffer) return;
    draw(o);
    wl_surface_attach(o->surface, o->buffer, 0, 0);
    wl_surface_damage(o->surface, 0, 0, o->width, o->height);
    wl_surface_commit(o->surface);
    wl_display_flush(o->display);  /* requests made in a callback need a flush */
    o->busy = 1;
}
static const struct xdg_surface_listener xdg_surface_listener = { .configure = xdg_configure };

static void toplevel_configure(void *data, struct xdg_toplevel *t,
                               int32_t w, int32_t h, struct wl_array *states) {
    (void)data; (void)t; (void)w; (void)h; (void)states;
}
static void toplevel_close(void *data, struct xdg_toplevel *t) {
    (void)t; ((Ui *)data)->done = 1;
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
    Ui *o = data;
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

static void recommit(Ui *o) {
    if (o->busy) return;
    draw(o);
    wl_surface_attach(o->surface, o->buffer, 0, 0);
    wl_surface_damage(o->surface, 0, 0, o->width, o->height);
    wl_surface_commit(o->surface);
    wl_display_flush(o->display);
    o->busy = 1;
}

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

static void move_sel(Ui *o, int delta, double *last_nav) {
    int next = o->sel + delta;
    if (next < 0 || next >= ngames) return;
    o->sel = next;
    *last_nav = now_ms();
}

int main(void) {
    signal(SIGTERM, on_signal);
    signal(SIGINT, on_signal);
    FILE *flag = fopen(FRONTEND_FLAG, "w");
    if (flag) { fputs("1\n", flag); fclose(flag); }

    FILE *lf = fopen(UI_LANG_FILE, "r");
    char lang[8] = { 0 };
    if (lf) { (void)fgets(lang, sizeof(lang), lf); fclose(lf); }
    english = (strncmp(lang, "en", 2) == 0);
    scan_games();

    Ui o; memset(&o, 0, sizeof(o));
    const char *env;
    o.width = (env = getenv("FRONTEND_W")) ? atoi(env) : 1024;
    o.height = (env = getenv("FRONTEND_H")) ? atoi(env) : 768;
    o.stride = o.width;
    o.size = o.stride * o.height * 4;

    o.display = wl_display_connect(NULL);
    if (!o.display) { fprintf(stderr, "frontend: no Wayland display\n"); goto fail; }
    struct wl_registry *reg = wl_display_get_registry(o.display);
    wl_registry_add_listener(reg, &registry_listener, &o);
    wl_display_roundtrip(o.display);
    if (!o.compositor || !o.shm || !o.wm_base) {
        fprintf(stderr, "frontend: missing compositor/shm/xdg_wm_base\n"); goto fail;
    }

    FT_Library ft;
    if (FT_Init_FreeType(&ft) == 0) {
        for (int i = 0; fonts[i]; i++)
            if (FT_New_Face(ft, fonts[i], 0, &o.face) == 0) break;
    }

    int shm_fd = shm_open("/vita3k-frontend-buffer", O_CREAT | O_RDWR, 0600);
    if (shm_fd < 0) { perror("shm_open"); goto fail; }
    if (ftruncate(shm_fd, o.size) < 0) { perror("ftruncate"); goto fail; }
    o.pixels = mmap(NULL, o.size, PROT_READ | PROT_WRITE, MAP_SHARED, shm_fd, 0);
    if (o.pixels == MAP_FAILED) { perror("mmap"); goto fail; }
    struct wl_shm_pool *pool = wl_shm_create_pool(o.shm, shm_fd, o.size);
    o.buffer = wl_shm_pool_create_buffer(pool, 0, o.width, o.height,
                                         o.stride * 4, WL_SHM_FORMAT_ARGB8888);
    wl_buffer_add_listener(o.buffer, &buffer_listener, &o);
    shm_unlink("/vita3k-frontend-buffer");

    o.surface = wl_compositor_create_surface(o.compositor);
    o.xdg_surface = xdg_wm_base_get_xdg_surface(o.wm_base, o.surface);
    xdg_surface_add_listener(o.xdg_surface, &xdg_surface_listener, &o);
    struct xdg_toplevel *top = xdg_surface_get_toplevel(o.xdg_surface);
    xdg_toplevel_add_listener(top, &toplevel_listener, &o);
    xdg_toplevel_set_title(top, "Vita3K Handheld Frontend");
    xdg_toplevel_set_app_id(top, "vita3k-frontend");
    xdg_toplevel_set_fullscreen(top, NULL);
    wl_surface_commit(o.surface);
    wl_display_roundtrip(o.display);

    int pad = find_pad();
    int wlfd = wl_display_get_fd(o.display);
    int dirty = 1;
    int select_down = 0;
    int stick_active[2] = { 0, 0 };
    double last_nav = 0.0;
    double start_ms = now_ms();

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
                if (ie.type == EV_KEY) {
                    int code = ie.code, val = ie.value;
                    if (code == PAD_SELECT) select_down = (val > 0);
                    if (code == PAD_START && val == 1 && select_down) {
                        o.action = ACT_EXIT; o.done = 1; break;
                    }
                    if (val == 0) continue;   /* key release */
                    /* Ignore the hotkey that may still be bouncing right after
                     * the daemon launched us. */
                    if (now_ms() - start_ms < 700.0 &&
                        (code == PAD_A || code == PAD_B || code == BTN_HOME))
                        continue;
                    if (val == 1 && code == PAD_A) {
                        if (games[o.sel].special) o.action = ACT_NATIVE;
                        else {
                            o.action = ACT_GAME;
                            snprintf(o.launch_id, sizeof(o.launch_id), "%s", games[o.sel].id);
                        }
                        o.done = 1; break;
                    }
                    if (val == 1 && code == PAD_B) { o.action = ACT_EXIT; o.done = 1; break; }
                    if (val == 1 && code == BTN_HOME) { o.action = ACT_NATIVE; o.done = 1; break; }
                    if (val != 1 && val != 2) continue;
                    double now = now_ms();
                    if (now - last_nav < NAV_COOLDOWN_MS) continue;
                    if (code == DP_LEFT) move_sel(&o, -1, &last_nav);
                    else if (code == DP_RIGHT) move_sel(&o, 1, &last_nav);
                    else if (code == DP_UP) move_sel(&o, -COLS, &last_nav);
                    else if (code == DP_DOWN) move_sel(&o, COLS, &last_nav);
                    else continue;
                    dirty = 1;
                } else if (ie.type == EV_ABS && (ie.code == 0 || ie.code == 1)) {
                    int ax = ie.code;
                    int v = ie.value;
                    if (v > -STICK_RESET && v < STICK_RESET) { stick_active[ax] = 0; continue; }
                    if (v > -STICK_DEAD && v < STICK_DEAD) continue;
                    if (stick_active[ax]) continue;
                    double now = now_ms();
                    if (now - last_nav < STICK_COOLDOWN_MS) continue;
                    if (ax == 0) move_sel(&o, v > 0 ? 1 : -1, &last_nav);
                    else move_sel(&o, v > 0 ? COLS : -COLS, &last_nav);
                    stick_active[ax] = 1;
                    dirty = 1;
                }
            }
        }
        if (dirty) { recommit(&o); if (!o.busy) dirty = 0; }
    }

    if (pad >= 0) close(pad);
    wl_display_flush(o.display);
    wl_display_disconnect(o.display);
    unlink(FRONTEND_FLAG);

    if (o.action == ACT_GAME)
        execl(VITA3K_SH, "vita3k.sh", "-F", "-r", o.launch_id, (char *)NULL);
    else if (o.action == ACT_NATIVE)
        execl(VITA3K_SH, "vita3k.sh", "-F", (char *)NULL);
    if (o.action == ACT_GAME || o.action == ACT_NATIVE)
        perror("frontend: execl Vita3K");
    return 0;

fail:
    unlink(FRONTEND_FLAG);
    return 1;
}
