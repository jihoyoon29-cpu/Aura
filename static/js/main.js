import { initNav } from "./auth.js";

initNav();

const listEl = document.getElementById("post-list");

function timeAgo(seconds) {
  if (!seconds) return "";
  const diff = Math.floor(Date.now() / 1000 - seconds);
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function renderPosts(posts) {
  if (!posts.length) {
    listEl.innerHTML = `
      <div class="empty-state">
        No tracks yet.<br />
        <a href="/write">Create the first one →</a>
      </div>`;
    return;
  }

  listEl.innerHTML = posts
    .map((p) => {
      const createdSec = p.createdAt ? p.createdAt._seconds : null;
      return `
        <a class="post-card" href="/post/${p.id}">
          <div class="post-card__top">
            <h3>${escapeHtml(p.title)}</h3>
            <span class="post-card__meta">${timeAgo(createdSec)}</span>
          </div>
          ${p.prompt ? `<div class="post-card__prompt">${escapeHtml(p.prompt)}</div>` : ""}
          <div class="post-card__footer">
            <span>by ${escapeHtml(p.authorName || "Anonymous")}</span>
            ${p.youtubeUrl ? `<span>▶ YouTube</span>` : ""}
            ${p.hasScore ? `<span>♪ Orchestra score</span>` : ""}
            <span>${p.commentCount ?? 0} comments</span>
          </div>
        </a>`;
    })
    .join("");
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

async function loadPosts() {
  try {
    const res = await fetch("/api/posts");
    const posts = await res.json();
    renderPosts(Array.isArray(posts) ? posts : []);
  } catch (err) {
    listEl.innerHTML = `<div class="empty-state">Failed to load the list.</div>`;
  }
}

loadPosts();