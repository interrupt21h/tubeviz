// SPDX-License-Identifier: Apache-2.0
//!HOOK MAIN
//!BIND HOOKED
//!DESC tubeviz beat-local deformation prototype
//!PARAM beat_amount
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 1.0
0.0
//!PARAM beat_mode
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 7.0
4.0
//!PARAM beat_center_x
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 1.0
0.5
//!PARAM beat_center_y
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 1.0
0.5
//!PARAM beat_direction
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 6.4
0.0
//!PARAM beat_frequency
//!TYPE DYNAMIC float
//!MINIMUM 0.5
//!MAXIMUM 3.0
1.0
//!PARAM beat_phase
//!TYPE DYNAMIC float
//!MINIMUM 0.0
//!MAXIMUM 1.0
0.0
//!PARAM beat_polarity
//!TYPE DYNAMIC float
//!MINIMUM -1.0
//!MAXIMUM 1.0
1.0

vec4 hook()
{
    vec2 uv = HOOKED_pos;
    vec2 center = vec2(beat_center_x, beat_center_y);
    vec2 p = uv - center;
    float r = length(p);
    float pol = beat_polarity >= 0.0 ? 1.0 : -1.0;
    vec2 dir = vec2(cos(beat_direction), sin(beat_direction));
    vec2 nrm = vec2(-dir.y, dir.x);
    float a = beat_amount;

    if (beat_mode < 0.5) {
        uv -= p * a * 0.070 * pol * (0.72 + 0.28 * (1.0 - smoothstep(0.15, 0.82, r)));
    } else if (beat_mode < 1.5) {
        uv += p * a * 0.060 * pol * (0.72 + 0.28 * (1.0 - smoothstep(0.12, 0.86, r)));
    } else if (beat_mode < 2.5) {
        float osc = sin(dot(p, nrm) * 28.0 * beat_frequency + beat_phase * 10.0);
        uv += dir * osc * a * 0.035 * pol;
    } else if (beat_mode < 3.5) {
        float angle = a * 0.20 * pol * (1.0 - smoothstep(0.10, 0.78, r));
        float cs = cos(angle), sn = sin(angle);
        uv = center + mat2(cs, -sn, sn, cs) * p;
    } else {
        float osc = sin(dot(p, nrm) * 24.0 * beat_frequency + beat_phase * 12.0);
        uv += dir * osc * a * 0.027 * pol;
    }
    return HOOKED_tex(clamp(uv, vec2(0.001), vec2(0.999)));
}
