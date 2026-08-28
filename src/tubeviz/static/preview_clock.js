// SPDX-License-Identifier: Apache-2.0

// Live preview is clocked by the music, not by any one source decoder. The
// visualizer intentionally has a requestAnimationFrame fallback, but prefers
// requestVideoFrameCallback when the primary HTMLVideoElement exposes it.
//
// That preference is a bad fit for hidden source decoders: a segment loop,
// seek, demux hiccup, or decoder stall can leave requestVideoFrameCallback
// waiting for the next decoded source frame while the audio keeps advancing.
// The result looks like the entire preview has frozen even though the renderer
// and audio clock are healthy.
//
// Shadow requestVideoFrameCallback only on tubeviz's hidden decoder elements so
// the visualizer uses its display-clock requestAnimationFrame path. The browser
// still decodes the videos normally; this only prevents source decode cadence
// from owning the preview render loop.
const decoderElements = Array.from(document.querySelectorAll('video.decoder'));
let patchedDecoders = 0;

for (const video of decoderElements) {
  if (typeof video.requestVideoFrameCallback !== 'function') continue;
  try {
    Object.defineProperty(video, 'requestVideoFrameCallback', {
      configurable: true,
      value: undefined,
    });
    video.dataset.tubevizPreviewClock = 'display';
    patchedDecoders += 1;
  } catch (error) {
    console.debug('tubeviz preview clock: unable to detach decoder frame clock', error);
  }
}

globalThis.__tubevizPreviewClock = Object.freeze({
  mode: 'display',
  decoderCount: decoderElements.length,
  patchedDecoders,
});
