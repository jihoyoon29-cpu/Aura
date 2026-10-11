import { getCurrentUser, authedFetch, initNav } from "./auth.js";
import { extractYouTubeId, youtubeEmbedUrl } from "./youtube.js";

initNav();

const form = document.getElementById("post-form");
const promptInput = document.getElementById("prompt");
const generateBtn = document.getElementById("generate-btn");
const waveform = document.getElementById("waveform");
const statusEl = document.getElementById("generator-status");
const playerWrap = document.getElementById("player-wrap");
const player = document.getElementById("audio-player");
const youtubeUrlInput = document.getElementById("youtube-url");
const youtubePreviewWrap = document.getElementById("youtube-preview-wrap");
const youtubePreview = document.getElementById("youtube-preview");
const submitBtn = document.getElementById("submit-btn");
const msgEl = document.getElementById("form-msg");

let generatedAudioUrl = null;
let youtubeVideoId = null;

// Random waveform placeholder bar heights (purely visual rhythm)
for (let i = 0; i < 40; i++) {
  const bar = document.createElement("span");
  bar.style.height = `${20 + Math.random() * 80}%`;
  waveform.appendChild(bar);
}

function showMsg(text, type) {
  msgEl.textContent = text;
  msgEl.className = `form-msg ${type === "error" ? "is-error" : "is-ok"}`;
}

function updateSubmitState() {
  submitBtn.disabled = !generatedAudioUrl && !youtubeVideoId;
}

(async function guardLogin() {
  const user = await getCurrentUser();
  if (!user) {
    window.location.href = "/login";
  }
})();

generateBtn.addEventListener("click", async () => {
  const prompt = promptInput.value.trim();
  if (!prompt) {
    statusEl.textContent = "Please enter a music prompt first.";
    return;
  }

  generateBtn.disabled = true;
  waveform.classList.remove("is-ready");
  waveform.classList.add("is-active");
  statusEl.textContent = "Generating audio with Stable Audio 3... (can take 1–2 minutes)";
  playerWrap.style.display = "none";
  generatedAudioUrl = null;
  updateSubmitState();

  try {
    const res = await authedFetch("/api/generate-audio", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
    });
    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.error || "Failed to generate audio.");
    }

    generatedAudioUrl = data.audioUrl;
    player.src = generatedAudioUrl;
    playerWrap.style.display = "block";
    waveform.classList.remove("is-active");
    waveform.classList.add("is-ready");
    statusEl.textContent = "Done! Give it a listen, and post it below if you like it.";
  } catch (err) {
    waveform.classList.remove("is-active");
    statusEl.textContent = `${err.message} (If generation keeps failing, e.g. due to API rate limits, you can use a YouTube link instead below.)`;
  } finally {
    generateBtn.disabled = false;
    updateSubmitState();
  }
});

youtubeUrlInput.addEventListener("input", () => {
  const id = extractYouTubeId(youtubeUrlInput.value.trim());
  youtubeVideoId = id;

  if (id) {
    youtubePreview.src = youtubeEmbedUrl(id);
    youtubePreviewWrap.style.display = "block";
  } else {
    youtubePreview.src = "";
    youtubePreviewWrap.style.display = "none";
  }
  updateSubmitState();
});

form.addEventListener("submit", async (e) => {
  e.preventDefault();

  if (!generatedAudioUrl && !youtubeVideoId) {
    showMsg("Generate an AI track or enter a YouTube link.", "error");
    return;
  }

  const title = document.getElementById("title").value.trim();
  const content = document.getElementById("content").value.trim();

  submitBtn.disabled = true;
  submitBtn.textContent = "Posting...";

  try {
    const res = await authedFetch("/api/posts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title,
        content,
        prompt: promptInput.value.trim(),
        audioUrl: generatedAudioUrl,
        youtubeUrl: youtubeVideoId ? youtubeUrlInput.value.trim() : null,
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