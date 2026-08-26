// SPDX-License-Identifier: Apache-2.0
const $=id=>document.getElementById(id);
let activeJob=null;
let pollTimer=null;
let activeTrim=null;
let cliSchema=null;
let commandJobId=null;
let commandPollTimer=null;
let libraryClips=[];
let aiSettings={ai_enabled:true,vision_enabled:false};

function value(id){return $(id).value.trim()}
function number(id){return Number($(id).value)}
function checked(id){return $(id).checked}
function qs(obj){return new URLSearchParams(Object.entries(obj).filter(([,v])=>v!==undefined&&v!==null&&v!=="")).toString()}

const STATIC_HELP={
  libraryPath:"Root of the persistent tubeviz clip library. Metadata, normalized media, thumbnails, embeddings, visual features, transforms, and codec-glitch cache assets live below this directory.",
  audioPath:"Audio track used for analysis, preview, and rendering. Relative paths resolve from Studio's project root.",
  timelinePath:"Directed timeline JSON produced by Analyze. Preview and Render use the currently selected timeline.",
  outputPath:"Destination video path for final rendering.",
  hfToken:"Optional Hugging Face access token for this Studio session. Leave blank to inherit server-side HF_TOKEN. The environment token value is never sent to the browser.",
  sectionBars:"Preferred musical section length in bars. Larger values produce broader structural sections; dynamic shots can still cut within them.",
  maxLayers:"Maximum simultaneous video layers available to the composition director.",
  transformIntensity:"Strength of the legacy per-shot transform plan. This remains separate from the semantic creative renderer so either vocabulary can be reduced independently.",
  creativeIntensity:"Global strength of the semantic creative renderer. It controls motion-field deformation, temporal memory, saliency camera movement, pseudo-depth, recursive feedback, source-derived textures, palette propagation, and rare hero moments. Values around 0.7–1.2 retain recognizable footage while giving musical events room to escalate.",
  compositionIntensity:"Strength/frequency of multi-source compositions such as splits, mosaics, masks, and layered treatment.",
  targetUnique:"Desired number of unique source clips. Zero lets tubeviz scale diversity automatically from track duration and library size.",
  noveltyWeight:"Rewards clips that have not been used recently. Higher values increase visual variety but can reduce semantic continuity.",
  visualMatchWeight:"Weight given to motion, brightness, saturation, complexity, and other visual-feature compatibility with the current musical state.",
  transitionWeight:"Controls how strongly adjacent-shot continuity or contrast affects scene selection. High values make transitions more deliberate.",
  trajectoryStrength:"How strongly rising/falling musical tension changes clip motion, complexity, cut density, transforms, and payoff contrast.",
  anticipationSeconds:"How far ahead tubeviz begins visually preparing for an approaching peak/drop. Larger values create longer escalation arcs.",
  sequenceLookahead:"How many future beat-aligned shots are evaluated together. More lookahead can improve coherence at additional planning cost.",
  sequenceBeamWidth:"Number of competing multi-shot edit paths retained during lookahead search. Higher values explore more alternatives.",
  effectCompatibilityWeight:"Prefer footage whose natural motion/complexity is compatible with the intended effect family, reducing effects that fight the source.",
  preferenceWeight:"Strength of the soft preference signal learned from manually rejected clips. It never becomes a hard blacklist.",
  preferenceLearning:"Use repeated manual rejects as negative examples in visual-feature space so future candidate ranking gradually avoids similar footage.",
  choreography:"Enable phrase-aware build/drop/release analysis, pre-drop withholding, payoff shaping, and multi-shot sequence optimization.",
  vectorIntensity:"Global strength of footage-derived vector effects. Lower this if contours/flow geometry becomes too visually dominant.",
  codecGlitch:"Schedules FFglitch codec-space effects. 'musical' reserves them for musically meaningful moments; 'aggressive' uses them more often.",
  codecGlitchIntensity:"Global strength of scheduled FFglitch motion-vector/datamosh effects.",
  minShot:"Shortest dynamic shot duration in seconds. Raising this is one of the best ways to make an edit less erratic.",
  maxShot:"Maximum dynamic shot duration in seconds.",
  maxExcerpt:"Maximum amount of a selected source scene used for one shot; tubeviz can take short excerpts rather than playing an entire clip.",
  semanticDevice:"Device for OpenCLIP semantic scene selection, e.g. auto, cpu, cuda, or cuda:0.",
  audioAiDevice:"Device for CLAP audio-semantic inference, e.g. auto, cpu, cuda, or cuda:0. Auto now falls back when the installed torch wheel lacks kernels for the detected GPU.",
  musicAiDevice:"Device for optional MERT music-representation inference. Auto validates CUDA compute-capability support before choosing the GPU.",
  musicAiModel:"Optional Hugging Face MERT model used for music-specific representation dynamics. The default model uses trust_remote_code=True and is not required for ordinary tubeviz operation.",
  musicAi:"Enable optional MERT embeddings to measure musical-state novelty/velocity and strengthen structural cut/transition decisions.",
  audioVisualWeight:"Strength of CLAP-audio ↔ OpenCLIP-scene concept matching in candidate ranking.",
  audioAiWindow:"Length in seconds of each CLAP analysis window.",
  audioAiHop:"Seconds between successive CLAP windows. Smaller hops provide finer temporal semantic tracking at greater inference cost.",
  aiDirectorStrength:"Blend strength between deterministic tubeviz direction and the optional LLM whole-song treatment plan.",
  semantic:"Enable OpenCLIP semantic retrieval for scene selection.",
  audioAi:"Enable CLAP audio-semantic interpretation and cross-modal scene matching.",
  aiDirector:"Enable the whole-song LLM planning pass. It receives a compact manifest of the actual eligible library and enabled renderer effects before proposing the visual arc.",
  aiEditConsultant:"Second AI pass: for each section, rank only a bounded slate of scene IDs already validated by tubeviz. Hard timing, trim, cooldown and media constraints remain deterministic.",
  aiConsultantCandidates:"Maximum valid scene candidates exposed to the AI edit consultant per musical section. Higher values improve choice diversity but increase prompt size.",
  aiConsultantWeight:"Soft preference strength for the bounded AI consultant. It can break close ranking decisions but cannot bypass hard constraints.",
  reshuffle:"Generate a fresh selection seed for an alternate cut while preserving deterministic behavior within that run.",
  dynamicShots:"Allow beat-aligned shots inside broader musical sections rather than one scene per section.",
  rhythmAlignment:"Search source offsets/playback rates so natural motion accents in footage align with musical beats.",
  creativeEffects:"Enable the semantic creative renderer. Disable this to retain legacy transforms/vector effects without optical-flow deformation, temporal memory, virtual camera, depth/parallax, source-derived textures, recursive feedback, or hero effects.",
  vectorEffects:"Enable the vector scene graph: connected contours, flow, fracture, portals, motif glyphs, and invisible displacement.",
  codecPreviewMaterialize:"Materialize true FFglitch assets before browser preview. Leave off for faster approximate iteration.",
  backend:"Rendering backend. Native is fastest when built; browser is the reference implementation for some live effects; auto prefers native when available.",
  width:"Final render width in pixels.",height:"Final render height in pixels.",fps:"Final render frame rate.",
  crf:"Encoder quality target. Lower CRF means higher quality/larger files for software codecs; tubeviz maps this appropriately for supported hardware encoders.",
  codec:"Final video encoder used by FFmpeg.",nativePreset:"FFmpeg/native encoder speed-quality preset.",decoderCache:"Number of native decoder contexts retained across cuts to reduce reopen/decode overhead.",nativeThreads:"Native effect worker count. Zero lets the runtime choose automatically.",
  buildMissing:"Build the native C++ renderer automatically when the executable is missing.",codecRenderMaterialize:"Materialize scheduled FFglitch effects before final rendering.",
  visualBrief:"Describe the desired visual world in natural language. Tubeviz converts this prose into short YouTube-native searches; the brief itself is never used as a search query.",
  openaiModel:"Shared OpenAI model used for storyboard/clip understanding, acquisition planning, and whole-song AI directing. Configure it once here; Create workflows inherit it automatically.",termsPath:"Optional legacy text file containing one discovery search concept per line.",resultsPerTerm:"Target number of READY clips to ingest per seed search term.",hardMaxDuration:"Maximum library clip/segment length. Search results longer than this are not discarded when long-video sampling is enabled; Tubeviz downloads only a selected time range.",minSourceHeight:"Reject sources whose best reported height is below this value. The default requires 1080p footage.",maxSourceHeight:"Highest source format Tubeviz will download. The default caps acquisition at 1080p even when 1440p or 4K is available; zero disables the cap.",manualMinSourceHeight:"Reject a manual source when its reported height is below this value.",manualMaxSourceHeight:"Highest format downloaded for a manual source. The default caps acquisition at 1080p without forcing a later downscale.",mediaPrep:"Auto reuses H.264/MP4, VP8/VP9/WebM, and AV1 sources directly and creates an H.264 proxy only for incompatible media. Source never transcodes. Normalize forces the legacy proxy behavior.",normalizeEncoder:"Encoder used only when a compatibility proxy is required. Auto tests NVENC at runtime and otherwise uses libx264.",manualMediaPrep:"Choose whether manual ingest reuses compatible source media or creates an H.264 compatibility proxy.",manualNormalizeEncoder:"Compatibility-proxy encoder; Auto prefers working NVIDIA NVENC and falls back to libx264.",minDynamicScore:"Hard dynamicness floor after optical-flow analysis.",maxTextOverlay:"Maximum average frame area occupied by detected text-like regions.",maxPersistentText:"Maximum frame area occupied by text that persists across sampled frames.",minMotionCoverage:"Minimum fraction of the image participating in optical-flow motion; rejects tiny animated overlays on static scenes.",minTemporalDiversity:"Minimum actual frame-to-frame visual change.",maxFaceDominance:"Maximum frame area dominated by detected faces; helps reject talking-head footage.",minAestheticScore:"Minimum sharpness/exposure/saturation quality heuristic.",longVideoAttempts:"How many stratified randomized regions of a long source Tubeviz probes before choosing the strongest segment.",longVideoExcerptSeconds:"Length of the yt-dlp range downloaded around the best long-video probe.",sampleLongVideos:"Keep long finite videos eligible by probing randomized regions and downloading only the strongest bounded segment.",aiDevice:"Device used for AI pre-download candidate ranking.",aiCandidates:"Number of discovered candidates scored by AI before downloads are selected.",aiQueries:"Number of query variants generated/used per seed term.",cookiesBrowser:"Optional browser whose cookies yt-dlp should load, e.g. chrome or firefox.",aiDiscovery:"Use OpenCLIP/AI signals to rank candidate videos before downloading them.",visualIndexScenes:"After scene detection, index motion, palette, complexity, and natural visual accents.",manualSemanticDevice:"Device for OpenCLIP embedding and zero-shot classification of manually ingested scenes.",manualSemanticModel:"OpenCLIP architecture used to embed and classify manually ingested scene thumbnails.",manualSemanticPretrained:"OpenCLIP pretrained weights used for manual scene classification.",manualNoSemanticIndex:"Disable semantic embeddings for manually added URLs. Leave unchecked for automatic semantic scene retrieval.",manualNoSceneClassification:"Disable automatic zero-shot labels such as crowd, dancing, nightlife, city, tunnel, abstract, lights, text-heavy, and talking-head.",
  manualUrls:"Paste one hand-picked YouTube URL per line. Each accepted video enters the normal tubeviz download, normalization, scene-detection, visual-index, and duplicate-detection pipeline.",
  manualTerm:"Search/provenance tag assigned to manually ingested videos so they can be filtered and selected as a coherent source family.",manualCookies:"Optional browser cookies for manual yt-dlp ingestion.",manualMinDuration:"Reject manually supplied videos shorter than this duration. Zero disables.",manualHardMaxDuration:"Reject manually supplied videos longer than this duration. Zero disables, which is the manual-ingest default.",manualMinWidth:"Reject sources narrower than this width. Zero disables.",manualWidth:"Compatibility-proxy width. Zero preserves source geometry.",manualHeight:"Compatibility-proxy height. Zero preserves source geometry.",manualFps:"Compatibility-proxy frame rate. Zero preserves source timing.",manualSceneThreshold:"FFmpeg scene-change sensitivity used when detecting shot boundaries.",manualMinScene:"Minimum detected scene duration retained in the library.",manualSocketTimeout:"yt-dlp network socket timeout in seconds.",manualFragments:"Number of fragmented-media pieces yt-dlp may download concurrently.",manualRetries:"Number of overall download retries.",manualFragmentRetries:"Number of retries for individual media fragments.",manualKeepAudio:"Keep AAC audio when a compatibility proxy is created. Direct source media is never re-encoded merely to strip audio.",manualNoScenes:"Skip scene detection and scene thumbnails for these manually added videos.",manualNoVisualIndex:"Skip motion/palette/visual-accent indexing for these videos.",manualForce:"Redownload/reprocess even when the source already exists in the library.",manualVerbose:"Show verbose yt-dlp diagnostics in the job log.",
  statusFilter:"Filter Library cards by clip processing status.",termFilter:"Filter Library cards by provenance/search term.",tagFilter:"Filter Library cards by editable user tag.",trimIn:"Saved start of the usable source region. Material before this point is excluded from future scene selection.",trimOut:"Saved end of the usable source region. Material after this point is excluded from future scene selection.",loopTrim:"Loop only the highlighted usable range while editing a clip.",
};

const BUTTON_HELP={
  refreshLibrary:"Refresh project/library statistics from SQLite.",previewBtn:"Launch a fresh browser preview using the currently selected timeline, audio, and library.",audioAiDoctorBtn:"Check CLAP/Transformers/PyTorch availability and resolved device.",musicAiDoctorBtn:"Check optional MERT/Transformers/PyTorch availability and resolved device. MERT model code is loaded only when you explicitly enable Music AI.",analyzeBtn:"Analyze the selected audio and build a new directed timeline.",nativeBuildBtn:"Clean/rebuild the packaged native C++ renderer.",codecDoctorBtn:"Check FFglitch/ffedit installation and codec capabilities.",codecMaterializeBtn:"Materialize scheduled FFglitch effects into cached MP4 shot assets.",renderBtn:"Render the currently selected timeline to the output video.",ingestBtn:"Start search-based clip ingestion using the selected terms file.",manualIngestBtn:"Ingest every URL currently listed in the manual URL editor.",clearManualUrls:"Clear the manual URL editor.",loadClips:"Refresh visible Library cards.",selectVisible:"Temporarily restrict future scene plans to include the visible ready clips in the output pool.",unselectVisible:"Remove the visible ready clips from the temporary output pool.",selectTag:"Add every ready clip with the selected tag to the output pool.",unselectTag:"Remove every clip with the selected tag from the output pool.",clearOutputSelection:"Disable the temporary output pool so all ready clips are eligible again.",visualIndexBtn:"Rebuild temporal visual fingerprints for library scenes.",codecMotionBtn:"Extract/index codec motion-vector features using FFglitch where supported.",reloadCliSchema:"Reload Command Center directly from the current argparse tree.",syncCliProject:"Populate matching Command Center arguments from the Project fields.",runCliCommand:"Validate and launch the current Command Center argument vector.",refreshJobs:"Refresh background job history.",cancelJob:"Request cancellation of the active Create workflow job.",cancelCommandJob:"Request cancellation of the active Command Center job.",setTrimIn:"Set the clip's usable start to the current video playhead.",setTrimOut:"Set the clip's usable end to the current video playhead.",jumpTrimIn:"Seek playback to the current In marker.",jumpTrimOut:"Seek playback to the current Out marker.",clearTrim:"Remove saved source trim and restore the full video as eligible footage.",saveTrim:"Persist the selected usable In/Out range to the library database.",closeModal:"Close the clip playback/trim editor.",
};

function tooltipTextFor(el){
  if(STATIC_HELP[el.id])return STATIC_HELP[el.id];
  if(BUTTON_HELP[el.id])return BUTTON_HELP[el.id];
  const label=el.closest?.("label")||(el.id?document.querySelector(`label[for="${CSS.escape(el.id)}"]`):null);
  const labelText=label?Array.from(label.childNodes).filter(n=>n.nodeType===Node.TEXT_NODE).map(n=>n.textContent.trim()).filter(Boolean).join(" "):"";
  if(labelText)return `Configure ${labelText}.`;
  if(el.tagName==="BUTTON")return `${el.textContent.trim()}.`;
  return "Configure this tubeviz Studio option.";
}
let studioTooltip=null;
let studioTooltipAnchor=null;
function ensureStudioTooltip(){
  if(studioTooltip)return studioTooltip;
  const tip=document.createElement("div");
  tip.className="studio-tooltip";
  tip.setAttribute("role","tooltip");
  tip.setAttribute("aria-hidden","true");
  document.body.appendChild(tip);
  studioTooltip=tip;
  return tip;
}
function positionStudioTooltip(anchor){
  const tip=ensureStudioTooltip(),r=anchor.getBoundingClientRect();
  const gap=9,pad=10;
  tip.style.left="0px";tip.style.top="0px";
  const tr=tip.getBoundingClientRect();
  let left=r.left+r.width/2-tr.width/2;
  left=Math.max(pad,Math.min(window.innerWidth-tr.width-pad,left));
  let top=r.top-tr.height-gap;
  let placement="above";
  if(top<pad){top=r.bottom+gap;placement="below";}
  if(top+tr.height>window.innerHeight-pad)top=Math.max(pad,window.innerHeight-tr.height-pad);
  tip.style.left=`${Math.round(left)}px`;tip.style.top=`${Math.round(top)}px`;tip.dataset.placement=placement;
}
function showStudioTooltip(anchor){
  const text=anchor?.dataset.tooltip;if(!text)return;
  const tip=ensureStudioTooltip();studioTooltipAnchor=anchor;
  tip.textContent=text;tip.classList.add("visible");tip.setAttribute("aria-hidden","false");
  requestAnimationFrame(()=>positionStudioTooltip(anchor));
}
function hideStudioTooltip(anchor=null){
  if(anchor&&studioTooltipAnchor!==anchor)return;
  if(studioTooltip){studioTooltip.classList.remove("visible");studioTooltip.setAttribute("aria-hidden","true");}
  studioTooltipAnchor=null;
}
function bindHelpIcon(icon){
  if(icon.dataset.tooltipBound==="1")return;icon.dataset.tooltipBound="1";
  icon.addEventListener("mouseenter",()=>showStudioTooltip(icon));
  icon.addEventListener("mouseleave",()=>hideStudioTooltip(icon));
  icon.addEventListener("focus",()=>showStudioTooltip(icon));
  icon.addEventListener("blur",()=>hideStudioTooltip(icon));
  icon.addEventListener("click",()=>{if(studioTooltipAnchor===icon)hideStudioTooltip(icon);else showStudioTooltip(icon);});
  icon.addEventListener("keydown",e=>{if(e.key==="Escape")hideStudioTooltip(icon);});
}
window.addEventListener("scroll",()=>{if(studioTooltipAnchor)positionStudioTooltip(studioTooltipAnchor);},true);
window.addEventListener("resize",()=>{if(studioTooltipAnchor)positionStudioTooltip(studioTooltipAnchor);});
function addHelpToControl(el,explicit=null){
  if(!el||el.dataset.helpInstalled==="1")return;
  const text=explicit||tooltipTextFor(el);if(!text)return;
  el.dataset.helpInstalled="1";el.setAttribute("aria-description",text);el.title=text;
  const label=el.closest?.("label")||(el.id?document.querySelector(`label[for="${CSS.escape(el.id)}"]`):null);
  if(label&&!label.querySelector(":scope > .help-icon")){
    const icon=document.createElement("span");icon.className="help-icon";icon.tabIndex=0;icon.setAttribute("role","button");icon.setAttribute("aria-label",`Help: ${text}`);icon.dataset.tooltip=text;icon.textContent="?";bindHelpIcon(icon);
    const firstControl=label.querySelector("input,select,textarea");if(label.classList.contains("check"))label.appendChild(icon);else label.insertBefore(icon,firstControl||null);
  }else if(label){const icon=label.querySelector(":scope > .help-icon");if(icon)bindHelpIcon(icon);}
}
function installHelp(root=document){
  root.querySelectorAll("input,select,textarea,button").forEach(el=>{
    if(el.classList.contains("help-icon"))return;
    addHelpToControl(el,el.dataset.help||null);
  });
}

function bindCredentialToggle(){
  const button=$("toggleHfToken"),input=$("hfToken"),status=$("hfTokenStatus");if(!button||!input)return;
  button.addEventListener("click",()=>{
    if(!input.value){
      status.textContent=input.dataset.envAvailable==="1"?"HF_TOKEN is available in the server environment; its value is hidden by design. Type a session token here if you need to inspect/override one.":"No typed token to reveal. Enter a Hugging Face token first.";
      status.classList.toggle("ok",input.dataset.envAvailable==="1");
      input.focus();return;
    }
    const showing=input.type==="text";input.type=showing?"password":"text";button.textContent=showing?"Show typed token":"Hide typed token";button.setAttribute("aria-pressed",String(!showing));
  });
}
function updateManualUrlCount(){
  const el=$("manualUrls"),badge=$("manualUrlCount");if(!el||!badge)return;
  const count=el.value.split(/\r?\n/).map(x=>x.trim()).filter(Boolean).length;badge.textContent=`${count} URL${count===1?"":"s"}`;badge.classList.toggle("ok",count>0);
}

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
  if($("studioVersion")) $("studioVersion").textContent=`v${cfg.studio_version}`;
  const n=cfg.native;
  const ok=!!n.renderer;
  $("nativeBadge").textContent=ok?`native: ${n.renderer.split("/").pop()}`:"native: not built";
  $("nativeBadge").classList.add(ok?"ok":"warn");
  if(cfg.codec?.available){$("nativeBadge").textContent+=` · FFglitch ready`;}
  await loadAiSettings();
  await refreshLibrarySummary();
  loadClips();
  refreshJobs();
  loadCliSchema();
}

async function loadAiSettings(){
  aiSettings=await api("/api/gui/ai-settings");
  $("masterAiEnabled").checked=!!aiSettings.ai_enabled;
  $("visionAiEnabled").checked=!!aiSettings.vision_enabled;
  $("openaiBaseUrl").value=aiSettings.openai_base_url;
  $("openaiModel").value=aiSettings.openai_model;
  $("visionDetail").value=aiSettings.vision_detail;
  $("visionMaxFrames").value=aiSettings.vision_max_frames;
  $("visionTimeout").value=aiSettings.vision_timeout_seconds;
  $("aiCredentialStatus").innerHTML=`<span class="credential-status ${aiSettings.openai_key_configured?'ok':''}">OpenAI key: ${aiSettings.openai_key_configured?'configured':'missing'}</span><span class="credential-status ${aiSettings.hf_token_configured?'ok':''}">HF token: ${aiSettings.hf_token_configured?'configured':'missing'}</span><span class="credential-status">Saved at ${escapeHtml(aiSettings.config_path)}</span>`;
}

async function saveAi(clearOpenai=false,clearHf=false){
  aiSettings=await api("/api/gui/ai-settings",{method:"POST",body:JSON.stringify({
    ai_enabled:checked("masterAiEnabled"),vision_enabled:checked("visionAiEnabled"),
    openai_api_key:value("openaiApiKey")||null,hf_token:value("persistentHfToken")||null,
    openai_base_url:value("openaiBaseUrl"),openai_model:value("openaiModel"),
    vision_detail:value("visionDetail"),vision_max_frames:number("visionMaxFrames"),
    vision_timeout_seconds:number("visionTimeout"),clear_openai_key:clearOpenai,clear_hf_token:clearHf
  })});
  $("openaiApiKey").value="";$("persistentHfToken").value="";await loadAiSettings();
}

document.querySelectorAll(".tab").forEach(btn=>btn.onclick=()=>{
  document.querySelectorAll(".tab").forEach(x=>x.classList.remove("active"));
  document.querySelectorAll(".panel").forEach(x=>x.classList.remove("active"));
  btn.classList.add("active");
  $(btn.dataset.tab).classList.add("active");
  if(btn.dataset.tab==="library") loadClips();
  if(btn.dataset.tab==="jobs") refreshJobs();
  if(btn.dataset.tab==="command"&&!cliSchema) loadCliSchema();
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
    const hfToken=value("hfToken")||null;
    const job=await api("/api/gui/jobs",{method:"POST",body:JSON.stringify({kind,...payload,hf_token:hfToken})});
    activeJob=job.id;
    $("cancelJob").disabled=false;
    updateLiveLog($("jobLog"),job.log,{forceFollow:true});
    renderJobProgress(job);
    pollActiveJob();
  }catch(e){$("jobLog").textContent=`Error: ${e.message}`}
}

function compactDuration(seconds){
  const value=Math.max(0,Math.round(Number(seconds)||0));
  const hours=Math.floor(value/3600),minutes=Math.floor((value%3600)/60),secs=value%60;
  return hours?`${hours}h ${minutes}m ${secs}s`:minutes?`${minutes}m ${secs}s`:`${secs}s`;
}
function renderJobProgress(job){
  const box=$("jobProgress"),bar=$("jobProgressBar");
  const running=["queued","running","cancelling"].includes(job.status);
  const percent=Number.isFinite(job.progress_percent)?Math.max(0,Math.min(100,job.progress_percent)):null;
  box.className=`job-progress ${running?(percent===null?"indeterminate":"running"):job.status}`;
  $("jobStage").textContent=job.stage||job.status||"Working";
  const count=job.progress_total!=null?`${job.progress_current||0} / ${job.progress_total}`:"";
  $("jobProgressText").textContent=percent===null?(running?"Working…":job.status):`${percent.toFixed(1)}%${count?` · ${count}`:""}`;
  bar.style.width=percent===null?"35%":`${percent}%`;
  const timing=[];
  if(job.elapsed_seconds!=null)timing.push(`Elapsed ${compactDuration(job.elapsed_seconds)}`);
  if(job.progress_eta_seconds!=null&&running)timing.push(`ETA ${compactDuration(job.progress_eta_seconds)}`);
  $("jobTiming").textContent=timing.join(" · ");
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
    semantic:aiSettings.ai_enabled&&checked("semantic"),semantic_device:value("semanticDevice"),
    audio_ai:aiSettings.ai_enabled&&checked("audioAi"),audio_ai_device:value("audioAiDevice"),
    music_ai:aiSettings.ai_enabled&&checked("musicAi"),music_ai_device:value("musicAiDevice"),music_ai_model:value("musicAiModel"),
    audio_ai_window:number("audioAiWindow"),audio_ai_hop:number("audioAiHop"),
    audio_visual_match_weight:number("audioVisualWeight"),
    ai_director:aiSettings.ai_enabled&&checked("aiDirector"),
    ai_director_strength:number("aiDirectorStrength"),
    ai_edit_consultant:checked("aiEditConsultant"),
    ai_consultant_candidates:number("aiConsultantCandidates"),
    ai_consultant_weight:number("aiConsultantWeight"),
    section_bars:number("sectionBars"),max_video_layers:number("maxLayers"),
    transform_intensity:number("transformIntensity"),creative_effects:checked("creativeEffects"),creative_intensity:number("creativeIntensity"),composition_intensity:number("compositionIntensity"),
    target_unique_clips:number("targetUnique"),novelty_weight:number("noveltyWeight"),
    visual_match_weight:number("visualMatchWeight"),transition_weight:number("transitionWeight"),
    choreography:checked("choreography"),trajectory_strength:number("trajectoryStrength"),
    anticipation_seconds:number("anticipationSeconds"),sequence_lookahead:number("sequenceLookahead"),
    sequence_beam_width:number("sequenceBeamWidth"),effect_compatibility_weight:number("effectCompatibilityWeight"),
    preference_learning:checked("preferenceLearning"),preference_weight:number("preferenceWeight"),
    vector_effects:checked("vectorEffects"),vector_intensity:number("vectorIntensity"),
    codec_glitch:value("codecGlitch"),codec_glitch_intensity:number("codecGlitchIntensity"),
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
    native_build_if_missing:checked("buildMissing"),codec_materialize:checked("codecRenderMaterialize")
  }
});

$("ingestBtn").onclick=()=>startJob("ingest",{
  library:value("libraryPath"),terms:value("termsPath")||null,visual_brief:value("visualBrief")||null,audio:value("audioPath")||null,
  options:{
    results_per_term:number("resultsPerTerm"),hard_max_duration:number("hardMaxDuration"),
    min_source_height:number("minSourceHeight"),max_source_height:number("maxSourceHeight"),
    media_prep:value("mediaPrep")||"auto",normalize_encoder:value("normalizeEncoder")||"auto",width:0,height:0,fps:0,
    cookies_from_browser:value("cookiesBrowser")||null,ai_discovery:aiSettings.ai_enabled&&checked("aiDiscovery"),
    ai_device:value("aiDevice"),ai_candidates_per_term:number("aiCandidates"),
    ai_query_count:number("aiQueries"),acquisition_query_count:number("acquisitionQueries"),target_clips:number("targetClips"),
    min_video_fitness:number("minVideoFitness"),min_dynamic_score:number("minDynamicScore"),
    max_text_overlay_fraction:number("maxTextOverlay"),max_persistent_text_fraction:number("maxPersistentText"),
    min_motion_coverage:number("minMotionCoverage"),min_temporal_diversity:number("minTemporalDiversity"),
    max_face_dominance:number("maxFaceDominance"),min_aesthetic_score:number("minAestheticScore"),
    preview_gate:checked("previewGate"),sample_long_videos:checked("sampleLongVideos"),
    long_video_segment_attempts:number("longVideoAttempts"),long_video_excerpt_seconds:number("longVideoExcerptSeconds"),auto_trim:checked("autoTrim"),visual_index_scenes:checked("visualIndexScenes")
  }
});

$("manualIngestBtn").onclick=()=>{
  const urls=value("manualUrls").split(/\r?\n/).map(x=>x.trim()).filter(Boolean);
  if(!urls.length){$("jobLog").textContent="Manual ingest error: enter at least one YouTube URL.";return}
  return startJob("ingest-url",{
    library:value("libraryPath"),urls,
    options:{
      term:value("manualTerm")||"manual",
      min_duration:number("manualMinDuration"),hard_max_duration:number("manualHardMaxDuration"),
      min_width:number("manualMinWidth"),min_source_height:number("manualMinSourceHeight"),max_source_height:number("manualMaxSourceHeight"),media_prep:value("manualMediaPrep")||"auto",normalize_encoder:value("manualNormalizeEncoder")||"auto",width:number("manualWidth"),height:number("manualHeight"),fps:number("manualFps"),
      scene_threshold:number("manualSceneThreshold"),min_scene_seconds:number("manualMinScene"),
      cookies_from_browser:value("manualCookies")||null,download_socket_timeout:number("manualSocketTimeout"),
      concurrent_fragments:number("manualFragments"),download_retries:number("manualRetries"),fragment_retries:number("manualFragmentRetries"),
      keep_audio:checked("manualKeepAudio"),no_scenes:checked("manualNoScenes"),no_visual_index:checked("manualNoVisualIndex"),
      no_semantic_index:checked("manualNoSemanticIndex"),no_scene_classification:checked("manualNoSceneClassification"),
      semantic_device:value("manualSemanticDevice")||"auto",semantic_model:value("manualSemanticModel")||"ViT-B-32",
      semantic_pretrained:value("manualSemanticPretrained")||"laion2b_s34b_b79k",
      force:checked("manualForce"),verbose_ytdlp:checked("manualVerbose")
    }
  });
};

$("audioAiDoctorBtn").onclick=()=>startJob("audio-ai-doctor",{library:value("libraryPath"),options:{device:value("audioAiDevice"),model:"laion/clap-htsat-fused"}});
$("musicAiDoctorBtn").onclick=()=>startJob("music-ai-doctor",{library:value("libraryPath"),options:{device:value("musicAiDevice"),model:value("musicAiModel")||"m-a-p/MERT-v1-95M"}});
$("nativeBuildBtn").onclick=()=>startJob("native-build",{library:value("libraryPath"),options:{clean:true}});
$("visualIndexBtn").onclick=()=>startJob("visual-index",{library:value("libraryPath"),options:{force:true,fps:6,max_frames:180}});
$("codecDoctorBtn").onclick=()=>startJob("codec-doctor",{library:value("libraryPath"),options:{}});
$("codecMaterializeBtn").onclick=()=>startJob("codec-materialize",{...projectBase(),output:(value("timelinePath")||"timeline").replace(/\.json$/,".codec.json"),options:{}});
$("codecMotionBtn").onclick=()=>startJob("codec-motion-index",{library:value("libraryPath"),options:{force:false}});
async function startPreview(){
  const timeline=value("timelinePath");
  if(!timeline){
    $("jobLog").textContent="Preview error: select a timeline first.";
    return;
  }
  const preview=window.open("about:blank","tubevizPreview");
  if(preview){
    preview.document.write(`<title>tubeviz preview</title><body style="background:#080b10;color:#d9e6ef;font:16px system-ui;padding:30px">Starting preview for <code>${escapeHtml(timeline)}</code>…</body>`);
  }
  try{
    // port=0 asks Studio to allocate a fresh port. This prevents an old
    // in-memory timeline on :8080 from being mistaken for the current one.
    const job=await api("/api/gui/jobs",{
      method:"POST",
      body:JSON.stringify({
        kind:"preview",
        ...projectBase(),
        options:{port:0,host:"127.0.0.1",codec_materialize:checked("codecPreviewMaterialize")}
      })
    });
    activeJob=job.id;
    $("cancelJob").disabled=false;
    updateLiveLog($("jobLog"),job.log,{forceFollow:true});
    renderJobProgress(job);
    waitForPreview(job.id,job.preview_url,preview);
    pollActiveJob();
  }catch(e){
    $("jobLog").textContent=`Preview error: ${e.message}`;
    if(preview)preview.close();
  }
}
async function waitForPreview(jobId,url,previewWindow){
  const deadline=Date.now()+20000;
  while(Date.now()<deadline){
    try{
      const job=await api(`/api/gui/jobs/${jobId}?tail=100`);
      const log=(job.log||[]).join("\n");
      if(job.status==="failed"||job.status==="complete"){
        if(previewWindow&&!previewWindow.closed){
          previewWindow.document.body.textContent=`Preview failed: ${log.split("\n").slice(-8).join(" | ")}`;
        }
        return;
      }
      if(log.includes("Uvicorn running on")||log.includes("Application startup complete")){
        if(previewWindow&&!previewWindow.closed){
          const sep=url.includes("?")?"&":"?";
          previewWindow.location=`${url}${sep}studio_preview=${encodeURIComponent(jobId)}&t=${Date.now()}`;
        }
        return;
      }
    }catch(e){}
    await new Promise(resolve=>setTimeout(resolve,200));
  }
  if(previewWindow&&!previewWindow.closed){
    previewWindow.document.body.textContent="Preview server did not become ready within 20 seconds. Check the Studio job log.";
  }
}
$("previewBtn").onclick=startPreview;
$("refreshLibrary").onclick=()=>{refreshLibrarySummary();loadClips()};
$("cancelJob").onclick=async()=>{
  if(!activeJob)return;
  await api(`/api/gui/jobs/${activeJob}/cancel`,{method:"POST"});
};

function updateLiveLog(element, lines, {forceFollow=false}={}){
  const distanceFromBottom=element.scrollHeight-element.clientHeight-element.scrollTop;
  const wasFollowing=forceFollow||distanceFromBottom<=24;
  const previousScrollTop=element.scrollTop;
  element.textContent=(lines||[]).join("\n");
  if(wasFollowing)element.scrollTop=element.scrollHeight;
  else element.scrollTop=previousScrollTop;
}

async function pollActiveJob(){
  if(pollTimer)clearTimeout(pollTimer);
  if(!activeJob)return;
  try{
    const job=await api(`/api/gui/jobs/${activeJob}?tail=4000`);
    renderJobProgress(job);
    updateLiveLog($("jobLog"),job.log);
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

function cliArgId(dest){return `cliarg-${String(dest).replace(/[^a-zA-Z0-9_-]/g,"_")}`}
function cliCurrent(){
  if(!cliSchema)return null;
  const name=value("cliCommand");
  return cliSchema.commands.find(command=>command.name===name)||null;
}
function cliHelp(arg){
  const bits=[];
  if(arg.help)bits.push(arg.help);
  if(arg.default!==null&&arg.default!==undefined&&arg.default!=="")bits.push(`default: ${arg.default}`);
  if(arg.choices?.length)bits.push(`choices: ${arg.choices.join(", ")}`);
  return bits.join(" · ");
}
function cliField(arg){
  const id=cliArgId(arg.dest),required=arg.required?" required":"";
  const flags=arg.positional?`positional: ${arg.dest}`:(arg.flags||[]).join(" / ");
  let control="";
  const booleanOptional=arg.action==="BooleanOptionalAction";
  const storeTrue=arg.action==="_StoreTrueAction";
  const storeFalse=arg.action==="_StoreFalseAction";
  if(booleanOptional){
    control=`<select id="${id}" class="boolean-select" data-cli-kind="boolean-optional" data-dest="${escapeHtml(arg.dest)}" data-positive="${escapeHtml(arg.positive_flag||"")}" data-negative="${escapeHtml(arg.negative_flag||"")}"><option value="default">CLI default (${String(arg.default)})</option><option value="true">enabled</option><option value="false">disabled</option></select>`;
  }else if(storeTrue||storeFalse){
    control=`<label class="check"><input id="${id}" type="checkbox" data-cli-kind="boolean-flag" data-dest="${escapeHtml(arg.dest)}" data-flag="${escapeHtml(arg.positive_flag||arg.flags?.[0]||"")}"> pass ${escapeHtml(arg.flags?.[0]||arg.dest)}</label>`;
  }else if(arg.positional&&(arg.nargs==="+"||arg.nargs==="*")){
    control=`<textarea id="${id}" data-cli-kind="positional-list" data-dest="${escapeHtml(arg.dest)}" ${arg.required?"required":""} placeholder="one value per line"></textarea>`;
  }else if(arg.choices?.length){
    const blank=arg.required?"":`<option value="">use CLI default</option>`;
    control=`<select id="${id}" data-cli-kind="value" data-dest="${escapeHtml(arg.dest)}" data-positional="${arg.positional}" data-flag="${escapeHtml(arg.positive_flag||"")}">${blank}${arg.choices.map(choice=>`<option value="${escapeHtml(choice)}" ${choice===arg.default?"selected":""}>${escapeHtml(choice)}</option>`).join("")}</select>`;
  }else{
    const typ=arg.type==="int"||arg.type==="float"?"number":"text",step=arg.type==="float"?' step="any"':"";
    const initial=arg.positional?"":(arg.default===null||arg.default===undefined?"":String(arg.default));
    control=`<input id="${id}" type="${typ}"${step} data-cli-kind="value" data-dest="${escapeHtml(arg.dest)}" data-positional="${arg.positional}" data-flag="${escapeHtml(arg.positive_flag||"")}" value="${escapeHtml(initial)}" ${arg.required?"required":""}>`;
  }
  const help=cliHelp(arg)||`Configure ${arg.dest} for this CLI command.`;
  return `<div class="cli-arg${required}" data-help="${escapeHtml(help)}"><div class="arg-flags">${escapeHtml(flags)}</div><label>${escapeHtml(arg.dest)}${control}</label><small>${escapeHtml(help)}</small></div>`;
}
function populateCliCommands(filter=""){
  if(!cliSchema)return;
  const select=$("cliCommand"),previous=select.value,q=filter.trim().toLowerCase();
  const commands=cliSchema.commands.filter(command=>!q||command.name.toLowerCase().includes(q));
  select.innerHTML=commands.map(command=>`<option value="${escapeHtml(command.name)}">${escapeHtml(command.name)}</option>`).join("");
  if(commands.some(command=>command.name===previous))select.value=previous;
  renderCliCommand();
}
async function loadCliSchema(){
  try{
    cliSchema=await api("/api/gui/cli-schema");
    populateCliCommands(value("cliCommandFilter"));
  }catch(e){$("cliArguments").innerHTML=`<p>${escapeHtml(e.message)}</p>`}
}
function renderCliCommand(){
  const command=cliCurrent();
  if(!command){$("cliArguments").innerHTML="<p>No matching command.</p>";$("cliPreview").textContent="";return}
  $("cliCommandDescription").textContent=command.description||"Current tubeviz CLI command.";
  $("cliArguments").innerHTML=command.arguments.map(cliField).join("");
  syncCliProjectValues(false);
  $("cliArguments").querySelectorAll("input,select,textarea").forEach(el=>{el.addEventListener("input",updateCliPreview);const wrap=el.closest(".cli-arg");addHelpToControl(el,wrap?.dataset.help||null);});
  updateCliPreview();
}
function syncCliProjectValues(force=true){
  const command=cliCurrent();if(!command)return;
  const project={library:value("libraryPath"),audio:value("audioPath"),timeline:value("timelinePath"),output:value("outputPath")};
  for(const arg of command.arguments){
    const el=$(cliArgId(arg.dest));if(!el)continue;
    let proposed="";
    if(arg.dest==="library")proposed=project.library;
    else if(arg.dest==="audio")proposed=project.audio;
    else if(arg.dest==="timeline")proposed=project.timeline;
    else if(arg.dest==="output")proposed=command.path[0]==="analyze"?project.timeline:project.output;
    else if(arg.dest==="terms")proposed=value("termsPath");
    if(proposed&&(force||!el.value||el.value==="./library"||el.value==="timeline.json"||el.value==="tubeviz-output.mp4"))el.value=proposed;
  }
  updateCliPreview();
}
function buildCliArgv(){
  const command=cliCurrent();if(!command)return[];
  const positional=[],optional=[];
  for(const arg of command.arguments){
    const el=$(cliArgId(arg.dest));if(!el)continue;
    const kind=el.dataset.cliKind;
    if(kind==="boolean-optional"){
      if(el.value==="true"&&el.dataset.positive)optional.push(el.dataset.positive);
      else if(el.value==="false"&&el.dataset.negative)optional.push(el.dataset.negative);
      continue;
    }
    if(kind==="boolean-flag"){
      if(el.checked&&el.dataset.flag)optional.push(el.dataset.flag);
      continue;
    }
    if(kind==="positional-list"){
      const values=el.value.split(/\r?\n/).map(v=>v.trim()).filter(Boolean);positional.push(...values);continue;
    }
    const val=String(el.value??"");
    if(arg.positional){if(val!=="")positional.push(val)}
    else if(val!==""){optional.push(el.dataset.flag,val)}
  }
  return [...command.path,...positional,...optional];
}
function shellDisplay(tokens){
  return tokens.map(token=>/^[A-Za-z0-9_./:@%+=,-]+$/.test(token)?token:`'${token.replaceAll("'","'\\''")}'`).join(" ");
}
function updateCliPreview(){
  const argv=buildCliArgv();
  $("cliPreview").textContent=argv.length?`python -m tubeviz.cli ${shellDisplay(argv)}`:"";
}
async function startCommandJob(){
  const argv=buildCliArgv();
  if(!argv.length)return;
  try{
    const job=await api("/api/gui/jobs",{method:"POST",body:JSON.stringify({kind:"cli",library:value("libraryPath"),hf_token:value("hfToken")||null,options:{argv}})});
    commandJobId=job.id;$("cancelCommandJob").disabled=false;updateLiveLog($("commandJobLog"),job.log,{forceFollow:true});pollCommandJob();refreshJobs();
  }catch(e){$("commandJobLog").textContent=`Error: ${e.message}`}
}
async function pollCommandJob(){
  if(commandPollTimer)clearTimeout(commandPollTimer);if(!commandJobId)return;
  try{
    const job=await api(`/api/gui/jobs/${commandJobId}?tail=4000`);updateLiveLog($("commandJobLog"),job.log);
    const running=["queued","running","cancelling"].includes(job.status);$("cancelCommandJob").disabled=!running;
    if(running)commandPollTimer=setTimeout(pollCommandJob,600);else{commandJobId=null;refreshLibrarySummary();loadClips();refreshJobs()}
  }catch(e){$("commandJobLog").textContent+=`\n${e.message}`}
}
$("reloadCliSchema").onclick=loadCliSchema;
$("cliCommand").onchange=renderCliCommand;
$("cliCommandFilter").oninput=()=>populateCliCommands(value("cliCommandFilter"));
$("syncCliProject").onclick=()=>syncCliProjectValues(true);
$("runCliCommand").onclick=startCommandJob;
$("cancelCommandJob").onclick=async()=>{if(commandJobId)await api(`/api/gui/jobs/${commandJobId}/cancel`,{method:"POST"})};

async function loadClips(){
  const grid=$("clipGrid");
  grid.innerHTML="<p>Loading…</p>";
  try{
    const params={
      library:value("libraryPath"),
      status:value("statusFilter"),
      term:value("termFilter"),
      tag:value("tagFilter"),
      limit:300
    };
    const data=await api(`/api/gui/library?${qs(params)}`);
    libraryClips=data.clips;
    const tagFilter=$("tagFilter"),currentTag=tagFilter.value;
    tagFilter.innerHTML=`<option value="">all tags</option>${(data.tags||[]).map(tag=>`<option value="${escapeHtml(tag.name)}">${escapeHtml(tag.name)} (${tag.clip_count})</option>`).join("")}`;
    if((data.tags||[]).some(tag=>tag.name===currentTag))tagFilter.value=currentTag;
    const pool=data.output_selection||{active:false,count:0};
    $("outputPoolStatus").textContent=pool.active
      ?`${pool.count} marked clip${pool.count===1?"":"s"}; only marked ready clips are eligible for newly planned output`
      :"All ready clips are eligible; marking any clip activates the temporary pool";
    setStats($("libraryStats"),data.stats);
    if(!data.clips.length){grid.innerHTML="<p>No clips matched.</p>";return}
    grid.innerHTML=data.clips.map((c,index)=>{
      const enc=encodeURIComponent(c.source_id);
      const lp=encodeURIComponent(value("libraryPath"));
      const rejected=c.status==="rejected_manual";
      const tags=(c.tags||[]).map(tag=>`<span class="clip-tag">${escapeHtml(tag)}</span>`).join("");
      return `<div class="clip${c.output_selected?" output-selected":""}" data-clip-index="${index}">
        <img loading="lazy" src="/api/gui/clip/${enc}/thumbnail?library=${lp}" onerror="this.style.opacity=.15">
        <div class="clip-body">
          <label class="clip-output-toggle"><input type="checkbox" data-clip-action="toggle-output" data-clip-index="${index}" ${c.output_selected?"checked":""} ${c.status!=="ready"?"disabled":""}> Use in output pool</label>
          <div class="clip-title">${escapeHtml(c.title||c.source_id)}</div>
          <div class="clip-meta">${escapeHtml(c.source_id)} · ${escapeHtml(c.status)} · ${Number(c.scene_count)||0} scenes · ${c.duration?Number(c.duration).toFixed(1)+"s":"?"} ${c.ai_enhanced?'· AI described':''}</div>
          ${c.ai_metadata?`<div class="clip-ai-card-summary"><p>${escapeHtml(c.ai_metadata.summary||"AI visual metadata attached")}</p><div class="ai-chip-row">${aiChips(c.ai_metadata.semantic_tags)}${aiChips(c.ai_metadata.moods,"mood")}</div></div>`:""}
          <div class="clip-tags">${tags||'<span class="clip-tag empty">no tags</span>'}</div>
          ${(c.usable_start!=null||c.usable_end!=null)?`<div class="clip-trim-badge">trimmed ${formatTime(c.usable_start??0)} → ${formatTime(c.usable_end??c.duration??0)}</div>`:""}
          <div class="clip-actions">
            ${c.media_available
              ?`<button type="button" data-clip-action="play" data-clip-index="${index}">Play / Trim</button>`
              :`<button type="button" disabled title="No playable local media">No media</button>`}
            ${rejected
              ?`<button type="button" data-clip-action="restore" data-clip-index="${index}">Restore</button>`
              :`<button type="button" data-clip-action="reject" data-clip-index="${index}">Reject</button>`}
            <button type="button" data-clip-action="edit-tags" data-clip-index="${index}">Edit tags</button>
            <button type="button" class="danger" data-clip-action="delete" data-clip-index="${index}">Delete</button>
          </div>
        </div>
      </div>`;
    }).join("");
  }catch(e){grid.innerHTML=`<p>${escapeHtml(e.message)}</p>`}
}

async function updateOutputSelection(payload){
  await api("/api/gui/library/output-selection",{method:"POST",body:JSON.stringify({library:value("libraryPath"),...payload})});
  await loadClips();
}
window.toggleOutputClip=(clipId,selected)=>updateOutputSelection({clip_ids:[clipId],selected});
window.editClipTags=async(id,source)=>{
  const clip=libraryClips.find(item=>item.source_id===id&&item.source===source);
  const raw=prompt("Tags (comma separated):",(clip?.tags||[]).join(", "));
  if(raw===null)return;
  const tags=raw.split(",").map(tag=>tag.trim()).filter(Boolean);
  await api(`/api/gui/clip/${encodeURIComponent(id)}/tags`,{method:"POST",body:JSON.stringify({library:value("libraryPath"),source,tags})});
  await loadClips();
};

function clipForActionElement(element){
  const index=Number(element?.dataset?.clipIndex);
  if(!Number.isInteger(index)||index<0||index>=libraryClips.length)return null;
  return libraryClips[index]||null;
}
$("clipGrid").addEventListener("click",event=>{
  const button=event.target.closest("button[data-clip-action]");
  if(!button||!$("clipGrid").contains(button))return;
  const clip=clipForActionElement(button);
  if(!clip)return;
  switch(button.dataset.clipAction){
    case "play": playClip(clip.source_id,clip.source,clip.title||clip.source_id); break;
    case "restore": restoreClip(clip.source_id); break;
    case "reject": rejectClip(clip.source_id); break;
    case "edit-tags": editClipTags(clip.source_id,clip.source); break;
    case "delete": deleteClip(clip.source_id); break;
  }
});
$("clipGrid").addEventListener("change",event=>{
  const input=event.target.closest('input[data-clip-action="toggle-output"]');
  if(!input||!$("clipGrid").contains(input))return;
  const clip=clipForActionElement(input);
  if(clip)toggleOutputClip(clip.id,input.checked);
});
$("selectVisible").onclick=()=>updateOutputSelection({clip_ids:libraryClips.filter(c=>c.status==="ready").map(c=>c.id),selected:true});
$("unselectVisible").onclick=()=>updateOutputSelection({clip_ids:libraryClips.filter(c=>c.status==="ready").map(c=>c.id),selected:false});
$("selectTag").onclick=()=>{const tag=value("tagFilter");if(tag)return updateOutputSelection({tag,selected:true});alert("Choose a tag first.")};
$("unselectTag").onclick=()=>{const tag=value("tagFilter");if(tag)return updateOutputSelection({tag,selected:false});alert("Choose a tag first.")};
$("clearOutputSelection").onclick=async()=>{await api("/api/gui/library/output-selection/clear",{method:"POST",body:JSON.stringify({library:value("libraryPath")})});await loadClips()};

function escapeHtml(s){return String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]))}
function jsq(s){return String(s).replaceAll("\\","\\\\").replaceAll("'","\\'")}

function formatTime(seconds){
  const value=Math.max(0,Number(seconds)||0),minutes=Math.floor(value/60),secs=value-minutes*60;
  return `${minutes}:${secs.toFixed(3).padStart(6,"0")}`;
}
function aiList(value){return Array.isArray(value)?value.filter(item=>item!=null&&String(item).trim()):[]}
function aiText(value){
  if(value==null)return "";
  if(Array.isArray(value))return value.join(", ");
  if(typeof value==="object")return Object.entries(value).map(([key,item])=>`${key.replaceAll("_"," ")}: ${Array.isArray(item)?item.join(", "):item}`).join(" · ");
  return String(value);
}
function aiChips(values,kind=""){return aiList(values).map(value=>`<span class="ai-chip ${kind}">${escapeHtml(value)}</span>`).join("")}
function aiGroup(title,value){const text=aiText(value);return text?`<div class="clip-ai-group"><h4>${escapeHtml(title)}</h4><p>${escapeHtml(text)}</p></div>`:""}
function aiMetrics(utility={}){
  return ["energy","motion","complexity","continuity","build_fit","drop_fit","ambient_fit"].filter(key=>Number.isFinite(Number(utility[key]))).map(key=>{
    const score=Math.max(0,Math.min(1,Number(utility[key])));
    return `<div class="ai-metric"><span>${escapeHtml(key.replaceAll("_"," "))} · ${score.toFixed(2)}</span><div class="ai-meter"><i style="width:${(score*100).toFixed(1)}%"></i></div></div>`;
  }).join("");
}
function renderClipAiMetadata(details){
  const panel=$("clipAiMetadata"),data=details.ai_description;
  if(!data){panel.classList.add("hidden");panel.innerHTML="";return}
  const scenesByIndex=new Map((details.scenes||[]).map(scene=>[Number(scene.index),scene]));
  const sceneHtml=aiList(data.scenes).map(scene=>{
    if(typeof scene!=="object")return "";
    const indexed=scenesByIndex.get(Number(scene.scene_index));
    const start=indexed?Number(indexed.start):null,end=indexed?Number(indexed.end):null;
    const time=start==null?`scene ${scene.scene_index}`:`${formatTime(start)}–${formatTime(end)}`;
    const score=["energy","motion","drop_fit"].filter(key=>Number.isFinite(Number(scene[key]))).map(key=>`${key.replace("_"," ")} ${Number(scene[key]).toFixed(2)}`).join(" · ");
    return `<button class="ai-scene" type="button" ${start==null?"disabled":`onclick="seekTrim(${start})"`}><span class="ai-scene-time">${escapeHtml(time)}</span><span class="ai-scene-copy">${escapeHtml(scene.description||"No scene description")}<span class="ai-chip-row">${aiChips(scene.semantic_tags)}</span></span><span class="ai-scene-score">${escapeHtml(score)}</span></button>`;
  }).join("");
  const groups=[["Subjects",data.subjects],["Actions",data.actions],["Settings",data.settings],["Camera",data.camera],["Palette",data.palette],["Lighting",data.lighting],["Textures",data.textures],["Risks",data.risks]].map(([title,value])=>aiGroup(title,value)).join("");
  panel.innerHTML=`<div class="clip-ai-head"><div><h3>AI visual analysis</h3><p>${escapeHtml(data.summary||"Structured visual metadata is attached to this clip.")}</p></div><button type="button" onclick="enhanceClipAi(${details.id})">Re-analyze clip</button></div><div class="ai-chip-row">${aiChips(data.semantic_tags)}${aiChips(data.moods,"mood")}</div><div class="clip-ai-grid">${groups}<div class="clip-ai-group"><h4>Editing utility</h4><div class="ai-metrics">${aiMetrics(data.editing_utility||{})}</div></div></div>${sceneHtml?`<div class="ai-scenes"><h4>Scene descriptions · click to seek</h4>${sceneHtml}</div>`:""}<details class="ai-raw"><summary>Raw AI metadata</summary><pre>${escapeHtml(JSON.stringify(data,null,2))}</pre></details>`;
  panel.classList.remove("hidden");
}
window.enhanceClipAi=clipId=>startJob("ai-describe",{library:value("libraryPath"),options:{clip_id:clipId,force:true,limit:1}});
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
  renderClipAiMetadata(details);
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
  $("clipAiMetadata").classList.add("hidden");$("clipAiMetadata").innerHTML="";
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
        <button onclick="watchJob('${j.id}','${jsq(j.kind)}')">View log</button>
      </div>`).join(""):"<p>No jobs yet.</p>";
  }catch(e){$("jobsList").textContent=e.message}
}
window.watchJob=(id,kind)=>{
  if(kind==="cli"){
    commandJobId=id;
    document.querySelector('[data-tab="command"]').click();
    pollCommandJob();
  }else{
    activeJob=id;
    document.querySelector('[data-tab="create"]').click();
    pollActiveJob();
  }
};
$("refreshJobs").onclick=refreshJobs;
$("saveAiSettings").onclick=()=>saveAi(false,false).catch(e=>{$("aiCredentialStatus").textContent=e.message});
$("clearOpenAiKey").onclick=()=>saveAi(true,false).catch(e=>{$("aiCredentialStatus").textContent=e.message});
$("clearPersistentHf").onclick=()=>saveAi(false,true).catch(e=>{$("aiCredentialStatus").textContent=e.message});
$("enhanceLibraryAi").onclick=()=>startJob("ai-describe",{library:value("libraryPath"),options:{force:checked("forceAiDescribe"),limit:0}});
$("loadClips").onclick=loadClips;
$("statusFilter").onchange=loadClips;
$("tagFilter").onchange=loadClips;
$("termFilter").onkeydown=e=>{if(e.key==="Enter")loadClips()};

bindCredentialToggle();
$("manualUrls")?.addEventListener("input",updateManualUrlCount);
$("clearManualUrls")?.addEventListener("click",()=>{$("manualUrls").value="";updateManualUrlCount();$("manualUrls").focus();});
installHelp();
updateManualUrlCount();
init().catch(e=>console.error(e));


function installIntuitiveSliders(){
  document.querySelectorAll('.slider-value[data-for]').forEach(out=>{
    const input=$(out.dataset.for);
    if(!input)return;
    const render=()=>{
      const step=String(input.step||'1');
      const decimals=step.includes('.')?step.split('.')[1].length:0;
      out.textContent=Number(input.value).toFixed(Math.min(decimals,3));
      input.setAttribute('aria-valuetext',out.textContent);
    };
    input.addEventListener('input',render);
    input.addEventListener('change',render);
    render();
  });
}
installIntuitiveSliders();
