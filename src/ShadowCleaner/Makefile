include ../../build-support/build-lanes.mk
include $(THEOS)/makefiles/common.mk

TOOL_NAME = shadow-cleaner
shadow-cleaner_FILES = main.m Cleaner.m ../AppState/Archive.m ../AppState/State.m
APP_STATE_LANE = $(if $(SHADOW_LANE),$(SHADOW_LANE),rootful-modern)
APP_STATE_DEPS_ROOT = $(abspath $(if $(PREBUILT_ROOT),$(PREBUILT_ROOT),../../../prebuilt))/app-state/$(APP_STATE_LANE)
APP_STATE_PREFIX = $(APP_STATE_DEPS_ROOT)/$(THEOS_CURRENT_ARCH)
shadow-cleaner_CFLAGS = -fobjc-arc -fvisibility=hidden -DSHADOW_STATE_SUPPORT -I$(APP_STATE_PREFIX)/include -I../Shadow.framework/Headers
shadow-cleaner_LDFLAGS = -Wl,-x $(APP_STATE_PREFIX)/lib/libarchive.a $(APP_STATE_PREFIX)/lib/libzstd.a -F../ -rpath /Library/Frameworks -rpath /var/jb/Library/Frameworks -rpath /usr/lib -rpath /var/jb/usr/lib
shadow-cleaner_FRAMEWORKS = Foundation Security LocalAuthentication
shadow-cleaner_EXTRA_FRAMEWORKS = Shadow
shadow-cleaner_PRIVATE_FRAMEWORKS = MobileCoreServices
shadow-cleaner_CODESIGN_FLAGS = -Sentitlements.plist
shadow-cleaner_INSTALL_PATH = /usr/libexec

ifeq ($(THEOS_PACKAGE_SCHEME),roothide)
shadow-cleaner_CFLAGS += -DSHADOW_ROOTHIDE
endif

include $(THEOS_MAKE_PATH)/tool.mk

before-all::
	@for arch in $(ARCHS); do test -f "$(APP_STATE_DEPS_ROOT)/$$arch/lib/libarchive.a" && test -f "$(APP_STATE_DEPS_ROOT)/$$arch/lib/libzstd.a" || { echo "Missing AppState dependencies; run scripts/build-app-state-deps.sh $(APP_STATE_LANE)" >&2; exit 1; }; done
