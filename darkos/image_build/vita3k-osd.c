/* pocketAis Vita3K in-game OSD overlay.
 *
 * SDL2 window (Wayland) + FreeType for CJK text. Keyboard focus under
 * kiosk-shell is unreliable, so menu navigation reads the gamepad evdev node
 * directly instead of relying on Weston key delivery.
 *
 * Hotkey that OPENS this overlay is owned by vida3k-pad.py and derived from
 * `console-detect -t`. While the OSD is up, the mapper stops forwarding pad
 * keys (see /roms/vita3k/.osd-active), so the game cannot receive them.
 *
 * Build: gcc -O2 -Wall -o vita3k-osd vita3k-osd.c $(pkg-config --cflags --libs sdl2 freetype2)
 */
#define _POSIX_C_SOURCE 200809L
#include <SDL2/SDL.h>
#include <ft2build.h>
#include FT_FREETYPE_H

#include <fcntl.h>
#include <linux/input.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/select.h>
#include <unistd.h>

#define ACTIVE_FLAG "/roms/vita3k/.osd-active"
#define PENDING_FILE "/roms/vita3k/.osd-pending"
#define PAD_NAME "rk3562-joystick"
#define OSD_BTN_UP 544
#define OSD_BTN_DOWN 545
#define OSD_BTN_A 304
#define OSD_BTN_B 305

typedef struct {
    const char *label;
    const char *key;   /* NULL = resume */
    const char *value;
} MenuItem;

static const MenuItem items[] = {
    { "返回游戏  /  Resume", NULL, NULL },
    { "系统语言  简体中文", "sys-lang", "11" },
    { "系统语言  English", "sys-lang", "1" },
    { "画面倍率  1x 流畅", "resolution-multiplier", "1" },
    { "画面倍率  2x 清晰", "resolution-multiplier", "2" },
    { "性能  省电 2 核", "guest-cores", "2" },
    { "性能  平衡 3 核", "guest-cores", "3" },
};
#define ITEM_COUNT ((int)(sizeof(items) / sizeof(items[0])))

static volatile sig_atomic_t stop = 0;
static void on_signal(int s) { (void)s; stop = 1; }

static const char *font_candidates[] = {
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    NULL
};

/* Decode one UTF-8 code point. Returns bytes consumed. */
static int utf8_next(const unsigned char *s, unsigned int *cp) {
    if (!*s) { *cp = 0; return 0; }
    if (s[0] < 0x80) { *cp = s[0]; return 1; }
    if ((s[0] & 0xE0) == 0xC0 && s[1]) {
        *cp = ((s[0] & 0x1F) << 6) | (s[1] & 0x3F); return 2;
    }
    if ((s[0] & 0xF0) == 0xE0 && s[1] && s[2]) {
        *cp = ((s[0] & 0x0F) << 12) | ((s[1] & 0x3F) << 6) | (s[2] & 0x3F); return 3;
    }
    if ((s[0] & 0xF8) == 0xF0 && s[1] && s[2] && s[3]) {
        *cp = ((s[0] & 0x07) << 18) | ((s[1] & 0x3F) << 12) |
              ((s[2] & 0x3F) << 6) | (s[3] & 0x3F); return 4;
    }
    *cp = '?'; return 1;
}

/* Render a UTF-8 string to an ARGB8888 texture. */
static SDL_Texture *text_texture(SDL_Renderer *r, FT_Face face, const char *text,
                                 SDL_Color color, int *out_w, int *out_h) {
    const unsigned char *p = (const unsigned char *)text;
    int pen = 0, height = 30;
    unsigned int cp;
    int n;

    /* measure */
    const unsigned char *q = p;
    while ((n = utf8_next(q, &cp)) > 0) {
        if (FT_Load_Char(face, cp, FT_LOAD_DEFAULT) == 0)
            pen += face->glyph->advance.x >> 6;
        else
            pen += 12;
        q += n;
    }
    int w = pen + 4;
    if (w < 4) w = 4;
    SDL_Surface *surf = SDL_CreateRGBSurfaceWithFormat(0, w, height, 32, SDL_PIXELFORMAT_ARGB8888);
    if (!surf) return NULL;
    SDL_SetSurfaceBlendMode(surf, SDL_BLENDMODE_BLEND);

    pen = 0;
    while ((n = utf8_next(p, &cp)) > 0) {
        if (FT_Load_Char(face, cp, FT_LOAD_RENDER) == 0) {
            FT_Bitmap *b = &face->glyph->bitmap;
            int xoff = face->glyph->bitmap_left;
            int yoff = 24 - face->glyph->bitmap_top;
            for (int y = 0; y < (int)b->rows; y++) {
                for (int x = 0; x < (int)b->width; x++) {
                    int px = pen + xoff + x, py = yoff + y;
                    if (px < 0 || px >= w || py < 0 || py >= height) continue;
                    unsigned char a = b->buffer[y * b->pitch + x];
                    if (!a) continue;
                    Uint32 pix = ((Uint32)a << 24) |
                                 ((Uint32)color.r << 16) |
                                 ((Uint32)color.g << 8) | color.b;
                    ((Uint32 *)surf->pixels)[py * w + px] = pix;
                }
            }
            pen += face->glyph->advance.x >> 6;
        } else {
            pen += 12;
        }
        p += n;
    }
    SDL_Texture *tex = SDL_CreateTextureFromSurface(r, surf);
    SDL_FreeSurface(surf);
    *out_w = w; *out_h = height;
    return tex;
}

static int find_pad(void) {
    char path[64], name[128];
    /* Highest event number first: uinput clones (used by the verify harness)
     * appear after the real pad, matching evdev.list_devices() ordering. */
    for (int i = 31; i >= 0; i--) {
        snprintf(path, sizeof(path), "/dev/input/event%d", i);
        int fd = open(path, O_RDONLY | O_NONBLOCK);
        if (fd < 0) continue;
        memset(name, 0, sizeof(name));
        if (ioctl(fd, EVIOCGNAME(sizeof(name) - 1), name) >= 0 &&
            strcmp(name, PAD_NAME) == 0)
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

int main(void) {
    signal(SIGTERM, on_signal);
    signal(SIGINT, on_signal);

    FILE *flag = fopen(ACTIVE_FLAG, "w");
    if (flag) { fputs("1\n", flag); fclose(flag); }

    if (SDL_Init(SDL_INIT_VIDEO) != 0) {
        fprintf(stderr, "osd: SDL_Init: %s\n", SDL_GetError());
        unlink(ACTIVE_FLAG); return 1;
    }
    SDL_SetHint(SDL_HINT_VIDEODRIVER, "wayland");

    FT_Library ft;
    FT_Face face = NULL;
    if (FT_Init_FreeType(&ft) == 0) {
        for (int i = 0; font_candidates[i]; i++) {
            if (FT_New_Face(ft, font_candidates[i], 0, &face) == 0) break;
        }
        if (face) FT_Set_Pixel_Sizes(face, 0, 24);
    }

    SDL_Rect display = { 0, 0, 960, 544 };
    SDL_GetDisplayBounds(0, &display);
    SDL_Window *win = SDL_CreateWindow("Vita3K OSD",
        SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED,
        display.w, display.h,
        SDL_WINDOW_SHOWN | SDL_WINDOW_BORDERLESS | SDL_WINDOW_ALWAYS_ON_TOP);
    if (!win) {
        fprintf(stderr, "osd: window: %s\n", SDL_GetError());
        unlink(ACTIVE_FLAG); return 1;
    }
    SDL_SetWindowOpacity(win, 0.94f);
    SDL_RaiseWindow(win);
    SDL_SetWindowInputFocus(win);

    SDL_Renderer *r = SDL_CreateRenderer(win, -1, SDL_RENDERER_SOFTWARE);
    if (!r) r = SDL_CreateRenderer(win, -1, 0);
    if (!r) {
        fprintf(stderr, "osd: renderer: %s\n", SDL_GetError());
        unlink(ACTIVE_FLAG); return 1;
    }
    SDL_SetRenderDrawBlendMode(r, SDL_BLENDMODE_BLEND);

    int pad = find_pad();
    int sel = 0, dirty = 1, done = 0;

    while (!stop && !done) {
        SDL_Event ev;
        while (SDL_PollEvent(&ev)) {
            if (ev.type == SDL_QUIT) done = 1;
            else if (ev.type == SDL_KEYDOWN) {
                switch (ev.key.keysym.sym) {
                case SDLK_UP: sel = (sel + ITEM_COUNT - 1) % ITEM_COUNT; dirty = 1; break;
                case SDLK_DOWN: sel = (sel + 1) % ITEM_COUNT; dirty = 1; break;
                case SDLK_RETURN: case SDLK_KP_ENTER:
                    write_pending(&items[sel]); done = 1; break;
                case SDLK_ESCAPE: done = 1; break;
                default: break;
                }
            }
        }

        if (pad >= 0) {
            fd_set fds; FD_ZERO(&fds); FD_SET(pad, &fds);
            struct timeval tv = { 0, 40000 };
            if (select(pad + 1, &fds, NULL, NULL, &tv) > 0 && FD_ISSET(pad, &fds)) {
                struct input_event ie;
                while (read(pad, &ie, sizeof(ie)) == (ssize_t)sizeof(ie)) {
                    if (ie.type != EV_KEY || ie.value != 1) continue;
                    if (ie.code == OSD_BTN_DOWN) { sel = (sel + 1) % ITEM_COUNT; dirty = 1; }
                    else if (ie.code == OSD_BTN_UP) { sel = (sel + ITEM_COUNT - 1) % ITEM_COUNT; dirty = 1; }
                    else if (ie.code == OSD_BTN_A) { write_pending(&items[sel]); done = 1; }
                    else if (ie.code == OSD_BTN_B) { done = 1; }
                }
            }
        } else {
            SDL_Delay(40);
        }

        if (!dirty) continue;
        dirty = 0;

        SDL_SetRenderDrawColor(r, 8, 10, 16, 220);
        SDL_RenderClear(r);

        int card_w = display.w - 80, card_h = 90 + ITEM_COUNT * 46;
        if (card_h > display.h - 40) card_h = display.h - 40;
        SDL_Rect card = { 40, (display.h - card_h) / 2, card_w, card_h };
        SDL_SetRenderDrawColor(r, 24, 28, 38, 240);
        SDL_RenderFillRect(r, &card);
        SDL_SetRenderDrawColor(r, 80, 130, 220, 255);
        SDL_RenderDrawRect(r, &card);

        SDL_Color white = { 255, 255, 255, 255 };
        SDL_Color dim = { 190, 195, 205, 255 };
        SDL_Color blue = { 120, 180, 255, 255 };
        if (face) {
            int tw, th;
            SDL_Texture *title = text_texture(r, face, "Vita3K 快捷设置  Quick Settings", white, &tw, &th);
            if (title) {
                SDL_Rect dst = { card.x + 28, card.y + 16, tw, th };
                SDL_RenderCopy(r, title, NULL, &dst);
                SDL_DestroyTexture(title);
            }
        }
        for (int i = 0; i < ITEM_COUNT; i++) {
            SDL_Rect row = { card.x + 16, card.y + 62 + i * 46, card.w - 32, 40 };
            if (i == sel) {
                SDL_SetRenderDrawColor(r, 45, 127, 249, 255);
                SDL_RenderFillRect(r, &row);
            }
            if (face) {
                int tw, th;
                SDL_Texture *t = text_texture(r, face, items[i].label,
                                              i == sel ? white : dim, &tw, &th);
                if (t) {
                    SDL_Rect dst = { row.x + 16, row.y + 4, tw, th };
                    SDL_RenderCopy(r, t, NULL, &dst);
                    SDL_DestroyTexture(t);
                }
            }
            (void)blue;
        }
        SDL_RenderPresent(r);
    }

    if (pad >= 0) close(pad);
    if (r) SDL_DestroyRenderer(r);
    if (win) SDL_DestroyWindow(win);
    if (face) FT_Done_Face(face);
    SDL_Quit();
    unlink(ACTIVE_FLAG);
    return 0;
}
