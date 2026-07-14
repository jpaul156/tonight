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
  // Favorites are written to Firestore, so both keys must be frozen uids —
  // venue uid = the key in data/venues.json, artist uid = the id field in
  // data/artists.json. Never a display name (renames would orphan them).
  // Venue fallback: parse the old title-slug id shape, but only trust it if it
  // names a real venue — hash-derived ids (permalink events) parse to garbage.
  function venueKeyFor(e) {
    if (e.venue_id) return e.venue_id;
    const guess = e.id ? e.id.split("-").slice(0, 2).join("-") : null;
    return (guess && typeof venueData !== "undefined" && venueData[guess]) ? guess : null;
  }
  function artistKeyFor(e) {
    const a = (typeof artistFor === "function") ? artistFor(e) : null;
    return a && a.id ? a.id : null;
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
  let savedFlashUntil = 0; // "Saved ✓" survives the panel re-render on profile echo

  function buildAccountUI() {
    const A = window.TonightAuth;
    if (!A || !A.enabled || menuBuilt) return;
    menuBuilt = true;

    const header = document.getElementById("header");
    if (!header) return;
    header.classList.add("has-account"); // logo makes room for the button

    const btn = document.createElement("button");
    btn.id = "account-btn";
    btn.className = "account-btn";
    btn.setAttribute("aria-haspopup", "dialog");
    btn.setAttribute("aria-label", "Account");
    header.appendChild(btn);

    const panel = document.createElement("div");
    panel.id = "account-panel";
    panel.className = "account-panel";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", "Account");
    panel.hidden = true;
    document.body.appendChild(panel);

    btn.addEventListener("click", () => {
      const opening = panel.hidden;
      if (opening) renderPanel();
      setPanelOpen(opening);
    });
    document.addEventListener("click", (ev) => {
      if (panel.hidden || ev.target === btn) return;
      // A click inside the panel can remove its own target before this
      // bubbles up (e.g. "Suggest a venue…" swapping itself for the form) —
      // a detached target isn't "outside", so don't treat it as a close.
      if (!ev.target.isConnected) return;
      if (!panel.contains(ev.target)) setPanelOpen(false);
    });
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape" && !panel.hidden) setPanelOpen(false);
    });

    refreshAccountButton();
  }

  function setPanelOpen(open) {
    const panel = document.getElementById("account-panel");
    const btn = document.getElementById("account-btn");
    if (!panel) return;
    panel.hidden = !open;
    btn?.setAttribute("aria-expanded", String(open));
  }

  // Grayscale head-and-shoulders silhouette — the universal "account" glyph.
  const PERSON_SVG =
    '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">' +
    '<path d="M12 12a4.5 4.5 0 1 0-4.5-4.5A4.5 4.5 0 0 0 12 12zm0 2.2c-4.14 0-7.5 2.13-7.5 4.8v1.2h15V19c0-2.67-3.36-4.8-7.5-4.8z"/></svg>';

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
      btn.setAttribute("aria-label", "Account");
    } else {
      btn.innerHTML = PERSON_SVG;
      btn.classList.remove("is-verified");
      btn.title = "Sign in";
      btn.setAttribute("aria-label", "Sign in");
    }
    // Unread notifications → amber dot on the button, whatever the auth state.
    btn.classList.toggle("has-dot", (window.TonightAuth?.unreadCount?.() || 0) > 0);
  }

  // Panel layout: title bar (identity + ✕), then divided sections — sign-in,
  // Home Square, suggest-a-venue — and a quiet text "Sign out" at the very
  // bottom. Sectioned so this can grow toward a fuller menu without another
  // restructure. No save/Done button anywhere: Home Square saves on selection
  // (with a "Saved ✓" flash) and the panel closes via ✕ / Escape / outside tap.
  function renderPanel() {
    const A = window.TonightAuth;
    const panel = document.getElementById("account-panel");
    if (!panel) return;
    panel.innerHTML = "";

    const verified = A.isVerified();
    const u = A.current();

    const bar = document.createElement("div");
    bar.className = "ap-titlebar";
    const head = document.createElement("div");
    head.className = "ap-head";
    head.textContent = verified ? (u.displayName || u.email) : "Not signed in";
    const close = document.createElement("button");
    close.className = "ap-close";
    close.setAttribute("aria-label", "Close");
    close.textContent = "✕";
    close.addEventListener("click", () => setPanelOpen(false));
    bar.append(head, close);
    panel.appendChild(bar);

    const section = () => {
      const s = document.createElement("div");
      s.className = "ap-section";
      panel.appendChild(s);
      return s;
    };

    // Unread messages first — they're why the dot lit up.
    const notes = A.notifications?.() || [];
    if (notes.length) {
      const s = section();
      notes.forEach((n) => {
        const row = document.createElement("div");
        row.className = "ap-msg";
        const text = document.createElement("p");
        text.className = "ap-msg-text";
        text.textContent = n.text || "";
        const ok = document.createElement("button");
        ok.className = "ap-msg-dismiss";
        ok.textContent = "Got it";
        // The snapshot listener re-renders the panel once the write lands.
        ok.addEventListener("click", () => { ok.disabled = true; A.markNotificationRead(n.id); });
        row.append(text, ok);
        s.appendChild(row);
      });
    }

    if (!verified) {
      const signin = section();
      const note = document.createElement("p");
      note.className = "ap-note";
      note.textContent = "Sign in to favorite venues & artists and mark events Lit.";
      signin.appendChild(note);

      signin.appendChild(mkBtn("Continue with Google", () => A.signInGoogle().catch(showErr)));

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
      signin.appendChild(emailWrap);
    }

    // Home Square — allowed for everyone, even anonymous.
    section().appendChild(buildHomeSquarePicker());

    section().appendChild(buildVenueSuggest());

    if (verified) {
      const out = document.createElement("button");
      out.className = "ap-signout";
      out.textContent = "Sign out";
      out.addEventListener("click", async () => { await A.signOutUser(); setPanelOpen(false); });
      section().appendChild(out);
    }
  }

  // "Suggest a venue" — collapsed to one button; expands into a small form.
  // Anyone with a session (anonymous included) can submit; the suggestion is
  // stamped with their uid in Firestore so it's tied to their profile.
  function buildVenueSuggest() {
    const wrap = document.createElement("div");
    wrap.className = "ap-suggest";

    const open = mkBtn("Suggest a venue…", () => {
      open.remove();
      wrap.appendChild(form);
      urlInput.focus();
    });
    open.className = "ap-btn ap-btn-ghost";
    wrap.appendChild(open);

    const form = document.createElement("form");
    form.className = "ap-suggest-form";

    const hint = document.createElement("p");
    hint.className = "ap-note";
    hint.textContent = "Know a spot we're missing? Paste a link to their events / calendar page.";

    const urlInput = document.createElement("input");
    urlInput.type = "url";
    urlInput.required = true;
    urlInput.placeholder = "https://venue.com/calendar";
    urlInput.className = "ap-input";

    const nameInput = document.createElement("input");
    nameInput.type = "text";
    nameInput.maxLength = 100;
    nameInput.placeholder = "Venue name (optional)";
    nameInput.className = "ap-input";

    const send = document.createElement("button");
    send.type = "submit";
    send.className = "ap-btn";
    send.textContent = "Submit";

    form.append(hint, urlInput, nameInput, send);
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      let parsed;
      try { parsed = new URL(urlInput.value.trim()); } catch { parsed = null; }
      if (!parsed || !/^https?:$/.test(parsed.protocol)) {
        urlInput.setCustomValidity("Please paste a full link, starting with http(s)://");
        urlInput.reportValidity();
        urlInput.addEventListener("input", () => urlInput.setCustomValidity(""), { once: true });
        return;
      }
      send.disabled = true;
      send.textContent = "Sending…";
      try {
        const r = await window.TonightAuth?.submitVenueSuggestion?.({
          url: parsed.href,
          name: nameInput.value,
        });
        if (!r?.ok) throw new Error(r?.reason || "failed");
        const thanks = document.createElement("p");
        thanks.className = "ap-note";
        thanks.textContent = "Thanks — we'll check it out ✓";
        form.replaceWith(thanks);
      } catch (e) {
        console.error(e);
        send.disabled = false;
        send.textContent = "Submit";
        alert("Couldn't send that just now — please try again.");
      }
    });

    return wrap;
  }

  function buildHomeSquarePicker() {
    const wrap = document.createElement("div");
    wrap.className = "ap-home";
    const label = document.createElement("label");
    label.textContent = "Home square";
    label.className = "ap-label";
    const saved = document.createElement("span");
    saved.className = "ap-label ap-saved";
    label.appendChild(document.createTextNode(" "));
    label.appendChild(saved);
    const select = document.createElement("select");
    select.className = "ap-select";

    // Options: every named station on the traced map (stationLineIndex, built
    // by app.js from transit-layer.json) — your home square shouldn't depend
    // on whether it has events tonight. eventSquares is the fallback if the
    // map didn't load.
    const squares = new Set(
      typeof stationLineIndex !== "undefined" && Object.keys(stationLineIndex).length
        ? Object.keys(stationLineIndex)
        : (typeof eventSquares !== "undefined" ? Array.from(eventSquares) : [])
    );
    squares.delete("");
    const current = window.TonightAuth?.homeSquare?.();
    if (current) squares.add(current);

    // Placeholder so an unset home square doesn't masquerade as a choice.
    const ph = document.createElement("option");
    ph.value = ""; ph.textContent = "Not set";
    ph.selected = !current;
    select.appendChild(ph);

    Array.from(squares).sort().forEach((sq) => {
      const opt = document.createElement("option");
      opt.value = sq; opt.textContent = sq;
      if (sq === current) opt.selected = true;
      select.appendChild(opt);
    });
    // The Firestore write echoes back as tonight-profile-changed, which
    // re-renders the panel — so the flash must survive a rebuild.
    if (Date.now() < savedFlashUntil) {
      saved.textContent = "Saved ✓";
      setTimeout(() => { saved.style.opacity = "0"; }, Math.max(0, savedFlashUntil - Date.now()));
    }
    select.addEventListener("change", async () => {
      savedFlashUntil = Date.now() + 1600;
      await window.TonightAuth?.setHomeSquare?.(select.value || null);
      saved.textContent = "Saved ✓";
      setTimeout(() => { saved.style.opacity = "0"; }, 1600);
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
    if (panel) { renderPanel(); setPanelOpen(true); }
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
