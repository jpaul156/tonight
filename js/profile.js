// ============================================================
// Tonight — profile UI glue (Phase 1)
// ============================================================
// Classic script (runs in the same global scope as app.js) that bridges the
// Firebase data layer (window.TonightAuth) to the app: the account menu, the
// Home Square picker, favorite toggles in the detail overlay, and the
// re-render trigger when profile state changes.
//
// Everything here is guarded so that when TonightAuth is in DISABLED mode
// (Firebase not configured) the account button simply doesn't render and the
// app is untouched.
// ============================================================

(function () {
  // ---- identity keys: how an event joins to a favoritable venue / artist ---
  // Venue key mirrors venueFor()'s lookup: stamped venue_id, else the id-parse
  // fallback used for older events.
  function venueKeyFor(e) {
    return e.venue_id || (e.id ? e.id.split("-").slice(0, 2).join("-") : null);
  }
  function artistKeyFor(e) {
    const a = (typeof artistFor === "function") ? artistFor(e) : null;
    return a && a.name ? a.name : null;
  }

  // Exposed to app.js (all optional-chained there, so absence is safe).
  window.TonightProfile = {
    homeSquare() { return window.TonightAuth?.homeSquare?.() || null; },
    isFavoriteEvent(e) {
      const A = window.TonightAuth;
      if (!A || !A.enabled) return false;
      return A.isFavoriteVenue(venueKeyFor(e)) || A.isFavoriteArtist(artistKeyFor(e));
    },
    decorateDetail,
  };

  // ---- account menu --------------------------------------------------------
  let menuBuilt = false;

  function buildAccountUI() {
    const A = window.TonightAuth;
    if (!A || !A.enabled || menuBuilt) return;
    menuBuilt = true;

    const header = document.getElementById("header");
    if (!header) return;

    const btn = document.createElement("button");
    btn.id = "account-btn";
    btn.className = "account-btn";
    btn.setAttribute("aria-haspopup", "dialog");
    btn.setAttribute("aria-label", "Account");
    header.appendChild(btn);

    const panel = document.createElement("div");
    panel.id = "account-panel";
    panel.className = "account-panel";
    panel.hidden = true;
    document.body.appendChild(panel);

    btn.addEventListener("click", () => {
      panel.hidden = !panel.hidden;
      if (!panel.hidden) renderPanel();
    });
    document.addEventListener("click", (ev) => {
      if (!panel.hidden && !panel.contains(ev.target) && ev.target !== btn) panel.hidden = true;
    });

    refreshAccountButton();
  }

  function refreshAccountButton() {
    const btn = document.getElementById("account-btn");
    if (!btn) return;
    const u = window.TonightAuth?.current?.();
    const verified = window.TonightAuth?.isVerified?.();
    if (verified) {
      const label = (u.displayName || u.email || "You").trim();
      btn.textContent = label.charAt(0).toUpperCase();
      btn.classList.add("is-verified");
      btn.title = label;
    } else {
      btn.textContent = "☆";
      btn.classList.remove("is-verified");
      btn.title = "Sign in";
    }
  }

  function renderPanel() {
    const A = window.TonightAuth;
    const panel = document.getElementById("account-panel");
    if (!panel) return;
    panel.innerHTML = "";

    const verified = A.isVerified();
    const u = A.current();

    const head = document.createElement("div");
    head.className = "ap-head";
    head.textContent = verified ? (u.displayName || u.email) : "Not signed in";
    panel.appendChild(head);

    // Home Square — allowed for everyone, even anonymous.
    panel.appendChild(buildHomeSquarePicker());

    if (verified) {
      const sub = document.createElement("p");
      sub.className = "ap-note";
      sub.textContent = "★ Favorites & Lit unlocked.";
      panel.appendChild(sub);

      const out = mkBtn("Sign out", async () => { await A.signOutUser(); panel.hidden = true; });
      out.className = "ap-btn ap-btn-ghost";
      panel.appendChild(out);
    } else {
      const note = document.createElement("p");
      note.className = "ap-note";
      note.textContent = "Sign in to favorite venues & artists and mark events Lit.";
      panel.appendChild(note);

      panel.appendChild(mkBtn("Continue with Google", () => A.signInGoogle().catch(showErr)));

      const emailWrap = document.createElement("div");
      emailWrap.className = "ap-email";
      const input = document.createElement("input");
      input.type = "email";
      input.placeholder = "you@email.com";
      input.className = "ap-input";
      const send = mkBtn("Email me a link", async () => {
        if (!input.value) return;
        try { await A.startEmailLink(input.value); send.textContent = "Check your inbox ✓"; }
        catch (e) { showErr(e); }
      });
      emailWrap.append(input, send);
      panel.appendChild(emailWrap);
    }
  }

  function buildHomeSquarePicker() {
    const wrap = document.createElement("div");
    wrap.className = "ap-home";
    const label = document.createElement("label");
    label.textContent = "Home square";
    label.className = "ap-label";
    const select = document.createElement("select");
    select.className = "ap-select";

    // Options: squares that have events tonight (from app.js eventSquares),
    // sorted, plus whatever's currently saved. A fuller station list can
    // replace this later.
    const squares = new Set(
      (typeof eventSquares !== "undefined" ? Array.from(eventSquares) : []).filter(Boolean)
    );
    const saved = window.TonightAuth?.homeSquare?.();
    if (saved) squares.add(saved);
    const def = (typeof HOME_SQUARE !== "undefined") ? HOME_SQUARE : "Davis";
    squares.add(def);

    Array.from(squares).sort().forEach((sq) => {
      const opt = document.createElement("option");
      opt.value = sq; opt.textContent = sq;
      if (sq === (saved || def)) opt.selected = true;
      select.appendChild(opt);
    });
    select.addEventListener("change", () => {
      window.TonightAuth?.setHomeSquare?.(select.value);
    });
    wrap.append(label, select);
    return wrap;
  }

  // ---- favorite toggles in the detail overlay ------------------------------
  function decorateDetail(e) {
    const A = window.TonightAuth;
    if (!A || !A.enabled) return;
    const row = document.querySelector("#detail-overlay .venue-row");
    if (!row) return;

    // Clean up any button from a previous open.
    row.querySelector(".fav-btn")?.remove();

    const vKey = venueKeyFor(e);
    const btn = document.createElement("button");
    btn.className = "fav-btn";
    const paint = () => {
      const on = A.isFavoriteVenue(vKey);
      btn.textContent = on ? "★" : "☆";
      btn.classList.toggle("is-on", on);
      btn.title = on ? "Favorited — remove" : "Favorite this venue";
    };
    paint();
    btn.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      if (!A.isVerified()) { openAccountMenu(); return; }
      const r = await A.toggleFavoriteVenue(vKey);
      if (r.ok) paint();
    });
    row.appendChild(btn);
  }

  function openAccountMenu() {
    const panel = document.getElementById("account-panel");
    if (panel) { panel.hidden = false; renderPanel(); }
  }

  // ---- helpers -------------------------------------------------------------
  function mkBtn(text, onClick) {
    const b = document.createElement("button");
    b.className = "ap-btn";
    b.textContent = text;
    b.addEventListener("click", onClick);
    return b;
  }
  function showErr(e) { console.error(e); alert(e.message || "Sign-in failed."); }

  // ---- react to profile/auth changes --------------------------------------
  window.addEventListener("tonight-profile-changed", () => {
    buildAccountUI();
    refreshAccountButton();
    const panel = document.getElementById("account-panel");
    if (panel && !panel.hidden) renderPanel();
    // Let app.js re-rank the feed + re-home the map (it listens separately).
  });

  // In case the event already fired before this script parsed.
  if (window.TonightAuth) buildAccountUI();
})();
