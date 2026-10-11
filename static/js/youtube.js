// 다양한 형태의 유튜브 URL에서 11자리 영상 ID를 추출한다.
// 지원: watch?v=, youtu.be/, embed/, shorts/
export function extractYouTubeId(url) {
  if (!url) return null;
  try {
    const u = new URL(url.trim());
    const host = u.hostname.replace(/^www\./, "");

    if (host === "youtu.be") {
      const id = u.pathname.slice(1).split("/")[0];
      return /^[\w-]{11}$/.test(id) ? id : null;
    }

    if (host === "youtube.com" || host === "m.youtube.com" || host === "music.youtube.com") {
      if (u.pathname === "/watch") {
        const id = u.searchParams.get("v");
        return id && /^[\w-]{11}$/.test(id) ? id : null;
      }
      const match = u.pathname.match(/^\/(embed|shorts)\/([\w-]{11})/);
      if (match) return match[2];
    }

    return null;
  } catch {
    return null;
  }
}

export function youtubeEmbedUrl(videoId) {
  return `https://www.youtube.com/embed/${videoId}`;
}