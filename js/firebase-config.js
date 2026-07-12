// ============================================================
// Tonight — Firebase config (Phase 1: user profiles)
// ============================================================
// Web config values are NOT secret — access is enforced by Firestore
// Security Rules, not by hiding these keys. Safe to commit.
//
// Two projects, so test signups / junk venue requests / Lit spam never
// land in the same Firestore real users hit:
//   • tonight-dev  — used on localhost + branch previews
//   • tonight-prod — used on the live GitHub Pages domain
//
// Environment is chosen by hostname below. Fill in both blocks after you
// create the projects in the Firebase console (Project settings → Your apps
// → Web app → SDK setup and configuration → "Config").
//
// Until real values are filled in, apiKey stays "REPLACE_ME" and the auth
// layer runs in DISABLED mode — the site behaves exactly as it does today.

(function () {
  const CONFIGS = {
    dev: {
      apiKey: "AIzaSyAGocitQKPLmsFsC5sbmEHgq1jYM8NVXMs",
      authDomain: "tonight-dev-db064.firebaseapp.com",
      projectId: "tonight-dev-db064",
      storageBucket: "tonight-dev-db064.firebasestorage.app",
      messagingSenderId: "855560050469",
      appId: "1:855560050469:web:de67067d8d806e254faccc",
    },
    prod: {
      apiKey: "REPLACE_ME",
      authDomain: "tonight-prod.firebaseapp.com",
      projectId: "tonight-prod",
      storageBucket: "tonight-prod.appspot.com",
      messagingSenderId: "REPLACE_ME",
      appId: "REPLACE_ME",
    },
  };

  // Live prod domain(s). Everything else (localhost, *.pages.dev branch
  // previews, netlify previews) is treated as dev.
  const PROD_HOSTS = ["tonight.example.com"]; // TODO: set your GitHub Pages / custom domain
  const env = PROD_HOSTS.includes(location.hostname) ? "prod" : "dev";

  const cfg = CONFIGS[env];
  window.TONIGHT_ENV = env;
  window.TONIGHT_FIREBASE = cfg;
  // The auth layer reads this to decide whether to boot Firebase at all.
  window.TONIGHT_FIREBASE_ENABLED = cfg.apiKey !== "REPLACE_ME";
})();
