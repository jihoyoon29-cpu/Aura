import { auth } from "./firebase-config.js";
import {
  onAuthStateChanged,
  signOut,
} from "https://www.gstatic.com/firebasejs/10.12.0/firebase-auth.js";

// Updates the top nav based on login state.
export function initNav() {
  const navLinks = document.getElementById("nav-links");
  if (!navLinks) return;

  onAuthStateChanged(auth, (user) => {
    navLinks.innerHTML = "";

    if (user) {
      const writeLink = document.createElement("a");
      writeLink.href = "/write";
      writeLink.className = "btn btn--primary";
      writeLink.textContent = "Write";

      const nameSpan = document.createElement("span");
      nameSpan.className = "btn btn--ghost";
      nameSpan.textContent = user.displayName || user.email;

      const logoutBtn = document.createElement("button");
      logoutBtn.className = "btn btn--ghost";
      logoutBtn.textContent = "Log out";
      logoutBtn.addEventListener("click", async () => {
        await signOut(auth);
        window.location.href = "/";
      });

      navLinks.append(writeLink, nameSpan, logoutBtn);
    } else {
      const loginLink = document.createElement("a");
      loginLink.href = "/login";
      loginLink.className = "btn btn--ghost";
      loginLink.textContent = "Log in";

      const signupLink = document.createElement("a");
      signupLink.href = "/signup";
      signupLink.className = "btn btn--primary";
      signupLink.textContent = "Sign up";

      navLinks.append(loginLink, signupLink);
    }
  });
}

// Returns the current user as a Promise (waits for the first auth state to settle).
export function getCurrentUser() {
  return new Promise((resolve) => {
    const unsubscribe = onAuthStateChanged(auth, (user) => {
      unsubscribe();
      resolve(user);
    });
  });
}

// fetch wrapper that attaches the logged-in user's ID token when calling the backend API.
export async function authedFetch(url, options = {}) {
  const user = auth.currentUser;
  const headers = { ...(options.headers || {}) };

  if (user) {
    const token = await user.getIdToken();
    headers["Authorization"] = `Bearer ${token}`;
  }

  return fetch(url, { ...options, headers });
}

export function friendlyAuthError(error) {
  const map = {
    "auth/email-already-in-use": "That email is already registered.",
    "auth/invalid-email": "That doesn't look like a valid email address.",
    "auth/weak-password": "Password must be at least 6 characters.",
    "auth/user-not-found": "No account found with that email.",
    "auth/wrong-password": "Incorrect password.",
    "auth/invalid-credential": "Incorrect email or password.",
    "auth/too-many-requests": "Please try again in a moment.",
  };
  return map[error.code] || "Something went wrong. Please try again.";
}
