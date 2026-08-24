// SPDX-License-Identifier: Apache-2.0
//!HOOK MAIN
//!BIND HOOKED
//!DESC tubeviz Phase-2 beat warp prototype
//!PARAM beat_amount
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 1.0
0.0
//!PARAM beat_low
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 1.0
0.0

vec4 hook()
{
    vec2 uv = HOOKED_pos;
    vec2 center = vec2(0.5);
    vec2 d = uv - center;
    float r = length(d);
    float ring = exp(-18.0 * abs(r - 0.22));
    vec2 warped = uv - normalize(d + vec2(1e-6)) * ring * beat_amount * beat_low * 0.035;
    return HOOKED_tex(warped);
}
