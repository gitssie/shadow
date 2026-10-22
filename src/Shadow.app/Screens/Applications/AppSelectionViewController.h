#import <UIKit/UIKit.h>
@interface SHDWAppSelectionViewController : UITableViewController
@property(nonatomic, copy) void (^selectionChanged)(NSString *bundleIdentifier, NSSet<NSString *> *removedIdentifiers);
@end
