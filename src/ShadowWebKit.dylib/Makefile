include ../../build-support/build-lanes.mk
include ../../build-support/curl-impersonate.mk
include $(THEOS)/makefiles/common.mk
include ../../build-support/hookkit.mk

TWEAK_NAME = ShadowWebKit
ShadowWebKit_FILES = WebContent.m UserAgentSource.mm ../WebUserAgent/Bootstrap.m
ShadowWebKit_FILES += ../Localization/Bootstrap.m ../Localization/Environment.m ../Localization/WebTimeZone.m ../Localization/FunctionHook.m
ShadowWebKit_CCFLAGS += -std=c++17
ShadowWebKit_FRAMEWORKS = Foundation CoreFoundation
ShadowWebKit_EXTRA_FRAMEWORKS = HookKit
ShadowWebKit_CFLAGS = -fobjc-arc -fvisibility=hidden $(SHADOW_HOOKKIT_CFLAGS)
ShadowWebKit_LDFLAGS = -Wl,-x $(SHADOW_HOOKKIT_LDFLAGS) -rpath /Library/Frameworks -rpath /var/jb/Library/Frameworks
ifeq ($(SHADOW_CURL_IMPERSONATE),1)
ShadowWebKit_FILES += Networking.m Sessions.m CurlEngine.m HookSession.m CookieDiagnostics.m
ShadowWebKit_FILES += ../Transport/Bootstrap.m ../Transport/NetworkDiagnostics.m ../Transport/NativeTLS.m ../Transport/ExternalTLS.c ../Transport/NativeHTTP2.m
ShadowWebKit_FRAMEWORKS += CFNetwork Security Network
ShadowWebKit_EXTRA_FRAMEWORKS += Shadow
ShadowWebKit_CFLAGS += -DSHADOW_CURL_IMPERSONATE=1 -I$(SHADOW_CURL_ROOT)/include -I../Shadow.framework/Headers
ShadowWebKit_LDFLAGS += -F../ -rpath /usr/lib -rpath /var/jb/usr/lib
endif

include $(THEOS_MAKE_PATH)/tweak.mk
