// SPDX-License-Identifier: Apache-2.0
// libplacebo's FFmpeg helpers are header-implemented. Exactly one C translation
// unit instantiates them; C++ consumers include the declarations only.
#ifdef TUBEVIZ_HAVE_PLACEBO
#define PL_LIBAV_IMPLEMENTATION 1
#include <libplacebo/utils/libav.h>
#else
typedef int tubeviz_libav_bridge_disabled;
#endif
