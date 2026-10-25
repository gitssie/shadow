#import "Views/SheetViewController.h"
@interface SHDWIPSwitchDialogViewController : SHDWSheetViewController
- (instancetype)initWithEntries:(NSArray<NSDictionary<NSString *, NSString *> *> *)entries;
- (instancetype)initWithEntry:(NSDictionary<NSString *, NSString *> *)entry;
@end
