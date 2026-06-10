# AutoBVB v5.0 — Asymmetric Multi-Tenant Agentic Real Estate Auto-Poster

**AutoBVB** is an asymmetric multi-tenant agentic real estate auto-poster engineered to achieve **human-like browser posting** with **zero platform ban risks**. It targets the Noida Extension rental market, automating authenticated Facebook Marketplace and Group listings through a stealth, shadow-mode execution pipeline that halts immediately before publication for manual review.

---

## Architecture Overview: The "Two-Brain AI Engine"

AutoBVB v5.0 employs a dual-model asymmetric intelligence architecture decoupled from legacy monolithic prompts:

| Brain | Role | Model | Input | Output |
|-------|------|-------|-------|--------|
| **Brain 1: Visual Analyst** | Factual visual parsing & attribute extraction | **Gemini 2.0 Flash** | Property images + raw metadata (flat config, amenities, metro proximity) | Structured JSON: room counts, furnishing state, visible amenities, condition flags |
| **Brain 2: Marketing Copywriter** | Anti-spam caption generation (zero markdown) | **Gemini 2.0 Flash** | Brain 1 JSON + contact info + platform rules | 3 pure-text variations: Gold Standard, Lifestyle Narrative, Short & Urgent |

**Execution Loop**: Self-contained background worker powered by **native Playwright drivers** using **cookie state injection blocks** (`fb_state.json` → CDP session → persistent Chromium). No `browser-use` framework. No vision-model navigation. Deterministic DOM interaction only.

---

## Chronological Master Roadmap

### ✅ Phase 1: The AI Engine Refactor
- [x] Deleted legacy `vision_map.py` monolith
- [x] Implemented asymmetric **Two-Brain** architecture (Visual Analyst + Marketing Copywriter)
- [x] Pure-text variation generation — zero markdown formatting bugs
- [x] Structured JSON contract between brains for type-safe handoff

### ✅ Phase 2: The Controller Tooling
- [x] Overhauled `worker.py` with **localized session states** per tenant
- [x] **Clipboard paste wrappers** for text structure safety (bypasses Lexical/React input corruption)
- [x] **Native file chooser hooks** for multi-image uploads (no `set_input_files` race conditions)
- [x] Deterministic human-emulation: character delays, scroll mimicry, modal evasion

### ⬜ Phase 3: Central Database Migration
- [ ] Transition from `listings.json` → **Supabase PostgreSQL** (centralized listings table)
- [ ] Enterprise media buckets for property images (Supabase Storage)
- [ ] Row-level security policies for multi-tenant isolation
- [ ] Real-time subscriptions for worker polling (replaces 10s file watch)

### ⬜ Phase 4: VPS Container Deployment
- [ ] Hardcode production **static residential proxy routing** variables
- [ ] Finalize `docker-compose.yml` with **virtual framebuffers** (Xvfb) for headless Chromium
- [ ] Multi-tenant isolation scaling via container replication
- [ ] Health checks, log aggregation, and zero-downtime rolling updates

---

## Local Quickstart Guide

### Prerequisites
- Python 3.11+
- `fb_state.json` (valid Facebook session cookies — generate via `session_capture.py`)
- `dummy_flat.jpg` or real property images in `local_storage/`
- `.env` with `GOOGLE_API_KEY`

### Runtime Commands

```bash
# 1. Launch API server (FastAPI, port 8000)
python api.py

# 2. Launch background worker (polling loop)
python worker.py

# 3. Run Phase 1 verification test harness
python verify_phase1.py
```

### Verify Phase 1 Output
`verify_phase1.py` exercises the full Two-Brain pipeline:
1. Loads test image + metadata
2. Invokes Brain 1 → validates JSON schema compliance
3. Invokes Brain 2 → validates 3 variations, zero markdown, char limits
4. Asserts clipboard-safe text serialization
5. Exits 0 on success, non-zero on contract violation

---

## Project Structure (v5.0 Core)

```
AutoBVB/
├── api.py                    # FastAPI server for job ingestion & status
├── worker.py                 # Background polling loop + Playwright executor
├── content_engine.py         # Two-Brain orchestration (Brain1 + Brain2)
├── database.py               # Supabase client (Phase 3) / JSON fallback (Phase 1-2)
├── session_capture.py        # Interactive Chrome login → fb_state.json
├── verify_phase1.py          # Phase 1 contract test harness
├── _verify_*.py              # Internal verification utilities
├── fb_state.json             # Cookie state (gitignored in prod)
├── local_storage/            # Property images & proof screenshots
├── requirements.txt
└── docker-compose.yml        # Phase 4 target
```

---

## Environment Variables

```env
# Required
GOOGLE_API_KEY=your_gemini_api_key

# Phase 3+ (Supabase)
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_ANON_KEY=xxx
SUPABASE_SERVICE_ROLE_KEY=xxx

# Phase 4 (VPS)
PROXY_HOST=residential-proxy.example.com
PROXY_PORT=8080
PROXY_USER=xxx
PROXY_PASS=xxx
```

---

## Safety & Compliance

- **Shadow-mode only**: Worker **never clicks "Publish"**. Stops at composer review state.
- **Manual gate**: Human reviews screenshot proof (`local_storage/proofs/`) before any live post.
- **Account preservation**: Persistent cookie profiles, residential proxies, human delays — zero bot signatures.
- **Multi-tenant isolation**: Per-tenant `fb_state.json`, database rows, and container instances (Phase 4).

---

## License

Proprietary — Internal Use Only.