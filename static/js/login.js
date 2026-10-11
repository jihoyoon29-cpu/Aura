import { auth } from "./firebase-config.js";
import { signInWithEmailAndPassword } from "https://www.gstatic.com/firebasejs/10.12.0/firebase-auth.js";
import { initNav, friendlyAuthError } from "./auth.js";

initNav();

const form = document.getElementById("login-form");
const msgEl = document.getElementById("form-msg");
const submitBtn = document.getElementById("submit-btn");

function showMsg(text, type) {
  msgEl.textContent = text;
  msgEl.className = `form-msg ${type === "error" ? "is-error" : "is-ok"}`;
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const email = document.getElementById("email").value.trim();
  const password = document.getElementById("password").value;

  submitBtn.disabled = true;
  submitBtn.textContent = "Logging in...";

  try {
    await signInWithEmailAndPassword(auth, email, password);
    window.location.href = "/";
  } catch (err) {
    showMsg(friendlyAuthError(err), "error");
    submitBtn.disabled = false;
    submitBtn.textContent = "Log in";
  }
});
