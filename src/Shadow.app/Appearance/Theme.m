#import "Theme.h"
#import "Services/Language.h"
#import "Views/SheetViewController.h"
UIColor *SHDWBackground(void) { return [UIColor colorWithRed:245/255.0 green:246/255.0 blue:243/255.0 alpha:1]; }
UIColor *SHDWInk(void) { return [UIColor colorWithRed:32/255.0 green:41/255.0 blue:45/255.0 alpha:1]; }
UIColor *SHDWAccent(void) { return [UIColor colorWithRed:40/255.0 green:124/255.0 blue:115/255.0 alpha:1]; }
UIColor *SHDWDestructiveColor(void) { return [UIColor colorWithRed:0.79 green:0.34 blue:0.29 alpha:1]; }
NSString *SHDWText(NSString *key) { return SHDWLocalizedText(key); }
UIImage *SHDWSymbol(NSString *name, CGFloat size) {
    if (@available(iOS 13.0, *)) return [UIImage systemImageNamed:name withConfiguration:[UIImageSymbolConfiguration configurationWithPointSize:size weight:UIImageSymbolWeightRegular]];
    return nil;
}
void SHDWShowError(UIViewController *controller, NSError *error) {
    SHDWPresentMessageSheet(controller, SHDWText(@"Operation failed"), error.localizedDescription ?: SHDWText(@"Try again"));
}
