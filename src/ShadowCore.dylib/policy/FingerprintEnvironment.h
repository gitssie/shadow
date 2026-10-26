#ifndef SHDW_FINGERPRINT_ENVIRONMENT_H
#define SHDW_FINGERPRINT_ENVIRONMENT_H

#include <stdint.h>

typedef struct {
    float brightness;
    unsigned batteryPercent;
} SHDWFingerprintEnvironment;

static inline SHDWFingerprintEnvironment SHDWFingerprintEnvironmentSample(
    uint32_t brightnessDraw, uint32_t batteryDraw) {
    return (SHDWFingerprintEnvironment){
        (350000u + brightnessDraw % 450001u) / 1000000.0f, 10 + batteryDraw % 81};
}

static inline int SHDWFingerprintEnvironmentLowPower(SHDWFingerprintEnvironment value) {
    return value.batteryPercent < 30;
}

#endif
