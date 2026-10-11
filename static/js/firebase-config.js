// Firebase 프로젝트 콘솔 > 프로젝트 설정 > 일반 > 내 앱(웹)에서 발급받은 값으로 교체하세요.
// Firebase Console > Authentication > Sign-in method 에서 "이메일/비밀번호" 제공업체를 켜야 합니다.
// Firestore Database 도 콘솔에서 미리 생성해두어야 합니다 (테스트 모드 또는 규칙 설정).

import { initializeApp } from "https://www.gstatic.com/firebasejs/10.12.0/firebase-app.js";
import { getAuth } from "https://www.gstatic.com/firebasejs/10.12.0/firebase-auth.js";

const firebaseConfig = {
  apiKey: "AIzaSyA__5j-unXufm70LDfvpETK3ZiASX4zF_s",
  authDomain: "projectaura-bcb69.firebaseapp.com",
  projectId: "projectaura-bcb69",
  storageBucket: "projectaura-bcb69.firebasestorage.app",
  messagingSenderId: "467720802087",
  appId: "1:467720802087:web:4ceecb5cdde9c053826302",
};

export const app = initializeApp(firebaseConfig);
export const auth = getAuth(app);
