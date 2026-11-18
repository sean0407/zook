# Zook

**English** | [繁體中文](README.zh-TW.md)

A local macOS workspace for the AI command-line tools you already have. Zook runs Codex, Claude, Grok, Gemini or a CLI of your own behind one interface, using each tool's existing login. An iPhone companion app reaches the Mac through an end-to-end encrypted relay.

The layout is inspired by Grok Bot. The implementation is independent and uses none of its code or artwork.

## Features

- **Bots**: create, edit, pin and categorize Bots, each with its own instructions, model, look and conversation history.
- **Group chats**: 2–6 Bots in one conversation. Message everyone, direct a message with `@Bot`, and let Bots hand work to each other.
- **Any CLI**: Codex, Claude, Grok and Gemini are built in, and you can add a custom CLI.
- **Several accounts per model**: add more sign-ins or API keys for the same CLI and choose one for each Bot. Each sign-in stays in its own folder managed by the CLI; API keys are kept in the macOS Keychain.
- **Access scope per Bot**: the whole Mac (default), one folder, or only Zook's workspace.
- **Shared Skills, connectors and plugins**: configured once and available to every Bot. Connectors (MCP servers) can be added in Zook itself, as a local command or a web address, or picked up from your Codex and Claude settings.
- **Zook's own copies**: import Skills from Claude, Codex or a plugin into Zook (same-named ones are kept once), copy connectors over with their keys moved to the Keychain, and see which Skills mention a connector or tool Zook does not have. Export everything as one settings pack to set up another Mac; keys are never included.
- **Built-in Gmail**: search and read mail, save drafts and send, using a Google app password kept in the Keychain. Sending always asks for your approval.
- **Conversations**: each Bot can keep several conversations you can search. Answer again, edit a question or re-answer with another model; paste screenshots or drop files; choose fast, standard or deep thinking; or ask for a plan first and approve it before anything changes.
- **Schedules**: have a Bot or a group do something at a set time: once, hourly, daily, on weekdays, weekly or monthly. You can also just tell a Bot "every morning at 10…"; it proposes the schedule and creates it once you approve. A Mac notification tells you when a run finishes, fails or needs approval, and each schedule keeps its last 20 runs. Zook runs schedules while it is open and can catch up on a time it missed.
- **Usage**: provider quotas and token use per Bot.
- **Updates**: Zook checks this repository's releases and installs a new version with one click, after verifying its checksum and signature.
- **iPhone app**: read and send messages, approve requests, create Bots and check usage. Settings that change what a Bot may do stay on the Mac.

## Build and open

Requires macOS on Apple Silicon, Xcode Command Line Tools (Swift) and `/usr/bin/python3` 3.9 or later. There are no npm or Python package dependencies.

```sh
bash scripts/build.sh
open build/Zook.app
```

The build is ad-hoc signed and not notarized. The app starts a Python server on a loopback port, authenticates its own WebKit view, and stops the server when it quits.

## iPhone app

Open `ios/ZookMobile.xcodeproj` in Xcode, choose your own development team, and run it on your iPhone (iOS 17 or later). In Zook on the Mac, turn on remote access and scan the QR code with the phone.

The phone and the Mac talk through a relay that only forwards encrypted messages. To host your own, see [relay/README.md](relay/README.md).

## Data and privacy

- Zook's data is stored in `~/Library/Application Support/swarmr/swarmr.json` with private file permissions. It is plain local JSON, not encrypted at rest.
- Sending a message runs the selected CLI with that conversation's context. Account limits and billing are decided by the provider.
- The relay cannot read messages and stores no conversations.

## Development

```sh
python3 -m unittest discover -s tests -p '*test.py' -v
```

| Path | Contents |
|---|---|
| `native/` | macOS window, local service lifecycle, and the relay host |
| `backend/` | authenticated API, storage, CLI jobs, device permissions |
| `frontend/` | HTML, CSS and JavaScript interface |
| `ios/` | ZookMobile, the iPhone app |
| `relay/` | Cloudflare Worker that forwards encrypted messages |
| `tests/` | backend and protocol tests |

## License

Copyright © 2026 sean0407.

The source code is licensed under the [GNU General Public License v3.0](LICENSE). You may use, modify and redistribute it, and any version you distribute must be released under the same license with its source code.

The name "Zook", the app icon and the Bot avatar artwork are not covered by that license. All rights to them are reserved. A modified version must use a different name and icon.
