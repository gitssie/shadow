include ../../build-support/build-lanes.mk
include $(THEOS)/makefiles/common.mk

APPLICATION_NAME = ShadowManager
ShadowManager_FILES = $(wildcard App/*.m Screens/*/*.m Views/*.m Services/*.m Appearance/*.m)
ShadowManager_FRAMEWORKS = UIKit Foundation QuartzCore
ShadowManager_EXTRA_FRAMEWORKS = Shadow
ShadowManager_PRIVATE_FRAMEWORKS = MobileCoreServices
ShadowManager_CFLAGS = -fobjc-arc -fvisibility=hidden -I../Shadow.framework/Headers -I.
ShadowManager_LDFLAGS = -Wl,-x -F../ -rpath /Library/Frameworks -rpath /var/jb/Library/Frameworks -rpath /usr/lib -rpath /var/jb/usr/lib
ShadowManager_CODESIGN_FLAGS = -SShadowManager.entitlements
ShadowManager_RESOURCE_DIRS = Resources
ShadowManager_RESOURCE_FILES = Info.plist
ShadowManager_INSTALL_PATH = /Applications

include $(THEOS_MAKE_PATH)/application.mk
