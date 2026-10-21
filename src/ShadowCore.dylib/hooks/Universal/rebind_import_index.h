#ifndef SHDW_REBIND_IMPORT_INDEX_H
#define SHDW_REBIND_IMPORT_INDEX_H
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <limits.h>

/* The header must belong to a live, dyld-validated image for this call's
 * duration. No portable C API can establish mapping lifetime from a pointer.
 * All metadata offsets are checked against their declared mapped segments.
 * A zero return requires the caller to retain every rule. Positive matches
 * are conservative: an indirect-table entry need not name an active slot. */
static uint32_t shdw_ri_u32(const void *p) {
    uint32_t v; memcpy(&v, p, sizeof(v)); return v;
}
static uint64_t shdw_ri_u64(const void *p) {
    uint64_t v; memcpy(&v, p, sizeof(v)); return v;
}
static int shdw_ri_range(uint64_t off, uint64_t len, uint64_t size) {
    return off <= size && len <= size - off;
}
static void shdw_ri_match(const char *s, size_t len,
                          const char *const *names, size_t count, uint64_t *mask) {
    for(size_t i = 0; i < count; i++) {
        size_t n = strlen(names[i]);
        if((n == len && memcmp(names[i], s, n) == 0) ||
           (len && s[0] == '_' && n == len - 1 && memcmp(names[i], s + 1, n) == 0))
            mask[i / 64] |= UINT64_C(1) << (i % 64);
    }
}
static int shdw_ri_leb(const unsigned char *b, size_t len, size_t *at) {
    /* Neither value nor sign is needed for a name-only index. */
    for(unsigned i = 0; i < 10; i++) {
        if(*at == len) return 0;
        if(!(b[(*at)++] & 0x80)) return 1;
    }
    return 0;
}
static int shdw_ri_bind(const unsigned char *b, size_t len,
                         const char *const *names, size_t count, uint64_t *mask) {
    size_t at = 0;
    while(at < len) {
        unsigned byte = b[at++], op = byte & 0xf0;
        switch(op) {
        case 0x00: /* DONE also separates entries in the lazy stream. */
        case 0x10: case 0x30: case 0x50: case 0x90: case 0xb0: break;
        case 0x40: {
            const unsigned char *end = memchr(b + at, 0, len - at);
            if(!end) return 0;
            shdw_ri_match((const char *)b + at, (size_t)(end - b) - at, names, count, mask);
            at = (size_t)(end - b) + 1;
            break;
        }
        case 0x20: case 0x60: case 0x70: case 0x80: case 0xa0:
            if(!shdw_ri_leb(b, len, &at)) return 0;
            break;
        case 0xc0:
            if(!shdw_ri_leb(b, len, &at) || !shdw_ri_leb(b, len, &at)) return 0;
            break;
        case 0xd0:
            if((byte & 15) == 0) { if(!shdw_ri_leb(b, len, &at)) return 0; }
            else if((byte & 15) != 1) return 0;
            break;
        default: return 0;
        }
    }
    return 1;
}
static const unsigned char *shdw_ri_file_range(const unsigned char *header,
    uint64_t basevm, uint64_t levm, uint64_t levmsize, uint64_t leoff,
    uint64_t lesize, uint64_t off, uint64_t len) {
    if(levm < basevm || off < leoff || !shdw_ri_range(off - leoff, len, lesize) ||
       !shdw_ri_range(off - leoff, len, levmsize)) return NULL;
    uint64_t delta = levm - basevm;
    if(delta > UINTPTR_MAX || off - leoff > UINTPTR_MAX - delta) return NULL;
    delta += off - leoff;
    if((uintptr_t)header > UINTPTR_MAX - delta ||
       len > UINTPTR_MAX - ((uintptr_t)header + delta)) return NULL;
    return (const unsigned char *)((uintptr_t)header + (uintptr_t)delta);
}

/* mask has (count + 63) / 64 words, count <= 320. On unknown, all supplied
 * bits are set even if parsing had already discovered some names. */
static int shdw_rebind_import_mask(const void *image,
    const char *const *names, size_t count, uint64_t *mask) {
    uint64_t found[5] = {0};
    if(count > 320 || (count && (!names || !mask))) return 0;
    for(size_t i = 0; i < (count + 63) / 64; i++) mask[i] = UINT64_MAX;
    for(size_t i = 0; i < count; i++) if(!names[i] || !names[i][0]) return 0;
    if(!image) return 0;
    const unsigned char *h = image;
    if(shdw_ri_u32(h) != 0xfeedfacf || (shdw_ri_u32(h + 24) & 0x80000000U)) return 0;
    uint32_t ncmds = shdw_ri_u32(h + 16), cmds = shdw_ri_u32(h + 20);
    if(cmds > 1024 * 1024 || ncmds > cmds / 8 ||
       (uintptr_t)h > UINTPTR_MAX - 32 - cmds) return 0;
    const unsigned char *sym = NULL, *dysym = NULL, *dyld = NULL;
    uint64_t basevm = 0, levm = 0, levmsize = 0, leoff = 0, lesize = 0;
    int havebase = 0, havele = 0;
    size_t at = 32, end = 32 + (size_t)cmds;
    for(uint32_t i = 0; i < ncmds; i++) {
        if(!shdw_ri_range(at, 8, end)) return 0;
        const unsigned char *c = h + at;
        uint32_t cmd = shdw_ri_u32(c), size = shdw_ri_u32(c + 4);
        if(size < 8 || (size & 7) || !shdw_ri_range(at, size, end)) return 0;
        if(cmd == 0x80000034) return 0; /* Chained metadata needs the original file. */
        if(cmd == 0x19) {
            if(size < 72 || !shdw_ri_range(72, (uint64_t)shdw_ri_u32(c + 64) * 80, size)) return 0;
            uint64_t vm = shdw_ri_u64(c + 24), vs = shdw_ri_u64(c + 32);
            uint64_t fo = shdw_ri_u64(c + 40), fs = shdw_ri_u64(c + 48);
            if(fs > vs || vm > UINT64_MAX - vs || fo > UINT64_MAX - fs) return 0;
            if(fo == 0 && fs >= end && (shdw_ri_u32(c + 60) & 1)) {
                if(havebase) return 0;
                basevm = vm; havebase = 1;
            }
            if(memcmp(c + 8, "__LINKEDIT\0\0\0\0\0\0", 16) == 0) {
                if(havele || !(shdw_ri_u32(c + 60) & 1)) return 0;
                levm = vm; levmsize = vs; leoff = fo; lesize = fs; havele = 1;
            }
        } else if(cmd == 0x2) {
            if(size < 24 || sym) return 0;
            sym = c;
        } else if(cmd == 0xb) {
            if(size < 80 || dysym) return 0;
            dysym = c;
        } else if(cmd == 0x22 || cmd == 0x80000022) {
            if(size < 48 || dyld) return 0;
            dyld = c;
        }
        at += size;
    }
    if(at != end || !havebase || !havele || (!dysym && !dyld)) return 0;
#define SHDW_RI_BYTES(off, len) shdw_ri_file_range(h, basevm, levm, levmsize, leoff, lesize, (off), (len))
    if(dysym) {
        uint32_t num = shdw_ri_u32(dysym + 60);
        if(num) {
            if(!sym) return 0;
            uint32_t nsym = shdw_ri_u32(sym + 12), strsize = shdw_ri_u32(sym + 20);
            const unsigned char *ind = SHDW_RI_BYTES(shdw_ri_u32(dysym + 56), (uint64_t)num * 4);
            const unsigned char *syms = SHDW_RI_BYTES(shdw_ri_u32(sym + 8), (uint64_t)nsym * 16);
            const unsigned char *strings = SHDW_RI_BYTES(shdw_ri_u32(sym + 16), strsize);
            if(!ind || !syms || !strings) return 0;
            for(uint32_t i = 0; i < num; i++) {
                uint32_t index = shdw_ri_u32(ind + (size_t)i * 4);
                if(index & 0xc0000000U) continue;
                if(index >= nsym) return 0;
                uint32_t off = shdw_ri_u32(syms + (size_t)index * 16);
                if(off >= strsize) return 0;
                const unsigned char *nul = memchr(strings + off, 0, strsize - off);
                if(!nul) return 0;
                shdw_ri_match((const char *)strings + off, (size_t)(nul - strings) - off, names, count, found);
            }
        }
    }
    if(dyld) {
        for(unsigned field = 16; field <= 32; field += 8) {
            uint32_t len = shdw_ri_u32(dyld + field + 4);
            if(!len) continue;
            const unsigned char *stream = SHDW_RI_BYTES(shdw_ri_u32(dyld + field), len);
            if(!stream || !shdw_ri_bind(stream, len, names, count, found)) return 0;
        }
    }
#undef SHDW_RI_BYTES
    for(size_t i = 0; i < (count + 63) / 64; i++) mask[i] = found[i];
    return 1;
}
#endif
