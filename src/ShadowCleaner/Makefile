include ../../build-support/build-lanes.mk
include $(THEOS)/makefiles/common.mk

TOOL_NAME = shadow-cleaner
shadow-cleaner_FILES = main.m Cleaner.m
shadow-cleaner_CFLAGS = -fobjc-arc -fvisibility=hidden
shadow-cleaner_LDFLAGS = -Wl,-x
shadow-cleaner_FRAMEWORKS = Foundation Security LocalAuthentication
shadow-cleaner_PRIVATE_FRAMEWORKS = MobileCoreServices
shadow-cleaner_CODESIGN_FLAGS = -Sentitlements.plist
shadow-cleaner_INSTALL_PATH = /usr/libexec

include $(THEOS_MAKE_PATH)/tool.mk
