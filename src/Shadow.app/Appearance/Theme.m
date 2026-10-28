#import "Theme.h"
#include <math.h>
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
UIImage *SHDWIPSwitchSymbol(CGFloat size) {
    UIGraphicsImageRenderer *renderer = [[UIGraphicsImageRenderer alloc] initWithSize:CGSizeMake(size, size)];
    UIImage *image = [renderer imageWithActions:^(UIGraphicsImageRendererContext *context) {
        (void)context; [UIColor.blackColor setStroke]; CGPoint center = CGPointMake(size / 2, size / 2); CGFloat radius = size * 0.40;
        UIBezierPath *path = [UIBezierPath bezierPath]; path.lineWidth = size / 20; path.lineCapStyle = kCGLineCapRound; path.lineJoinStyle = kCGLineJoinRound;
        for (NSUInteger i = 0; i < 2; i++) {
            CGFloat rotation = (CGFloat)i * 180;
            CGFloat start = (-65.0 + rotation) * M_PI / 180, end = (85.0 + rotation) * M_PI / 180;
            [path moveToPoint:CGPointMake(center.x + radius * cos(start), center.y + radius * sin(start))];
            [path addArcWithCenter:center radius:radius startAngle:start endAngle:end clockwise:YES];
            CGPoint tip = CGPointMake(center.x + radius * cos(end), center.y + radius * sin(end));
            CGFloat dx = -sin(end), dy = cos(end), length = size * 0.14, width = size * 0.085;
            [path moveToPoint:CGPointMake(tip.x - dx * length + dy * width, tip.y - dy * length - dx * width)]; [path addLineToPoint:tip];
            [path addLineToPoint:CGPointMake(tip.x - dx * length - dy * width, tip.y - dy * length + dx * width)];
        }
        [path stroke];
        NSDictionary *attributes = @{NSFontAttributeName:[UIFont systemFontOfSize:size * 0.42 weight:UIFontWeightSemibold], NSForegroundColorAttributeName:UIColor.blackColor};
        CGSize text = [@"IP" sizeWithAttributes:attributes]; [@"IP" drawAtPoint:CGPointMake((size - text.width) / 2, (size - text.height) / 2) withAttributes:attributes];
    }];
    return [image imageWithRenderingMode:UIImageRenderingModeAlwaysTemplate];
}
void SHDWShowError(UIViewController *controller, NSError *error) {
    SHDWPresentMessageSheet(controller, SHDWText(@"Operation failed"), error.localizedDescription ?: SHDWText(@"Try again"));
}
