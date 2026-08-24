// SPDX-License-Identifier: Apache-2.0
#include "tubeviz/effects.hpp"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <random>

#ifdef TUBEVIZ_HAVE_OPENMP
#include <omp.h>
#endif

namespace tubeviz {
namespace {

inline std::uint8_t clamp8(double value) {
    return static_cast<std::uint8_t>(std::clamp(value, 0.0, 255.0));
}

inline double decay_for(double base, double fps) {
    return std::pow(base, 60.0 / std::max(1.0, fps));
}

inline double hash_noise(std::uint64_t x) {
    x ^= x >> 33;
    x *= 0xff51afd7ed558ccdULL;
    x ^= x >> 33;
    x *= 0xc4ceb9fe1a85ec53ULL;
    x ^= x >> 33;
    return (static_cast<double>(x & 0xffffu) / 32767.5) - 1.0;
}

} // namespace

void ReactiveState::decay(double fps) {
    beat_warp *= decay_for(0.76, fps);
    beat_low *= decay_for(0.82, fps);
    beat_mid *= decay_for(0.80, fps);
    beat_high *= decay_for(0.76, fps);
    ripple *= decay_for(0.90, fps);
    chroma *= decay_for(0.90, fps);
    vortex *= decay_for(0.91, fps);
    bloom *= decay_for(0.92, fps);
    harmonic *= decay_for(0.94, fps);
}

void ReactiveState::apply(const Cue& cue) {
    if (cue.action == "beat_warp" || cue.action == "video_edit_beat_warp") {
        beat_warp = std::max(beat_warp, cue.amount);
        beat_low = std::max(beat_low, cue.low);
        beat_mid = std::max(beat_mid, cue.mid);
        beat_high = std::max(beat_high, cue.high);
    } else if (cue.action == "video_edit_ripple") {
        ripple = std::max(ripple, cue.amount);
    } else if (cue.action == "video_edit_chroma_delay") {
        chroma = std::max(chroma, cue.amount);
    } else if (cue.action == "video_edit_vortex") {
        vortex = std::max(vortex, cue.amount);
    } else if (cue.action == "energy_bloom") {
        bloom = std::max(bloom, cue.amount);
    } else if (cue.action == "harmonic_warp") {
        harmonic = std::max(harmonic, cue.amount);
    }
}

void apply_transform(
    std::vector<std::uint8_t>& rgb,
    int width,
    int height,
    const Transform& t,
    std::uint64_t frame_index
) {
    if (rgb.empty()) return;
    const bool color = std::abs(t.brightness - 1.0) > 1e-4 ||
                       std::abs(t.contrast - 1.0) > 1e-4 ||
                       std::abs(t.saturation - 1.0) > 1e-4 ||
                       std::abs(t.hue_degrees) > 1e-4 ||
                       t.grayscale > 1e-4 || t.noise > 1e-4;
    if (color) {
        const double gray = std::clamp(t.grayscale, 0.0, 1.0);
        const double noise_amount = 28.0 * std::clamp(t.noise, 0.0, 1.0);
        const double hue = t.hue_degrees * 3.14159265358979323846 / 180.0;
        const double hc = std::cos(hue), hs = std::sin(hue);
#ifdef TUBEVIZ_HAVE_OPENMP
#pragma omp parallel for schedule(static)
#endif
        for (int y = 0; y < height; ++y) {
            std::size_t i = static_cast<std::size_t>(y) * width * 3;
            for (int x = 0; x < width; ++x, i += 3) {
                double r = rgb[i], g = rgb[i + 1], b = rgb[i + 2];
                const double luma = 0.2126 * r + 0.7152 * g + 0.0722 * b;
                r = luma + (r - luma) * t.saturation;
                g = luma + (g - luma) * t.saturation;
                b = luma + (b - luma) * t.saturation;
                if (std::abs(t.hue_degrees) > 1e-4) {
                    const double yiq_y = 0.299*r + 0.587*g + 0.114*b;
                    const double ii = 0.596*r - 0.274*g - 0.322*b;
                    const double qq = 0.211*r - 0.523*g + 0.312*b;
                    const double ir = ii*hc - qq*hs;
                    const double qr = ii*hs + qq*hc;
                    r = yiq_y + 0.956*ir + 0.621*qr;
                    g = yiq_y - 0.272*ir - 0.647*qr;
                    b = yiq_y - 1.106*ir + 1.703*qr;
                }
                r = r * (1.0 - gray) + luma * gray;
                g = g * (1.0 - gray) + luma * gray;
                b = b * (1.0 - gray) + luma * gray;
                r = (r - 127.5) * t.contrast + 127.5;
                g = (g - 127.5) * t.contrast + 127.5;
                b = (b - 127.5) * t.contrast + 127.5;
                r *= t.brightness; g *= t.brightness; b *= t.brightness;
                if (noise_amount > 1e-4) {
                    const std::uint64_t key =
                        frame_index * 0x9e3779b97f4a7c15ULL +
                        static_cast<std::uint64_t>(y) * width +
                        static_cast<std::uint64_t>(x);
                    const double n = hash_noise(key) * noise_amount;
                    r += n; g += n; b += n;
                }
                rgb[i] = clamp8(r); rgb[i + 1] = clamp8(g); rgb[i + 2] = clamp8(b);
            }
        }
    }

    if (t.mirror) {
        const int stride = width * 3;
#ifdef TUBEVIZ_HAVE_OPENMP
#pragma omp parallel for schedule(static)
#endif
        for (int y = 0; y < height; ++y) {
            auto* row = rgb.data() + static_cast<std::size_t>(y) * stride;
            for (int x = 0; x < width / 2; ++x) {
                const int a = x * 3;
                const int b = (width - 1 - x) * 3;
                std::swap(row[a], row[b]);
                std::swap(row[a + 1], row[b + 1]);
                std::swap(row[a + 2], row[b + 2]);
            }
        }
    }

    if (t.scanlines > 1e-4) {
        const double gain = 1.0 - 0.32 * std::clamp(t.scanlines, 0.0, 1.0);
#ifdef TUBEVIZ_HAVE_OPENMP
#pragma omp parallel for schedule(static)
#endif
        for (int y = 1; y < height; y += 2) {
            auto i = static_cast<std::size_t>(y) * width * 3;
            for (int x = 0; x < width; ++x, i += 3) {
                rgb[i] = clamp8(rgb[i] * gain);
                rgb[i + 1] = clamp8(rgb[i + 1] * gain);
                rgb[i + 2] = clamp8(rgb[i + 2] * gain);
            }
        }
    }

    if (t.vignette > 1e-4) {
        const double amount = std::clamp(t.vignette, 0.0, 1.0);
        const double cx = (width - 1) * 0.5, cy = (height - 1) * 0.5;
        const double inv_r2 = 1.0 / std::max(1.0, cx * cx + cy * cy);
#ifdef TUBEVIZ_HAVE_OPENMP
#pragma omp parallel for schedule(static)
#endif
        for (int y = 0; y < height; ++y) {
            for (int x = 0; x < width; ++x) {
                const double dx = x - cx, dy = y - cy;
                const double r2 = std::min(1.0, (dx * dx + dy * dy) * inv_r2);
                // Cheap smooth radial approximation; avoids millions of
                // sqrt()/pow() calls per HD frame.
                const double shaped = r2 * (0.68 + 0.32 * r2);
                const double gain = 1.0 - amount * 0.58 * shaped;
                const auto i = static_cast<std::size_t>((y * width + x) * 3);
                rgb[i] = clamp8(rgb[i] * gain);
                rgb[i + 1] = clamp8(rgb[i + 1] * gain);
                rgb[i + 2] = clamp8(rgb[i + 2] * gain);
            }
        }
    }
}

void apply_reactive_effects(
    std::vector<std::uint8_t>& rgb,
    int width,
    int height,
    const ReactiveState& state,
    double phase
) {
    if (rgb.empty()) return;
    const double ripple = std::clamp(
        state.ripple + state.beat_warp * state.beat_mid * 0.35, 0.0, 1.0
    );
    const double radial = std::clamp(
        state.beat_warp * state.beat_low + state.vortex * 0.25, 0.0, 1.0
    );
    if (ripple > 0.015 || radial > 0.015) {
        const auto src = rgb;
        const double cx = width * (0.5 + 0.05 * std::sin(phase * 0.7));
        const double cy = height * (0.5 + 0.04 * std::cos(phase * 0.6));
        const double inv_scale2 =
            1.0 / (static_cast<double>(std::max(width, height)) *
                   std::max(width, height));
#ifdef TUBEVIZ_HAVE_OPENMP
#pragma omp parallel for schedule(static)
#endif
        for (int y = 0; y < height; ++y) {
            const double wave =
                std::sin(y * 0.055 + phase * 11.0) * width * 0.012 * ripple;
            for (int x = 0; x < width; ++x) {
                double sx = x - wave;
                double sy = y;
                if (radial > 0.0) {
                    const double dx = x - cx, dy = y - cy;
                    const double rr2 = (dx * dx + dy * dy) * inv_scale2;
                    // Ring centered around r ~= .22 using a rational falloff.
                    // This is visually close to the old exp/sqrt formulation
                    // and dramatically cheaper on multi-megapixel frames.
                    const double distance = std::abs(rr2 - 0.0484);
                    const double envelope = 1.0 / (1.0 + 125.0 * distance);
                    const double push = radial * 0.072 * envelope;
                    sx -= dx * push;
                    sy -= dy * push;
                }
                const int ix = std::clamp(static_cast<int>(sx + 0.5), 0, width - 1);
                const int iy = std::clamp(static_cast<int>(sy + 0.5), 0, height - 1);
                const auto di = static_cast<std::size_t>((y * width + x) * 3);
                const auto si = static_cast<std::size_t>((iy * width + ix) * 3);
                rgb[di] = src[si];
                rgb[di + 1] = src[si + 1];
                rgb[di + 2] = src[si + 2];
            }
        }
    }

    const double chroma = std::clamp(
        state.chroma + state.beat_warp * state.beat_high * 0.55, 0.0, 1.0
    );
    if (chroma > 0.015) {
        const auto src = rgb;
        const int offset = std::max(
            1, static_cast<int>(width * 0.012 * chroma + 0.5)
        );
#ifdef TUBEVIZ_HAVE_OPENMP
#pragma omp parallel for schedule(static)
#endif
        for (int y = 0; y < height; ++y) {
            for (int x = 0; x < width; ++x) {
                const auto i = static_cast<std::size_t>((y * width + x) * 3);
                const int xr = std::min(width - 1, x + offset);
                const int xb = std::max(0, x - offset);
                rgb[i] = src[static_cast<std::size_t>((y * width + xr) * 3)];
                rgb[i + 2] =
                    src[static_cast<std::size_t>((y * width + xb) * 3 + 2)];
            }
        }
    }

    if (state.bloom > 0.02 || state.harmonic > 0.02) {
        const double gain =
            1.0 + 0.24 * std::clamp(state.bloom, 0.0, 1.0)
            + 0.10 * state.harmonic;
#ifdef TUBEVIZ_HAVE_OPENMP
#pragma omp parallel for schedule(static)
#endif
        for (std::int64_t i = 0; i < static_cast<std::int64_t>(rgb.size()); ++i) {
            rgb[static_cast<std::size_t>(i)] =
                clamp8(rgb[static_cast<std::size_t>(i)] * gain);
        }
    }
}


namespace {

inline std::uint64_t mix64(std::uint64_t x) {
    x ^= x >> 30; x *= 0xbf58476d1ce4e5b9ULL;
    x ^= x >> 27; x *= 0x94d049bb133111ebULL;
    x ^= x >> 31; return x;
}

inline double unit_rand(std::uint64_t seed, std::uint64_t index) {
    return static_cast<double>(mix64(seed + index * 0x9e3779b97f4a7c15ULL) & 0xffffffULL) / 16777216.0;
}

inline double effect_amount(const VectorEffect& e, double p) {
    p = std::clamp(p, 0.0, 1.0);
    const double q = p * 3.0;
    const int i = std::min(2, static_cast<int>(q));
    const double f = q - i;
    return std::clamp(e.amount_samples[i] * (1.0 - f) + e.amount_samples[i + 1] * f, 0.0, 1.0);
}

inline void blend_pixel(std::vector<std::uint8_t>& rgb, int width, int height, int x, int y,
                        double r, double g, double b, double alpha) {
    if (x < 0 || x >= width || y < 0 || y >= height) return;
    const auto i = static_cast<std::size_t>((y * width + x) * 3);
    const double a = std::clamp(alpha, 0.0, 1.0);
    rgb[i] = clamp8(rgb[i] * (1.0 - a) + r * a);
    rgb[i + 1] = clamp8(rgb[i + 1] * (1.0 - a) + g * a);
    rgb[i + 2] = clamp8(rgb[i + 2] * (1.0 - a) + b * a);
}

void draw_line(std::vector<std::uint8_t>& rgb, int width, int height,
               int x0, int y0, int x1, int y1,
               double r, double g, double b, double alpha, int thickness = 1) {
    const int dx = std::abs(x1 - x0), sx = x0 < x1 ? 1 : -1;
    const int dy = -std::abs(y1 - y0), sy = y0 < y1 ? 1 : -1;
    int err = dx + dy;
    while (true) {
        for (int oy = -thickness/2; oy <= thickness/2; ++oy)
            for (int ox = -thickness/2; ox <= thickness/2; ++ox)
                blend_pixel(rgb, width, height, x0 + ox, y0 + oy, r, g, b, alpha);
        if (x0 == x1 && y0 == y1) break;
        const int e2 = 2 * err;
        if (e2 >= dy) { err += dy; x0 += sx; }
        if (e2 <= dx) { err += dx; y0 += sy; }
    }
}

inline double luminance(const std::vector<std::uint8_t>& rgb, int width, int x, int y) {
    const auto i = static_cast<std::size_t>((y * width + x) * 3);
    return .2126*rgb[i] + .7152*rgb[i+1] + .0722*rgb[i+2];
}

void draw_native_contours(std::vector<std::uint8_t>& rgb, int width, int height,
                          const VectorEffect& e, double amount, bool semantic) {
    if (amount <= .01) return;
    const auto src = rgb;
    const int step = std::max(3, std::min(width, height) / 210);
    const int gw = std::max(3, width / step), gh = std::max(3, height / step);
    std::vector<double> mags(static_cast<std::size_t>(gw) * gh, 0.0);
    std::vector<std::uint8_t> edge(mags.size(), 0), visited(mags.size(), 0);
    const double threshold = semantic ? 150.0 : 115.0;
    auto sample = [&](int gx, int gy) {
        return luminance(src, width, std::clamp(gx * step, 0, width - 1), std::clamp(gy * step, 0, height - 1));
    };
    for (int gy = 1; gy < gh - 1; ++gy) {
        for (int gx = 1; gx < gw - 1; ++gx) {
            const double sx = -sample(gx-1,gy-1)-2*sample(gx-1,gy)-sample(gx-1,gy+1)
                              +sample(gx+1,gy-1)+2*sample(gx+1,gy)+sample(gx+1,gy+1);
            const double sy = -sample(gx-1,gy-1)-2*sample(gx,gy-1)-sample(gx+1,gy-1)
                              +sample(gx-1,gy+1)+2*sample(gx,gy+1)+sample(gx+1,gy+1);
            const auto i = static_cast<std::size_t>(gy * gw + gx);
            mags[i] = std::hypot(sx, sy);
            if (mags[i] >= threshold) edge[i] = 1;
        }
    }

    struct Component { std::vector<int> cells; double score{0.0}; };
    std::vector<Component> components;
    constexpr int dx8[8] = {-1,0,1,-1,1,-1,0,1};
    constexpr int dy8[8] = {-1,-1,-1,0,0,1,1,1};
    for (int gy = 1; gy < gh - 1; ++gy) for (int gx = 1; gx < gw - 1; ++gx) {
        const int start = gy * gw + gx;
        if (!edge[start] || visited[start]) continue;
        Component c; std::vector<int> stack{start}; visited[start] = 1;
        while (!stack.empty()) {
            const int cur = stack.back(); stack.pop_back(); c.cells.push_back(cur); c.score += mags[cur];
            const int x = cur % gw, y = cur / gw;
            for (int k = 0; k < 8; ++k) {
                const int nx=x+dx8[k], ny=y+dy8[k];
                if(nx<=0||nx>=gw-1||ny<=0||ny>=gh-1) continue;
                const int n=ny*gw+nx;
                if(edge[n]&&!visited[n]){visited[n]=1;stack.push_back(n);}
            }
        }
        if (c.cells.size() >= 7) {
            c.score *= std::sqrt(static_cast<double>(c.cells.size()));
            components.push_back(std::move(c));
        }
    }
    std::sort(components.begin(), components.end(), [](const Component& a,const Component& b){return a.score>b.score;});
    const int max_paths = std::min<int>(semantic ? 5 : 9, std::min<int>(e.count, components.size()));
    for (int ci=0; ci<max_paths; ++ci) {
        const auto& comp=components[ci];
        std::vector<std::uint8_t> remaining(mags.size(),0);
        for(int cell:comp.cells) remaining[cell]=1;
        auto degree=[&](int cell){int d=0,x=cell%gw,y=cell/gw;for(int k=0;k<8;k++){int nx=x+dx8[k],ny=y+dy8[k];if(nx>0&&nx<gw-1&&ny>0&&ny<gh-1&&remaining[ny*gw+nx])++d;}return d;};
        int cur=comp.cells.front();
        for(int cell:comp.cells) if(degree(cell)<=1){cur=cell;break;}
        double last_angle=0.0; bool have_angle=false; std::vector<std::pair<int,int>> path;
        while(cur>=0&&remaining[cur]){
            remaining[cur]=0;const int x=cur%gw,y=cur/gw;path.emplace_back(x*step,y*step);
            int best=-1;double best_score=1e9,best_angle=last_angle;
            for(int k=0;k<8;k++){const int nx=x+dx8[k],ny=y+dy8[k];if(nx<=0||nx>=gw-1||ny<=0||ny>=gh-1)continue;const int n=ny*gw+nx;if(!remaining[n])continue;const double a=std::atan2(static_cast<double>(ny-y),static_cast<double>(nx-x));const double turn=have_angle?std::abs(std::atan2(std::sin(a-last_angle),std::cos(a-last_angle))):0.0;const double score=turn-.0007*mags[n];if(score<best_score){best_score=score;best=n;best_angle=a;}}
            if (best < 0) break;
            cur = best;
            last_angle = best_angle;
            have_angle = true;
        }
        if(path.size()<5)continue;
        const double hue=std::fmod(185.0+ci*17.0+70.0*amount,360.0),rr=128+127*std::sin(hue*.0174533),gg=128+127*std::sin((hue+120)*.0174533),bb=128+127*std::sin((hue+240)*.0174533);
        for(std::size_t i=1;i<path.size();++i){
            draw_line(rgb,width,height,path[i-1].first,path[i-1].second,path[i].first,path[i].second,rr,gg,bb,e.opacity*amount*(semantic?.40:.34),std::max(1,static_cast<int>(e.line_width)));
        }
    }
}

void draw_native_flow(std::vector<std::uint8_t>& rgb, int width, int height,
                      const VectorEffect& e, double amount, double phase, bool particles) {
    const auto src=rgb;
    struct Seed { int x; int y; double mag; };
    std::vector<Seed> seeds;
    const int step=std::max(8,std::min(width,height)/90);
    for(int y=step;y<height-step;y+=step)for(int x=step;x<width-step;x+=step){
        const double gx=luminance(src,width,x+step/2,y)-luminance(src,width,x-step/2,y);
        const double gy=luminance(src,width,x,y+step/2)-luminance(src,width,x,y-step/2);
        const double mag=std::hypot(gx,gy);if(mag>18)seeds.push_back({x,y,mag});
    }
    std::sort(seeds.begin(),seeds.end(),[](const Seed&a,const Seed&b){return a.mag>b.mag;});
    const int count=std::min<int>(particles?24:12,std::min<int>(e.count,seeds.size()));
    const double base=std::atan2(e.motion_y,e.motion_x==0?1e-6:e.motion_x);
    for(int i=0;i<count;i++){
        const auto& seed=seeds[i];double x=seed.x,y=seed.y,angle=base+std::sin(phase*.7+i*.61)*(.12+.28*amount);const int segments=particles?2:7;
        const double ds=(particles?8.0:18.0)*(0.55+amount);
        const double hue=190+i*8,rr=128+110*std::sin(hue*.0174533),gg=150+90*std::sin((hue+120)*.0174533),bb=240;
        for(int seg=0;seg<segments;seg++){
            const double bend=std::sin(phase*.55+i*.43+seg*.7)*(.05+.14*amount);angle+=bend;
            const int nx=static_cast<int>(x+std::cos(angle)*ds),ny=static_cast<int>(y+std::sin(angle)*ds);
            draw_line(rgb,width,height,static_cast<int>(x),static_cast<int>(y),nx,ny,rr,gg,bb,e.opacity*amount*(particles?.32:.46),std::max(1,static_cast<int>(e.line_width)));
            x=nx;y=ny;if(x<0||x>=width||y<0||y>=height)break;
        }
    }
}

void draw_native_grid(std::vector<std::uint8_t>& rgb,int width,int height,const VectorEffect& e,double amount,double phase){
    const int vx=static_cast<int>(width*(.5+.22*e.motion_x+.04*std::sin(phase*.4)));
    const int vy=static_cast<int>(height*(.38+.16*e.motion_y));
    const int count=std::max(6,std::min(40,e.count));
    for(int i=0;i<=count;i++){
        const int x=static_cast<int>(static_cast<double>(i)/count*width);
        draw_line(rgb,width,height,vx,vy,x,height,80,210,255,e.opacity*amount,std::max(1,static_cast<int>(e.line_width)));
    }
    for(int j=1;j<=10;j++){
        const double q=static_cast<double>(j)/10.0, z=q*q*q;
        const int y=static_cast<int>(vy+(height-vy)*z), spread=static_cast<int>(width*(.12+.88*z));
        draw_line(rgb,width,height,vx-spread/2,y,vx+spread/2,y,120,180,255,e.opacity*amount*.8,std::max(1,static_cast<int>(e.line_width)));
    }
}

void draw_native_fracture(std::vector<std::uint8_t>& rgb,int width,int height,const VectorEffect& e,double amount,bool voronoi){
    const int n=std::max(8,std::min(64,e.count));
    std::vector<std::pair<int,int>> pts;pts.reserve(n);
    for(int i=0;i<n;i++)pts.emplace_back(static_cast<int>(unit_rand(e.seed,i*2)*width),static_cast<int>(unit_rand(e.seed,i*2+1)*height));
    if(voronoi){
        const int step=std::max(4,std::min(width,height)/180);
        for(int y=step;y<height-step;y+=step)for(int x=step;x<width-step;x+=step){
            int a=-1,b=-1;double da=1e30,db=1e30;
            for(int i=0;i<n;i++){const double dx=x-pts[i].first,dy=y-pts[i].second,d=dx*dx+dy*dy;if(d<da){db=da;b=a;da=d;a=i;}else if(d<db){db=d;b=i;}}
            if(a>=0&&b>=0&&std::abs(std::sqrt(db)-std::sqrt(da))<step*1.6)
                blend_pixel(rgb,width,height,x,y,210,100+120*unit_rand(e.seed,a),255,e.opacity*amount);
        }
    }else{
        const int cx=width/2,cy=height/2;
        std::sort(pts.begin(),pts.end(),[&](auto&a,auto&b){return std::atan2(a.second-cy,a.first-cx)<std::atan2(b.second-cy,b.first-cx);});
        for(int i=0;i<n;i++){
            auto a=pts[i],b=pts[(i+1)%n];
            draw_line(rgb,width,height,cx,cy,a.first,a.second,255,100+100*unit_rand(e.seed,i),180,e.opacity*amount,std::max(1,static_cast<int>(e.line_width)));
            draw_line(rgb,width,height,a.first,a.second,b.first,b.second,120,200,255,e.opacity*amount*.8,std::max(1,static_cast<int>(e.line_width)));
        }
    }
}

void draw_native_glyph(std::vector<std::uint8_t>& rgb,int width,int height,const VectorEffect& e,double amount,double phase){
    const int arms=std::max(3,std::min(12,e.count)),cx=width/2,cy=height/2;
    const double radius=std::min(width,height)*(.05+.09*amount);
    for(int a=0;a<arms;a++){
        double angle=static_cast<double>(a)/arms*6.28318530718+phase*.08;
        int px=cx,py=cy;
        for(int n=1;n<=6;n++){
            angle+=std::sin(e.seed*.001+n*1.7)*.18;
            const double r=radius*n/6.0;
            const int x=cx+static_cast<int>(std::cos(angle)*r),y=cy+static_cast<int>(std::sin(angle)*r);
            draw_line(rgb,width,height,px,py,x,y,170,100+120*unit_rand(e.seed,n+a*7),255,e.opacity*amount,std::max(1,static_cast<int>(e.line_width)));
            px=x;py=y;
        }
    }
}

void apply_native_displacement(std::vector<std::uint8_t>& rgb,int width,int height,const VectorEffect& e,double amount,double phase){
    const auto src=rgb;const int strips=std::max(6,std::min(36,e.count));const int sh=std::max(1,height/strips);
    for(int s=0;s<strips;s++){
        const int y0=s*sh,y1=std::min(height,y0+sh);
        const int dx=static_cast<int>(std::sin(phase*(1.4+amount*2)+s*.73+e.seed*.0001)*width*.026*amount);
        const int dy=static_cast<int>(std::cos(phase*1.31+s*.37)*height*.008*amount);
        for(int y=y0;y<y1;y++)for(int x=0;x<width;x++){
            const int sx=std::clamp(x-dx,0,width-1),sy=std::clamp(y-dy,0,height-1);
            const auto di=static_cast<std::size_t>((y*width+x)*3),si=static_cast<std::size_t>((sy*width+sx)*3);
            rgb[di]=clamp8(src[di]*(1-.32*amount)+src[si]*.32*amount);
            rgb[di+1]=clamp8(src[di+1]*(1-.32*amount)+src[si+1]*.32*amount);
            rgb[di+2]=clamp8(src[di+2]*(1-.32*amount)+src[si+2]*.32*amount);
        }
    }
}

void apply_native_portal(std::vector<std::uint8_t>& rgb,const std::vector<std::uint8_t>* companion,
                         int width,int height,const VectorEffect& e,double amount,double phase){
    if(!companion||companion->size()!=rgb.size())return;
    const double radius=std::min(width,height)*(e.radius>0?e.radius:(.12+.18*amount));
    const double cx=width*(.5+.18*std::sin(phase*.7+e.seed*.001)),cy=height*(.5+.14*std::cos(phase*.55+e.seed*.002));
    for(int y=0;y<height;y++)for(int x=0;x<width;x++){
        const double dx=x-cx,dy=y-cy,rr=std::sqrt(dx*dx+dy*dy);
        const double wobble=radius*(1+.10*std::sin(std::atan2(dy,dx)*5+phase*1.7));
        if(rr>wobble)continue;
        const double edge=std::clamp((wobble-rr)/std::max(1.0,radius*.16),0.0,1.0);
        const double a=e.opacity*amount*edge;
        const auto i=static_cast<std::size_t>((y*width+x)*3);
        rgb[i]=clamp8(rgb[i]*(1-a)+(*companion)[i]*a);
        rgb[i+1]=clamp8(rgb[i+1]*(1-a)+(*companion)[i+1]*a);
        rgb[i+2]=clamp8(rgb[i+2]*(1-a)+(*companion)[i+2]*a);
    }
}

} // namespace

void apply_vector_effects(
    std::vector<std::uint8_t>& rgb,
    const std::vector<std::uint8_t>* companion,
    const std::vector<std::uint8_t>* previous,
    int width,
    int height,
    const std::vector<VectorEffect>& effects,
    double progress,
    double phase
) {
    for(const auto& e:effects){
        const double amount=effect_amount(e,progress);
        if(amount<=.012)continue;
        if(e.kind=="contours") draw_native_contours(rgb,width,height,e,amount,false);
        else if(e.kind=="semantic_outline") draw_native_contours(rgb,width,height,e,amount,true);
        else if(e.kind=="flow_ribbons") draw_native_flow(rgb,width,height,e,amount,phase,false);
        else if(e.kind=="flow_particles") draw_native_flow(rgb,width,height,e,amount,phase,true);
        else if(e.kind=="vector_echo"){
            draw_native_contours(rgb,width,height,e,amount*.5,false);
            if(previous&&previous->size()==rgb.size()) blend_layer(rgb,*previous,e.opacity*amount*.16,"screen");
        }
        else if(e.kind=="perspective_grid") draw_native_grid(rgb,width,height,e,amount,phase);
        else if(e.kind=="delaunay_fracture"){ if(e.displace)apply_native_displacement(rgb,width,height,e,amount*e.explode,phase); if(e.visible)draw_native_fracture(rgb,width,height,e,amount,false); }
        else if(e.kind=="voronoi"){ if(e.displace)apply_native_displacement(rgb,width,height,e,amount*.35,phase); if(e.visible)draw_native_fracture(rgb,width,height,e,amount,true); }
        else if(e.kind=="portal") apply_native_portal(rgb,companion,width,height,e,amount,phase);
        else if(e.kind=="motif_glyph") draw_native_glyph(rgb,width,height,e,amount,phase);
        else if(e.kind=="vector_displacement") apply_native_displacement(rgb,width,height,e,amount,phase);
    }
}

void blend_layer(
    std::vector<std::uint8_t>& dst,
    const std::vector<std::uint8_t>& src,
    double opacity,
    const std::string& mode
) {
    if (dst.size() != src.size()) return;
    const double a = std::clamp(opacity, 0.0, 1.0);
#ifdef TUBEVIZ_HAVE_OPENMP
#pragma omp parallel for schedule(static)
#endif
    for (std::int64_t idx = 0; idx < static_cast<std::int64_t>(dst.size()); ++idx) {
        const auto i = static_cast<std::size_t>(idx);
        const double d = dst[i] / 255.0;
        const double sv = src[i] / 255.0;
        double mixed = sv;
        if (mode == "screen") mixed = 1.0 - (1.0 - d) * (1.0 - sv);
        else if (mode == "multiply") mixed = d * sv;
        else if (mode == "overlay")
            mixed = d < 0.5
                ? 2.0 * d * sv
                : 1.0 - 2.0 * (1.0 - d) * (1.0 - sv);
        else if (mode == "lighten") mixed = std::max(d, sv);
        const double out = d * (1.0 - a) + mixed * a;
        dst[i] = clamp8(out * 255.0);
    }
}

void crossfade(
    std::vector<std::uint8_t>& dst,
    const std::vector<std::uint8_t>& previous,
    double amount
) {
    if (dst.size() != previous.size()) return;
    const double a = std::clamp(amount, 0.0, 1.0);
#ifdef TUBEVIZ_HAVE_OPENMP
#pragma omp parallel for schedule(static)
#endif
    for (std::int64_t idx = 0; idx < static_cast<std::int64_t>(dst.size()); ++idx) {
        const auto i = static_cast<std::size_t>(idx);
        dst[i] = clamp8(previous[i] * (1.0 - a) + dst[i] * a);
    }
}

} // namespace tubeviz
