# Shadow build configuration for upstream Theos. All lane fields live here;
# no additional scripts are required inside the Theos checkout.

shadow_lanes() { echo "rootful-legacy rootful-modern rootless"; }

shadow_lane_field() { # <lane> <field>
    case "$1:$2" in
    rootful-legacy:ARCHS)         echo "armv7 armv7s arm64 arm64e" ;;
    rootful-legacy:TARGET)        echo "iphone:clang:13.7" ;;
    rootful-legacy:SCHEME)        echo "" ;;
    rootful-legacy:DEPLOY)        echo "9.0" ;;
    rootful-legacy:DEPLOY_ARM64E) echo "12.0" ;;
    rootful-legacy:ABI)           echo "old" ;;
    rootful-modern:ARCHS)         echo "arm64 arm64e" ;;
    rootful-modern:TARGET)        echo "iphone:clang:16.5:14.0" ;;
    rootful-modern:SCHEME)        echo "" ;;
    rootful-modern:DEPLOY)        echo "" ;;
    rootful-modern:DEPLOY_ARM64E) echo "" ;;
    rootful-modern:ABI)           echo "new" ;;
    rootless:ARCHS)               echo "arm64 arm64e" ;;
    rootless:TARGET)              echo "iphone:clang:16.5:15.0" ;;
    rootless:SCHEME)              echo "rootless" ;;
    rootless:DEPLOY)              echo "" ;;
    rootless:DEPLOY_ARM64E)       echo "" ;;
    rootless:ABI)                 echo "new" ;;
    rootful-legacy:FLOOR)         echo "9.0" ;;
    rootful-legacy:CEILING)       echo "14.0" ;;
    rootful-legacy:PACKAGE)       echo "me.jjolano.shadow.legacy" ;;
    rootful-legacy:PACKAGE_ARCH)  echo "iphoneos-arm" ;;
    rootful-modern:FLOOR)         echo "14.0" ;;
    rootful-modern:CEILING)       echo "" ;;
    rootful-modern:PACKAGE)       echo "me.jjolano.shadow" ;;
    rootful-modern:PACKAGE_ARCH)  echo "iphoneos-arm" ;;
    rootless:FLOOR)               echo "15.0" ;;
    rootless:CEILING)             echo "" ;;
    rootless:PACKAGE)             echo "me.jjolano.shadow" ;;
    rootless:PACKAGE_ARCH)        echo "iphoneos-arm64" ;;
    *) echo "unknown lane '$1' or field '$2'" >&2; return 1 ;;
    esac
}
