// SPDX-License-Identifier: Apache-2.0
// libplacebo's FFmpeg helpers are header-implemented. Exactly one translation
// unit must instantiate them; resident_gpu.cpp only consumes the public API.
#ifdef TUBEVIZ_HAVE_PLACEBO
#define PL_LIBAV_IMPLEMENTATION 1
#include <libplacebo/utils/libav.h>
#endif
