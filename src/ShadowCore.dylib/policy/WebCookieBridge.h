#pragma once
#import <Foundation/Foundation.h>

static inline NSHTTPCookie *SHDWWebCookieBridgeSelect(NSHTTPCookie *candidate,
        NSHTTPCookieStorage *storage, NSString *bundleID) {
    if (![bundleID isEqualToString:@"lt.manodrabuziai.fr"] || ![candidate.name isEqualToString:@"datadome"]) return candidate;
    NSURL *url = [NSURL URLWithString:@"https://www.vinted.com/"];
    for (NSHTTPCookie *cookie in [storage cookiesForURL:url]) {
        if ([cookie.name isEqualToString:@"datadome"]) return cookie;
    }
    return candidate;
}
