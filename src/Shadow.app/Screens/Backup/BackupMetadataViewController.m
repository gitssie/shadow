#import "BackupMetadataViewController.h"
#import "Services/InstalledApplications.h"
#import "Services/OperationCoordinator.h"
#import "Appearance/Theme.h"

@interface SHDWBackupMetadataViewController () <UITextFieldDelegate, UITextViewDelegate>
@property(nonatomic, strong) SHDWInstalledApplication *application;
@property(nonatomic, copy) NSDictionary *snapshot;
@property(nonatomic, strong) UITextField *nameField;
@property(nonatomic, strong) UITextView *noteField;
@property(nonatomic, strong) UILabel *errorLabel;
@property(nonatomic, strong) UIButton *saveButton;
@property(nonatomic, strong) NSLayoutConstraint *noteHeight;
@property(nonatomic) BOOL finishing;
@end

@implementation SHDWBackupMetadataViewController
- (instancetype)initWithApplication:(SHDWInstalledApplication *)application snapshot:(NSDictionary *)snapshot {
    if ((self = [super init])) { _application = application; _snapshot = [snapshot copy]; }
    return self;
}
- (UILabel *)fieldLabel:(NSString *)text {
    UILabel *label = [UILabel new]; label.text = SHDWText(text); label.textColor = UIColor.secondaryLabelColor; label.font = [[UIFontMetrics metricsForTextStyle:UIFontTextStyleCaption1] scaledFontForFont:[UIFont systemFontOfSize:12]]; label.adjustsFontForContentSizeCategory = YES; return label;
}
- (void)viewDidLoad {
    self.sheetTitle = SHDWText(self.snapshot ? @"Edit backup" : @"New backup"); self.sheetIcon = [SHDWInstalledApplications iconForApplication:self.application];
    [super viewDidLoad]; self.view.accessibilityIdentifier = @"backup.metadata-sheet";
    UIStackView *card = [UIStackView new]; card.axis = UILayoutConstraintAxisVertical; card.spacing = 6; card.backgroundColor = UIColor.whiteColor; card.layer.cornerRadius = 16; card.layoutMarginsRelativeArrangement = YES; card.layoutMargins = UIEdgeInsetsMake(14, 16, 14, 16);
    UIFont *font = [[UIFontMetrics metricsForTextStyle:UIFontTextStyleBody] scaledFontForFont:[UIFont systemFontOfSize:16]];
    self.nameField = [UITextField new]; self.nameField.text = self.snapshot ? self.snapshot[@"title"] : self.application.name; self.nameField.placeholder = SHDWText(@"Name"); self.nameField.font = font; self.nameField.adjustsFontForContentSizeCategory = YES; self.nameField.textColor = SHDWInk(); self.nameField.tintColor = SHDWAccent(); self.nameField.clearButtonMode = UITextFieldViewModeWhileEditing; self.nameField.returnKeyType = UIReturnKeyNext; self.nameField.delegate = self; self.nameField.accessibilityIdentifier = @"backup.metadata.name"; [self.nameField.heightAnchor constraintGreaterThanOrEqualToConstant:36].active = YES;
    self.noteField = [UITextView new]; self.noteField.text = self.snapshot[@"note"] ?: @""; self.noteField.font = font; self.noteField.adjustsFontForContentSizeCategory = YES; self.noteField.textColor = SHDWInk(); self.noteField.tintColor = SHDWAccent(); self.noteField.backgroundColor = UIColor.clearColor; self.noteField.textContainerInset = UIEdgeInsetsMake(4, 0, 4, 0); self.noteField.textContainer.lineFragmentPadding = 0; self.noteField.delegate = self; self.noteField.accessibilityLabel = SHDWText(@"Note"); self.noteField.accessibilityIdentifier = @"backup.metadata.note"; self.noteHeight = [self.noteField.heightAnchor constraintEqualToConstant:72]; self.noteHeight.active = YES;
    [card addArrangedSubview:[self fieldLabel:@"Name"]]; [card addArrangedSubview:self.nameField]; [card setCustomSpacing:12 afterView:self.nameField]; [card addArrangedSubview:[self fieldLabel:@"Note"]]; [card addArrangedSubview:self.noteField]; [self.contentStack addArrangedSubview:card];
    self.errorLabel = [UILabel new]; self.errorLabel.font = [[UIFontMetrics metricsForTextStyle:UIFontTextStyleFootnote] scaledFontForFont:[UIFont systemFontOfSize:12]]; self.errorLabel.adjustsFontForContentSizeCategory = YES; self.errorLabel.textColor = UIColor.systemRedColor; self.errorLabel.numberOfLines = 0; self.errorLabel.hidden = YES; self.errorLabel.accessibilityIdentifier = @"backup.metadata.error"; [self.contentStack addArrangedSubview:self.errorLabel];
    self.saveButton = SHDWSheetPrimaryButton(SHDWText(@"Save"), @"checkmark", self, @selector(saveMetadata)); self.saveButton.accessibilityIdentifier = @"backup.metadata.save"; [self.contentStack addArrangedSubview:self.saveButton];
}
- (BOOL)textFieldShouldReturn:(UITextField *)textField { (void)textField; [self.noteField becomeFirstResponder]; return NO; }
- (void)textFieldDidBeginEditing:(UITextField *)textField { [self scrollToView:textField animated:YES]; }
- (void)textViewDidBeginEditing:(UITextView *)textView { [self scrollToView:textView animated:YES]; }
- (void)textViewDidChange:(UITextView *)textView {
    CGFloat width = textView.bounds.size.width; if (width <= 0) return;
    CGFloat height = MIN(144, MAX(72, ceil([textView sizeThatFits:CGSizeMake(width, CGFLOAT_MAX)].height)));
    if (fabs(self.noteHeight.constant - height) > 0.5) { self.noteHeight.constant = height; [self requestSheetLayout]; }
}
- (void)saveMetadata {
    if (self.finishing || [SHDWOperationCoordinator isRunning]) return;
    NSString *title = [self.nameField.text stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet] ?: @"", *note = self.noteField.text ?: @"";
    if (!title.length || title.length > 100 || note.length > 1000) {
        self.errorLabel.text = SHDWText(@"Use a name of 1–100 characters and a note up to 1000 characters."); self.errorLabel.hidden = NO; [self requestSheetLayout]; [self scrollToView:self.errorLabel animated:YES]; UIAccessibilityPostNotification(UIAccessibilityAnnouncementNotification, self.errorLabel.text); return;
    }
    self.finishing = YES; self.saveButton.enabled = NO; self.view.userInteractionEnabled = NO; [self.view endEditing:YES]; NSDictionary *metadata = @{ @"title": title, @"note": note }; void (^save)(NSDictionary *) = self.save;
    [self dismissViewControllerAnimated:YES completion:^{ if (save && ![SHDWOperationCoordinator isRunning]) save(metadata); }];
}
@end
