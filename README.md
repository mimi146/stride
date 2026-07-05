# Stride

A calm, fast task planner for people who want to get meaningful work done without burning out. Single HTML file, offline-first, with optional AI coaching and deep macOS integration.

Stride is built around one idea: **fewer decisions, less clutter, sustainable pace.** It guides you toward the next most important task instead of showing an endless list, warns you before you overcommit, and celebrates consistency over volume.

## Features

**Planning without friction.** One capture box that understands plain language — `Review deck tomorrow !high ~45m #work` sets the date, priority, estimate, and project in a single line. Inbox, Today, Upcoming, This Week, and Someday views; drag-and-drop reordering (dragging across days reschedules); subtasks, recurring tasks, projects, habits with streaks; a command palette (⌘K) and full keyboard control (press `?` for the map).

**Burnout prevention, built in.** Daily capacity tracking that counts your real meetings, overload warnings with a one-click Rebalance, a top-3 daily plan instead of a task avalanche, focus mode with break nudges after 50 minutes, and a Review view that celebrates showing up — not task volume.

**AI coaching (bring your own key).** Connect Anthropic, OpenAI, NVIDIA NIM, OpenRouter, or any OpenAI/Anthropic-compatible endpoint. The Assistant analyzes your habits, workload, calendar, and (optionally) Mac activity, then delivers a daily report: habit insights, mistakes to watch out for, and your next three actions — each addable as a task in one click. It can also break big tasks into steps.

**Deep macOS integration** (via a small local helper, all optional):

- **SQLite persistence** — everything lives in `stride.db`, queryable with plain SQL and shared across browsers.
- **Calendar** — reads Calendar.app or any ICS URL, shows your schedule alongside tasks, and subtracts meeting time from your day's capacity.
- **Apple Reminders sync** — mirrors your plan to a "Stride" list that iCloud puts on your iPhone; check items off on the phone and Stride completes them.
- **Activity awareness** (opt-in) — notices what you work on and reminds you about things you left unfinished.

**Eight themes**, light and dark, including Paper (warm sepia), Midnight, Forest, and Ink (monochrome).

## Quick start

```bash
git clone https://github.com/YOUR-USERNAME/stride.git
cd stride
open index.html          # runs entirely in your browser, no build step
```

On macOS, double-click **Stride.app** instead — it opens Stride in its own dock-able window and starts the local helper that powers SQLite storage, Calendar, Reminders, and activity features. The helper needs Python 3 (`xcode-select --install` if you don't have it).

To use the AI features, open Settings → AI assistant and paste an API key. Keys are stored only in your browser and sent only to the provider you choose.

## Architecture

Three files, no dependencies, no build step:

- `index.html` — the entire app: UI, task engine, AI client, sync logic. Vanilla JS, ~3,000 lines.
- `stride-helper.py` — optional local connector on `127.0.0.1:8787` (Python 3 stdlib only): SQLite persistence, CORS proxy for AI providers that block browser calls, and AppleScript bridges to Calendar, Reminders, and System Events.
- `Stride.app` — a thin macOS launcher (shell script bundle) that starts the helper and opens the app in a chromeless browser window.

Data flow: the app saves to `localStorage` instantly (offline-first), then syncs to `stride.db` through the helper. On startup it adopts whichever copy is newer.

## Privacy

Everything stays on your machine. No accounts, no telemetry, no servers. The only data that ever leaves is the summary sent to *your chosen* AI provider when you use AI features — and those are off until you add a key. Activity tracking is off by default, records only app names and window titles, and keeps 14 days.

## Contributing

Issues and pull requests welcome. The codebase is deliberately simple — one HTML file, one Python file — so read through, keep changes small and dependency-free, and include a test where practical (see the jsdom test patterns in the repo history).

## License

[MIT](LICENSE) © 2026 Milan Niroula
