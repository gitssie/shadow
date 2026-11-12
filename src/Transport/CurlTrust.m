#import "CurlTrust.h"
#import <Security/Security.h>
#include <math.h>
#include <time.h>

static double SHDWCurlTrustNow(void) {
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return now.tv_sec + now.tv_nsec / 1e9;
}

@interface NSURLProtectionSpace (SHDWCurlNativeTrust)
- (void)_setServerTrust:(SecTrustRef)trust;
@end

static NSURLProtectionSpace *SHDWCurlProtectionSpaceCreate(NSString *host, NSInteger port, SecTrustRef trust) {
    NSURLProtectionSpace *space = [[NSURLProtectionSpace alloc] initWithHost:host port:port protocol:@"https"
        realm:nil authenticationMethod:NSURLAuthenticationMethodServerTrust];
    if (![space respondsToSelector:@selector(_setServerTrust:)]) return nil;
    [space _setServerTrust:trust];
    return space.serverTrust == trust ? space : nil;
}

@interface SHDWCurlChallengeSender : NSObject <NSURLAuthenticationChallengeSender> {
    SecTrustRef _trust;
}
@property(nonatomic, strong) NSCondition *condition;
@property(nonatomic) BOOL answered;
@property(nonatomic) BOOL accepted;
- (instancetype)initWithTrust:(SecTrustRef)trust;
- (void)finish:(BOOL)accepted;
- (BOOL)waitForResponse:(NSTimeInterval)timeout cancelled:(BOOL (^)(void))cancelled;
@end
@implementation SHDWCurlChallengeSender
- (instancetype)initWithTrust:(SecTrustRef)trust {
    if ((self = [super init])) { _trust = (SecTrustRef)CFRetain(trust); _condition = [NSCondition new]; }
    return self;
}
- (void)dealloc { if (_trust) CFRelease(_trust); }
- (void)finish:(BOOL)accepted {
    [self.condition lock];
    if (!self.answered) { self.answered = YES; self.accepted = accepted; [self.condition broadcast]; }
    [self.condition unlock];
}
// Native NSURLSession continues default trust handling for nil credentials and rejected spaces.
// This sender exists only after chain and hostname validation has succeeded.
- (void)useCredential:(NSURLCredential *)credential forAuthenticationChallenge:(NSURLAuthenticationChallenge *)challenge {
    (void)challenge;
    (void)credential;
    [self finish:YES];
}
- (void)continueWithoutCredentialForAuthenticationChallenge:(NSURLAuthenticationChallenge *)challenge { (void)challenge; [self finish:YES]; }
- (void)cancelAuthenticationChallenge:(NSURLAuthenticationChallenge *)challenge { (void)challenge; [self finish:NO]; }
- (void)performDefaultHandlingForAuthenticationChallenge:(NSURLAuthenticationChallenge *)challenge { (void)challenge; [self finish:YES]; }
- (void)rejectProtectionSpaceAndContinueWithChallenge:(NSURLAuthenticationChallenge *)challenge { (void)challenge; [self finish:YES]; }
- (BOOL)waitForResponse:(NSTimeInterval)timeout cancelled:(BOOL (^)(void))cancelled {
    double deadline = SHDWCurlTrustNow() + (isfinite(timeout) && timeout > 0 ? MIN(timeout, 300.0) : 0);
    for (;;) {
        // Never invoke caller code while holding the response lock.
        BOOL stop = cancelled && cancelled();
        [self.condition lock];
        double remaining = deadline - SHDWCurlTrustNow();
        if (stop || remaining <= 0) {
            self.answered = YES; self.accepted = NO;
        }
        if (self.answered) {
            BOOL result = self.accepted;
            [self.condition unlock];
            return result;
        }
        [self.condition waitUntilDate:[NSDate dateWithTimeIntervalSinceNow:MIN(remaining, 0.1)]];
        [self.condition unlock];
    }
}
@end

BOOL SHDWCurlEvaluateTrust(NSArray<NSData *> *DERCertificates, NSString *host, NSInteger port,
                          NSTimeInterval timeout,
                          void (^sendChallenge)(NSURLAuthenticationChallenge *), BOOL (^cancelled)(void)) {
    if (![DERCertificates isKindOfClass:NSArray.class] || !DERCertificates.count || DERCertificates.count > 32 ||
        ![host isKindOfClass:NSString.class] || !host.length || host.length > 255 ||
        [host rangeOfCharacterFromSet:NSCharacterSet.controlCharacterSet].location != NSNotFound ||
        port <= 0 || port > 65535 || !isfinite(timeout) || timeout <= 0 || !sendChallenge || (cancelled && cancelled())) return NO;
    NSMutableArray *chain = [NSMutableArray new];
    for (id data in DERCertificates) {
        if (![data isKindOfClass:NSData.class] || ![data length] || [data length] > 1024 * 1024) return NO;
        SecCertificateRef certificate = SecCertificateCreateWithData(NULL, (__bridge CFDataRef)data);
        if (!certificate) return NO;
        [chain addObject:CFBridgingRelease(certificate)];
    }
    SecPolicyRef policy = SecPolicyCreateSSL(true, (__bridge CFStringRef)host);
    if (!policy) return NO;
    SecTrustRef trust = NULL;
    OSStatus status = SecTrustCreateWithCertificates((__bridge CFArrayRef)chain, policy, &trust);
    CFRelease(policy);
    if (status != errSecSuccess || !trust) { if (trust) CFRelease(trust); return NO; }
    SecTrustSetNetworkFetchAllowed(trust, false);
    BOOL valid = SecTrustEvaluateWithError(trust, NULL);
    if (!valid || (cancelled && cancelled())) { CFRelease(trust); return NO; }
    NSURLProtectionSpace *space = SHDWCurlProtectionSpaceCreate(host, port, trust);
    if (!space) { CFRelease(trust); return NO; }
    SHDWCurlChallengeSender *sender = [[SHDWCurlChallengeSender alloc] initWithTrust:trust];
    NSURLAuthenticationChallenge *challenge = [[NSURLAuthenticationChallenge alloc] initWithProtectionSpace:space
        proposedCredential:[NSURLCredential credentialForTrust:trust] previousFailureCount:0 failureResponse:nil error:nil sender:sender];
    CFRelease(trust);
    if (cancelled && cancelled()) { [sender finish:NO]; return NO; }
    sendChallenge(challenge);
    return [sender waitForResponse:timeout cancelled:cancelled];
}
