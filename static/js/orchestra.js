import { getCurrentUser, authedFetch, initNav } from "./auth.js";
import { INSTRUMENT_GROUPS, makePreviewAudio } from "./instruments.js";
import { renderPerInstrument, renderFullScore, createPlayback, renderMuteToggles, exportScoreToPdf, bindSeekBar, fileSafeName } from "./score.js";

initNav();

(async function guardLogin() {
  const user = await getCurrentUser();
  if (!user) window.location.href = "/login";
})();

const $ = (id) => document.getElementById(id);

const moodInput = $("mood");
const recommendBtn = $("recommend-btn");
const recReason = $("rec-reason");
const beatsSel = $("beats");
const beatTypeSel = $("beat-type");
const tempoInput = $("tempo");
const tempoVal = $("tempo-val");
const tempoTerm = $("tempo-term");
const fifthsSel = $("fifths");
const measuresSel = $("measures");
const instGroups = $("inst-groups");
const generateBtn = $("generate-btn");
const genStatus = $("gen-status");
const resultEl = $("result");
const refNote = $("ref-note");
const fullScoreEl = $("full-score");
const perInstrumentEl = $("per-instrument");
const pbPlay = $("pb-play");
const pbPause = $("pb-pause");
const pbStop = $("pb-stop");
const pbNote = $("pb-note");
const pbMutes = $("pb-mutes");
const downloadXmlBtn = $("download-xml");
const downloadPdfBtn = $("download-pdf");
const togglePostBtn = $("toggle-post");
const postForm = $("post-form");
const msgEl = $("form-msg");

const moodCount = $("mood-count");
const syncMoodCount = () => {
  moodCount.textContent = String(moodInput.value.length);
};
moodInput.addEventListener("input", syncMoodCount);
syncMoodCount();

// Title for downloaded files: what the user typed as the post title, else the first sentence of the description.
function pieceTitle() {
  const typed = $("post-title").value.trim();
  if (typed) return typed;
  return moodInput.value.trim().split(/[.!?\n。]/)[0].slice(0, 50);
}

let lastMusicXml = null;
let lastMeta = null;
let playback = null;

function showMsg(text, type) {
  msgEl.textContent = text;
  msgEl.className = `form-msg ${type === "error" ? "is-error" : "is-ok"}`;
  msgEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

// --- Populate the key signature select (-7 ~ +7) ---
const KEY_LABELS = {
  "-7": "♭ 7 (C♭ major)",
  "-6": "♭ 6 (G♭ major)",
  "-5": "♭ 5 (D♭ major)",
  "-4": "♭ 4 (A♭ major)",
  "-3": "♭ 3 (E♭ major)",
  "-2": "♭ 2 (B♭ major)",
  "-1": "♭ 1 (F major)",
  "0": "None (C major / A minor)",
  "1": "♯ 1 (G major)",
  "2": "♯ 2 (D major)",
  "3": "♯ 3 (A major)",
  "4": "♯ 4 (E major)",
  "5": "♯ 5 (B major)",
  "6": "♯ 6 (F♯ major)",
  "7": "♯ 7 (C♯ major)",
};
for (let f = -7; f <= 7; f += 1) {
  const opt = document.createElement("option");
  opt.value = String(f);
  opt.textContent = KEY_LABELS[String(f)];
  if (f === 0) opt.selected = true;
  fifthsSel.appendChild(opt);
}

// --- Tempo slider ---
function tempoTermFor(bpm) {
  if (bpm < 60) return "· Largo (very slow)";
  if (bpm < 76) return "· Adagio (slow)";
  if (bpm < 108) return "· Andante (walking pace)";
  if (bpm < 132) return "· Moderato (moderate)";
  if (bpm < 168) return "· Allegro (fast)";
  return "· Presto (very fast)";
}
function syncTempo() {
  tempoVal.textContent = tempoInput.value;
  tempoTerm.textContent = tempoTermFor(Number(tempoInput.value));
}
tempoInput.addEventListener("input", syncTempo);
syncTempo();

// --- Instrument checkbox list ---
const previewAudios = new Map();
let currentPreview = null;

function playPreview(inst, btn) {
  if (currentPreview && currentPreview !== previewAudios.get(inst.id)) {
    currentPreview.pause();
    currentPreview.currentTime = 0;
  }
  let audio = previewAudios.get(inst.id);
  if (!audio) {
    audio = makePreviewAudio(inst);
    previewAudios.set(inst.id, audio);
  }
  currentPreview = audio;
  audio.currentTime = 0;
  btn.classList.add("is-playing");
  audio.play().catch(() => {
    btn.classList.remove("is-playing");
  });
  window.clearTimeout(audio._stopT);
  audio._stopT = window.setTimeout(() => {
    audio.pause();
    audio.currentTime = 0;
    btn.classList.remove("is-playing");
  }, 1050);
  audio.onended = () => btn.classList.remove("is-playing");
}

INSTRUMENT_GROUPS.forEach((group) => {
  const wrap = document.createElement("div");
  wrap.className = "inst-group";

  const h = document.createElement("h3");
  h.className = "inst-group__title";
  h.textContent = group.group;
  wrap.appendChild(h);

  group.items.forEach((inst) => {
    const row = document.createElement("div");
    row.className = "inst-item";
    row.dataset.id = inst.id;

    const label = document.createElement("label");
    label.className = "inst-item__label";

    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.value = inst.id;
    cb.className = "inst-item__cb";

    const nameSpan = document.createElement("span");
    nameSpan.className = "inst-item__name";
    nameSpan.textContent = inst.name;

    const chip = document.createElement("span");
    chip.className = "inst-item__chip";
    chip.textContent = "Suggested";

    label.append(cb, nameSpan, chip);

    const pv = document.createElement("button");
    pv.type = "button";
    pv.className = "inst-item__pv";
    pv.textContent = "▶";
    pv.title = `Preview ${inst.name}`;
    pv.addEventListener("click", () => playPreview(inst, pv));

    const desc = document.createElement("p");
    desc.className = "inst-item__desc";
    desc.textContent = inst.desc;

    row.append(label, pv, desc);
    wrap.appendChild(row);
  });

  instGroups.appendChild(wrap);
});

function checkedInstrumentIds() {
  // Returned in DOM order (strings → woodwinds → brass → percussion)
  return [...instGroups.querySelectorAll(".inst-item__cb:checked")].map((cb) => cb.value);
}

// --- Instrument recommendations ---
recommendBtn.addEventListener("click", async () => {
  const prompt = moodInput.value.trim();
  if (!prompt) {
    showMsg("Write the mood you want in one line first.", "error");
    return;
  }
  recommendBtn.disabled = true;
  recommendBtn.textContent = "Getting recommendations...";
  try {
    const res = await authedFetch("/api/orchestra/recommend", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Failed to get recommendations.");

    const recommended = new Set(data.recommended || []);
    instGroups.querySelectorAll(".inst-item").forEach((row) => {
      const on = recommended.has(row.dataset.id);
      row.classList.toggle("is-recommended", on);
      if (on) row.querySelector(".inst-item__cb").checked = true;
    });

    if (data.reason) {
      recReason.textContent = `Suggested lineup: ${data.reason}`;
      recReason.style.display = "block";
    } else {
      recReason.style.display = "none";
    }
  } catch (err) {
    showMsg(err.message, "error");
  } finally {
    recommendBtn.disabled = false;
    recommendBtn.textContent = "Get instrument recommendations for this mood";
  }
});

// --- Score generation ---
generateBtn.addEventListener("click", async () => {
  const instruments = checkedInstrumentIds();
  if (!instruments.length) {
    showMsg("Please select at least one instrument.", "error");
    return;
  }

  const payload = {
    prompt: moodInput.value.trim(),
    instruments,
    beats: Number(beatsSel.value),
    beatType: Number(beatTypeSel.value),
    tempo: Number(tempoInput.value),
    fifths: Number(fifthsSel.value),
    mode: $("key-mode").value,
    measures: Number(measuresSel.value),
    difficulty: document.querySelector('input[name="difficulty"]:checked').value,
    variation: {
      repetition: $("var-repetition").value,
      dynamics: $("var-dynamics").value,
      plan: $("var-plan").checked,
      tempoChanges: $("var-tempo").checked,
      meterChanges: $("var-meter").checked,
    },
  };

  generateBtn.disabled = true;
  genStatus.textContent = "GPT is composing the score... (takes 20 seconds to a minute depending on the number of instruments)";
  resultEl.style.display = "none";

  try {
    const res = await authedFetch("/api/orchestra/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Failed to generate the score.");

    lastMusicXml = data.musicXml;
    lastMeta = data.meta || null;

    genStatus.textContent = "Rendering the sheet music...";
    resultEl.style.display = "block";

    const notes = [];
    if (lastMeta && lastMeta.mood) {
      const modeText = lastMeta.mode === "minor" ? "minor" : "major";
      const source = { you: "your choice", description: "from your description", music: "as the music turned out" }[lastMeta.modeSource] || "";
      notes.push(`🎭 Read from your description: ${lastMeta.mood}. Mode: ${modeText} (${source}).`);
    }
    if (lastMeta && lastMeta.referenceWork) {
      notes.push(`🎼 Real music used as a reference: 「${lastMeta.referenceWork}」.`);
    }
    if (lastMeta && lastMeta.tempoHint) {
      notes.push(`💡 Your description sounds closer to about ${lastMeta.tempoHint} BPM than the ${lastMeta.tempo} BPM you set — lower or raise the tempo slider and regenerate if you want that feel.`);
    }
    if (notes.length) {
      refNote.textContent = notes.join("\n");
      refNote.style.whiteSpace = "pre-line";
      refNote.style.display = "block";
    } else {
      refNote.style.display = "none";
    }

    // Full score + playback
    fullScoreEl.innerHTML = "";
    if (playback) playback.stop();
    playback = null;
    pbNote.textContent = "";
    try {
      await renderFullScore(fullScoreEl, lastMusicXml);
    } catch (e) {
      fullScoreEl.innerHTML = `<p class="score-err">Couldn't render the full score (MusicXML error) — download the MusicXML below to check it.</p>`;
    }

    [pbPlay, pbPause, pbStop].forEach((b) => (b.disabled = false));
    pbMutes.innerHTML = "";
    try {
      playback = await createPlayback(lastMusicXml);
      renderMuteToggles(pbMutes, playback);
      bindSeekBar($("pb-seek"), $("pb-time"), playback);
    } catch (e) {
      playback = null;
      pbNote.textContent = "Couldn't set up ensemble playback in this browser. The sheet music view is unaffected.";
      [pbPlay, pbPause, pbStop].forEach((b) => (b.disabled = true));
    }

    // Sheet music by instrument
    await renderPerInstrument(perInstrumentEl, lastMusicXml, instruments);

    genStatus.textContent = lastMeta && lastMeta.truncated
      ? "Done (the response may have been cut off — fewer instruments or measures should be more reliable)."
      : "Done! Check it out below, and post it if you like it.";
    resultEl.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    genStatus.textContent = "";
    showMsg(err.message, "error");
  } finally {
    generateBtn.disabled = false;
  }
});

// --- Playback controls ---
pbPlay.addEventListener("click", async () => {
  if (!playback) return;
  pbNote.textContent = "Loading soundfonts...";
  try {
    await playback.play();
    pbNote.textContent = "";
  } catch (e) {
    pbNote.textContent = "Playback failed: " + e.message;
  }
});
pbPause.addEventListener("click", () => playback && playback.pause());
pbStop.addEventListener("click", () => playback && playback.stop());

// --- MusicXML download ---
downloadXmlBtn.addEventListener("click", () => {
  if (!lastMusicXml) return;
  const blob = new Blob([lastMusicXml], { type: "application/vnd.recordare.musicxml+xml" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = fileSafeName(pieceTitle(), "orchestra", "musicxml");
  a.click();
  URL.revokeObjectURL(a.href);
});

// --- PDF download ---
downloadPdfBtn.addEventListener("click", async () => {
  if (!lastMusicXml) return;
  downloadPdfBtn.disabled = true;
  const original = downloadPdfBtn.textContent;
  downloadPdfBtn.textContent = "Preparing PDF...";
  try {
    await exportScoreToPdf(lastMusicXml, fileSafeName(pieceTitle(), "orchestra", "pdf"));
  } catch (err) {
    showMsg("Failed to create the PDF: " + err.message, "error");
  } finally {
    downloadPdfBtn.disabled = false;
    downloadPdfBtn.textContent = original;
  }
});

// --- Post it ---
togglePostBtn.addEventListener("click", () => {
  postForm.style.display = postForm.style.display === "none" ? "block" : "none";
});

postForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!lastMusicXml) return;
  const submitBtn = $("post-submit");
  submitBtn.disabled = true;
  submitBtn.textContent = "Posting...";
  try {
    const res = await authedFetch("/api/posts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: $("post-title").value.trim(),
        content: $("post-content").value.trim(),
        prompt: moodInput.value.trim(),
        musicXml: lastMusicXml,
        audioUrl: null,
        youtubeUrl: null,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Failed to create the post.");
    window.location.href = `/post/${data.id}`;
  } catch (err) {
    showMsg(err.message, "error");
    submitBtn.disabled = false;
    submitBtn.textContent = "Post";
  }
});
