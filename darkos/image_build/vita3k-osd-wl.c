/* pocketAis quick settings OSD -- pure Wayland, controller-driven.
 *
 * Two modes:
 *   default  : opened DURING A GAME by vita3k-pad.py (console-detect -t key).
 *              A settings grid; A writes .osd-pending, applied on game exit.
 *   --setup : opened by psvita-launch.sh BEFORE the game boots when the PS Vita
 *              firmware (fs/vs0) or font package (fs/sa0) is missing. Vita3K's
 *              own modal "Missing Firmware" / welcome dialog is never shown.
 *              Adds "install firmware" / "install font" cards that open a
 *              gamepad-driven file browser over /roms; picking a .PUP writes
 *              .osd-action and the launcher installs it headlessly, then boots
 *              the game as soon as both components are present.
 *
 * Build (on device):
 *   wayland-scanner client-header xdg-shell.xml xdg-shell-client-protocol.h
 *   wayland-scanner private-code  xdg-shell.xml xdg-shell-protocol.c
 *   gcc -O2 -Wall -o vita3k-osd vita3k-osd-wl.c xdg-shell-protocol.c -I. \
 *       $(pkg-config --cflags --libs wayland-client freetype2) -lrt -lm
 */
#define _POSIX_C_SOURCE 200809L
#include <wayland-client.h>
#include "xdg-shell-client-protocol.h"
#include <ft2build.h>
#include FT_FREETYPE_H

#include <ctype.h>
#include <dirent.h>
#include <fcntl.h>
#include <linux/input.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/select.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define ACTIVE_FLAG "/roms/vita3k/.osd-active"
#define PENDING_FILE "/roms/vita3k/.osd-pending"
#define ACTION_FILE "/roms/vita3k/.osd-action"
#define UI_LANG_FILE "/roms/vita3k/.ui-lang"
#define VITA_FS "/roms/vita3k/fs"
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

#define COLS 2
#define CARD_W 460
#define CARD_H 96
#define CARD_GAP 14
#define GRID_X 44
#define GRID_Y 112
#define MENU_ROWS 5
#define MENU_PER_PAGE (COLS * MENU_ROWS)
#define BROWSER_ROWS 9
#define BROWSER_ROW_H 48
#define BROWSER_Y 140
#define MAX_ENTRIES 512

static const char *fonts[] = {
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    NULL
};

typedef struct {
    const char *label;
    const char *sub;
    const char *key;
    const char *value;
    const char *action;   /* setup-only: launch / install / region / quit */
    const char *kind;     /* install/region cards: preinstall / firmware / font */
} MenuItem;

/* Android's InitialSetupScreen uses three FirmwareCards with a StatusBadge:
 * Installed (green), Missing (orange) and Optional (grey) for the pre-install
 * package. Mirror that here so the state is readable at a glance. */
static int dir_has_files(const char *path);
static int component_status(const char *kind);
static char region_sub[160];
static int region_idx = 0;
static const char *region_codes[] = {
    "zh-hans-cn", "zh-hant-hk", "en-us", "ja-jp", "ko-kr", NULL
};
static const char *region_labels_zh[] = {
    "简体中文", "繁體中文", "English (US)", "日本語", "한국어"
};
static const char *region_labels_en[] = {
    "Chinese (Simplified)", "Chinese (Traditional)", "English (US)",
    "Japanese", "Korean"
};

static const MenuItem items_normal_zh[] = {
    { "返回游戏", "继续当前游戏", NULL, NULL, NULL, NULL },
    { "系统语言 · 简体中文", "sys-lang = 11", "sys-lang", "11", NULL, NULL },
    { "系统语言 · English", "sys-lang = 1", "sys-lang", "1", NULL, NULL },
    { "画面倍率 · 1x 流畅", "resolution-multiplier = 1", "resolution-multiplier", "1", NULL, NULL },
    { "画面倍率 · 2x 清晰", "resolution-multiplier = 2", "resolution-multiplier", "2", NULL, NULL },
    { "性能 · 省电 2 核", "guest-cores = 2", "guest-cores", "2", NULL, NULL },
    { "性能 · 平衡 3 核", "guest-cores = 3", "guest-cores", "3", NULL, NULL },
};
static const MenuItem items_setup_zh[] = {
    { "继续启动游戏", "忽略缺失并启动", NULL, NULL, "launch", NULL },
    { "预装包（可选）", "选择 PSP2UPDAT.PUP", NULL, NULL, "install", "preinstall" },
    { "主固件", "选择 PSP2UPDAT.PUP", NULL, NULL, "install", "firmware" },
    { "字体包", "选择字体包 .PUP", NULL, NULL, "install", "font" },
    { "固件下载区域", "按 A 切换区域", NULL, NULL, "region", NULL },
    { "系统语言 · 简体中文", "sys-lang = 11", "sys-lang", "11", NULL, NULL },
    { "系统语言 · English", "sys-lang = 1", "sys-lang", "1", NULL, NULL },
    { "画面倍率 · 1x 流畅", "resolution-multiplier = 1", "resolution-multiplier", "1", NULL, NULL },
    { "画面倍率 · 2x 清晰", "resolution-multiplier = 2", "resolution-multiplier", "2", NULL, NULL },
    { "返回 ES", "退出到主界面", NULL, NULL, "quit", NULL },
};
static const MenuItem items_normal_en[] = {
    { "Resume", "Back to the game", NULL, NULL, NULL, NULL },
    { "System language · Chinese", "sys-lang = 11", "sys-lang", "11", NULL, NULL },
    { "System language · English", "sys-lang = 1", "sys-lang", "1", NULL, NULL },
    { "Resolution · 1x (fast)", "resolution-multiplier = 1", "resolution-multiplier", "1", NULL, NULL },
    { "Resolution · 2x (sharp)", "resolution-multiplier = 2", "resolution-multiplier", "2", NULL, NULL },
    { "Performance · Power save (2 cores)", "guest-cores = 2", "guest-cores", "2", NULL, NULL },
    { "Performance · Balanced (3 cores)", "guest-cores = 3", "guest-cores", "3", NULL, NULL },
};
static const MenuItem items_setup_en[] = {
    { "Launch game", "Start anyway", NULL, NULL, "launch", NULL },
    { "Pre-install package (optional)", "Pick a .PUP file", NULL, NULL, "install", "preinstall" },
    { "Main firmware", "Pick a .PUP file", NULL, NULL, "install", "firmware" },
    { "Font package", "Pick a .PUP file", NULL, NULL, "install", "font" },
    { "Firmware download region", "Press A to change", NULL, NULL, "region", NULL },
    { "System language · Chinese", "sys-lang = 11", "sys-lang", "11", NULL, NULL },
    { "System language · English", "sys-lang = 1", "sys-lang", "1", NULL, NULL },
    { "Resolution · 1x (fast)", "resolution-multiplier = 1", "resolution-multiplier", "1", NULL, NULL },
    { "Resolution · 2x (sharp)", "resolution-multiplier = 2", "resolution-multiplier", "2", NULL, NULL },
    { "Back to ES", "Quit to the menu", NULL, NULL, "quit", NULL },
};

static const MenuItem *items = items_normal_zh;
static int item_count = 7;
static int setup_mode = 0;
static int english = 0;

static const char *title_text = "Vita3K 快捷设置   Quick Settings";
static const char *sub_text = "设置将在下次启动游戏时生效";
static const char *hint_text = "方向键 / 摇杆 选择     A 确认     B 返回游戏";
static const char *browser_hint = "方向键 / 摇杆 选择     A 打开 / 确认     B 上级     Home 返回菜单";

typedef struct { char name[256]; char path[768]; int is_dir; } Entry;
static Entry entries[MAX_ENTRIES];
static int nentries = 0;
static int bsel = 0;
static char cwd[512] = "/roms";
static char browse_root[512] = "/roms";
static char install_kind[16] = "firmware";

typedef enum { VIEW_MENU = 0, VIEW_BROWSER = 1 } View;

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
    View view;
} Ui;

static volatile sig_atomic_t stop_flag = 0;
static void on_signal(int s) { (void)s; stop_flag = 1; }

static double now_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec * 1000.0 + (double)ts.tv_nsec / 1e6;
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
            for (int j = 0; j < (int)b->rows; j++)
                for (int i = 0; i < (int)b->width; i++) {
                    unsigned char a = b->buffer[j * b->pitch + i];
                    if (a < 8) continue;
                    uint32_t src = (color & 0x00FFFFFFu) | ((uint32_t)a << 24);
                    blend_pixel(o, gx + i, gy + j, src);
                }
            pen += o->face->glyph->advance.x >> 6;
        } else pen += size / 2;
        p += n;
    }
}

static uint32_t group_color(int idx) {
    if (!setup_mode) {
        if (idx == 0) return 0xFF8E9AB0u;
        if (idx <= 2) return 0xFFA78BF0u;
        if (idx <= 4) return 0xFF5082DCu;
        return 0xFF5DCAA5u;
    }
    if (idx == 0) return 0xFF5DCAA5u;   /* launch */
    if (idx <= 3) return 0xFFEF9F27u;   /* three firmware cards */
    if (idx == 4) return 0xFFA78BF0u;   /* download region */
    if (idx <= 6) return 0xFFA78BF0u;   /* language */
    if (idx <= 8) return 0xFF5082DCu;   /* resolution */
    return 0xFF8E9AB0u;                 /* back to ES */
}

/* 1 = installed, 0 = missing, 2 = missing but optional, -1 = not a component */
static int component_status(const char *kind) {
    if (!kind) return -1;
    if (!strcmp(kind, "preinstall"))
        return dir_has_files(VITA_FS "/pd0") ? 1 : 2;
    if (!strcmp(kind, "firmware"))
        return dir_has_files(VITA_FS "/vs0") ? 1 : 0;
    if (!strcmp(kind, "font"))
        return dir_has_files(VITA_FS "/sa0") ? 1 : 0;
    return -1;
}

static void region_apply(void) {
    if (region_idx < 0 || region_idx > 4) region_idx = 0;
    const char *name = english ? region_labels_en[region_idx] : region_labels_zh[region_idx];
    if (english)
        snprintf(region_sub, sizeof(region_sub), "Current: %s  (URL saved to file)", name);
    else
        snprintf(region_sub, sizeof(region_sub), "当前：%s  ·  官网链接已写入文件", name);
    FILE *idx = fopen("/roms/vita3k/.firmware-region", "w");
    if (idx) { fprintf(idx, "%d\n", region_idx); fclose(idx); }
    FILE *f = fopen("/roms/vita3k/firmware-download-url.txt", "w");
    if (f) {
        fprintf(f, "https://www.playstation.com/%s/support/hardware/psvita/system-software/\n",
                region_codes[region_idx]);
        fclose(f);
    }
}

static void draw_card(Ui *o, int idx, int cx, int cy) {
    int selected = (idx == o->sel);
    int installed = component_status(items[idx].kind) == 1;
    if (selected) {
        fill_rect(o, cx - 3, cy - 3, CARD_W + 6, CARD_H + 6, 0xFF2D7FF9u);
        fill_rect(o, cx, cy, CARD_W, CARD_H, 0xFF243A5Eu);
    } else {
        fill_rect(o, cx, cy, CARD_W, CARD_H, 0xFF1B2130u);
        fill_rect(o, cx, cy, CARD_W, 2, 0xFF2B3446u);
    }
    fill_rect(o, cx + 12, cy + 14, 6, CARD_H - 28, group_color(idx));
    uint32_t fg = selected ? 0xFFFFFFFFu : 0xFFE8ECF4u;
    uint32_t sub = selected ? 0xFFCFE0FFu : 0xFF8E9AB0u;
    if (installed && !selected) { fg = 0xFF9AA6BCu; sub = 0xFF6E7A90u; }
    int label_w = CARD_W - 50;
    if (items[idx].kind) label_w = CARD_W - 160;   /* leave room for the badge */
    draw_text(o, items[idx].label, cx + 30, cy + 12, 24, fg, label_w);
    const char *st = items[idx].sub;
    if (items[idx].action && !strcmp(items[idx].action, "region")) st = region_sub;
    if (installed && items[idx].kind)
        st = english ? "Installed - no action needed" : "已安装，无需操作";
    draw_text(o, st, cx + 30, cy + 52, 17, sub, CARD_W - 50);

    /* StatusBadge, mirroring InitialSetupScreen.kt on Android. */
    int status = component_status(items[idx].kind);
    if (status >= 0) {
        const char *txt = status == 1 ? (english ? "Installed" : "已安装")
                        : status == 2 ? (english ? "Optional" : "可选")
                                      : (english ? "Missing" : "缺失");
        uint32_t col = status == 1 ? 0xFF1B8A5Au
                     : status == 2 ? 0xFF8E9AB0u : 0xFFEF9F27u;
        int bx = cx + CARD_W - 118, by = cy + 18;
        fill_rect(o, bx, by, 104, 34, 0xFF121826u);
        fill_rect(o, bx + 10, by + 13, 8, 8, col);
        draw_text(o, txt, bx + 26, by + 5, 17, col, 74);
    }
}

static int dir_has_files(const char *path) {
    DIR *d = opendir(path);
    if (!d) return 0;
    struct dirent *de;
    int found = 0;
    while ((de = readdir(d)) != NULL) {
        if (de->d_name[0] == '.') continue;
        found = 1; break;
    }
    closedir(d);
    return found;
}

static void setup_subtitle(char *buf, size_t cap) {
    int fw = dir_has_files(VITA_FS "/vs0");
    int font = dir_has_files(VITA_FS "/sa0");
    if (english) {
        if (fw && font) snprintf(buf, cap, "Firmware and font package are installed");
        else if (!fw && !font) snprintf(buf, cap, "Missing: main firmware + font package");
        else if (!fw) snprintf(buf, cap, "Missing: main firmware");
        else snprintf(buf, cap, "Missing: font package");
    } else {
        if (fw && font) snprintf(buf, cap, "固件与字体已齐全，可直接启动游戏");
        else if (!fw && !font) snprintf(buf, cap, "缺少：主固件 + 字体包，请先安装");
        else if (!fw) snprintf(buf, cap, "缺少：主固件，请先安装");
        else snprintf(buf, cap, "缺少：字体包，请先安装");
    }
}

static void draw_menu(Ui *o) {
    char sub[160];
    if (setup_mode) setup_subtitle(sub, sizeof(sub));
    else snprintf(sub, sizeof(sub), "%s", sub_text);
    fill_rect(o, 0, 0, o->width, 96, 0xFF151C2Cu);
    fill_rect(o, 0, 94, o->width, 2, 0xFF2D7FF9u);
    draw_text(o, title_text, 44, 12, 33, 0xFFFFFFFFu, 0);
    draw_text(o, sub, 44, 56, 19, setup_mode ? 0xFFEFB96Au : 0xFF9AA6BCu, 0);
    for (int k = 0; k < MENU_PER_PAGE && k < item_count; k++) {
        int col = k % COLS, row = k / COLS;
        int cx = GRID_X + col * (CARD_W + CARD_GAP);
        int cy = GRID_Y + row * (CARD_H + CARD_GAP);
        draw_card(o, k, cx, cy);
    }
}

static int entry_cmp(const void *a, const void *b) {
    const Entry *x = a, *y = b;
    if (x->is_dir != y->is_dir) return y->is_dir - x->is_dir;
    return strcmp(x->name, y->name);
}

static int pup_file(const char *name) {
    const char *dot = strrchr(name, '.');
    if (!dot) return 0;
    return strcasecmp(dot, ".pup") == 0;
}

static int dir_has_pup(const char *path) {
    DIR *d = opendir(path);
    if (!d) return 0;
    struct dirent *de;
    int found = 0;
    while ((de = readdir(d)) != NULL) {
        if (de->d_name[0] == '.' || !pup_file(de->d_name)) continue;
        char full[768];
        snprintf(full, sizeof(full), "%s/%s", path, de->d_name);
        struct stat st;
        if (stat(full, &st) == 0 && S_ISREG(st.st_mode)) { found = 1; break; }
    }
    closedir(d);
    return found;
}

static void load_dir(const char *path) {
    /* path may BE cwd: copy first, snprintf with the same buffer is UB. */
    char local[512];
    snprintf(local, sizeof(local), "%s", path);
    nentries = 0;
    bsel = 0;
    snprintf(cwd, sizeof(cwd), "%s", local);
    DIR *d = opendir(local);
    if (!d) return;
    struct dirent *de;
    while ((de = readdir(d)) != NULL && nentries < MAX_ENTRIES) {
        if (de->d_name[0] == '.') continue;
        char full[768];
        snprintf(full, sizeof(full), "%s/%s", local, de->d_name);
        struct stat st;
        int is_dir = (stat(full, &st) == 0 && S_ISDIR(st.st_mode));
        if (!is_dir && !pup_file(de->d_name)) continue;
        Entry *e = &entries[nentries++];
        size_t nlen = strlen(de->d_name);
        if (nlen > sizeof(e->name) - 2) nlen = sizeof(e->name) - 2;
        memcpy(e->name, de->d_name, nlen);
        e->name[nlen] = 0;
        if (is_dir) strcat(e->name, "/");
        snprintf(e->path, sizeof(e->path), "%s", full);
        e->is_dir = is_dir;
    }
    closedir(d);
    qsort(entries, nentries, sizeof(Entry), entry_cmp);
}

static void parent_dir(char *out, size_t cap) {
    snprintf(out, cap, "%s", cwd);
    char *slash = strrchr(out, '/');
    if (!slash || slash == out) { snprintf(out, cap, "/"); return; }
    *slash = 0;
    if (strncmp(out, browse_root, strlen(browse_root)) != 0)
        snprintf(out, cap, "%s", browse_root);
}

static void draw_browser(Ui *o) {
    fill_rect(o, 0, 0, o->width, 96, 0xFF151C2Cu);
    fill_rect(o, 0, 94, o->width, 2, 0xFFEF9F27u);
    const char *t;
    if (!strcmp(install_kind, "font"))
        t = english ? "Select font package (.PUP)" : "选择字体包 (.PUP)";
    else if (!strcmp(install_kind, "preinstall"))
        t = english ? "Select pre-install package (.PUP)" : "选择预装包 (.PUP)";
    else
        t = english ? "Select main firmware (.PUP)" : "选择主固件 (.PUP)";
    draw_text(o, t, 44, 12, 32, 0xFFFFFFFFu, 0);
    draw_text(o, cwd, 44, 56, 18, 0xFF9AA6BCu, 0);
    int page = bsel / BROWSER_ROWS;
    int first = page * BROWSER_ROWS;
    if (nentries == 0)
        draw_text(o, english ? "No folders or .PUP files here" : "此目录没有子目录或 .PUP 文件",
                  44, BROWSER_Y + 20, 22, 0xFF9AA6BCu, 0);
    for (int k = 0; k < BROWSER_ROWS && first + k < nentries; k++) {
        int idx = first + k;
        int y = BROWSER_Y + k * BROWSER_ROW_H;
        if (idx == bsel) fill_rect(o, 44, y, o->width - 88, 44, 0xFF2D7FF9u);
        else fill_rect(o, 44, y, o->width - 88, 44, 0xFF1B2130u);
        uint32_t fg = idx == bsel ? 0xFFFFFFFFu : 0xFFE8ECF4u;
        draw_text(o, entries[idx].name, 60, y + 8, 22, fg, o->width - 130);
    }
    char pg[32];
    int pages = nentries ? (nentries + BROWSER_ROWS - 1) / BROWSER_ROWS : 1;
    snprintf(pg, sizeof(pg), "%d / %d", page + 1, pages);
    draw_text(o, pg, o->width - 130, 56, 18, 0xFF9AA6BCu, 0);
}

static void draw(Ui *o) {
    fill_rect(o, 0, 0, o->width, o->height, 0xFF0E1220u);
    if (o->view == VIEW_BROWSER) draw_browser(o);
    else draw_menu(o);
    fill_rect(o, 0, o->height - 84, o->width, 84, 0xFF151C2Cu);
    fill_rect(o, 0, o->height - 84, o->width, 2, 0xFF2B3446u);
    draw_text(o, o->view == VIEW_BROWSER ? browser_hint : hint_text,
              44, o->height - 60, 20, 0xFFBEC8DAu, 0);
}

static void write_pending(const MenuItem *it) {
    if (!it->key) return;
    FILE *f = fopen(PENDING_FILE, "a");
    if (!f) return;
    fprintf(f, "%s=%s\n", it->key, it->value);
    fclose(f);
}

static void write_action(const char *text) {
    FILE *f = fopen(ACTION_FILE, "w");
    if (!f) return;
    fputs(text, f);
    fputc('\n', f);
    fclose(f);
}

static void write_install(const char *kind, const char *path) {
    FILE *f = fopen(ACTION_FILE, "w");
    if (!f) return;
    fprintf(f, "install\t%s\t%s\n", kind, path);
    fclose(f);
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
    wl_display_flush(o->display);
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

static void move_menu(Ui *o, int delta, double *last_nav) {
    int next = o->sel + delta;
    if (next < 0 || next >= item_count) return;
    o->sel = next;
    *last_nav = now_ms();
}

static void move_browser(int delta, double *last_nav) {
    if (nentries <= 0) return;
    int next = bsel + delta;
    if (next < 0) next = 0;
    if (next >= nentries) next = nentries - 1;
    bsel = next;
    *last_nav = now_ms();
}

int main(int argc, char **argv) {
    for (int i = 1; i < argc; i++)
        if (!strcmp(argv[i], "--setup")) setup_mode = 1;

    signal(SIGTERM, on_signal);
    signal(SIGINT, on_signal);
    FILE *flag = fopen(ACTIVE_FLAG, "w");
    if (flag) { fputs("1\n", flag); fclose(flag); }
    unlink(ACTION_FILE);

    FILE *lf = fopen(UI_LANG_FILE, "r");
    char lang[8] = { 0 };
    if (lf) { (void)fgets(lang, sizeof(lang), lf); fclose(lf); }
    english = (strncmp(lang, "en", 2) == 0);
    if (english) {
        items = setup_mode ? items_setup_en : items_normal_en;
        title_text = setup_mode ? "Vita3K first-run setup" : "Vita3K Quick Settings";
        sub_text = "Changes apply the next time you launch a game";
        hint_text = "D-pad / stick select     A confirm     B resume game";
        browser_hint = "D-pad / stick select     A open / confirm     B parent     Home back";
    } else {
        items = setup_mode ? items_setup_zh : items_normal_zh;
        title_text = setup_mode ? "Vita3K 首次设置   First-run setup" : "Vita3K 快捷设置   Quick Settings";
    }
    item_count = setup_mode ? 10 : 7;
    if (setup_mode) {
        FILE *ri = fopen("/roms/vita3k/.firmware-region", "r");
        if (ri) {
            int n = -1;
            if (fscanf(ri, "%d", &n) == 1 && n >= 0 && n <= 4) region_idx = n;
            fclose(ri);
        }
        region_apply();   /* restore badge text + download URL file */
    }
    const char *root = getenv("V3K_BROWSE_ROOT");
    snprintf(browse_root, sizeof(browse_root), "%s", root ? root : "/roms");
    snprintf(cwd, sizeof(cwd), "%s", browse_root);
    /* Firmware PUPs are shipped/downloaded into /roms/vita3k; open there so
     * the user does not have to walk the whole /roms tree first. */
    if (!root && dir_has_pup("/roms/vita3k"))
        snprintf(cwd, sizeof(cwd), "/roms/vita3k");

    Ui o; memset(&o, 0, sizeof(o));
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
    xdg_toplevel_set_title(top, "Vita3K Quick Settings");
    xdg_toplevel_set_app_id(top, "vita3k-osd");
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
                    if (code == PAD_START && val == 1 && select_down) { o.done = 1; break; }
                    if (val == 0) continue;
                    if (now_ms() - start_ms < 600.0 &&
                        (code == PAD_A || code == PAD_B || code == BTN_HOME))
                        continue;
                    if (o.view == VIEW_BROWSER) {
                        if (val == 1 && code == PAD_A) {
                            if (nentries > 0 && bsel < nentries) {
                                Entry *e = &entries[bsel];
                                if (e->is_dir) load_dir(e->path);
                                else { write_install(install_kind, e->path); o.done = 1; break; }
                            }
                            dirty = 1;
                        } else if (val == 1 && code == PAD_B) {
                            char parent[512];
                            parent_dir(parent, sizeof(parent));
                            if (strcmp(parent, cwd) == 0) o.view = VIEW_MENU;
                            else load_dir(parent);
                            dirty = 1;
                        } else if (val == 1 && code == BTN_HOME) {
                            o.view = VIEW_MENU; dirty = 1;
                        } else if (val == 1 || val == 2) {
                            if (now_ms() - last_nav < NAV_COOLDOWN_MS) continue;
                            if (code == DP_UP) move_browser(-1, &last_nav);
                            else if (code == DP_DOWN) move_browser(1, &last_nav);
                            else if (code == DP_LEFT) move_browser(-BROWSER_ROWS, &last_nav);
                            else if (code == DP_RIGHT) move_browser(BROWSER_ROWS, &last_nav);
                            else continue;
                            dirty = 1;
                        }
                        continue;
                    }
                    if (val == 1 && code == PAD_A) {
                        const MenuItem *it = &items[o.sel];
                        if (setup_mode) {
                            if (it->action && !strcmp(it->action, "install")) {
                                /* Android hides the Install button once the
                                 * component is present: do the same here. */
                                if (component_status(it->kind) == 1) {
                                    dirty = 1; continue;
                                }
                                snprintf(install_kind, sizeof(install_kind), "%s", it->kind);
                                load_dir(cwd); o.view = VIEW_BROWSER; dirty = 1;
                                continue;
                            }
                            if (it->action && !strcmp(it->action, "region")) {
                                region_idx = (region_idx + 1) % 5;
                                region_apply();
                                dirty = 1; continue;
                            }
                            if (it->action) write_action(it->action);
                            else { write_pending(it); write_action("menu"); }
                        } else {
                            write_pending(it);
                        }
                        o.done = 1; break;
                    }
                    if (val == 1 && (code == PAD_B || code == BTN_HOME)) {
                        if (setup_mode) write_action("menu");
                        o.done = 1; break;
                    }
                    if (val != 1 && val != 2) continue;
                    if (now_ms() - last_nav < NAV_COOLDOWN_MS) continue;
                    if (code == DP_LEFT) move_menu(&o, -1, &last_nav);
                    else if (code == DP_RIGHT) move_menu(&o, 1, &last_nav);
                    else if (code == DP_UP) move_menu(&o, -COLS, &last_nav);
                    else if (code == DP_DOWN) move_menu(&o, COLS, &last_nav);
                    else continue;
                    dirty = 1;
                } else if (ie.type == EV_ABS && (ie.code == 0 || ie.code == 1)) {
                    int ax = ie.code, v = ie.value;
                    if (v > -STICK_RESET && v < STICK_RESET) { stick_active[ax] = 0; continue; }
                    if (v > -STICK_DEAD && v < STICK_DEAD) continue;
                    if (stick_active[ax]) continue;
                    if (now_ms() - last_nav < STICK_COOLDOWN_MS) continue;
                    if (o.view == VIEW_BROWSER) {
                        if (ax == 0) move_browser(v > 0 ? 1 : -1, &last_nav);
                        else move_browser(v > 0 ? BROWSER_ROWS : -BROWSER_ROWS, &last_nav);
                    } else {
                        if (ax == 0) move_menu(&o, v > 0 ? 1 : -1, &last_nav);
                        else move_menu(&o, v > 0 ? COLS : -COLS, &last_nav);
                    }
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
    unlink(ACTIVE_FLAG);
    return 0;

fail:
    unlink(ACTIVE_FLAG);
    return 1;
}
