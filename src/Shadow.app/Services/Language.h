#import <Foundation/Foundation.h>
FOUNDATION_EXPORT NSNotificationName const SHDWLanguageDidChangeNotification;
FOUNDATION_EXPORT NSString *SHDWLanguage(void);
FOUNDATION_EXPORT void SHDWSetLanguage(NSString *language);
FOUNDATION_EXPORT NSString *SHDWLocalizedText(NSString *key);
