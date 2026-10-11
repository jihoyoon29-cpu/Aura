import { auth } from "./firebase-config.js";
import {
  createUserWithEmailAndPassword,
  updateProfile,
} from "https://www.gstatic.com/firebasejs/10.12.0/firebase-auth.js";
import { initNav, friendlyAuthError } from "./auth.js";

initNav();

const form = document.getElementById("signup-form");
const msgEl = document.getElementById("form-msg");
const submitBtn = document.getElementById("submit-btn");

function showMsg(text, type) {
  msgEl.textContent = text;
  msgEl.className = `form-msg ${type === "error" ? "is-error" : "is-ok"}`;
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = document.getElementById("name").value.trim();
  const email = document.getElementById("email").value.trim();
  const password = document.getElementById("password").value;

  submitBtn.disabled = true;
  submitBtn.textContent = "Signing up...";

  try {
    const cred = await createUserWithEmailAndPassword(auth, email, password);
    if (name) {
      await updateProfile(cred.user, { displayName: name });
    }
    showMsg("Account created. Taking you to the homepage...", "ok");
    setTimeout(() => (window.location.href = "/"), 800);
  } catch (err) {
    showMsg(friendlyAuthError(err), "error");
    submitBtn.disabled = false;
    submitBtn.textContent = "Sign up";
  }
});
