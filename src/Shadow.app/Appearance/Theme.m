#import "Theme.h"
#import "Services/Language.h"
UIColor *SHDWBackground(void) { return [UIColor colorWithRed:245/255.0 green:246/255.0 blue:243/255.0 alpha:1]; }
UIColor *SHDWInk(void) { return [UIColor colorWithRed:32/255.0 green:41/255.0 blue:45/255.0 alpha:1]; }
UIColor *SHDWAccent(void) { return [UIColor colorWithRed:40/255.0 green:124/255.0 blue:115/255.0 alpha:1]; }
UIColor *SHDWLockColor(void) { return [UIColor colorWithRed:201/255.0 green:149/255.0 blue:59/255.0 alpha:1]; }
NSString *SHDWText(NSString *key) { return SHDWLocalizedText(key); }
UIImage *SHDWSymbol(NSString *name, CGFloat size) {
    if (@available(iOS 13.0, *)) return [UIImage systemImageNamed:name withConfiguration:[UIImageSymbolConfiguration configurationWithPointSize:size weight:UIImageSymbolWeightRegular]];
    return nil;
}
void SHDWShowError(UIViewController *controller, NSError *error) {
    UIAlertController *alert = [UIAlertController alertControllerWithTitle:SHDWText(@"Operation failed") message:error.localizedDescription ?: SHDWText(@"Try again") preferredStyle:UIAlertControllerStyleAlert];
    [alert addAction:[UIAlertAction actionWithTitle:SHDWText(@"OK") style:UIAlertActionStyleDefault handler:nil]];
    [controller presentViewController:alert animated:YES completion:nil];
}
