# TuriX-CUA — Session Notes (May 2026)

Wrap-up notes for the bundle / OmniParser / Qwen integration work shipped in
early May 2026. Scope spans both `main` (macOS Intel) and
`multi-agent-windows` (Windows x64) on `tricorelife-labs/TuriX-CUA`.

---

## Releases shipped

All releases are conda-pack tarballs uploaded to GitHub Releases on
`tricorelife-labs/TuriX-CUA`. Mac builds are produced by
`build-mac-intel.yml` on `macos-15-intel`; Windows builds by
`build-win-amd64.yml` on `windows-latest`.

| Tag | Date (UTC) | What it fixes / adds |
|---|---|---|
| `bundle-mac-intel-v0.1`   | 2026-05-04 | First mac-intel bundle (conda-pack tarball; Python 3.11 + torch CPU + ultralytics + opencv). |
| `bundle-mac-intel-v0.1.1` | 2026-05-04 | CI: `contents:write` for release upload; drop deprecated conda flag. |
| `bundle-mac-intel-v0.2`   | 2026-05-05 | OmniParser end-to-end fixes for WeChat-style apps (see Bugs fixed). |
| `bundle-mac-intel-v0.3`   | 2026-05-05 | CI on Node 24 (`FORCE_JAVASCRIPT_ACTIONS_TO_NODE24`); actor sees the OmniParser-annotated screenshot. |
| `bundle-mac-intel-v0.4`   | 2026-05-07 | Pin `numpy<2` and `opencv-python<4.11` so the bundle imports on macOS 12 (LP64 BLAS issue). |
| `bundle-mac-intel-v0.5`   | 2026-05-07 | `build_tree` crash when AX returns `None` for the main window — guards the post-window block. **Latest mac bundle.** |
| `bundle-win-amd64-v0.1`   | 2026-05-04 | First Windows x64 bundle (OmniParser v2 + Qwen + CI). |
| `bundle-win-amd64-v0.1.1` | 2026-05-05 | Force JS actions onto Node 24 (deprecation cleanup); doc additions. |

CI status at wrap-up: `bundle-mac-intel-v0.5` build succeeded
(`build-mac-intel-bundle`, run id `25474099780`, 10m22s). Release published
2026-05-07 03:27 UTC; asset `TuriX-CUA-mac-intel-bundle.tar.gz`
(~696 MB, sha256 `c2d42add5082c5b05f08116845c0948388d9b33a3bc416676c01c311cd010fa8`).

---

## Bugs fixed (upstream TuriX issues)

Each item is a code-level fix with the symptom, root cause, and the commit
that landed it. All are on `tricore/main` unless noted.

- **`open_app` returned `pid=None`, so the AX subtree was never built.**
  Spotlight launches (`do script "open -a 'TextEdit'"`) hand back no PID, so
  the controller had nothing to scope to. Fixed by adding a fuzzy PID
  resolver (`fuzzy_find_pid`) that walks the running-app list with name
  normalization. Landed in `b5ea092` (`fix omniparser end-to-end on
  wechat-style apps`).

- **`last_pid` was reset between failed steps, so `build_tree` only fired
  once per session.** When a step errored, the controller cleared the cached
  PID, and the next step lost the AX context entirely. Fixed by making
  `last_pid` update monotonically and adding an `NSWorkspace.frontmostApplication`
  fallback. Same commit: `b5ea092`.

- **OmniParser merge silently no-op'd because two tree builders existed.**
  `_merge_omni_elements` ran on the Controller's tree builder, but the agent
  used its own private builder, so vision-only boxes never reached the AX
  tree the brain consumed. Fixed by propagating the same builder handle into
  the agent. Landed in `b5ea092`.

- **`screenshot_annotated` was the raw screenshot, never annotated.**
  The actor was seeing un-numbered pixels and hallucinating element IDs.
  Fixed by calling `annotate_screenshot(root)` after `build_tree` and
  routing the annotated PNG to the actor's prompt path. Landed in `cd4d9b6`
  (`ci: node24 + actor sees omniparser-annotated screenshot`).

- **`build_tree` crashed on `window_node.attributes` when `_process_element`
  returned `None`.** AX returned no main window for some Cocoa apps (e.g.
  Finder cold start), and the post-window block dereferenced the `None`
  result. Fixed by guarding the post-window block with an explicit
  `if window_node is None: continue`. Landed in `1b28f49`
  (`fix tree: build_tree crash when AX returns None main window`) — this is
  the v0.5 fix.

- **`numpy 2.x` and `opencv-python>=4.11` link macOS 13.3+ NEWLAPACK ILP64
  symbols (`__isoc23_strtoll`, `dgesv_64_`) that don't exist on macOS 12.**
  Bundle imports failed at `import numpy` on the user's Intel Mac. Fixed by
  pinning `numpy<2` and `opencv-python<4.11` in the build env. Landed in
  `2a423b9` (`deps: pin numpy<2 + opencv<4.11 for macOS 12 (LP64 BLAS)`) —
  this is the v0.4 fix.

---

## Architecture notes

**macOS pipeline (Mac Intel bundle).** Hybrid: Accessibility-API tree
collection + OmniParser vision merge.

1. `open_app` resolves the PID (Spotlight or `NSWorkspace`).
2. `build_tree(pid)` walks the AX subtree to extract semantic elements.
3. `OmniParser v2` runs YOLOv8 on the screenshot to find clickable regions.
4. `_merge_omni_elements` injects vision-only boxes (those with no AX
   counterpart) into the same tree.
5. `annotate_screenshot(root)` draws numbered overlays for every node.
6. The actor LLM sees the annotated PNG plus the merged tree.

**Windows pipeline (Win x64 bundle).** Pure-VLM. No UIA tree builder is in
use; the actor relies on OmniParser drawing numbered boxes onto each
screenshot, and the brain reasons over the resulting image directly. This
is by design for the multi-agent-windows branch and reduces the Windows
agent's surface area to the VLM + OmniParser only.

**Controller actions added.** `type` and `type_text` are registered as
aliases for `input_text`, because Qwen3-VL emits all three names
non-deterministically and rejecting any of them caused step retries.

---

## CI infrastructure

- `.github/workflows/build-mac-intel.yml` — runs on `macos-15-intel`,
  builds a conda env (Python 3.11 + torch CPU + ultralytics + opencv, with
  the v0.4 pins), runs `conda-pack`, uploads the tarball as a release
  asset.
- `.github/workflows/build-win-amd64.yml` — runs on `windows-latest`, same
  shape, Windows-specific deps.
- Both workflows set `permissions: contents: write` for the release upload
  step and set `env: FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: "true"` so the
  GitHub-provided JS actions (checkout, upload-artifact, softprops/action-gh-release)
  don't trip the Node 16/20 deprecation.
- Release artifact for both platforms is a conda-pack tarball; consumer
  unpacks, runs `conda-unpack`, and points TuriX-CUA at the env's Python.

---

## Verified on user's Intel Mac (macOS 12.7.6)

End-to-end verification was run against `bundle-mac-intel-v0.5` on a real
Intel MacBook running macOS 12.7.6.

- **Imports clean.** After `tar xzf` + `conda-unpack`,
  `import torch`, `ultralytics`, `cv2`, and `numpy` all import without
  symbol errors. (This was the v0.4 fix — pre-v0.4 it crashed at
  `import numpy`.)
- **TCC permission chain works only via iTerm.app.** The user runs from
  iTerm, not Terminal.app. The Accessibility / Screen Recording grants
  must be on `iTerm.app`; granting Terminal.app does nothing for an iTerm
  session.
- **SSH-launched processes do NOT inherit TCC permissions.** Launching the
  agent over `ssh user@mac` and then having it run `osascript ... do script`
  to spawn Spotlight breaks the TCC chain — the responsible process becomes
  `sshd`, which has no Accessibility grant. Must launch from a local iTerm
  window.
- **End-to-end run succeeded.** Spotlight → TextEdit → type → done. 4 steps
  executed, 0 failed.
- **OmniParser merge contributed dominantly on WeChat.** On the real WeChat
  UI, the merge added 65 of 70 boxes (92.8% vision-only). This confirms
  empirically that the AX tree is nearly empty for WeChat (Cocoa wrapper
  around a custom renderer), and that without OmniParser the agent would
  have effectively no targets to click.
- **`Eval: Success` is the brain's self-judgment, not ground truth.** The
  brain occasionally emits `Eval: Success` while the screen state shows the
  task is not actually done — covered separately in the
  `feedback_agent_eval_hallucination.md` memory. Any harness that wraps
  TuriX-CUA must side-channel verify (screenshot diff, target-window
  presence check, etc.) rather than trusting the brain's own eval.

---

## Known open issues

- **Qwen3-VL hallucinates step success.** Most often on lock-screen / login
  dialogs where the screen content barely changes between turns, the brain
  emits `Eval: Success` despite no progress. Tracked in
  `feedback_agent_eval_hallucination.md`.
- **Brain occasionally picks suboptimal action paths.** Common case: the
  target app is already running and frontmost, but the brain plans a Dock
  click anyway. Symptom is wasted steps, not a hard failure.
- **DashScope `BalanceError` 500 under burst load with
  `enable_thinking=true`.** Not deterministic — happens when concurrent
  thinking-mode calls stack up against the account's QPS. Mitigation is
  retries with backoff; not yet wired into the provider layer.
- **Brain LLM call sometimes hangs >8 min (transient).** Observed once on
  the Intel Mac run; the call returned eventually with a normal response,
  so likely a DashScope tail-latency event rather than a client bug.

---

## Pointers

- macOS bundle deploy + TCC + CI rebuild guide: `doc/BUNDLE-DEPLOY.md`
  (this branch, `main`).
- Windows bundle deploy + arch notes + common errors:
  `doc/BUNDLE-DEPLOY-WIN.md` (on the `multi-agent-windows` branch).
- Latest macOS release:
  https://github.com/tricorelife-labs/TuriX-CUA/releases/tag/bundle-mac-intel-v0.5
- Latest Windows release:
  https://github.com/tricorelife-labs/TuriX-CUA/releases/tag/bundle-win-amd64-v0.1.1
