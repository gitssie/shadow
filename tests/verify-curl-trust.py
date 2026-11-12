"""Exercise production Security trust rejection and challenge sender lifecycle."""
from pathlib import Path
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation and Security")
root = Path(__file__).resolve().parents[1]
source = r'''
#include "CurlTrust.m"
#include <assert.h>
@interface NSURLProtectionSpace (SHDWTrustRoundTrip)
- (NSDictionary *)_webKitPropertyListData;
- (instancetype)_initWithWebKitPropertyListData:(NSDictionary *)data;
@end
static SHDWCurlChallengeSender *sender(SecTrustRef trust) { return [[SHDWCurlChallengeSender alloc] initWithTrust:trust]; }
static BOOL notCancelled(void) { return NO; }
int main(int argc, char **argv) { @autoreleasepool {
    assert(argc==2);
    NSData *der=[NSData dataWithContentsOfFile:@(argv[1])];assert(der);
    SecCertificateRef certificate=SecCertificateCreateWithData(NULL,(__bridge CFDataRef)der);assert(certificate);
    SecPolicyRef policy=SecPolicyCreateSSL(true,CFSTR("trust.test"));
    SecTrustRef trust=NULL,other=NULL;
    assert(SecTrustCreateWithCertificates(certificate,policy,&trust)==errSecSuccess);
    assert(SecTrustCreateWithCertificates(certificate,policy,&other)==errSecSuccess);
    CFRelease(policy);CFRelease(certificate);
    NSURLProtectionSpace *space=SHDWCurlProtectionSpaceCreate(@"trust.test",443,trust);
    assert(space && [space class]==NSURLProtectionSpace.class);
    CFRelease(trust);trust=space.serverTrust;
    assert(trust && SecTrustGetCertificateCount(trust)==1);
    assert([space.host isEqual:@"trust.test"] && space.port==443);
    assert([space.authenticationMethod isEqual:NSURLAuthenticationMethodServerTrust]);
    SHDWCurlChallengeSender *s=sender(trust);
    NSURLProtectionSpace *copiedSpace=[space copy];
    assert(copiedSpace.serverTrust==trust);
    if ([space respondsToSelector:@selector(_webKitPropertyListData)] &&
        [NSURLProtectionSpace instancesRespondToSelector:@selector(_initWithWebKitPropertyListData:)]) {
        NSDictionary *serialized=[space _webKitPropertyListData];
        assert(serialized[@"trust"] && CFGetTypeID((__bridge CFTypeRef)serialized[@"trust"])==SecTrustGetTypeID());
        NSURLProtectionSpace *decoded=[[NSURLProtectionSpace alloc] _initWithWebKitPropertyListData:serialized];
        assert(decoded.serverTrust && SecTrustGetCertificateCount(decoded.serverTrust)==1);
    }
    NSURLAuthenticationChallenge *challenge=[[NSURLAuthenticationChallenge alloc] initWithProtectionSpace:space
        proposedCredential:[NSURLCredential credentialForTrust:trust] previousFailureCount:0 failureResponse:nil error:nil sender:s];
    assert(challenge.protectionSpace.serverTrust==trust);
    NSURLAuthenticationChallenge *forwarded=[[NSURLAuthenticationChallenge alloc] initWithAuthenticationChallenge:challenge sender:s];
    assert(forwarded.protectionSpace.serverTrust==trust);
    space=nil;copiedSpace=nil;challenge=nil;
    assert(SecTrustGetCertificateCount(forwarded.protectionSpace.serverTrust)==1);
    [s performDefaultHandlingForAuthenticationChallenge:nil];
    [s cancelAuthenticationChallenge:nil];assert([s waitForResponse:1 cancelled:^BOOL{return notCancelled();}]);
    s=sender(trust);[s useCredential:[NSURLCredential credentialForTrust:trust] forAuthenticationChallenge:nil];
    assert([s waitForResponse:1 cancelled:nil]);
    s=sender(trust);[s useCredential:[NSURLCredential credentialForTrust:other] forAuthenticationChallenge:nil];
    assert([s waitForResponse:1 cancelled:nil]);
    s=sender(trust);[s useCredential:nil forAuthenticationChallenge:nil];assert([s waitForResponse:1 cancelled:nil]);
    s=sender(trust);[s continueWithoutCredentialForAuthenticationChallenge:nil];assert([s waitForResponse:1 cancelled:nil]);
    s=sender(trust);[s rejectProtectionSpaceAndContinueWithChallenge:nil];assert([s waitForResponse:1 cancelled:nil]);
    s=sender(trust);[s cancelAuthenticationChallenge:nil];[s performDefaultHandlingForAuthenticationChallenge:nil];
    assert(![s waitForResponse:1 cancelled:nil]);
    s=sender(trust);double start=SHDWCurlTrustNow();assert(![s waitForResponse:0.025 cancelled:nil]);
    assert(SHDWCurlTrustNow()-start<0.5);[s performDefaultHandlingForAuthenticationChallenge:nil];assert(!s.accepted);
    s=sender(trust);start=SHDWCurlTrustNow();
    assert(![s waitForResponse:1 cancelled:^BOOL{return SHDWCurlTrustNow()-start>0.015;}]);
    assert(SHDWCurlTrustNow()-start<0.3);
    s=sender(trust);[s performDefaultHandlingForAuthenticationChallenge:nil];
    assert(![s waitForResponse:1 cancelled:^BOOL{return YES;}]);
    s=sender(trust);SHDWCurlChallengeSender *asyncSender=s;
    dispatch_async(dispatch_get_global_queue(DISPATCH_QUEUE_PRIORITY_DEFAULT,0),^{[asyncSender performDefaultHandlingForAuthenticationChallenge:nil];});
    assert([s waitForResponse:1 cancelled:nil]);
    __block unsigned challenges=0;
    void (^send)(NSURLAuthenticationChallenge *)=^(NSURLAuthenticationChallenge *c){(void)c;challenges++;};
    assert(!SHDWCurlEvaluateTrust(@[der],@"trust.test",443,1,send,nil));
    assert(!SHDWCurlEvaluateTrust(@[[NSData dataWithBytes:"invalid" length:7]],@"trust.test",443,1,send,nil));
    assert(!SHDWCurlEvaluateTrust(@[],@"trust.test",443,1,send,nil));
    assert(!SHDWCurlEvaluateTrust(@[der],@"",443,1,send,nil));
    assert(!SHDWCurlEvaluateTrust(@[der],@"trust.test",0,1,send,nil));
    assert(!SHDWCurlEvaluateTrust(@[der],@"trust.test",443,0,send,nil));
    assert(!SHDWCurlEvaluateTrust(@[der],@"trust.test",443,1,send,^BOOL{return YES;}));
    assert(challenges==0);
    CFRelease(other);
    puts("curl trust: actual Security self-signed/invalid rejection, retained protection space, default/credential acceptance, rejection, duplicates, timeout and cancellation passed");
} }
'''
with tempfile.TemporaryDirectory(prefix="shadow-curl-trust-") as temporary:
    directory = Path(temporary)
    cert, key = directory / "certificate.der", directory / "key.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                    "-subj", "/CN=trust.test", "-keyout", str(key), "-outform", "DER", "-out", str(cert)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    test, binary = directory / "test.m", directory / "test"
    test.write_text(source)
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
                    "-Wno-deprecated-declarations", "-Wno-nonnull", "-fsanitize=address,undefined", "-framework", "Foundation",
                    "-framework", "Security", "-I", str(root / "src/Transport"), str(test), "-o", str(binary)], check=True)
    subprocess.run([str(binary), str(cert)], check=True)
