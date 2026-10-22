#import "OperationCoordinator.h"
#import "Language.h"
NSNotificationName const SHDWOperationDidChangeNotification = @"Shadow.OperationDidChange";
static BOOL active;
@implementation SHDWOperationCoordinator
+ (BOOL)isRunning { @synchronized(self) { return active; } }
+ (void)changed {
    void (^notify)(void) = ^{ [[NSNotificationCenter defaultCenter] postNotificationName:SHDWOperationDidChangeNotification object:nil]; };
    if (NSThread.isMainThread) notify(); else dispatch_async(dispatch_get_main_queue(), notify);
}
+ (BOOL)beginOperation:(NSError **)error {
    @synchronized(self) {
        if (active) {
            if (error) *error = [NSError errorWithDomain:@"me.jjolano.shadow.operations" code:1 userInfo:@{NSLocalizedDescriptionKey:SHDWLocalizedText(@"An operation is already running.")}];
            return NO;
        }
        active = YES;
    }
    [self changed]; return YES;
}
+ (void)endOperation {
    @synchronized(self) { if (!active) return; active = NO; }
    [self changed];
}
@end
