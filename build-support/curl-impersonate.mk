SHADOW_CURL_IMPERSONATE ?= 0
SHADOW_CURL_PROJECT_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)
SHADOW_CURL_PREBUILT_ROOT := $(if $(PREBUILT_ROOT),$(PREBUILT_ROOT),$(SHADOW_CURL_PROJECT_ROOT)/../prebuilt)
SHADOW_CURL_ROOT ?= $(SHADOW_CURL_PREBUILT_ROOT)/curl-impersonate/2.3.2/ios
ifeq ($(SHADOW_CURL_IMPERSONATE),1)
ifneq ($(SHADOW_LANE),rootless)
$(error curl-impersonate currently requires the rootless lane)
endif
ifeq ($(wildcard $(SHADOW_CURL_ROOT)/include/curl/curl.h),)
$(error Run scripts/prepare-curl-impersonate.sh before enabling SHADOW_CURL_IMPERSONATE)
endif
SHADOW_CURL_VALID := $(shell python3 "$(SHADOW_CURL_PROJECT_ROOT)/scripts/check-curl-impersonate.py" "$(SHADOW_CURL_ROOT)/libcurl-impersonate.4.dylib" --quiet >/dev/null 2>&1 && echo yes)
ifneq ($(SHADOW_CURL_VALID),yes)
$(error Run scripts/prepare-curl-impersonate.sh to prepare both arm64 and modern arm64e curl slices)
endif
endif
