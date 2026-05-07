# TuriX-CUA Bundle Deployment Guide

This document captures how the **mac-intel** and **win-amd64** bundles are
built, deployed, and what gotchas to watch for. It complements the
top-level `README.md`, which is for the source-install path.

---

## 1. What ships in a bundle

```
TuriX-CUA-<platform>-bundle.tar.gz
└── TuriX-CUA-<platform>/
    ├── .turix_env/                 # extracted at first run, ~600 MB
    ├── turix_env-<platform>.tar.gz # the conda-pack tarball
    ├── src/                        # branch-specific (mac vs windows)
    ├── examples/
    │   ├── main.py
    │   └── config.example.json     # template — copy + edit, never commit real
    ├── skills/
    ├── weights/icon_detect/
    │   └── model.pt                # OmniParser v2 detector (YOLOv11m, 39 MB)
    ├── requirements.txt
    ├── setup-mac.sh   OR   setup-win.ps1
    └── README.txt                  # bundle-internal cheat sheet
```

`task` lives in `examples/config.json` — **always set by the operator per
the actual ask**. The template's `task` field is only a syntactic
placeholder; do not run with it as-is.

---

## 2. Branches & releases

| Branch | Platform | Latest tag | Notes |
|---|---|---|---|
| `main` | macOS Intel | `bundle-mac-intel-v0.3` | AX tree + OmniParser merge; actor sees annotated screenshot |
| `multi-agent-windows` | Windows x64 | `bundle-win-amd64-v0.1.1` | VLM-only; OmniParser draws numbered red boxes onto every screenshot |

Tag convention: `bundle-<platform>-vX.Y[.Z]`. Pushing a tag in this
shape triggers the matching CI workflow which builds the bundle and
publishes it to GitHub Releases. The artifact attached to the release
is the **permanent download URL** — share that, not Actions artifacts
(which expire after 30 days).

---

## 3. Quick install — Mac Intel (macOS 12+)

```bash
curl -L -o TuriX-CUA-mac-intel-bundle.tar.gz \
  https://github.com/<org>/TuriX-CUA/releases/download/bundle-mac-intel-v0.3/TuriX-CUA-mac-intel-bundle.tar.gz

tar xzf TuriX-CUA-mac-intel-bundle.tar.gz
cd TuriX-CUA-mac-intel
bash setup-mac.sh
```

`setup-mac.sh` will:
1. Verify Intel x86_64 and warn if macOS < 13.
2. Unpack `.turix_env/` and run `conda-unpack` (one-time, ~30 s).
3. Copy `examples/config.example.json` → `examples/config.json`.
4. If the placeholder API key is still present, open the file in TextEdit and exit. **Edit it, set your `task`, save, re-run setup.**
5. Open System Settings → Screen Recording + Accessibility panes.
6. Wait for `Enter`, then launch the agent.

Force-stop hotkey at runtime: **`Cmd+Shift+2`**.

---

## 4. Quick install — Windows 11 (x64)

```powershell
curl.exe -L -o TuriX-CUA-win-amd64-bundle.tar.gz `
  https://github.com/<org>/TuriX-CUA/releases/download/bundle-win-amd64-v0.1.1/TuriX-CUA-win-amd64-bundle.tar.gz

tar -xzf TuriX-CUA-win-amd64-bundle.tar.gz
cd TuriX-CUA-win-amd64
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\setup-win.ps1
```

Force-stop hotkey: **`Ctrl+Shift+2`**.

No conda required on the target machine; `setup-win.ps1` runs
`Scripts\conda-unpack.exe` to fix env paths post-extraction.

---

## 5. Configuring `task`

`examples/config.json` is **gitignored**. Always start from the template
and tailor the `task` to whatever you actually need to do this run:

```json
{
  "agent": {
    "task": "<your real instruction goes here, in any language>",
    "use_ui": true,
    "use_omniparser": true,
    "use_plan": false,
    "max_steps": 30,
    "max_actions_per_step": 3
  }
}
```

Practical rules learned the hard way:
- **Do not rely on Dock-icon clicks** — Qwen3-VL's coordinate accuracy
  on retina displays is unreliable for ~32 px Dock icons. Prefer
  `open_app` style instructions ("open WeChat") that route through
  `NSWorkspace.launchApplication_` in the controller.
- Keep `max_steps` modest (15–30) for iterative testing. Failures
  burn LLM tokens fast.
- `use_plan: true` adds a planner LLM call per step. Disable for
  short tasks; DashScope's `enable_thinking` route has been observed
  to return spurious `BalanceError` 500s under burst load.

---

## 6. macOS 12 (Monterey) — known incompatibilities

The bundle is built on `macos-15-intel` runners and the wheels it
captures link against macOS 13.3+ Accelerate symbols
(`_cblas_*$NEWLAPACK$ILP64`). On macOS 12 the loader will refuse:

```
Symbol not found: (_cblas_caxpy$NEWLAPACK$ILP64)
Expected in: /System/Library/Frameworks/Accelerate.framework
```

Two packages are affected: **numpy 2.x** and **opencv-python 4.11+**.

### One-time downgrade (target machine)

```bash
cd ~/Downloads/TuriX-CUA-mac-intel
./.turix_env/bin/python -m pip install --quiet --force-reinstall \
    "numpy>=1.24,<2"
./.turix_env/bin/python -m pip install --quiet --force-reinstall --no-deps \
    "opencv-python>=4.8,<4.11"
```

(The `bin/pip` shebang points at `/usr/bin/env python3.12`, which is
not on `PATH` on the target. Always invoke via `python -m pip`.)

After downgrade, all imports succeed:

| Package | Working version on macOS 12 |
|---|---|
| numpy | 1.26.4 |
| opencv-python | 4.10.0 |
| scipy | 1.17.1 (works as-is) |
| torch | 2.2.2 (works as-is) |
| ultralytics | 8.4.46 (works after cv2 fix) |

### Long-term fix in CI

Pin numpy and opencv-python in the Mac branch's `requirements.txt`:

```text
numpy>=1.24,<2
opencv-python>=4.8,<4.11
```

Then push a new tag (`bundle-mac-intel-v0.4`) and the bundle ships
ready-for-macOS-12 by default.

---

## 7. macOS permissions (TCC) — chain of pain

The agent calls `CGPreflightScreenCaptureAccess()` at startup. If this
returns False, `main.py` exits immediately with:

```
Please enable screen recording permission for this script in
System Settings ▸ Privacy & Security ▸ Screen Recording.
```

What macOS actually checks (Sonoma and later are stricter; macOS 12
is comparatively lenient):

1. **The terminal app the user is sitting in.** If they used iTerm2 to
   run `setup-mac.sh`, granting Terminal.app does *nothing* — verify
   by `ps -ef | grep -i term` to see what's actually open.
2. **The python binary** at `.turix_env/bin/python3.12`. Some macOS
   builds gate per-binary and require explicit grant (drag-drop the
   binary into the list since the file picker grays out non-`.app`).

### The remote-access pitfall

`ssh → osascript → Terminal.app → do script → bash → python` does
**not** inherit Screen Recording permission, even when Terminal.app
itself has it. macOS marks the responsible process as `sshd` and
strips TCC grants. There is no workaround except:

- Run from a **physically open** terminal session, or
- Grant permission to the `python3.12` binary itself (drag-drop into
  the Privacy list).

Practical playbook to unblock:
1. Identify the actual terminal app: `ps -ef | grep -iE "iTerm|Terminal|ghostty|warp"`.
2. Add **that** app to Screen Recording AND Accessibility, toggle ON.
3. **Cmd+Q** to fully quit the terminal (closing the window is not enough).
4. Reopen from Dock or Spotlight, re-run `bash setup-mac.sh`.

To verify before launching the full agent:

```bash
./.turix_env/bin/python -c '
import ctypes
CG = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
print("Screen Recording:", bool(CG.CGPreflightScreenCaptureAccess()))
from ApplicationServices import AXIsProcessTrusted
print("Accessibility   :", bool(AXIsProcessTrusted()))
'
```

Both must report `True`.

---

## 8. Validating that OmniParser is actually firing

The whole point of the bundle is that OmniParser v2 augments the AX
tree (Mac) or annotates the screenshot (Win) with vision-detected
clickable boxes. To confirm it's working in a live run:

**Mac:**
```bash
tail -f .turix_tmp/logging.log | grep -E "OmniParser merge|OmniParser detected"
```
Expect lines like:
```
OmniParser detected 61 boxes
OmniParser merge: 64 AX nodes, 61 boxes, added 60 (deduped 1)
```

If `added` is consistently 0, either AX coverage is already
exhaustive (rare — only rich AppKit apps), or `use_ui` is `false`
in the config (which skips the AX path entirely on Mac).

**Win:**
```bash
tail -f .turix_tmp\logging.log | findstr "OmniParser"
```
Expect:
```
OmniParser drew 75 numbered boxes on screenshot
```

Brain VLM then sees red-numbered boxes overlaid on the UI and clicks
by referring to those numbers/positions.

---

## 9. CI / rebuild flow

Workflows live in `.github/workflows/`:

- `build-mac-intel.yml` (on `main`, runs on `macos-15-intel`)
- `build-win-amd64.yml` (on `multi-agent-windows`, runs on `windows-latest`)

Both fire on:
- `workflow_dispatch` (manual button in the Actions tab)
- Tag push matching `bundle-<platform>-*`

Tag-push runs additionally create a GitHub Release and attach the
bundle tarball — that's what gives a permanent external URL.

Rebuild loop after a code change:

```bash
# (Mac branch example)
git switch main
# ... edit code, commit ...
git tag bundle-mac-intel-v0.4
git push origin main bundle-mac-intel-v0.4
# CI runs ~7-10 min; release auto-published when green.
```

To watch and gate on success from the CLI:

```bash
gh run list -R <org>/TuriX-CUA --workflow build-mac-intel.yml --limit 1
gh run watch <run-id> -R <org>/TuriX-CUA --exit-status
gh release view bundle-mac-intel-v0.4 -R <org>/TuriX-CUA
```

The `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: "true"` env on each workflow
silences the Node 20 deprecation banner without bumping every action
version. Remove it once upstream actions catch up.

---

## 10. Common runtime errors & responses

| Error | Cause | Fix |
|---|---|---|
| `Symbol not found: _cblas_*$NEWLAPACK$ILP64` | macOS < 13.3, numpy 2.x or opencv 4.11+ | Section 6 — downgrade numpy + opencv |
| `Please enable screen recording permission` | TCC chain broken | Section 7 — grant the right terminal/binary |
| `Action type not found` (or `type_text`) | Old bundle (pre-v0.2) without aliases | Use v0.2 or newer; aliases are registered |
| `BalanceError: There are no suitable services` | DashScope burst-rejection or model not enabled | Wait 30 s, retry; disable `use_plan` to halve LLM calls; verify model is enabled in Bailian console |
| `JSONDecodeError: Expecting value` | Qwen3-VL emitted non-JSON | Agent retries internally up to `max_failures`; persistent → set `supports_response_format: false` |
| Agent loops clicking Dock | Coordinate hallucination on small icons | Rephrase task to use `open_app` semantics ("open X") instead of "click the X icon" |

---

## 11. Security

- `examples/config.json` is in `.gitignore`. Always.
- Never paste an API key into chat or commits. Even after `git rm --cached` the value remains in history if it was once committed; rotate the key in that case.
- The CI workflow uses `permissions: contents: write` only because `softprops/action-gh-release` needs it. No other secrets are injected.
- macOS Accessibility + Screen Recording grants are TCC-bound to the path of the granting app/binary. Moving or replacing the bundle dir invalidates the grant; re-grant after any path change.
