include ../../build-support/build-lanes.mk
include $(THEOS)/makefiles/common.mk
include ../../build-support/hookkit.mk

TWEAK_NAME = ShadowWebContent
ShadowWebContent_FILES = Entry.m ../Localization/Bootstrap.m ../Localization/Environment.m ../Localization/WebTimeZone.m ../Localization/FunctionHook.m
ShadowWebContent_FILES += UserAgentSource.mm ../WebUserAgent/Bootstrap.m
ShadowWebContent_CCFLAGS += -std=c++17
ShadowWebContent_FRAMEWORKS = Foundation CoreFoundation
ShadowWebContent_EXTRA_FRAMEWORKS = HookKit
ShadowWebContent_CFLAGS = -fobjc-arc -fvisibility=hidden $(SHADOW_HOOKKIT_CFLAGS)
ShadowWebContent_LDFLAGS = -Wl,-x $(SHADOW_HOOKKIT_LDFLAGS) -rpath /Library/Frameworks -rpath /var/jb/Library/Frameworks

include $(THEOS_MAKE_PATH)/tweak.mk
