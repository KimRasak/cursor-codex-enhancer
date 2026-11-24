# Cursor Codex Enhancer

A lightweight, zero-dependency Python patcher that unlocks missing desktop-class session management features in the official **OpenAI Codex (`openai.chatgpt`)** extension for Cursor and VS Code.

## Features

1. **Collapsible & Dockable Session Sidebar (`Cmd/Ctrl + B`)**
   - Adds a sidebar toggle button `[| ]` to the top-left of the Codex panel (`Cmd/Ctrl + B` or `Cmd/Ctrl + Shift + S`).
   - Switch between **Docked mode (`常驻`)** (sits alongside your active conversation without covering content) and **Drawer mode (`浮层`)** (slide-over overlay for narrow panels).
2. **Resizable Sidebar Width**
   - Drag the right border of the session sidebar (`150px – 520px`) with real-time layout adjustment.
   - Double-click the right border to reset to the default width (`240px`).
3. **Session Pinning (`📌 Pin / Unpin`)**
   - Enables the backend `list-pinned-threads`, `set-thread-pinned`, and `set-pinned-threads-order` handlers in `out/extension.js` (persisted in `~/.codex/.codex-global-state.json` and `localStorage`).
   - Unlocks the native **Pin chat / Unpin chat** item in the conversation `...` overflow menu.
   - Adds one-click **📌 Pin / Unpin** buttons on session row hover and in the active conversation top bar, plus a collapsible **`📌 置顶会话`** section at the top of the session list.
4. **Drag-and-Drop Session Reordering**
   - Press and drag any session row up or down to reorder within **`📌 置顶会话`** or **`历史会话`**.
   - Drag a session between **`历史会话`** and **`📌 置顶会话`** to automatically pin or unpin it at the target position.
5. **Compact Recent History & IDE-Native Typography (`13px`)**
   - Shows a compact **`历史会话`** list (default `3` items with collapsible header and `展开更多` toggle) and `26px` compact row height.
   - Normalizes the oversized `1rem (16px)` extension font down to standard IDE **`13px` UI / `12px` Code**, and adds an **`A- | 13 | A+`** font-size controller (`Cmd/Ctrl + -`, `Cmd/Ctrl + =`, `Cmd/Ctrl + 0`) to the top bar.

## Quick Start

### Apply Patch

```bash
python3 patch.py
```

Or run directly from GitHub once pushed:

```bash
curl -fsSL https://raw.githubusercontent.com/KimRasak/cursor-codex-enhancer/main/patch.py | python3
```

Then in Cursor / VS Code, press `Cmd/Ctrl + Shift + P` and run:

```text
Developer: Reload Window
```

### Check Status / Revert

```bash
# Check patch status
python3 patch.py --status

# Revert all files to original backups
python3 patch.py --revert
```

## License

MIT
