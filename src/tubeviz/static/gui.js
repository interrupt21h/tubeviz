const $=id=>document.getElementById(id);
let activeJob=null;
let pollTimer=null;
let activeTrim=null;

function value(id){return $(id).value.trim()}
function number(id){return Number($(id).value)}
function checked(id){return $(id).checked}
function qs(obj){return new URLSearchParams(Object.entries(obj).filter(([,v])=>v!==undefined&&v!==null&&v!=="")).toString()}

async function api(url, options={}){
  const response=await fetch(url,{headers:{"Content-Type":"application/json"},...options});
  if(!response.ok){
    let detail=await response.text();
    try{detail=JSON.parse(detail).detail||detail}catch{}
    throw new Error(detail);
  }
  const type=response.headers.get("content-type")||"";
  return type.includes("application/json")?response.json():response.text();
}

function setStats(el,data){
  el.innerHTML=Object.entries(data).map(([k,v])=>`<span><b>${v}</b> ${k.replaceAll("_"," ")}</span>`).join("");
}

async function init(){
  const cfg=await api("/api/gui/config");
  $("libraryPath").value=cfg.library;
  const n=cfg.native;
  const ok=!!n.renderer;
  $("nativeBadge").textContent=ok?`native: ${n.renderer.split("/").pop()}`:"native: not built";
  $("nativeBadge").classList.add(ok?"ok":"warn");
  await refreshLibrarySummary();
  loadClips();
  refreshJobs();
}

document.querySelectorAll(".tab").forEach(btn=>btn.onclick=()=>{
  document.querySelectorAll(".tab").forEach(x=>x.classList.remove("active"));
  document.querySelectorAll(".panel").forEach(x=>x.classList.remove("active"));
  btn.classList.add("active");
  $(btn.dataset.tab).classList.add("active");
  if(btn.dataset.tab==="library") loadClips();
  if(btn.dataset.tab==="jobs") refreshJobs();
});

async function refreshLibrarySummary(){
  try{
    const data=await api(`/api/gui/library?${qs({library:value("libraryPath"),limit:1})}`);
    setStats($("projectStats"),data.stats);
    setStats($("libraryStats"),data.stats);
  }catch(e){$("projectStats").textContent=e.message}
}

async function startJob(kind, payload){
  try{
    const job=await api("/api/gui/jobs",{method:"POST",body:JSON.stringify({kind,...payload})});
    activeJob=job.id;
    $("cancelJob").disabled=false;
    $("jobLog").textContent=(job.log||[]).join("\n");
    pollActiveJob();
  }catch(e){$("jobLog").textContent=`Error: ${e.message}`}
}

function projectBase(){
  return {library:value("libraryPath"),audio:value("audioPath")||null,timeline:value("timelinePath")||null,output:value("outputPath")||null};
}

$("analyzeBtn").onclick=()=>{
  if(!value("timelinePath") && value("audioPath")){
    const base=value("audioPath").split("/").pop().replace(/\.[^.]+$/,"");
    $("timelinePath").value=`timelines/${base}.json`;
  }
  return startJob("analyze",{
  library:value("libraryPath"),
  audio:value("audioPath")||null,
  output:value("timelinePath")||"timeline.json",
  options:{
    semantic:checked("semantic"),semantic_device:value("semanticDevice"),
    section_bars:number("sectionBars"),max_video_layers:number("maxLayers"),
    transform_intensity:number("transformIntensity"),composition_intensity:number("compositionIntensity"),
    target_unique_clips:number("targetUnique"),novelty_weight:number("noveltyWeight"),
    visual_match_weight:number("visualMatchWeight"),transition_weight:number("transitionWeight"),
    vector_effects:checked("vectorEffects"),vector_intensity:number("vectorIntensity"),
    rhythm_alignment:checked("rhythmAlignment"),
    selection_variation:.30,min_shot_seconds:number("minShot"),max_shot_seconds:number("maxShot"),
    source_excerpt_max_seconds:number("maxExcerpt"),reshuffle:checked("reshuffle"),
    dynamic_shots:checked("dynamicShots")
  }
  });
};

$("renderBtn").onclick=()=>startJob("render",{
  ...projectBase(),
  options:{
    backend:value("backend"),width:number("width"),height:number("height"),fps:number("fps"),
    crf:number("crf"),video_codec:value("codec"),native_preset:value("nativePreset"),
    native_decoder_cache:number("decoderCache"),native_threads:number("nativeThreads"),
    native_build_if_missing:checked("buildMissing")
  }
});

$("ingestBtn").onclick=()=>startJob("ingest",{
  library:value("libraryPath"),terms:value("termsPath"),
  options:{
    results_per_term:number("resultsPerTerm"),hard_max_duration:number("hardMaxDuration"),
    cookies_from_browser:value("cookiesBrowser")||null,ai_discovery:checked("aiDiscovery"),
    ai_device:value("aiDevice"),ai_candidates_per_term:number("aiCandidates"),
    ai_query_count:number("aiQueries"),visual_index_scenes:checked("visualIndexScenes")
  }
});

$("nativeBuildBtn").onclick=()=>startJob("native-build",{library:value("libraryPath"),options:{clean:true}});
$("visualIndexBtn").onclick=()=>startJob("visual-index",{library:value("libraryPath"),options:{force:true,fps:6,max_frames:180}});
$("previewBtn").onclick=()=>{
  const preview=window.open("about:blank","tubevizPreview");
  startJob("preview",{...projectBase(),options:{port:8080,host:"127.0.0.1"}});
  setTimeout(()=>{if(preview)preview.location="http://127.0.0.1:8080/"},1200);
};
$("refreshLibrary").onclick=()=>{refreshLibrarySummary();loadClips()};
$("cancelJob").onclick=async()=>{
  if(!activeJob)return;
  await api(`/api/gui/jobs/${activeJob}/cancel`,{method:"POST"});
};

async function pollActiveJob(){
  if(pollTimer)clearTimeout(pollTimer);
  if(!activeJob)return;
  try{
    const job=await api(`/api/gui/jobs/${activeJob}?tail=800`);
    $("jobLog").textContent=(job.log||[]).join("\n");
    $("jobLog").scrollTop=$("jobLog").scrollHeight;
    const running=["queued","running","cancelling"].includes(job.status);
    $("cancelJob").disabled=!running;
    if(running){
      pollTimer=setTimeout(pollActiveJob,700);
    }else{
      refreshLibrarySummary();
      refreshJobs();
      activeJob=null;
    }
  }catch(e){
    $("jobLog").textContent+=`\n${e.message}`;
  }
}

async function loadClips(){
  const grid=$("clipGrid");
  grid.innerHTML="<p>Loading…</p>";
  try{
    const params={
      library:value("libraryPath"),
      status:value("statusFilter"),
      term:value("termFilter"),
      limit:300
    };
    const data=await api(`/api/gui/library?${qs(params)}`);
    setStats($("libraryStats"),data.stats);
    if(!data.clips.length){grid.innerHTML="<p>No clips matched.</p>";return}
    grid.innerHTML=data.clips.map(c=>{
      const enc=encodeURIComponent(c.source_id);
      const lp=encodeURIComponent(value("libraryPath"));
      const rejected=c.status==="rejected_manual";
      return `<div class="clip">
        <img loading="lazy" src="/api/gui/clip/${enc}/thumbnail?library=${lp}" onerror="this.style.opacity=.15">
        <div class="clip-body">
          <div class="clip-title">${escapeHtml(c.title||c.source_id)}</div>
          <div class="clip-meta">${escapeHtml(c.source_id)} · ${c.status} · ${c.scene_count} scenes · ${c.duration?Number(c.duration).toFixed(1)+"s":"?"}</div>
          ${(c.usable_start!=null||c.usable_end!=null)?`<div class="clip-trim-badge">trimmed ${formatTime(c.usable_start??0)} → ${formatTime(c.usable_end??c.duration??0)}</div>`:""}
          <div class="clip-actions">
            ${c.media_available
              ?`<button onclick="playClip('${jsq(c.source_id)}','${jsq(c.source)}','${jsq(c.title||c.source_id)}')">Play / Trim</button>`
              :`<button disabled title="No playable local media">No media</button>`}
            ${rejected
              ?`<button onclick="restoreClip('${jsq(c.source_id)}')">Restore</button>`
              :`<button onclick="rejectClip('${jsq(c.source_id)}')">Reject</button>`}
            <button class="danger" onclick="deleteClip('${jsq(c.source_id)}')">Delete</button>
          </div>
        </div>
      </div>`;
    }).join("");
  }catch(e){grid.innerHTML=`<p>${escapeHtml(e.message)}</p>`}
}

function escapeHtml(s){return String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]))}
function jsq(s){return String(s).replaceAll("\\","\\\\").replaceAll("'","\\'")}

function formatTime(seconds){
  const value=Math.max(0,Number(seconds)||0),minutes=Math.floor(value/60),secs=value-minutes*60;
  return `${minutes}:${secs.toFixed(3).padStart(6,"0")}`;
}
function clampTrim(){
  if(!activeTrim)return;
  const duration=Math.max(.05,activeTrim.duration||Number($("modalVideo").duration)||0);
  let tin=Number($("trimIn").value),tout=Number($("trimOut").value);
  tin=Math.max(0,Math.min(duration-.05,tin));
  tout=Math.max(.05,Math.min(duration,tout));
  if(tout<=tin+.05){
    if(document.activeElement===$("trimIn"))tin=Math.max(0,tout-.05);
    else tout=Math.min(duration,tin+.05);
  }
  $("trimIn").value=tin;$("trimOut").value=tout;
  activeTrim.in=tin;activeTrim.out=tout;
  const left=100*tin/duration,right=100*tout/duration;
  $("trimTrackKeep").style.left=`${left}%`;
  $("trimTrackKeep").style.width=`${Math.max(0,right-left)}%`;
  $("trimInLabel").textContent=formatTime(tin);
  $("trimOutLabel").textContent=formatTime(tout);
  $("trimDurationLabel").textContent=formatTime(tout-tin);
  const trimmed=tin>.001||tout<duration-.001;
  $("trimStatus").textContent=trimmed
    ?`Visualizer may use only ${formatTime(tin)} – ${formatTime(tout)} (${formatTime(tout-tin)} kept)`
    :`Entire ${formatTime(duration)} clip is currently usable`;
}
function seekTrim(value){
  const video=$("modalVideo");
  if(Number.isFinite(value))video.currentTime=Math.max(0,Math.min(video.duration||value,value));
}
async function initializeTrimEditor(id,source,title){
  const params=qs({library:value("libraryPath"),source});
  const details=await api(`/api/gui/clip/${encodeURIComponent(id)}?${params}`);
  const video=$("modalVideo");
  const setup=()=>{
    const duration=Number.isFinite(video.duration)&&video.duration>0?video.duration:Number(details.duration||0);
    const tin=details.usable_start==null?0:Number(details.usable_start);
    const tout=details.usable_end==null?duration:Number(details.usable_end);
    activeTrim={id,source,title,duration,in:tin,out:tout,scenes:details.scenes||[]};
    $("trimSceneMarkers").innerHTML=(details.scenes||[]).flatMap(scene=>[scene.start,scene.end]).filter((t,i,a)=>t>0&&t<duration&&a.indexOf(t)===i).map(t=>`<i class="trim-scene-marker" style="left:${(100*Number(t)/duration).toFixed(4)}%" title="scene boundary ${formatTime(t)}"></i>`).join("");
    for(const range of [$("trimIn"),$("trimOut")]){range.max=duration;range.step=Math.max(.01,Math.min(.05,duration/5000));}
    $("trimIn").value=tin;$("trimOut").value=tout;
    clampTrim();seekTrim(tin);
  };
  if(video.readyState>=1&&Number.isFinite(video.duration))setup();
  else video.onloadedmetadata=setup;
}
window.playClip=async(id,source,title)=>{
  $("modalTitle").textContent=title;
  $("trimStatus").textContent="Loading clip…";
  activeTrim=null;
  const params=qs({library:value("libraryPath"),source});
  const video=$("modalVideo");
  video.src=`/api/gui/clip/${encodeURIComponent(id)}/media?${params}`;
  video.onerror=async()=>{
    try{
      const response=await fetch(video.src),body=await response.json(),detail=body.detail||body;
      $("modalTitle").textContent=`${title} — ${detail.message||"media unavailable"}`;
      console.error("tubeviz media diagnostic",detail);
    }catch(e){console.error("tubeviz playback error",e)}
  };
  $("videoModal").classList.remove("hidden");
  video.load();
  try{await initializeTrimEditor(id,source,title)}catch(e){$("trimStatus").textContent=`Trim editor error: ${e.message}`}
  video.play().catch(()=>{});
};
$("trimIn").oninput=()=>{clampTrim();seekTrim(Number($("trimIn").value))};
$("trimOut").oninput=()=>{clampTrim();seekTrim(Math.max(0,Number($("trimOut").value)-.03))};
$("setTrimIn").onclick=()=>{if(!activeTrim)return;$("trimIn").value=$("modalVideo").currentTime;clampTrim()};
$("setTrimOut").onclick=()=>{if(!activeTrim)return;$("trimOut").value=$("modalVideo").currentTime;clampTrim()};
$("jumpTrimIn").onclick=()=>activeTrim&&seekTrim(activeTrim.in);
$("jumpTrimOut").onclick=()=>activeTrim&&seekTrim(Math.max(activeTrim.in,activeTrim.out-.05));
$("modalVideo").ontimeupdate=()=>{
  if(!activeTrim)return;
  const video=$("modalVideo"),pct=100*Math.max(0,Math.min(activeTrim.duration,video.currentTime))/Math.max(.05,activeTrim.duration);
  $("trimPlayhead").style.left=`${pct}%`;
  if(!checked("loopTrim"))return;
  if(video.currentTime>=activeTrim.out-.015||video.currentTime<activeTrim.in-.05){
    video.currentTime=activeTrim.in;
    if(!video.paused)video.play().catch(()=>{});
  }
};
$("saveTrim").onclick=async()=>{
  if(!activeTrim)return;
  clampTrim();
  try{
    const result=await api(`/api/gui/clip/${encodeURIComponent(activeTrim.id)}/trim`,{
      method:"POST",body:JSON.stringify({
        library:value("libraryPath"),source:activeTrim.source,
        usable_start:activeTrim.in,usable_end:activeTrim.out
      })
    });
    activeTrim.in=result.usable_start??0;
    activeTrim.out=result.usable_end??activeTrim.duration;
    $("trimIn").value=activeTrim.in;$("trimOut").value=activeTrim.out;clampTrim();
    $("trimStatus").textContent+=` · saved`;
    loadClips();refreshLibrarySummary();
  }catch(e){$("trimStatus").textContent=`Save failed: ${e.message}`}
};
$("clearTrim").onclick=async()=>{
  if(!activeTrim)return;
  try{
    await api(`/api/gui/clip/${encodeURIComponent(activeTrim.id)}/trim/clear`,{
      method:"POST",body:JSON.stringify({library:value("libraryPath"),source:activeTrim.source})
    });
    activeTrim.in=0;activeTrim.out=activeTrim.duration;
    $("trimIn").value=0;$("trimOut").value=activeTrim.duration;clampTrim();seekTrim(0);
    $("trimStatus").textContent+=` · trim cleared`;
    loadClips();refreshLibrarySummary();
  }catch(e){$("trimStatus").textContent=`Clear failed: ${e.message}`}
};
$("closeModal").onclick=()=>{
  const video=$("modalVideo");video.pause();video.removeAttribute("src");video.load();video.onloadedmetadata=null;
  activeTrim=null;$("videoModal").classList.add("hidden");
};

window.rejectClip=async id=>{
  const reason=prompt("Reason (optional):","not useful for visualizer");
  if(reason===null)return;
  await api(`/api/gui/clip/${encodeURIComponent(id)}/reject`,{
    method:"POST",body:JSON.stringify({library:value("libraryPath"),reason})
  });
  loadClips();refreshLibrarySummary();
};
window.restoreClip=async id=>{
  await api(`/api/gui/clip/${encodeURIComponent(id)}/restore`,{
    method:"POST",body:JSON.stringify({library:value("libraryPath")})
  });
  loadClips();refreshLibrarySummary();
};
window.deleteClip=async id=>{
  if(!confirm(`Permanently delete ${id} and its derived files?`))return;
  await api(`/api/gui/clip/${encodeURIComponent(id)}/delete`,{
    method:"POST",body:JSON.stringify({library:value("libraryPath"),keep_original:false})
  });
  loadClips();refreshLibrarySummary();
};

async function refreshJobs(){
  try{
    const jobs=await api("/api/gui/jobs");
    $("jobsList").innerHTML=jobs.length?jobs.map(j=>`
      <div class="job-row">
        <div><b>${escapeHtml(j.kind)}</b> <span class="status-${j.status}">${j.status}</span> <code>${j.id}</code></div>
        <div class="clip-meta">${escapeHtml(j.command.join(" "))}</div>
        <button onclick="watchJob('${j.id}')">View log</button>
      </div>`).join(""):"<p>No jobs yet.</p>";
  }catch(e){$("jobsList").textContent=e.message}
}
window.watchJob=id=>{
  activeJob=id;
  document.querySelector('[data-tab="create"]').click();
  pollActiveJob();
};
$("refreshJobs").onclick=refreshJobs;
$("loadClips").onclick=loadClips;
$("statusFilter").onchange=loadClips;
$("termFilter").onkeydown=e=>{if(e.key==="Enter")loadClips()};

init().catch(e=>console.error(e));
