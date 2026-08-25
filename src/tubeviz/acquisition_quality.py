# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations
from pathlib import Path
import math
import numpy as np


def _cv2():
    try:
        import cv2
        return cv2
    except ImportError as exc:
        raise RuntimeError("quality acquisition requires opencv-python-headless; reinstall tubeviz") from exc


def _text_mask(gray):
    """Detect text-like high-contrast horizontal glyph groups; no OCR is performed."""
    cv2=_cv2(); h,w=gray.shape[:2]
    # blackhat catches dark glyphs on bright backgrounds; gradient catches either polarity.
    rect=cv2.getStructuringElement(cv2.MORPH_RECT,(17,5))
    bh=cv2.morphologyEx(gray,cv2.MORPH_BLACKHAT,rect)
    grad=cv2.morphologyEx(gray,cv2.MORPH_GRADIENT,cv2.getStructuringElement(cv2.MORPH_RECT,(3,3)))
    x=cv2.max(bh,grad)
    _,bw=cv2.threshold(x,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)
    bw=cv2.morphologyEx(bw,cv2.MORPH_CLOSE,cv2.getStructuringElement(cv2.MORPH_RECT,(11,3)),iterations=1)
    mask=np.zeros_like(gray,dtype=np.uint8)
    contours,_=cv2.findContours(bw,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    for c in contours:
        x,y,cw,ch=cv2.boundingRect(c); area=cw*ch
        if area < max(35, h*w*0.00008): continue
        if ch < max(5,h*0.008) or ch > h*0.22: continue
        if cw < ch*1.4 or cw > w*0.98: continue
        roi=bw[y:y+ch,x:x+cw]
        fill=float(np.count_nonzero(roi))/max(1,area)
        if .08 <= fill <= .75:
            cv2.rectangle(mask,(x,y),(x+cw,y+ch),255,-1)
    return mask


def analyze_video_quality(path: str|Path, *, max_frames:int=48) -> dict:
    cv2=_cv2(); cap=cv2.VideoCapture(str(path))
    if not cap.isOpened(): raise RuntimeError(f"cannot open preview: {path}")
    count=int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0); fps=float(cap.get(cv2.CAP_PROP_FPS) or 0) or 24.0
    wanted=max(8,min(max_frames,count if count>0 else max_frames))
    indices=np.linspace(0,max(0,count-1),wanted,dtype=int) if count>0 else np.arange(wanted)
    frames=[]
    for idx in indices:
        if count>0: cap.set(cv2.CAP_PROP_POS_FRAMES,int(idx))
        ok,frame=cap.read()
        if not ok: continue
        h,w=frame.shape[:2]
        scale=min(1.0,480/max(h,w))
        if scale<1: frame=cv2.resize(frame,(int(w*scale),int(h*scale)),interpolation=cv2.INTER_AREA)
        frames.append(frame)
    cap.release()
    if len(frames)<3: raise RuntimeError("preview has too few decodable frames")

    grays=[cv2.cvtColor(f,cv2.COLOR_BGR2GRAY) for f in frames]
    text_masks=[_text_mask(g) for g in grays]
    text_ratios=[float(np.count_nonzero(m))/m.size for m in text_masks]
    persistent=np.mean(np.stack([(m>0).astype(np.float32) for m in text_masks]),axis=0)
    persistent_text=float(np.mean(persistent>=0.45))
    large_text_fraction=float(np.mean([r>=0.12 for r in text_ratios]))

    flows=[]; coverages=[]; directions=[]; frame_diffs=[]
    for a,b in zip(grays,grays[1:]):
        flow=cv2.calcOpticalFlowFarneback(a,b,None,.5,3,15,3,5,1.2,0)
        mag,ang=cv2.cartToPolar(flow[...,0],flow[...,1])
        p90=float(np.percentile(mag,90)); threshold=max(.35,p90*.18)
        active=mag>threshold
        flows.append(float(np.mean(np.clip(mag/8.0,0,1))))
        coverages.append(float(np.mean(active)))
        if np.any(active):
            hist,_=np.histogram(ang[active],bins=12,range=(0,2*math.pi),density=False)
            p=hist/(hist.sum()+1e-9); directions.append(float(-(p*np.log2(p+1e-12)).sum()/math.log2(12)))
        frame_diffs.append(float(np.mean(cv2.absdiff(a,b))/255.0))

    # Face dominance: use OpenCV's bundled frontal-face cascade. It is a penalty, not identity analysis.
    cascade_path=str(Path(cv2.data.haarcascades)/'haarcascade_frontalface_default.xml')
    face=cv2.CascadeClassifier(cascade_path); face_ratios=[]
    for g in grays:
        boxes=face.detectMultiScale(g,scaleFactor=1.15,minNeighbors=4,minSize=(30,30)) if not face.empty() else []
        face_ratios.append(sum(w*h for x,y,w,h in boxes)/g.size)

    sharp=[]; exposure=[]; saturation=[]
    for f,g in zip(frames,grays):
        sharp.append(min(1.0,float(cv2.Laplacian(g,cv2.CV_64F).var())/900.0))
        mean=float(np.mean(g))/255.0
        exposure.append(max(0.0,1.0-abs(mean-.48)/.48))
        hsv=cv2.cvtColor(f,cv2.COLOR_BGR2HSV); saturation.append(float(np.mean(hsv[...,1]))/255.0)
    aesthetic=float(np.clip(.45*np.mean(sharp)+.35*np.mean(exposure)+.20*np.mean(saturation),0,1))
    temporal=float(np.clip(np.mean(frame_diffs)*5.0,0,1))
    flow_mean=float(np.mean(flows)); flow_cov=float(np.mean(coverages)); flow_entropy=float(np.mean(directions) if directions else 0)
    # Requires broad spatial motion, not merely a small animated caption/logo.
    dynamic=float(np.clip(.34*flow_mean+.42*flow_cov+.14*flow_entropy+.10*temporal,0,1))
    return {
        'frame_count':len(frames),'fps':fps,
        'text_overlay_fraction':float(np.mean(text_ratios)),
        'text_overlay_peak':float(max(text_ratios)),
        'persistent_text_fraction':persistent_text,
        'large_text_frame_fraction':large_text_fraction,
        'flow_mean':flow_mean,'motion_coverage':flow_cov,'flow_direction_entropy':flow_entropy,
        'temporal_diversity':temporal,'face_dominance':float(np.mean(face_ratios)),
        'aesthetic_score':aesthetic,'dynamic':dynamic,
    }


def quality_failures(q:dict, *, max_text:float=.10, max_persistent_text:float=.045,
                     max_face:float=.42, min_motion_coverage:float=.20,
                     min_temporal_diversity:float=.12, min_aesthetic:float=.22) -> list[str]:
    failures=[]
    if q['text_overlay_fraction']>max_text: failures.append(f"text occupancy {q['text_overlay_fraction']:.3f} > {max_text:.3f}")
    if q['persistent_text_fraction']>max_persistent_text: failures.append(f"persistent text {q['persistent_text_fraction']:.3f} > {max_persistent_text:.3f}")
    if q['face_dominance']>max_face: failures.append(f"face dominance {q['face_dominance']:.3f} > {max_face:.3f}")
    if q['motion_coverage']<min_motion_coverage: failures.append(f"motion coverage {q['motion_coverage']:.3f} < {min_motion_coverage:.3f}")
    if q['temporal_diversity']<min_temporal_diversity: failures.append(f"temporal diversity {q['temporal_diversity']:.3f} < {min_temporal_diversity:.3f}")
    if q['aesthetic_score']<min_aesthetic: failures.append(f"aesthetic {q['aesthetic_score']:.3f} < {min_aesthetic:.3f}")
    return failures
