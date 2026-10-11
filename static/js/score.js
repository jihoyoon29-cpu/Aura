// OpenSheetMusicDisplay(OSMD) 로더 + MusicXML 렌더링,
// 그리고 MusicXML 을 직접 파싱해 soundfont-player 로 재생하는 합주 미리듣기 엔진.
// (OSMD CDN 번들에는 재생 클래스가 없어서 재생은 자체 구현한다.)

const OSMD_SRC =
  "https://cdn.jsdelivr.net/npm/opensheetmusicdisplay@1.8.7/build/opensheetmusicdisplay.min.js";
const SOUNDFONT_SRC =
  "https://cdn.jsdelivr.net/npm/soundfont-player@0.12.0/dist/soundfont-player.min.js";
const JSPDF_SRC = "https://cdn.jsdelivr.net/npm/jspdf@2.5.1/dist/jspdf.umd.min.js";
const SVG2PDF_SRC = "https://cdn.jsdelivr.net/npm/svg2pdf.js@2.8.1/dist/svg2pdf.umd.min.js";

const _scriptPromises = new Map();
function loadScript(src) {
  if (_scriptPromises.has(src)) return _scriptPromises.get(src);
  const p = new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = src;
    s.async = true;
    s.addEventListener("load", () => resolve());
    s.addEventListener("error", () => reject(new Error(`load fail: ${src}`)));
    document.head.appendChild(s);
  });
  _scriptPromises.set(src, p);
  return p;
}

export async function ensureOSMD() {
  await loadScript(OSMD_SRC);
  if (!window.opensheetmusicdisplay) throw new Error("Failed to load OSMD");
  return window.opensheetmusicdisplay;
}

export async function ensureSoundfont() {
  await loadScript(SOUNDFONT_SRC);
  if (!window.Soundfont) throw new Error("Failed to load soundfont-player");
  return window.Soundfont;
}

// jsPDF + svg2pdf.js (the latter patches jsPDF's prototype with a .svg() method).
export async function ensurePdfLibs() {
  await loadScript(JSPDF_SRC);
  await loadScript(SVG2PDF_SRC);
  if (!window.jspdf || !window.jspdf.jsPDF) throw new Error("Failed to load jsPDF");
  return window.jspdf.jsPDF;
}

// Exports the score to a multi-page A4-landscape PDF: the full score first, then one section per
// instrument. The score is re-rendered offscreen with OSMD's page layout (a single tall SVG would
// exceed jsPDF's maximum page size for long pieces), and each OSMD page becomes one PDF page.
export async function exportScoreToPdf(musicXml, filename) {
  const [OSMD, jsPDF] = await Promise.all([ensureOSMD(), ensurePdfLibs()]);
  const baseOptions = {
    backend: "svg",
    autoResize: false,
    drawTitle: false,
    drawSubtitle: false,
    drawComposer: false,
    drawLyricist: false,
  };

  const host = document.createElement("div");
  host.style.cssText = "position:absolute;left:-99999px;top:0;width:900px";
  document.body.appendChild(host);

  let doc = null;
  try {
    const probe = new OSMD.OpenSheetMusicDisplay(host, baseOptions);
    await probe.load(musicXml);
    const names = probe.Sheet.Instruments.map((inst, i) => instrumentName(inst, i));
    const sections = [{ label: "Full score", only: null }, ...names.map((n, i) => ({ label: n, only: i }))];

    for (const section of sections) {
      host.innerHTML = "";
      const osmd = new OSMD.OpenSheetMusicDisplay(host, {
        ...baseOptions,
        drawPartNames: section.only === null,
      });
      await osmd.load(musicXml);
      if (section.only !== null) {
        osmd.Sheet.Instruments.forEach((inst, i) => {
          inst.Visible = i === section.only;
        });
      }
      osmd.setPageFormat("A4_L");
      osmd.render();

      const pages = [...host.querySelectorAll("svg")];
      for (let p = 0; p < pages.length; p += 1) {
        const svg = pages[p];
        const w = parseFloat(svg.getAttribute("width")) || 900;
        const h = parseFloat(svg.getAttribute("height")) || 636;
        if (!doc) doc = new jsPDF({ unit: "px", format: [w, h], orientation: "landscape", compress: true });
        else doc.addPage([w, h], "landscape");
        // eslint-disable-next-line no-await-in-loop
        await doc.svg(svg, { x: 0, y: 0, width: w, height: h });
        doc.setFont("helvetica", "bold");
        doc.setFontSize(10);
        doc.text(`${section.label}  (${p + 1}/${pages.length})`, 24, 18);
      }
    }
  } finally {
    host.remove();
  }
  if (!doc) throw new Error("No sheet music available to export.");
  doc.save(filename);
}

function instrumentName(inst, idx) {
  return (
    inst?.Name ||
    inst?.NameLabel?.text ||
    inst?.nameLabel?.text ||
    `Part ${idx + 1}`
  ).trim();
}

// 컨테이너에 "악기별로 분리된" 악보를 나열. 반환: [{ id?, name, osmd }]
export async function renderPerInstrument(rootEl, musicXml, instrumentIds = []) {
  const OSMD = await ensureOSMD();
  rootEl.innerHTML = "";

  const probeDiv = document.createElement("div");
  probeDiv.style.display = "none";
  document.body.appendChild(probeDiv);
  const probe = new OSMD.OpenSheetMusicDisplay(probeDiv, { autoResize: false });
  await probe.load(musicXml);
  const parts = probe.Sheet.Instruments.map((inst, i) => instrumentName(inst, i));
  probeDiv.remove();

  const results = [];
  for (let idx = 0; idx < parts.length; idx += 1) {
    const card = document.createElement("div");
    card.className = "score-inst";
    const head = document.createElement("div");
    head.className = "score-inst__head";
    head.textContent = parts[idx];
    const canvas = document.createElement("div");
    canvas.className = "score-inst__canvas";
    card.append(head, canvas);
    rootEl.appendChild(card);

    const osmd = new OSMD.OpenSheetMusicDisplay(canvas, {
      autoResize: true,
      backend: "svg",
      drawTitle: false,
      drawSubtitle: false,
      drawComposer: false,
      drawLyricist: false,
      drawPartNames: false,
      drawingParameters: "compacttight",
    });
    await osmd.load(musicXml);
    osmd.Sheet.Instruments.forEach((inst, i) => {
      inst.Visible = i === idx;
    });
    try {
      osmd.render();
    } catch (e) {
      canvas.innerHTML = `<p class="score-err">Couldn't render this part.</p>`;
    }
    results.push({ id: instrumentIds[idx], name: parts[idx], osmd });
  }
  return results;
}

// 전체 총보 1개 렌더링. 반환: osmd 인스턴스
export async function renderFullScore(div, musicXml) {
  const OSMD = await ensureOSMD();
  const osmd = new OSMD.OpenSheetMusicDisplay(div, {
    autoResize: true,
    backend: "svg",
    drawTitle: false,
    drawSubtitle: false,
    drawComposer: false,
  });
  await osmd.load(musicXml);
  osmd.render();
  return osmd;
}

function formatClock(sec) {
  const t = Math.max(0, Math.round(sec));
  return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`;
}

// Wires a range input + time label to a playback object: shows the position while playing and
// lets the user drag to jump anywhere in the piece.
export function bindSeekBar(seekEl, timeEl, playback) {
  if (seekEl._timer) window.clearInterval(seekEl._timer);
  const STEPS = 1000;
  let dragging = false;
  seekEl.min = "0";
  seekEl.max = String(STEPS);
  const total = playback.duration;
  const paint = (pos) => {
    seekEl.value = String(Math.round((pos / total) * STEPS));
    timeEl.textContent = `${formatClock(pos)} / ${formatClock(total)}`;
  };
  paint(0);
  seekEl.oninput = () => {
    dragging = true;
    timeEl.textContent = `${formatClock((Number(seekEl.value) / STEPS) * total)} / ${formatClock(total)}`;
  };
  seekEl.onchange = () => {
    playback.seek((Number(seekEl.value) / STEPS) * total);
    dragging = false;
  };
  seekEl._timer = window.setInterval(() => {
    if (!dragging) paint(playback.position);
  }, 250);
}

// createPlayback() 이 반환한 playback 객체를 위한 악기별 음소거 토글 버튼들을 그린다.
// 재생 중에도 바로 눌러서 켜고 끌 수 있다 (GainNode 를 즉시 조절하기 때문).
export function renderMuteToggles(container, playback) {
  container.innerHTML = "";
  playback.parts.forEach((p, i) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "pb-mute-chip";
    btn.textContent = p.name;
    btn.setAttribute("aria-pressed", "false");
    btn.title = `Toggle ${p.name}`;
    btn.addEventListener("click", () => {
      const next = !playback.isMuted(i);
      playback.setMuted(i, next);
      btn.classList.toggle("is-muted", next);
      btn.setAttribute("aria-pressed", String(next));
    });
    container.appendChild(btn);
  });
}

// --------------------------------------------------------------------
// MusicXML -> 재생 이벤트 파서
// --------------------------------------------------------------------
const GM_PROGRAM_TO_SF = {
  0: "acoustic_grand_piano",
  40: "violin",
  41: "viola",
  42: "cello",
  43: "contrabass",
  46: "orchestral_harp",
  47: "timpani",
  56: "trumpet",
  57: "trombone",
  58: "tuba",
  60: "french_horn",
  68: "oboe",
  70: "bassoon",
  71: "clarinet",
  72: "piccolo",
  73: "flute",
};
const STEP_TO_SEMITONE = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };
// Relative loudness for written dynamics (mf = 1, the default).
const DYNAMIC_GAIN = { pp: 0.45, p: 0.65, mp: 0.85, mf: 1, f: 1.25, ff: 1.5 };

function parseMusicXml(xmlString) {
  const doc = new DOMParser().parseFromString(xmlString, "application/xml");
  if (doc.querySelector("parsererror")) throw new Error("MusicXML parsing error");

  const partMeta = {};
  doc.querySelectorAll("part-list > score-part").forEach((sp) => {
    const id = sp.getAttribute("id");
    const name = sp.querySelector("part-name")?.textContent?.trim() || id;
    const progRaw = parseInt(
      sp.querySelector("midi-instrument > midi-program")?.textContent || "1",
      10
    );
    partMeta[id] = {
      name,
      program: Number.isNaN(progRaw) ? 0 : Math.max(0, progRaw - 1),
    };
  });

  // Tempo changes are score-wide: build a measure-index -> bpm map first, so every part follows the
  // same tempo timeline (a single running variable would leak the last tempo into later parts).
  const tempoByMeasure = new Map();
  doc.querySelectorAll("part").forEach((partEl) => {
    partEl.querySelectorAll("measure").forEach((m, idx) => {
      const snd = m.querySelector("sound[tempo]");
      const pm = m.querySelector("metronome > per-minute");
      const bpm = snd ? parseFloat(snd.getAttribute("tempo")) : pm ? parseFloat(pm.textContent) : NaN;
      if (bpm > 0 && !tempoByMeasure.has(idx)) tempoByMeasure.set(idx, bpm);
    });
  });
  const parts = [];

  doc.querySelectorAll("part").forEach((partEl) => {
    const id = partEl.getAttribute("id");
    const meta = partMeta[id] || { name: id, program: 0 };
    let divisions = 4;
    let cursor = 0; // 초 단위
    let lastStart = 0;
    let tempo = tempoByMeasure.get(0) || 120;
    let vel = 1; // current loudness factor from written dynamics
    let ramp = 0; // +1 while a "cresc." is active, -1 for "dim." (ends at the next written dynamic)
    const events = [];
    const spd = () => 60 / tempo / divisions;

    partEl.querySelectorAll("measure").forEach((m, mIdx) => {
      const div = m.querySelector("attributes > divisions");
      if (div) divisions = parseInt(div.textContent, 10) || divisions;
      if (tempoByMeasure.has(mIdx)) tempo = tempoByMeasure.get(mIdx);
      if (ramp) vel = Math.max(0.45, Math.min(1.5, vel * (ramp > 0 ? 1.08 : 0.92)));

      for (const child of m.children) {
        const tag = child.tagName.toLowerCase();
        if (tag === "note") {
          if (child.querySelector("grace")) continue;
          const dur = parseInt(child.querySelector("duration")?.textContent || "0", 10);
          const isChord = !!child.querySelector("chord");
          const isRest = !!child.querySelector("rest");
          const start = isChord ? lastStart : cursor;
          if (!isRest) {
            const step = child.querySelector("pitch > step")?.textContent;
            if (step) {
              const oct = parseInt(
                child.querySelector("pitch > octave")?.textContent || "4",
                10
              );
              const alter = parseInt(
                child.querySelector("pitch > alter")?.textContent || "0",
                10
              );
              const midi = (oct + 1) * 12 + STEP_TO_SEMITONE[step] + alter;
              events.push({ midi, start, dur: Math.max(dur * spd(), 0.08), vel });
            }
          }
          if (!isChord) {
            lastStart = cursor;
            cursor += dur * spd();
          }
        } else if (tag === "direction") {
          const dyn = child.querySelector("dynamics");
          const words = child.querySelector("words")?.textContent?.toLowerCase() || "";
          if (dyn && dyn.firstElementChild) {
            const key = dyn.firstElementChild.tagName.toLowerCase();
            if (DYNAMIC_GAIN[key] != null) {
              vel = DYNAMIC_GAIN[key];
              ramp = 0;
            }
          } else if (words.startsWith("cresc")) {
            ramp = 1;
          } else if (words.startsWith("dim")) {
            ramp = -1;
          }
        } else if (tag === "backup") {
          cursor -= parseInt(child.querySelector("duration")?.textContent || "0", 10) * spd();
        } else if (tag === "forward") {
          cursor += parseInt(child.querySelector("duration")?.textContent || "0", 10) * spd();
        }
      }
    });
    events.sort((x, y) => x.start - y.start);
    parts.push({ name: meta.name, program: meta.program, events, end: cursor });
  });

  const duration = parts.reduce((a, p) => Math.max(a, p.end), 0);
  return { parts, duration, tempo: tempoByMeasure.get(0) || 120 };
}

// MusicXML 문자열을 받아 합주 재생 컨트롤러를 만든다.
// 파트(악기)마다 독립된 GainNode 를 붙여서, 재생 중에도 즉시 악기별 음소거를 켜고 끌 수 있다.
// 반환: { play(), pause(), stop(), duration, parts: [{name}], setMuted(i, bool), isMuted(i) }
export async function createPlayback(musicXml) {
  const Soundfont = await ensureSoundfont();
  const parsed = parseMusicXml(musicXml);
  if (!parsed.parts.some((p) => p.events.length)) {
    throw new Error("No notes to play.");
  }

  let ac = null;
  let players = []; // parsed.parts 와 같은 순서의 soundfont-player 인스턴스
  let gainNodes = []; // 파트별 GainNode (음소거용)
  let muted = parsed.parts.map(() => false);
  let state = "idle"; // idle | playing | paused
  // Notes are scheduled a few seconds ahead instead of all at once: thousands of pre-scheduled
  // nodes (long, many-instrument pieces) overload the audio thread and the audio clock crawls.
  const LOOKAHEAD_SEC = 8;
  const TICK_MS = 400;
  let base = 0; // audio-clock time at which piece time 0 starts
  let cursors = []; // per part: index of the next unscheduled event
  let timer = null;
  let resumeAt = 0; // piece time (s) the next play() starts from while idle (set by stop/seek)

  async function ensureLoaded() {
    if (ac) return;
    ac = new (window.AudioContext || window.webkitAudioContext)();
    gainNodes = parsed.parts.map((_p, i) => {
      const g = ac.createGain();
      g.gain.value = muted[i] ? 0 : 1;
      g.connect(ac.destination);
      return g;
    });
    // 파트마다 독립된 GainNode 로 라우팅해야 실시간 음소거가 가능해서,
    // 같은 악기를 여러 파트가 써도 인스턴스를 공유하지 않고 파트별로 각각 로드한다.
    players = await Promise.all(
      parsed.parts.map(async (p, i) => {
        const sfName = GM_PROGRAM_TO_SF[p.program] || "acoustic_grand_piano";
        try {
          return await Soundfont.instrument(ac, sfName, {
            soundfont: "FluidR3_GM",
            destination: gainNodes[i],
          });
        } catch (e) {
          return await Soundfont.instrument(ac, "acoustic_grand_piano", {
            destination: gainNodes[i],
          });
        }
      })
    );
  }

  function stopTimer() {
    if (timer) window.clearInterval(timer);
    timer = null;
  }

  function scheduleWindow() {
    const horizon = ac.currentTime + LOOKAHEAD_SEC - base; // piece time up to which to schedule
    parsed.parts.forEach((p, i) => {
      const evs = p.events;
      while (cursors[i] < evs.length && evs[cursors[i]].start < horizon) {
        const ev = evs[cursors[i]];
        cursors[i] += 1;
        players[i].play(ev.midi, base + ev.start, { duration: ev.dur, gain: 2.2 * (ev.vel ?? 1) });
      }
    });
    if (ac.currentTime - base > parsed.duration + 1.5) {
      stopTimer();
      state = "idle";
      resumeAt = 0;
    }
  }

  function currentPosition() {
    if (state === "idle" || !ac) return resumeAt;
    return Math.max(0, Math.min(parsed.duration, ac.currentTime - base));
  }

  function firstEventAtOrAfter(events, t) {
    let lo = 0;
    let hi = events.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (events[mid].start < t - 1e-6) lo = mid + 1;
      else hi = mid;
    }
    return lo;
  }

  function startAt(t) {
    stopTimer();
    players.forEach((pl) => pl.stop());
    base = ac.currentTime + 0.2 - t;
    cursors = parsed.parts.map((p) => firstEventAtOrAfter(p.events, t));
    scheduleWindow();
    timer = window.setInterval(scheduleWindow, TICK_MS);
  }

  return {
    get duration() {
      return parsed.duration;
    },
    get parts() {
      return parsed.parts.map((p) => ({ name: p.name }));
    },
    get position() {
      return currentPosition();
    },
    get isPlaying() {
      return state === "playing";
    },
    // Jump to piece time t (seconds). Keeps the current state: playing continues from t,
    // paused/stopped stays silent and the next play() starts from t.
    seek(t) {
      const target = Math.max(0, Math.min(parsed.duration, t));
      if (state === "idle" || !ac) {
        resumeAt = target;
        return;
      }
      startAt(target);
    },
    isMuted(i) {
      return !!muted[i];
    },
    setMuted(i, isMuted) {
      muted[i] = isMuted;
      const g = gainNodes[i];
      if (g && ac) {
        const t = ac.currentTime;
        g.gain.cancelScheduledValues(t);
        g.gain.setValueAtTime(g.gain.value, t);
        g.gain.linearRampToValueAtTime(isMuted ? 0 : 1, t + 0.03);
      }
    },
    async play() {
      if (state === "playing") return;
      await ensureLoaded();
      if (ac.state === "suspended") await ac.resume();
      if (state === "paused") {
        state = "playing";
        return;
      }
      startAt(resumeAt >= parsed.duration - 0.1 ? 0 : resumeAt);
      state = "playing";
    },
    async pause() {
      if (state === "playing" && ac) {
        await ac.suspend();
        state = "paused";
      }
    },
    // Silences everything but remembers where it stopped: play() continues from that point.
    stop() {
      resumeAt = currentPosition();
      stopTimer();
      if (ac) {
        players.forEach((pl) => pl.stop && pl.stop());
        if (ac.state === "suspended") ac.resume();
      }
      state = "idle";
    },
  };
}
