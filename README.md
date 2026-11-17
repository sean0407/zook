# swarmr

Local macOS AI workspace. The interface follows the directly observed Grok Bot layout: Bot sidebar, conversation canvas, pill composer, details panel, and Bot creation dialog. The implementation is independent and uses no extracted Grok Bot code/assets.

## Build and open

Requires macOS on Apple Silicon, Xcode Command Line Tools (Swift), and `/usr/bin/python3` 3.9+. This version uses the tools already installed on the development Mac and has no npm/Python package dependencies.

```sh
bash scripts/build.sh
open build/swarmr.app
```

The build is locally ad-hoc signed. It is not a notarized public distribution. The app starts a Python server on an ephemeral loopback port, authenticates its nonpersistent WebKit view, and stops the server when the app quits.

## Features

- Create, edit, pin, categorize and switch Bots, with separate instructions and conversation history.
- Group chats of 2–6 Bots: message everyone, direct with `@Bot`, and let Bots hand work to each other with `@` (max 8 Bot replies per message, stoppable).
- Submit conversations to an installed Codex or Claude CLI, view failures and cancel jobs.
- Create/search/edit/delete knowledge notes. Shared and Bot-specific notes are included as bounded reference context in new conversations.
- Inspect local usage records, Skills and MCP configuration inventory. CLI detection does not establish login; MCP configuration does not establish a successful connection.
- Choose CLI/model defaults and export swarmr's own data. No API key is requested or copied.
- New Bot and settings forms automatically detect model choices for the selected provider. Codex uses the installed CLI's model-list service with a local-cache fallback. Claude lists aliases reported by its installed CLI and model IDs observed in local records. Cache/alias labels are not account entitlement checks. Refresh, default and custom model choices are supported.

Sending a message runs the selected CLI and transmits that conversation context and relevant notes using its existing login. Claude uses the user's personal CLI login: gateway endpoints, environment credentials and third-party provider selectors are removed only from that subprocess's copied environment. Shell profiles and the desktop app's cookies are not changed. Account limits and billing are determined by the provider. Chat subprocesses retain restricted tools; swarmr does not yet provide unrestricted autonomous desktop actions.

Voice input and external service connections are not implemented in this version. The UI explains their availability instead of claiming a working connection.

## Data and development

Own application data is stored in `~/Library/Application Support/swarmr/swarmr.json` using atomic replacement and private file permissions. Conversations and notes are plain local JSON, not encrypted at rest. CLI login remains managed by the original CLI. Usage reads are bounded and expose aggregates rather than prompt text. Dollar cost is omitted because no verified pricing table is bundled.

```sh
python3 -m unittest discover -s tests -p '*test.py' -v
```

- `native/Swarmr.swift`: native window, local service lifecycle, authentication cookie and export save panel.
- `backend/server.py`: authenticated API, persistence, CLI jobs and local inventory.
- `frontend/`: local HTML/CSS/JavaScript interface.
- `.scratch/swarmr/`: scope, acceptance criteria and verification checkpoint.

Automated AI execution tests use isolated fake CLI fixtures. Live tests successfully received Codex and personal Claude replies. In 0.2.1, the inherited company gateway settings were isolated from Claude's personal login path; the official CLI sign-in completed, and the installed native app displayed `Claude 連線成功` in response to a real request. All 16 backend tests passed. See `.scratch/swarmr/progress.md` for verification evidence and remaining product work.

For UI verification without changing the main app's data, `bash scripts/build.sh --preview` builds `build/swarmr-preview.app` with a separate bundle identifier and data directory. An already running app uses its loaded code; finish any unsaved form and reopen swarmr to apply an installed update.
