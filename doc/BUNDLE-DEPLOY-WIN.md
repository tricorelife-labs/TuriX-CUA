# TuriX-CUA Windows Bundle Deployment Guide

This branch (`multi-agent-windows`) ships a self-contained Windows
x64 bundle. The architecture differs from `main` (Mac):

- **No UI Automation tree** — agent is pure VLM-driven on raw screenshots.
- **OmniParser draws numbered red boxes onto every screenshot** before
  the brain VLM sees it; brain decides which box to click.
- Force-stop hotkey: **`Ctrl+Shift+2`** (different from Mac's `Cmd+Shift+2`).

For the Mac counterpart see `doc/BUNDLE-DEPLOY.md` on `main`.

---

## 1. What ships in the bundle

```
TuriX-CUA-win-amd64-bundle.tar.gz
└── TuriX-CUA-win-amd64/
    ├── .turix_env/                    # extracted at first run, ~600 MB
    ├── turix_env-win-amd64.tar.gz     # the conda-pack tarball
    ├── src/
    │   └── windows/
    │       ├── omni_parser.py         # cross-platform YOLO+caption wrapper
    │       └── ...
    ├── examples/
    │   ├── main.py
    │   └── config.example.json        # template — copy + edit, never commit real
    ├── skills/
    ├── weights/icon_detect/
    │   └── model.pt                   # OmniParser v2 detector (39 MB)
    ├── requirements.txt
    ├── setup-win.ps1
    └── README.txt
```

`task` is in `examples/config.json` and is **always set by the operator
per the actual ask**. The template's `task` is a placeholder; do not
run with it as-is.

---

## 2. Quick install

PowerShell (any user, no admin needed for the install itself):

```powershell
# Download
curl.exe -L -o TuriX-CUA-win-amd64-bundle.tar.gz `
  https://github.com/<org>/TuriX-CUA/releases/download/bundle-win-amd64-v0.1.1/TuriX-CUA-win-amd64-bundle.tar.gz

# Extract (Windows 10+ has tar built-in)
tar -xzf TuriX-CUA-win-amd64-bundle.tar.gz
cd TuriX-CUA-win-amd64

# First-run setup (one-time policy bypass for the script)
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\setup-win.ps1
```

`setup-win.ps1` will:
1. Verify AMD64 architecture.
2. Unpack `.turix_env\` (one-time, ~30 s). No conda required.
3. Run `Scripts\conda-unpack.exe` to fix env paths.
4. Copy `examples\config.example.json` → `examples\config.json`.
5. If the placeholder API key is still present, open the file in
   `notepad` and exit. **Edit it, set your `task`, save, re-run.**
6. Launch the agent with the env's `python.exe`.

To stop a running agent: **`Ctrl+Shift+2`** (registered as a global
hotkey at startup).

---

## 3. Configuring `task`

`examples\config.json` is **gitignored**. Always start from the template
and tailor `task` to whatever you actually need this run:

```json
{
  "agent": {
    "task": "<your real instruction goes here, in any language>",
    "use_omniparser": true,
    "use_plan": false,
    "max_steps": 30,
    "max_actions_per_step": 3,
    "force_stop_hotkey": "ctrl+shift+2"
  }
}
```

Practical rules:
- **OmniParser is THE ground truth on Windows.** With no UIA tree, the
  brain only sees what OmniParser annotates. Setting
  `use_omniparser: false` will make the agent click random
  hallucinated coordinates.
- Keep `max_steps` modest (15–30) for iterative testing.
- `use_plan: true` adds a planner LLM call per step. DashScope's
  `enable_thinking` route has been observed to return spurious
  `BalanceError` 500s under burst load; disable for short tasks.

---

## 4. Windows-specific gotchas

### 4.1 ExecutionPolicy

Default Windows refuses unsigned `.ps1`. The setup script needs:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

This is per-process — it only affects the current PowerShell session
and does not change machine policy. Alternative without changing
policy: `powershell.exe -ExecutionPolicy Bypass -File .\setup-win.ps1`.

### 4.2 Antivirus / Defender

Windows Defender's real-time scan can:
- Slow `tar -xzf` extraction by 2–3× (it scans every file).
- Quarantine `python.exe` if signature looks suspicious to heuristics.

Mitigation: add the bundle directory to Defender exclusions
(`Settings → Virus & threat protection → Manage settings →
Exclusions`). Not required, but speeds up first run.

### 4.3 pywin32 post-install

`pywin32` ships some COM registrations done at install time. The
conda-packed env should already have them, but if the bundle was
extracted to a path where Windows can't find pywin32's DLLs, run:

```powershell
.\.turix_env\python.exe .\.turix_env\Scripts\pywin32_postinstall.py -install
```

(Only needed if you see `ImportError: DLL load failed while importing
win32api`.)

### 4.4 High-DPI scaling

Windows' fractional scaling (125%, 150%) can put pyautogui
coordinates at half/different pixel positions than where you'd expect
visually. OmniParser's bounding boxes are in screenshot pixel space,
so this stays consistent. But if the agent clicks ~10 px off, check
`Display Settings → Scale and layout`.

### 4.5 No `.app` security gate

Unlike macOS TCC, Windows does **not** require per-app permission
grants for Screen Recording or input synthesis. Once setup-win.ps1
launches python, it has full access. (UAC prompts may appear if a
target task itself needs admin — unrelated to TuriX.)

---

## 5. Validating that OmniParser is firing

```powershell
Get-Content .\.turix_tmp\logging.log -Wait | Select-String OmniParser
```

Expected pattern every step:

```
OmniParser drew 75 numbered boxes on screenshot
```

If you instead see:

```
OmniParser annotation failed; using raw screenshot
```

→ check `weights/icon_detect/model.pt` exists, and `use_omniparser: true`.

The brain VLM gets the screenshot **with red numbered boxes overlaid**
on every clickable region. It picks a box and emits click coordinates
that the agent translates via the `omni_index_to_center` map.

---

## 6. Common runtime errors

| Error | Cause | Fix |
|---|---|---|
| `Set-ExecutionPolicy ... cannot be loaded` | Default PowerShell policy | Run with `-Scope Process -ExecutionPolicy Bypass`, or use `powershell -ExecutionPolicy Bypass -File ...` |
| `ImportError: DLL load failed while importing win32api` | pywin32 post-install missing | Section 4.3 |
| `tar: not a recognized command` | Pre–Windows 10 1803 | Use 7-Zip or Windows Terminal/WSL `tar` |
| `Action type not found` (or `type_text`) | Old bundle (pre-v0.1) without aliases | Use v0.1.1 or newer; aliases are registered |
| `BalanceError: There are no suitable services` | DashScope burst-rejection | Wait 30 s; disable `use_plan`; verify model is enabled in Bailian console |
| `JSONDecodeError: Expecting value` | Qwen3-VL emitted non-JSON | Internal retry handles it; persistent → set `supports_response_format: false` |
| Agent clicks miss UI | High-DPI scaling, OmniParser conf too low | Section 4.4; raise `omniparser_conf` to `0.30`+ |

---

## 7. CI / rebuild flow

Workflow: `.github/workflows/build-win-amd64.yml` (runs on
`windows-latest`). Triggers:

- `workflow_dispatch` (manual button in Actions tab)
- Tag push matching `bundle-win-amd64-*`

Tag-push runs additionally create a GitHub Release and attach the
bundle tarball — that's what gives a permanent external URL.

Rebuild loop after a code change:

```bash
git switch multi-agent-windows
# ... edit code, commit ...
git tag bundle-win-amd64-v0.2
git push origin multi-agent-windows bundle-win-amd64-v0.2
# CI runs ~8-10 min on windows-latest; release auto-published when green.
```

CLI watch:

```bash
gh run list -R <org>/TuriX-CUA --workflow build-win-amd64.yml --limit 1
gh run watch <run-id> -R <org>/TuriX-CUA --exit-status
gh release view bundle-win-amd64-v0.2 -R <org>/TuriX-CUA
```

The `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: "true"` env on the workflow
silences the Node 20 deprecation banner without bumping every action
version. Remove it once upstream actions catch up.

---

## 8. Why the architecture differs from Mac

The Mac branch (`main`) has macOS Accessibility (AX) APIs — a
structured tree of every UI element. The Windows branch was built
without UIA integration; the agent reasons over raw pixels.

Practical implications:
- **Mac**: AX tree is the spine. OmniParser fills gaps where AX is
  weak (e.g. WeChat's custom-drawn UI). Brain sees a numbered
  screenshot and a textual element list.
- **Windows**: OmniParser **is** the only structured signal. Brain
  sees only the numbered screenshot — no textual tree.

If a task on Windows misbehaves and you suspect missed elements, dump
the latest annotated screenshot from `.turix_tmp\images\` and
visually verify the boxes correspond to real interactive controls.
You can tune `omniparser_conf` (lower → more boxes, more noise;
higher → fewer boxes, fewer false positives).

---

## 9. Security

- `examples\config.json` is in `.gitignore`. Always.
- Never paste an API key into chat or commits. After committing a key,
  even `git rm --cached` doesn't remove it from history; rotate the key.
- No TCC equivalent on Windows — the bundle has full input/screen
  access as soon as launched. Run only on a machine you control.
- The CI workflow uses `permissions: contents: write` only because
  `softprops/action-gh-release` needs it. No other secrets injected.
