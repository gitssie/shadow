include ../../build-support/build-lanes.mk
include ../../build-support/curl-impersonate.mk
include $(THEOS)/makefiles/common.mk
include ../../build-support/hookkit.mk

TWEAK_NAME = ShadowNetworking
ShadowNetworking_FILES = Entry.m Sessions.m CurlEngine.m HookSession.m ../Transport/Bootstrap.m ../Transport/CurlTrust.m ../Localization/FunctionHook.m
ShadowNetworking_FRAMEWORKS = Foundation CoreFoundation CFNetwork Security
ShadowNetworking_EXTRA_FRAMEWORKS = HookKit Shadow
ShadowNetworking_CFLAGS = -fobjc-arc -fvisibility=hidden -DSHADOW_CURL_IMPERSONATE=1 $(SHADOW_HOOKKIT_CFLAGS) -I$(SHADOW_CURL_ROOT)/include -I../Shadow.framework/Headers
ShadowNetworking_LDFLAGS = -Wl,-x $(SHADOW_HOOKKIT_LDFLAGS) -F../ -rpath /Library/Frameworks -rpath /var/jb/Library/Frameworks -rpath /usr/lib -rpath /var/jb/usr/lib

include $(THEOS_MAKE_PATH)/tweak.mk
