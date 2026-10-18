import { getCurrentUser, authedFetch, initNav } from "./auth.js";
import { extractYouTubeId, youtubeEmbedUrl } from "./youtube.js";
import { renderPerInstrument, renderFullScore, createPlayback, renderMuteToggles, exportScoreToPdf, bindSeekBar, fileSafeName, showPdfLink, showPdfError } from "./score.js";

initNav();

const postId = document.body.dataset.postId;

const titleEl = document.getElementById("post-title");
const metaEl = document.getElementById("post-meta");
const promptEl = document.getElementById("post-prompt");
const contentEl = document.getElementById("post-content");
const audioBlockEl = document.getElementById("audio-player-block");
const playerEl = document.getElementById("post-player");
const youtubeBlockEl = document.getElementById("youtube-player-block");
const youtubePlayerEl = document.getElementById("youtube-player");
const commentListEl = document.getElementById("comment-list");
const commentFormWrap = document.getElementById("comment-form-wrap");
const commentLoginNote = document.getElementById("comment-login-note");

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

function formatDate(seconds) {
  if (!seconds) return "";
  return new Date(seconds * 1000).toLocaleString("en-US");
}

function renderComments(comments) {
  if (!comments.length) {
    commentListEl.innerHTML = `<p class="comment-login-note">No comments yet. Be the first to leave one.</p>`;
    return;
  }
  commentListEl.innerHTML = comments
    .map(
      (c) => `
      <div class="comment-item">
        <div class="comment-item__meta">${escapeHtml(c.authorName || "Anonymous")} · ${formatDate(
          c.createdAt ? c.createdAt._seconds : null
        )}</div>
        <p>${escapeHtml(c.text)}</p>
      </div>`
    )
    .join("");
}

function renderPlayer(post) {
  const youtubeId = post.youtubeUrl ? extractYouTubeId(post.youtubeUrl) : null;

  if (youtubeId) {
    youtubePlayerEl.src = youtubeEmbedUrl(youtubeId);
    youtubeBlockEl.style.display = "block";
    audioBlockEl.style.display = "none";
  } else if (post.audioUrl) {
    playerEl.src = post.audioUrl;
    audioBlockEl.style.display = "block";
    youtubeBlockEl.style.display = "none";
  } else {
    audioBlockEl.style.display = "none";
    youtubeBlockEl.style.display = "none";
  }
}

async function renderScore(musicXml) {
  const block = document.getElementById("score-block");
  block.style.display = "block";
  const fullEl = document.getElementById("score-full");
  const noteEl = document.getElementById("sc-note");
  const playBtn = document.getElementById("sc-play");
  const pauseBtn = document.getElementById("sc-pause");
  const stopBtn = document.getElementById("sc-stop");

  // Wire the PDF button first: it only needs the XML, not the (slower) score rendering and playback setup.
  const pdfBtn = document.getElementById("score-download-pdf");
  pdfBtn.addEventListener("click", async () => {
    pdfBtn.disabled = true;
    const original = pdfBtn.textContent;
    pdfBtn.textContent = "Preparing PDF...";
    try {
      const result = await exportScoreToPdf(musicXml, fileSafeName(titleEl.textContent, `score_${postId}`, "pdf"));
      showPdfLink(document.getElementById("score-pdf-status"), result);
    } catch (e) {
      showPdfError(document.getElementById("score-pdf-status"), e.message);
    } finally {
      pdfBtn.disabled = false;
      pdfBtn.textContent = original;
    }
  });

  try {
    await renderFullScore(fullEl, musicXml);
  } catch (e) {
    fullEl.innerHTML = `<p class="score-err">Couldn't render the sheet music.</p>`;
  }

  let playback = null;
  try {
    playback = await createPlayback(musicXml);
    renderMuteToggles(document.getElementById("sc-mutes"), playback);
    bindSeekBar(document.getElementById("sc-seek"), document.getElementById("sc-time"), playback);
  } catch (e) {
    noteEl.textContent = "Couldn't set up ensemble playback in this browser.";
    [playBtn, pauseBtn, stopBtn].forEach((b) => (b.disabled = true));
  }
  if (playback) {
    playBtn.addEventListener("click", async () => {
      noteEl.textContent = "Loading soundfonts...";
      try {
        await playback.play();
        noteEl.textContent = "";
      } catch (e) {
        noteEl.textContent = "Playback failed: " + e.message;
      }
    });
    pauseBtn.addEventListener("click", () => playback.pause());
    stopBtn.addEventListener("click", () => playback.stop());
  }

  const details = block.querySelector(".score-parts");
  const partsListEl = document.getElementById("score-parts-list");
  let partsRendered = false;
  async function ensurePartsRendered() {
    if (partsRendered) return;
    partsRendered = true;
    await renderPerInstrument(partsListEl, musicXml);
  }
  details.addEventListener("toggle", () => {
    if (details.open) ensurePartsRendered();
  });

}

async function loadPost() {
  const res = await fetch(`/api/posts/${postId}`);
  if (!res.ok) {
    titleEl.textContent = "Post not found.";
    return;
  }
  const post = await res.json();

  titleEl.textContent = post.title;
  metaEl.textContent = `by ${post.authorName || "Anonymous"} · ${formatDate(
    post.createdAt ? post.createdAt._seconds : null
  )}`;
  promptEl.textContent = post.prompt ? `"${post.prompt}"` : "";
  contentEl.textContent = post.content || "";
  renderPlayer(post);
  if (post.musicXml) renderScore(post.musicXml);

  renderComments(post.comments || []);
}

async function setupCommentForm() {
  const user = await getCurrentUser();
  if (!user) {
    commentFormWrap.style.display = "none";
    commentLoginNote.style.display = "block";
    return;
  }

  commentFormWrap.style.display = "flex";
  commentLoginNote.style.display = "none";

  commentFormWrap.addEventListener("submit", async (e) => {
    e.preventDefault();
    const textarea = document.getElementById("comment-text");
    const text = textarea.value.trim();
    if (!text) return;

    const submitBtn = commentFormWrap.querySelector("button");
    submitBtn.disabled = true;

    try {
      const res = await authedFetch(`/api/posts/${postId}/comments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.error || "Failed to post the comment.");
      }
      textarea.value = "";
      await loadPost();
    } catch (err) {
      alert(err.message);
    } finally {
      submitBtn.disabled = false;
    }
  });
}

loadPost();
setupCommentForm();