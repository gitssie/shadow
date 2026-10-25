// Decode the property-list types used in DER entitlement dictionaries.
// Bounds and work limits apply even when the surrounding Mach-O is well formed.
typedef struct { const uint8_t *cursor; const uint8_t *end; NSUInteger nodes; } EntitlementDER;
static void DERElement(EntitlementDER *reader, uint8_t *tag, EntitlementDER *body) {
    Require(reader->cursor < reader->end && ++reader->nodes <= 32768, @"Invalid DER signed entitlements");
    *tag = *reader->cursor++;
    Require(reader->cursor < reader->end && (*tag & 0x1f) != 0x1f, @"Invalid DER signed entitlements");
    NSUInteger length = *reader->cursor++;
    if (length & 0x80) {
        NSUInteger count = length & 0x7f; length = 0;
        Require(count && count <= sizeof(NSUInteger) && (NSUInteger)(reader->end - reader->cursor) >= count && *reader->cursor, @"Invalid DER signed entitlements");
        for (NSUInteger i = 0; i < count; i++) { Require(length <= (NSUIntegerMax >> 8), @"Invalid DER signed entitlements"); length = (length << 8) | *reader->cursor++; }
        Require(length >= 128, @"Invalid DER signed entitlements");
    }
    Require(length <= (NSUInteger)(reader->end - reader->cursor), @"Invalid DER signed entitlements");
    *body = (EntitlementDER){reader->cursor, reader->cursor + length, reader->nodes}; reader->cursor += length;
}
static id DERValue(EntitlementDER *reader, NSUInteger depth) {
    Require(depth <= 32, @"Invalid DER signed entitlements");
    uint8_t tag; EntitlementDER body; DERElement(reader, &tag, &body);
    NSUInteger length = (NSUInteger)(body.end - body.cursor);
    if (tag == 0x0c) {
        NSString *value = [[NSString alloc] initWithBytes:body.cursor length:length encoding:NSUTF8StringEncoding];
        Require(value != nil, @"Invalid DER signed entitlements"); return value;
    }
    if (tag == 0x01) { Require(length == 1, @"Invalid DER signed entitlements"); return @(*body.cursor != 0); }
    if (tag == 0x02) {
        Require(length && length <= 8, @"Invalid DER signed entitlements");
        uint64_t value = (*body.cursor & 0x80) ? UINT64_MAX : 0;
        for (NSUInteger i = 0; i < length; i++) value = (value << 8) | body.cursor[i];
        return @((int64_t)value);
    }
    if (tag == 0x04) return [NSData dataWithBytes:body.cursor length:length];
    if (tag == 0x30) {
        NSMutableArray *values = [NSMutableArray new];
        while (body.cursor < body.end) [values addObject:DERValue(&body, depth + 1)];
        reader->nodes = body.nodes; return values;
    }
    Require(tag == 0x31, @"Unsupported DER signed entitlement type");
    NSMutableDictionary *values = [NSMutableDictionary new];
    while (body.cursor < body.end) {
        uint8_t pairTag; EntitlementDER pair; DERElement(&body, &pairTag, &pair);
        Require(pairTag == 0x30, @"Invalid DER signed entitlements");
        id key = DERValue(&pair, depth + 1);
        Require([key isKindOfClass:NSString.class] && !values[key], @"Invalid DER signed entitlements");
        id value = DERValue(&pair, depth + 1);
        Require(pair.cursor == pair.end, @"Invalid DER signed entitlements");
        values[key] = value; body.nodes = pair.nodes;
    }
    reader->nodes = body.nodes; return values;
}
static NSDictionary *DEREntitlements(const uint8_t *bytes, NSUInteger length) {
    Require(length && length <= 2 * 1024 * 1024, @"Invalid DER signed entitlements");
    EntitlementDER reader = {bytes, bytes + length, 0}; id result = DERValue(&reader, 0);
    Require(reader.cursor == reader.end && [result isKindOfClass:NSDictionary.class], @"Invalid DER signed entitlements"); return result;
}
