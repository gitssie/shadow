#import <Foundation/Foundation.h>

// Dispatches a challenge only after Security validates the chain and hostname.
// Default handling and credential-free continuation retain that validation; cancellation rejects.
BOOL SHDWCurlEvaluateTrust(NSArray<NSData *> *DERCertificates, NSString *host, NSInteger port,
                          NSTimeInterval timeout,
                          void (^sendChallenge)(NSURLAuthenticationChallenge *),
                          BOOL (^cancelled)(void));
