# User Profiles — Phase 1 setup

Phase 1 = anonymous-friendly accounts, **Home Square**, and **favorites** (venues/artists)
re-ranking the feed. Lit + venue/artist accounts come in later phases.

Until you fill in `js/firebase-config.js`, everything runs in **DISABLED mode** — the
account button doesn't render and the site behaves exactly as before. Nothing on `main`
changes until this branch is merged.

## What was added

| File | Role |
|---|---|
| `js/firebase-config.js` | dev/prod config, chosen by hostname. Web keys are public — safe to commit. |
| `js/auth.js` (module) | Firebase Auth + Firestore data layer → `window.TonightAuth`. Fires `tonight-profile-changed`. |
| `js/profile.js` | Account menu, Home Square picker, favorite stars → `window.TonightProfile`. |
| `css/profile.css` | Styles for the injected UI. |
| `js/app.js` hooks | `currentHomeSquare()`, favorite re-ranking in `render()`, `decorateDetail()` call, re-render on change. All optional-chained (no-op when disabled). |

## Firebase console steps

1. Create two projects: **tonight-dev** and **tonight-prod**.
2. In each: Build → **Authentication** → enable **Anonymous**, **Google**, and **Email link (passwordless)**.
3. Authorized domains: add `localhost` (dev) and your Pages/custom domain (prod).
4. Build → **Firestore Database** → create in production mode, then paste the rules below.
5. Project settings → Your apps → Web app → copy the config into the matching block of
   `js/firebase-config.js`. Set `PROD_HOSTS` to your live domain.

## Firestore Security Rules (the real gate)

The client hides favorite/Lit behind "verified," but these rules **enforce** it — a user
can only touch their own doc, anyone (even anonymous) may set `homeSquare`, and only a
verified account may write `favorites`.

```
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {

    function isOwner(uid) { return request.auth != null && request.auth.uid == uid; }
    // Verified = signed in, not anonymous, verified email.
    function isVerified() {
      return request.auth != null
        && request.auth.token.firebase.sign_in_provider != 'anonymous'
        && request.auth.token.email_verified == true;
    }
    // Which top-level fields changed in this write.
    function changed() {
      return request.resource.data.diff(resource.data).affectedKeys();
    }

    match /users/{uid} {
      allow read: if isOwner(uid);
      // Create: owner only; a fresh doc may include favorites only if verified.
      allow create: if isOwner(uid)
        && (!('favorites' in request.resource.data) || isVerified());
      // Update: owner only; if the write touches favorites, must be verified.
      allow update: if isOwner(uid)
        && (!changed().hasAny(['favorites']) || isVerified());
      allow delete: if isOwner(uid);
    }
  }
}
```

## Test

`python3 -m http.server 8000` → `http://localhost:8000`.

- **Disabled (before keys):** no account button; site unchanged.
- **After dev keys:** ☆ button appears top-right → anonymous session starts silently →
  pick a **Home Square** (works anonymous) → the metro map opens centered there **and the
  feed opens filtered to that square** on load (falls back to "Near me" if the square has no
  events tonight, or once you tap another square / "Near me").
- **Sign in with Google:** star in an event's detail overlay favorites the venue; it jumps
  to the top of the feed. Try favoriting while anonymous → it opens the sign-in menu instead.

## Phase 2+ (not built)

- **Lit** — verified-only, ephemeral (~event length), aggregate counter per event feeding a
  nav-layer heatmap; selecting a hot area prioritizes the Lit event.
- **Venue/artist accounts** — custom claims (`venue`/`artist`/`admin`), claim/verify flow,
  Firestore→`events.json` materialization Action, day-of event verification for a placement boost.
- **Venue requests** — URL intake → auto-first-pass scraper → app-health approval.
