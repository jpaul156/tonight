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
2. In each: Build → **Authentication** → enable **Anonymous** and **Google**. (Email link
   is parked — the plumbing exists in `js/auth.js` but the UI is removed until sending
   moves to a custom tonight.quest domain; the default Firebase sender lands in spam.)
3. Authorized domains: add `localhost` (dev — projects created after Apr 2025 don't
   include it by default) and your Pages/custom domain (prod).
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
    // You. Sign in to the app (or dashboard) with your Google account, then
    // copy your uid from Firebase console → Authentication → Users. Set it
    // separately in each project (dev uid ≠ prod uid).
    function isAdmin() {
      return request.auth != null && request.auth.uid == 'vpYicmgCouPWk8xHlr4KFGQRY2K3';
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

      // Messages to this user ("your venue was added", personal thank-yous).
      // Admin writes them (dashboard "Send note"); the owner reads them and
      // may only flip read/readAt (dismissal) — never edit the text.
      match /notifications/{nid} {
        allow read: if isOwner(uid);
        allow create: if isAdmin();
        allow update: if isOwner(uid)
          && request.resource.data.diff(resource.data).affectedKeys().hasOnly(['read', 'readAt']);
        allow delete: if isOwner(uid) || isAdmin();
      }
    }

    // "Suggest a venue" intake. Create-only from the client — no reads,
    // edits, or deletes (review happens in app_health.html). VERIFIED
    // accounts only: a suggestion that becomes a venue earns the account
    // points (future swag redemption), and an anonymous uid dies with
    // cleared storage or a new phone — the credit must outlive both. Doc
    // shape locked down hard: exact keys, capped string sizes, http(s)
    // only, status pinned to 'new'.
    match /venue_suggestions/{id} {
      allow create: if isVerified()
        && request.resource.data.uid == request.auth.uid
        && request.resource.data.keys().hasOnly(['uid', 'url', 'name', 'status', 'createdAt'])
        && request.resource.data.url is string
        && request.resource.data.url.matches('https?://.+')
        && request.resource.data.url.size() <= 500
        && request.resource.data.name is string
        && request.resource.data.name.size() <= 120
        && request.resource.data.status == 'new';
      // Admin (the app_health.html review section): read the queue, set
      // status/reviewedAt/reviewedBy on approve/deny, delete spam.
      allow read, update, delete: if isAdmin();
    }
  }
}
```

## Test

`python3 -m http.server 8000` → `http://localhost:8000`.

- **Disabled (before keys):** no account button; site unchanged.
- **After dev keys:** a **Sign in** pill appears top-right → anonymous session starts
  silently → pick a **Home Square** (works anonymous; options = every named station on
  the traced map) → the metro map opens centered there and, on "Near me", events in that
  square **rank first**. The Home Square is never a filter — the feed still shows
  everything (first step toward multi-factor ranking: distance, favorites, sponsored).
- **Sign in with Google:** star in an event's detail overlay favorites the venue; it jumps
  to the top of the feed. Try favoriting while anonymous → it opens the sign-in menu instead.
- **Suggest a venue:** in the account panel, "Suggest a venue…" expands to a URL (+ optional
  name) form; submitting writes a `/venue_suggestions` doc stamped with your uid (check the
  Firestore console). **Signed-in accounts only** (tapping it anonymous explains why) — the
  uid is how suggestion credit/points survive cleared cookies or a new phone. Requires the
  rules above to be deployed first.
- **Review suggestions:** open `app_health.html` → "Venue suggestions" → Sign in with Google
  (must be the account whose uid is in `isAdmin()`). Approve/Deny sets status; "Send note"
  writes a notification to the suggester.
- **Notifications:** after sending a note, the suggester's account button grows an amber dot;
  opening the panel shows the message with a "Got it" dismiss (marks it read, dot clears).

## Phase 2+ (not built)

- **Lit** — verified-only, ephemeral (~event length), aggregate counter per event feeding a
  nav-layer heatmap; selecting a hot area prioritizes the Lit event.
- **Venue/artist accounts** — custom claims (`venue`/`artist`/`admin`), claim/verify flow,
  Firestore→`events.json` materialization Action, day-of event verification for a placement boost.
- **Venue requests** — ~~URL intake~~ (built: the "Suggest a venue" form above) → auto-first-pass
  scraper reading `/venue_suggestions` → app-health review/approval view.
