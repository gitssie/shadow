#!/usr/bin/env python3
"""Execute Manager pagination methods with Foundation service/view doubles.

This checks controller state and interaction gates, not UIKit rendering.
"""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/Shadow.app/Screens/Backup/BackupViewController.m"


def method(source, signature):
    start = source.index(signature)
    end = source.find("\n- (", start + len(signature))
    if end == -1:
        end = source.index("\n@end", start)
    return source[start:end]


PRELUDE = r'''
#import <Foundation/Foundation.h>
#import "Services/BackupPolicy.h"
#include <stdio.h>
#include <stdlib.h>
enum { UIControlStateNormal, UIAccessibilityAnnouncementNotification };
static void UIAccessibilityPostNotification(int value, id message) { (void)value; (void)message; }
static NSString *SHDWText(NSString *value) { return value; }
static NSString *CanonicalIDFV(NSString *value) { return value; }
static NSString *ProgressTitle(NSDictionary *event) { return event[@"stage"]; }
typedef struct { CGFloat top, left, bottom, right; } UIEdgeInsets;
@interface UIColor : NSObject
+ (id)systemRedColor;
+ (id)secondaryLabelColor;
@end
@implementation UIColor
+ (id)systemRedColor { return @"red"; }
+ (id)secondaryLabelColor { return @"secondary"; }
@end
@interface UIView : NSObject
@property BOOL enabled, hidden, userInteractionEnabled, dragging, decelerating, animating;
@property double constant, alpha;
@property CGPoint contentOffset;
@property CGRect bounds;
@property CGSize contentSize;
@property UIEdgeInsets adjustedContentInset;
@property(copy) NSString *text, *bundleIdentifier;
@property(strong) id textColor, tableFooterView;
- (void)setWorking:(BOOL)value;
- (void)setTitle:(NSString *)title forState:(NSInteger)state;
- (void)reloadData;
- (void)setContentOffset:(CGPoint)point animated:(BOOL)animated;
- (void)startAnimating;
- (void)stopAnimating;
@end
@implementation UIView
- (void)setWorking:(BOOL)value { (void)value; }
- (void)setTitle:(NSString *)title forState:(NSInteger)state { (void)state; self.text=title; }
- (void)reloadData {}
- (void)setContentOffset:(CGPoint)point animated:(BOOL)animated { self.contentOffset=point; (void)animated; }
- (void)startAnimating { self.animating=YES; }
- (void)stopAnimating { self.animating=NO; }
@end
#define UIScrollView UIView
@interface SHDWOperationCoordinator : NSObject
+ (BOOL)isRunning;
@end
@implementation SHDWOperationCoordinator
+ (BOOL)isRunning { return NO; }
@end
@interface SHDWFingerprintStore : NSObject
+ (instancetype)sharedStore;
- (NSDictionary *)profileForBundleIdentifier:(NSString *)bundle;
@end
@implementation SHDWFingerprintStore
+ (instancetype)sharedStore { return [self new]; }
- (NSDictionary *)profileForBundleIdentifier:(NSString *)bundle { (void)bundle; return @{@"VendorIdentifier":@"active"}; }
@end
@interface Service : NSObject
@property(copy) void (^pageCompletion)(NSDictionary *, NSError *);
@property(copy) void (^operationCompletion)(id, NSError *);
@property NSUInteger offset, requests;
@property(copy) NSString *search;
@property BOOL refresh;
- (void)loadCatalogForSearch:(NSString *)search offset:(NSUInteger)offset refresh:(BOOL)refresh completion:(void (^)(NSDictionary *, NSError *))completion;
- (void)performAction:(NSString *)action request:(NSDictionary *)request progress:(void (^)(NSDictionary *))progress completion:(void (^)(id, NSError *))completion;
- (void)finishPage:(NSDictionary *)page error:(NSError *)error;
@end
@implementation Service
- (void)loadCatalogForSearch:(NSString *)search offset:(NSUInteger)offset refresh:(BOOL)refresh completion:(void (^)(NSDictionary *, NSError *))completion {
    NSCAssert(!self.pageCompletion, @"overlapping requests");
    self.search=search; self.offset=offset; self.refresh=refresh; self.requests++; self.pageCompletion=completion;
}
- (void)performAction:(NSString *)action request:(NSDictionary *)request progress:(void (^)(NSDictionary *))progress completion:(void (^)(id, NSError *))completion {
    (void)action; (void)request; (void)progress; self.operationCompletion=completion;
}
- (void)finishPage:(NSDictionary *)page error:(NSError *)error {
    void (^completion)(NSDictionary *, NSError *)=self.pageCompletion;
    NSCAssert(completion, @"missing request"); self.pageCompletion=nil; completion(page,error);
}
@end
@interface Controller : NSObject
@property(strong) Service *service;
@property(strong) UIView *searchField, *status, *table, *tableHeight, *selector, *action, *pagingSpinner, *listBackground, *listSpinner, *selected, *empty, *emptyIcon;
@property(nonatomic,copy) NSArray *catalog, *visibleCatalog;
@property(copy) NSDictionary *currentBackup;
@property(copy) NSString *liveIDFV;
@property BOOL loading, loadingMore, working, queryPending, catalogFailed, refreshCatalog, reloadPending, restorePending, hasMore, catalogErrorVisible;
@property NSUInteger loadGeneration, nextOffset;
- (void)loadCatalog;
- (void)loadMore;
- (void)loadMoreIfNeeded;
- (void)scrollViewDidScroll:(UIScrollView *)scrollView;
- (void)scrollViewWillBeginDragging:(UIScrollView *)scrollView;
- (void)loadPage:(BOOL)append;
- (void)updateControls;
- (NSDictionary *)currentSnapshot;
- (void)reloadApplications;
- (void)collapseSelector;
- (void)perform:(NSString *)action request:(NSDictionary *)request;
@end
@implementation Controller
@synthesize catalog=_catalog;
- (void)reloadApplications { NSCAssert(NO,@"unexpected application reload"); }
- (void)collapseSelector {}
'''

SCENARIOS = r'''
@end
static NSUInteger failures;
static void Check(BOOL value, NSString *message) {
    if (!value) { fprintf(stderr,"FAIL: %s\n",message.UTF8String); failures++; }
}
static NSDictionary *Page(NSArray *items, NSUInteger next, BOOL more) {
    return @{@"items":items,@"total":@2,@"nextOffset":@(next),@"hasMore":@(more),@"currentSnapshot":@{@"idfv":@"active"},@"restorePending":@NO};
}
static Controller *Fixture(void) {
    Controller *c=[Controller new]; c.service=[Service new];
    for(NSString *key in @[@"searchField",@"status",@"table",@"tableHeight",@"selector",@"action",@"pagingSpinner",@"listBackground",@"listSpinner",@"selected",@"empty",@"emptyIcon"])
        [c setValue:[UIView new] forKey:key];
    c.searchField.text=@""; c.liveIDFV=@"active"; c.selected.bundleIdentifier=@"fixture.app"; c.refreshCatalog=YES;
    c.table.bounds=CGRectMake(0,0,320,400); c.table.contentSize=CGSizeMake(320,1000);
    c.table.adjustedContentInset=(UIEdgeInsets){0,0,20,0};
    return c;
}
int main(void) { @autoreleasepool {
    Controller *c=Fixture(); Service *s=c.service;
    NSDictionary *first=@{@"idfv":@"one"}, *second=@{@"idfv":@"two"};
    NSError *error=[NSError errorWithDomain:@"fixture" code:1 userInfo:@{NSLocalizedDescriptionKey:@"Temporary query failure"}];
    [c loadCatalog];
    Check(c.loading && s.offset==0 && s.refresh,@"first page request bounds/refresh");
    [s finishPage:Page(@[first],1,YES) error:nil];
    Check([c.catalog isEqual:@[first]] && c.hasMore && c.table.userInteractionEnabled && !c.pagingSpinner.animating,@"first page allows scrolling with idle spinner");
    NSUInteger requests=s.requests;
    // Non-table scrolling and programmatic table movement never fetch pages.
    UIView *other=[UIView new]; other.dragging=YES;
    [c scrollViewDidScroll:other]; [c scrollViewWillBeginDragging:other];
    c.table.contentOffset=CGPointMake(0,600); [c scrollViewDidScroll:c.table];
    Check(s.requests==requests,@"non-table and programmatic scrolling do not load");
    c.table.dragging=YES; c.table.contentOffset=CGPointMake(0,499);
    [c scrollViewDidScroll:c.table];
    Check(s.requests==requests,@"121 points from adjusted bottom does not load");
    c.queryPending=YES; c.table.contentOffset=CGPointMake(0,500);
    [c scrollViewDidScroll:c.table];
    Check(s.requests==requests,@"pending new search prevents appending an old page");
    c.queryPending=NO; [c scrollViewDidScroll:c.table];
    Check(s.requests==requests+1 && s.offset==1 && !s.refresh,@"within 120 points triggers one append at returned cursor");
    Check(c.loadingMore && c.loading && c.pagingSpinner.animating && c.table.userInteractionEnabled,@"append displays spinner and leaves table scrollable");
    [c scrollViewDidScroll:c.table]; [c scrollViewWillBeginDragging:c.table];
    Check(s.requests==requests+1,@"concurrent scroll callbacks cannot duplicate an in-flight request");
    [s finishPage:nil error:error];
    Check([c.catalog isEqual:@[first]] && c.hasMore && c.nextOffset==1,@"append failure retains current items and cursor");
    Check(c.table.userInteractionEnabled && !c.loadingMore && !c.pagingSpinner.animating,@"append failure leaves table scrollable and stops spinner");
    Check([c.status.text isEqual:error.localizedDescription] && [c.status.textColor isEqual:UIColor.systemRedColor],@"append error is displayed");
    [c scrollViewDidScroll:c.table]; c.table.dragging=NO; c.table.decelerating=YES;
    [c scrollViewDidScroll:c.table];
    Check(s.requests==requests+1,@"failed request cannot loop on the same drag/deceleration");
    c.table.decelerating=NO; c.table.dragging=YES;
    [c scrollViewWillBeginDragging:c.table];
    Check(s.requests==requests+2 && s.offset==1 && c.loadingMore,@"new drag retries the failed page at the same cursor");
    [s finishPage:Page(@[second],2,NO) error:nil];
    Check([c.catalog isEqual:@[first,second]] && !c.hasMore && !c.catalogFailed,@"retry appends once and finishes pagination");
    Check(!c.loadingMore && !c.pagingSpinner.animating,@"successful append stops spinner");
    Check(!c.status.text.length && ![c.status.textColor isEqual:UIColor.systemRedColor],@"successful retry clears previous query error and red color");
    [c scrollViewDidScroll:c.table]; [c scrollViewWillBeginDragging:c.table];
    Check(s.requests==requests+2,@"exhausted pages never request another append");
    // First-page errors recover as well, independently of append handling.
    [c loadCatalog]; [s finishPage:nil error:error];
    Check(c.catalogFailed && !c.table.userInteractionEnabled,@"first page failure disables unauthoritative results");
    c.searchField.text=@"new search"; [c loadCatalog];
    [s finishPage:Page(@[first],1,NO) error:nil];
    Check([s.search isEqual:@"new search"] && !c.catalogFailed && !c.status.text.length && ![c.status.textColor isEqual:UIColor.systemRedColor],@"new successful search clears first-page query error");
    // A successful write replaces any query error; its message survives refresh.
    [c loadCatalog]; [s finishPage:nil error:error];
    [c perform:@"edit" request:@{}];
    void (^done)(id,NSError *)=s.operationCompletion; s.operationCompletion=nil; done(@{},nil);
    Check([c.status.text isEqual:@"Backup saved"] && [c.status.textColor isEqual:UIColor.secondaryLabelColor],@"perform success message survives refresh start after query error");
    [s finishPage:Page(@[first],1,NO) error:nil];
    Check([c.status.text isEqual:@"Backup saved"] && [c.status.textColor isEqual:UIColor.secondaryLabelColor],@"perform success message survives successful refresh");
    if(failures)return 1;
    puts("backup pagination: real scroll callbacks, bounded auto paging, spinner, retry, query recovery and operation messages passed");
} return 0; }
'''


def main():
    if sys.platform != "darwin":
        raise SystemExit("This optional check requires macOS Foundation")
    source = SOURCE.read_text()
    signatures = [
        "- (void)setCatalog:", "- (void)loadCatalog {", "- (void)loadMore {",
        "- (void)loadMoreIfNeeded {", "- (void)scrollViewDidScroll:",
        "- (void)scrollViewWillBeginDragging:",
        "- (void)loadPage:", "- (NSDictionary *)currentSnapshot",
        "- (void)updateControls {", "- (void)perform:",
    ]
    code = PRELUDE + "\n".join(method(source, s) for s in signatures) + SCENARIOS
    with tempfile.TemporaryDirectory(prefix="shadow-backup-pagination-") as directory:
        temp = Path(directory)
        harness = temp / "main.m"
        harness.write_text(code)
        binary = temp / "check"
        subprocess.run(["xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
                        "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-g", "-O1",
                        "-framework", "Foundation", "-framework", "CoreGraphics", "-I" + str(ROOT / "src/Shadow.app"),
                        str(harness), "-o", str(binary)], check=True)
        env = dict(os.environ, ASAN_OPTIONS="detect_leaks=0:abort_on_error=1",
                   UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
        subprocess.run([str(binary)], env=env, check=True, timeout=30)


if __name__ == "__main__":
    main()
