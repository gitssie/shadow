include build-support/build-lanes.mk

# Package metadata + maintainer scripts live under packaging/layout/ (kept out
# of the project root). Local to this Makefile: the subprojects keep their own
# conventional layout/ dirs, so this must never be exported to them.
THEOS_LAYOUT_DIR_NAME := packaging/layout

include $(THEOS)/makefiles/common.mk
SUBPROJECTS += src/Shadow.framework
SUBPROJECTS += src/Shadow.dylib
SUBPROJECTS += src/ShadowCore.dylib
SUBPROJECTS += src/ShadowSettings.bundle
ifneq ($(SHADOW_LANE),rootful-legacy)
SUBPROJECTS += src/Shadow.app
SUBPROJECTS += src/ShadowCleaner
endif
SUBPROJECTS += src/shdw
include $(THEOS_MAKE_PATH)/aggregate.mk

# The rootless scheme stages the whole layout/ under /var/jb. Select the
# matching ruleset-watcher plist after staging, before packaging.
before-package::
ifneq ($(SHADOW_LANE),rootful-legacy)
	$(ECHO_NOTHING)chmod 4755 "$(THEOS_STAGING_DIR)/usr/libexec/shadow-cleaner"$(ECHO_END)
endif
ifeq ($(THEOS_PACKAGE_SCHEME),rootless)
	$(ECHO_NOTHING)rm -f "$(THEOS_STAGING_DIR)/Library/LaunchDaemons/me.jjolano.shadow.watcher.plist"$(ECHO_END)
	$(ECHO_NOTHING)test -f "$(THEOS_STAGING_DIR)/Library/LaunchDaemons/me.jjolano.shadow.watcher.rootless.plist" && mv "$(THEOS_STAGING_DIR)/Library/LaunchDaemons/me.jjolano.shadow.watcher.rootless.plist" "$(THEOS_STAGING_DIR)/Library/LaunchDaemons/me.jjolano.shadow.watcher.plist" || true$(ECHO_END)
else
	$(ECHO_NOTHING)rm -f "$(THEOS_STAGING_DIR)/Library/LaunchDaemons/me.jjolano.shadow.watcher.rootless.plist"$(ECHO_END)
endif
