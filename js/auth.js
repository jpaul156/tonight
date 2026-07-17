// ============================================================
// Tonight — auth + profile data layer (Phase 1)
// ============================================================
// Loaded as a <script type="module"> so it can import the modular Firebase
// SDK from the CDN (no build step, matches the site's no-bundler ethos).
// Exposes a small synchronous-friendly API on window.TonightAuth and fires
// a `tonight-profile-changed` event on window whenever auth state, the
// user's profile, or their favorites change. The rest of the app (classic
// scripts) only ever touches window.TonightAuth — never Firebase directly.
//
// DISABLED mode: if firebase-config.js hasn't been filled in
// (window.TONIGHT_FIREBASE_ENABLED === false) every method is a safe no-op
// and the site behaves exactly as it did before profiles existed.
//
// Access model (enforced for real by Firestore Security Rules, mirrored
// here for UX):
//   • Anyone (even anonymous) may set a Home Square.
//   • Favorites + Lit require a VERIFIED account (signed in, not anonymous,
//     verified email) — anti-abuse for favorite counts / Lit heatmap.
// ============================================================

const state = {
  ready: false,
  user: null,                 // firebase user or null
  profile: null,              // /users/{uid} doc data
  favVenues: new Set(),
  favArtists: new Set(),
  notifications: [],          // unread /users/{uid}/notifications docs, newest first
};

function emitChanged() {
  window.dispatchEvent(new CustomEvent("tonight-profile-changed"));
}

// iOS/iPadOS Safari and other mobile WebKit browsers lose the popup→opener
// handshake under ITP storage partitioning, leaving sign-in silently stuck
// until a reload. Prefer full-page redirect there. Covers iPhone/iPad
// (including iPadOS masquerading as desktop Safari, detected via touch) and
// any browser on iOS (Chrome/Firefox on iOS are WebKit under the hood).
function preferRedirectSignIn() {
  const ua = navigator.userAgent || "";
  const iOS = /iPad|iPhone|iPod/.test(ua) ||
    // iPadOS 13+ reports as "Macintosh" but is a touch device.
    (navigator.platform === "MacIntel" && (navigator.maxTouchPoints || 0) > 1);
  const crios = /CriOS|FxiOS|EdgiOS/.test(ua); // Chrome/Firefox/Edge on iOS
  return iOS || crios;
}

// ---- DISABLED mode ---------------------------------------------------------
// Stand up a no-op API so callers don't need to null-check everywhere.
function installDisabled() {
  window.TonightAuth = {
    enabled: false,
    ready: Promise.resolve(),
    current: () => null,
    isVerified: () => false,
    signInGoogle: async () => { warnDisabled(); },
    startEmailLink: async () => { warnDisabled(); },
    completeEmailLinkIfPresent: async () => false,
    signOutUser: async () => {},
    homeSquare: () => null,
    setHomeSquare: async () => {},
    favorites: () => ({ venues: new Set(), artists: new Set() }),
    isFavoriteVenue: () => false,
    isFavoriteArtist: () => false,
    toggleFavoriteVenue: async () => ({ ok: false, reason: "disabled" }),
    toggleFavoriteArtist: async () => ({ ok: false, reason: "disabled" }),
    submitVenueSuggestion: async () => ({ ok: false, reason: "disabled" }),
    notifications: () => [],
    unreadCount: () => 0,
    markNotificationRead: async () => {},
  };
  function warnDisabled() {
    console.info("[Tonight] Firebase not configured — sign-in disabled. Fill js/firebase-config.js.");
  }
  emitChanged();
}

if (!window.TONIGHT_FIREBASE_ENABLED) {
  installDisabled();
} else {
  boot().catch((err) => {
    console.error("[Tonight] auth boot failed, falling back to disabled:", err);
    installDisabled();
  });
}

async function boot() {
  const V = "11.0.2"; // Firebase modular SDK version (CDN)
  const [{ initializeApp }, authMod, fsMod] = await Promise.all([
    import(`https://www.gstatic.com/firebasejs/${V}/firebase-app.js`),
    import(`https://www.gstatic.com/firebasejs/${V}/firebase-auth.js`),
    import(`https://www.gstatic.com/firebasejs/${V}/firebase-firestore.js`),
  ]);

  const app = initializeApp(window.TONIGHT_FIREBASE);
  const auth = authMod.getAuth(app);
  const db = fsMod.getFirestore(app);

  // Keep a live reference to profile + favorites doc unsubscribers so we can
  // swap them when the signed-in user changes.
  let unsubProfile = null;
  let unsubNotifs = null;

  const api = {
    enabled: true,
    ready: null, // set below

    current() {
      if (!state.user) return null;
      const u = state.user;
      return {
        uid: u.uid,
        isAnonymous: u.isAnonymous,
        email: u.email || null,
        emailVerified: u.emailVerified,
        displayName: u.displayName || null,
        isVerified: this.isVerified(),
      };
    },

    // Verified = a real, email-verified account. Google sign-ins arrive
    // pre-verified; email-link sign-ins are inherently verified too.
    isVerified() {
      const u = state.user;
      return !!(u && !u.isAnonymous && u.emailVerified);
    },

    async signInGoogle() {
      const provider = new authMod.GoogleAuthProvider();
      // Always show Google's account chooser. Without this, a lone
      // already-granted Google session is reused silently — so sign-out →
      // sign-in bounces back into the same account with no way to switch.
      // Cheap here because this only runs on an explicit "Continue with
      // Google" tap; returning users ride Firebase's persisted session.
      provider.setCustomParameters({ prompt: "select_account" });

      // iOS Safari (and mobile WebKit generally) partitions the popup's
      // storage under ITP and routinely drops the popup→opener postMessage
      // handshake: the popup completes and persists the session, but
      // onAuthStateChanged never fires in the opener, so the page looks
      // signed-out until a reload. Redirect has no cross-window handshake —
      // getRedirectResult() in boot() finishes it on return — so prefer it
      // on those browsers. Desktop keeps the nicer popup.
      const useRedirect = preferRedirectSignIn();

      // If currently anonymous, link so the uid (and their Home Square) carries over.
      if (state.user && state.user.isAnonymous) {
        if (useRedirect) {
          // getRedirectResult() handles credential-already-in-use on return.
          await authMod.linkWithRedirect(state.user, provider);
          return;
        }
        try {
          await authMod.linkWithPopup(state.user, provider);
          return;
        } catch (e) {
          if (e.code === "auth/popup-blocked") {
            // Popup blocked (strict settings) — full-page redirect instead.
            // getRedirectResult() in boot() finishes it on return.
            await authMod.linkWithRedirect(state.user, provider);
            return;
          }
          if (e.code !== "auth/credential-already-in-use") throw e;
          // That Google account already exists as a user, so it can't be
          // linked — but the error carries the credential the user just
          // picked in the chooser. Sign in with it directly rather than
          // opening a second popup (which re-showed the account chooser).
          const cred = authMod.GoogleAuthProvider.credentialFromError(e);
          if (cred) { await authMod.signInWithCredential(auth, cred); return; }
          // No recoverable credential (shouldn't happen) — plain sign-in.
        }
      }
      if (useRedirect) {
        await authMod.signInWithRedirect(auth, provider);
        return;
      }
      try {
        await authMod.signInWithPopup(auth, provider);
      } catch (e) {
        if (e.code !== "auth/popup-blocked") throw e;
        await authMod.signInWithRedirect(auth, provider);
      }
    },

    // Passwordless email link. Sends the link; completeEmailLinkIfPresent()
    // finishes it when the user returns via that link.
    async startEmailLink(email) {
      const actionCodeSettings = { url: location.origin + location.pathname, handleCodeInApp: true };
      await authMod.sendSignInLinkToEmail(auth, email, actionCodeSettings);
      window.localStorage.setItem("tonightEmailForSignIn", email);
    },

    async completeEmailLinkIfPresent() {
      if (!authMod.isSignInWithEmailLink(auth, window.location.href)) return false;
      let email = window.localStorage.getItem("tonightEmailForSignIn");
      if (!email) email = window.prompt("Confirm your email to finish signing in:");
      if (!email) return false;
      if (state.user && state.user.isAnonymous) {
        const cred = authMod.EmailAuthProvider.credentialWithLink(email, window.location.href);
        try {
          await authMod.linkWithCredential(state.user, cred);
        } catch (e) {
          if (e.code === "auth/credential-already-in-use") {
            await authMod.signInWithEmailLink(auth, email, window.location.href);
          } else throw e;
        }
      } else {
        await authMod.signInWithEmailLink(auth, email, window.location.href);
      }
      window.localStorage.removeItem("tonightEmailForSignIn");
      // Strip the sign-in params from the URL bar.
      history.replaceState(null, "", location.origin + location.pathname);
      return true;
    },

    async signOutUser() {
      await authMod.signOut(auth);
      // Back to a fresh anonymous session so Home Square etc. still work.
      await authMod.signInAnonymously(auth);
    },

    homeSquare() {
      return state.profile?.homeSquare || null;
    },

    async setHomeSquare(square) {
      if (!state.user) return;
      await writeProfile({ homeSquare: square || null });
    },

    favorites() {
      return { venues: new Set(state.favVenues), artists: new Set(state.favArtists) };
    },
    isFavoriteVenue(key) { return !!key && state.favVenues.has(key); },
    isFavoriteArtist(key) { return !!key && state.favArtists.has(key); },

    async toggleFavoriteVenue(key) { return toggleFav("favVenues", "venues", key); },
    async toggleFavoriteArtist(key) { return toggleFav("favArtists", "artists", key); },

    // "Suggest a venue" intake (Phase 2's venue-requests pipeline starts here).
    // One doc per suggestion in /venue_suggestions, stamped with the sender's
    // uid. VERIFIED accounts only (enforced for real by the Firestore rules):
    // a suggestion that becomes a venue earns the account points (future swag
    // redemption), and an anonymous uid dies with cleared storage or a new
    // phone — the credit has to outlive both. Write-only from the client:
    // review happens in app_health.html.
    async submitVenueSuggestion({ url, name }) {
      if (!state.user) return { ok: false, reason: "no-session" };
      if (!api.isVerified()) return { ok: false, reason: "needs-verified" };
      await fsMod.addDoc(fsMod.collection(db, "venue_suggestions"), {
        uid: state.user.uid,
        url: String(url || "").trim(),
        name: String(name || "").trim(),
        status: "new",
        createdAt: fsMod.serverTimestamp(),
      });
      return { ok: true };
    },

    // Per-user messages (/users/{uid}/notifications) — written by the admin
    // (dashboard "send note", venue-added announcements), read/dismissed by
    // the owner. Only unread ones are held in memory; dismissing marks
    // read:true rather than deleting so there's a record.
    notifications() { return state.notifications.slice(); },
    unreadCount() { return state.notifications.length; },
    async markNotificationRead(id) {
      if (!state.user || !id) return;
      await fsMod.setDoc(
        fsMod.doc(db, "users", state.user.uid, "notifications", id),
        { read: true, readAt: fsMod.serverTimestamp() },
        { merge: true }
      );
    },
  };

  // ---- profile doc I/O -----------------------------------------------------
  const userRef = () => fsMod.doc(db, "users", state.user.uid);

  async function writeProfile(patch) {
    await fsMod.setDoc(userRef(), { ...patch, updatedAt: fsMod.serverTimestamp() }, { merge: true });
  }

  async function toggleFav(localSet, field, key) {
    if (!key) return { ok: false, reason: "no-key" };
    if (!api.isVerified()) return { ok: false, reason: "needs-verified" };
    const set = state[localSet];
    const has = set.has(key);
    await fsMod.setDoc(
      userRef(),
      { favorites: { [field]: has ? fsMod.arrayRemove(key) : fsMod.arrayUnion(key) } },
      { merge: true }
    );
    return { ok: true, favorited: !has };
  }

  function applyProfileSnapshot(data) {
    state.profile = data || {};
    const fav = state.profile.favorites || {};
    state.favVenues = new Set(fav.venues || []);
    state.favArtists = new Set(fav.artists || []);
    emitChanged();
  }

  // ---- auth lifecycle ------------------------------------------------------
  // Finish a redirect sign-in if we're returning from one (the popup-blocked
  // fallback). Resolves null on a normal page load. A linkWithRedirect against
  // an already-existing Google account rejects like linkWithPopup does — fall
  // back to signing in as that account, same as the popup path.
  authMod.getRedirectResult(auth).catch(async (e) => {
    if (e.code === "auth/credential-already-in-use") {
      const cred = authMod.GoogleAuthProvider.credentialFromError(e);
      if (cred) { await authMod.signInWithCredential(auth, cred); return; }
    }
    console.error("[Tonight] redirect sign-in failed:", e);
  });

  api.ready = new Promise((resolve) => {
    authMod.onAuthStateChanged(auth, async (user) => {
      // Detach previous listeners.
      if (unsubProfile) { unsubProfile(); unsubProfile = null; }
      if (unsubNotifs) { unsubNotifs(); unsubNotifs = null; }

      if (!user) {
        // No session yet — start an anonymous one so Home Square works with
        // zero friction. onAuthStateChanged fires again with the anon user.
        state.user = null; state.profile = null;
        state.favVenues = new Set(); state.favArtists = new Set();
        state.notifications = [];
        try { await authMod.signInAnonymously(auth); } catch (e) { console.error(e); }
        emitChanged();
        return;
      }

      state.user = user;
      // Live-subscribe to the user's profile doc (Home Square + favorites).
      unsubProfile = fsMod.onSnapshot(userRef(), (snap) => {
        applyProfileSnapshot(snap.exists() ? snap.data() : {});
      });
      // ...and to their unread notifications (sorted client-side so no
      // composite index is needed).
      unsubNotifs = fsMod.onSnapshot(
        fsMod.query(
          fsMod.collection(db, "users", user.uid, "notifications"),
          fsMod.where("read", "==", false)
        ),
        (snap) => {
          state.notifications = snap.docs
            .map((d) => ({ id: d.id, ...d.data() }))
            .sort((a, b) => (b.createdAt?.seconds || 0) - (a.createdAt?.seconds || 0));
          emitChanged();
        },
        (err) => console.warn("[Tonight] notifications listener:", err.code || err)
      );

      // Finish a pending email-link sign-in if we arrived via one.
      try { await api.completeEmailLinkIfPresent(); } catch (e) { console.error(e); }

      state.ready = true;
      emitChanged();
      resolve();
    });
  });

  window.TonightAuth = api;
  emitChanged();
}
