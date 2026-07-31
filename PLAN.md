# Rewrite `patch_chatgpt_providers.py` per advisor review

## Context

The advisor reviewed `patch_chatgpt_providers.py` (a macOS installer that injects a custom
model-provider picker + per-model provider routing into the desktop Codex client's minified
JS bundles, with exact-hunk matching, ASAR integrity checks, full-app backup, ad-hoc
codesigning, and rollback) and returned 6 findings plus a test recommendation. A second
advisor pass refined the fixes further. This plan addresses all of them while keeping the
version-sensitive exact-hunk design and every embedded `CENTRAL_DIFF*` / `PICKER_DIFF*`
hunk byte-identical.

Findings to fix (merged):
1. `sudo` creates a root-owned `0600` config the user cannot edit.
2. Restore is not robust — a partial `ditto` can leave a non-empty destination.
3. Marker-only "already installed" can accept half-applied/corrupt bundles.
4. Config validation has type-safety gaps (`true` as version, unhashable → `TypeError`).
5. Processes are shut down before validation and before already-installed detection.
6. Config mutation happens before bundle compatibility is established.

Advisor refinements folded in:
- Ownership must not be mutated during early validation; config is committed only after the
  app is patched, codesigned, and verified.
- Config state is modeled as `keep / create / replace`; only `keep` validates the existing
  file, so `--overwrite-config` repairs malformed JSON instead of rejecting it.
- Recovery never silently swallows failure; diagnostics name `backup`, `failed_copy`, and
  `staging`, and the live app path is never silently left absent.
- READY verification rejects mixed markers (V3 present + V2 absent + hash matches plist +
  picker symbol + valid signature).
- Target executable is derived from `CFBundleExecutable`, not hardcoded.
- Tests move from "diffs parse" to synthetic old-source fixtures that prove unique variant
  matching, repeat-application failure, READY state rejection, and restore diagnostics.

## Target app (finding 7)

- The supported default stays `/Applications/ChatGPT.app` — the desktop Codex client whose
  bundles contain the exact hunks below. We do **not** claim `/Applications/Codex.app`
  support; if a Codex.app bundle is supplied via `--app`, it patches only if the JS markers
  match, and otherwise fails cleanly (existing behavior).
- `stop_target_app_processes()` will read `CFBundleExecutable` from `Contents/Info.plist`
  and target `Contents/MacOS/<CFBundleExecutable>` instead of the hardcoded `ChatGPT`.
- `--app` help text and the module docstring clarify this wording.

## Approach

### Config lifecycle: `keep / create / replace` (findings 4, 6; refinements 1–3)

- `check_provider_config(path, overwrite)` — **read-only**, runs early, returns one of:
  - `"replace"` if `overwrite` is set (existing file is *not* read or validated — this is the
    repair path, so malformed JSON must not block `--overwrite-config`);
  - `"create"` if missing or zero-byte;
  - `"keep"` if present, parses, and validates (validation = strict JS-aligned rules below).
  - Raises `PatchError` only in the `keep` case (present + invalid + no overwrite).
- `validate_provider_config(data)` — strict and JS-aligned (mirrors
  `codexNormalizeProviderRoutingConfig`):
  - `version` must be the **integer** `1`; `True`/`1.0`/`"1"`/`None` all rejected.
  - `default_provider` and every mapping value must be strings (checked with `isinstance`
    before any set membership → no unhashable `TypeError`).
  - Mapping values are checked with the **untrimmed** value (JS parity: `"openrouter "` must
    not silently match).
- `write_provider_config(path)` — the only config write; called strictly after app
  verification (see flow). Writes the built-in template via `atomic_write_json`.
- Early status message announces the planned action ("validated; will be left untouched" /
  "will be created after the app is patched and verified" / "will be replaced…"); the
  commit happens at the end, so a failed patch never changes the user's configuration.

### Ownership policy (findings 1; refinement 4)

One helper `resolve_config_owner(path)` decides the owner for a file we are about to write:

- Not root → `None` (file is created by the current user).
- Root + path resolves under the invoking user's home (`invoking_user_home()`) → that user's
  `(uid, gid)`. This covers the default `~/.codex/desktop-model-providers.json`.
- Root + custom `--config` path **not** under the user home:
  - existing file → preserve its current owner (`stat` before replace);
  - missing → leave root (default).
- `atomic_write_json` applies the resolved owner to the temp file and to any *freshly
  created* parent directories; `chown`/directory-ownership failures raise `PatchError`
  (never swallowed). On the `keep` path the existing file's owner is preserved untouched.

### READY verification (findings 3; refinement 6)

`verify_installed_bundle(asar_path, info)` (pure, unit-testable) rejects READY unless all
hold, each mismatch a `PatchError` with recovery guidance:

- `asar_header_hash(asar_path) == asar_integrity_hash(info)` (plist)
- V3 patch marker present in the asar
- V2 legacy marker **absent** (mixed-marker state)
- `CodexCustomProviderPickerSection` symbol present in the asar bytes

`verify_installed_state(app, asar_path, info)` wraps the pure check and additionally runs
`/usr/bin/codesign --verify --deep --strict`; any subprocess failure (raised or nonzero exit)
is converted to `PatchError`. Both run on the READY path before
`print_completion_summary(..., already_installed=True)`.

### Robust restore (finding 2; refinement 5)

`restore_backup(app, backup)`:

1. `ditto backup → staging` (sibling dir); verify staging has `app.asar`; on any failure
   quarantine staging via `_remove_path()` and raise.
2. `os.replace(app, failed_copy)`; on failure remove staging and raise.
3. `os.replace(staging, app)`; on failure, try to move `failed_copy` back; **never swallow**
   a failed move-back — raise a `PatchError` naming `backup`, `failed_copy`, and `staging`
   and stating explicitly whether the app path was restored or may be absent.

### Deferred shutdown (finding 5)

`main()` no longer stops processes. `patch_app(app, config, backup_dir, overwrite_config,
allow_running)` calls `stop_target_app_processes(app, allow_running)` only after the patched
asar is packed and verified, immediately before `make_backup()` and live mutation.

### New patch_app flow (findings 5, 6; refinements 1–3)

1. Platform/bundle/npx checks; load plist; `version`/`build`.
2. `config_state = check_provider_config(config, overwrite_config)` (read-only) + status msg.
3. If V3 marker present → `verify_installed_state(...)`; if state is `create`/`replace`,
   commit config; print READY summary; return.
4. V2 marker detection (upgrade path), pre-patch header-hash verification (unchanged).
5. Extract → prettier → `apply_supported_patch_variant` → post-patch marker checks →
   prettier → pack → packed-asar marker checks → compute patched header hash → dump patched
   plist to temp.
6. `stop_target_app_processes(app, allow_running)`.
7. `make_backup(...)`.
8. Live mutation (atomic asar + plist replace, codesign `--deep --force --sign -`, verify,
   final hash/marker checks) inside the existing try/except with backup rollback.
9. After verification succeeds: if state is `create`/`replace`, `write_provider_config()`
   (ownership policy applied); else report kept. A config-commit failure here raises
   `PatchError` whose message states the app patch itself succeeded.
10. `print_completion_summary(...)`.

### Self-test mode (test recommendation; refinement 8)

New `--self-test` flag → `run_self_tests()`; never touches the app or network. Tests:

**Config validation (never `TypeError`, always `PatchError`):** valid default config; empty
`model_providers` accepted; version `True/False/1.0/"1"/None` rejected; empty/missing
providers rejected; unhashable `default_provider` (list/dict) rejected; duplicate/blank ids;
blank labels; unhashable mapping values (list) rejected; unknown and whitespace-padded
mapping values rejected (JS parity); `default_provider` trimmed like JS.

**Config lifecycle:** `check_provider_config` returns `replace` for `--overwrite-config`
even when the existing file is malformed JSON; returns `create` for missing/empty; `keep`
for valid; raises for invalid-without-overwrite; `write_provider_config` writes `0600`.

**Synthetic bundle fixtures (from hunk contexts):** `build_synthetic_source(diff)`
concatenates each hunk's `old_lines` in order. For every `PATCH_VARIANTS` entry, write
temp `central`/`picker` files from the variant's own synthetic sources and assert
`apply_supported_patch_variant` returns **exactly that variant's name** (unique match among
all five), then assert **repeat application fails** with `PatchError`. Covers fresh layouts
and both V2→V3 upgrade layouts.

**README state rejection (pure `verify_installed_bundle`):** build a minimal valid fake asar
(real asar header pickle layout via `struct`) with a computed header hash; assert pass for
{hash matches plist + V3 marker + no V2 + picker symbol}, and `PatchError` for each of:
hash mismatch, V3+V2 mixed markers, missing picker symbol. Also assert
`verify_installed_state` converts a failing `codesign` (monkeypatched `subprocess.run`
raising) into `PatchError`.

**Restore diagnostics:** end-to-end happy path with real `ditto` on temp dirs (app moved
aside, restored copy in place, `failed_copy` retained). Failure path: monkeypatch
`os.replace` to fail the staging→app swap; assert `PatchError` message names `backup`,
`failed_copy`, `staging`, that `failed_copy` is moved back (app path present), and staging
is quarantined; second case where the move-back also fails asserts the message says the app
path may be absent.

**Mechanics (unchanged functions):** `render_unified_diff` (apply, trailing-newline state,
ambiguous/absent context, anchor hunks), `parse_hunks` malformed input, `derive_versioned_diff`
count guards, `unique_candidate` exactly-one-match, `contains_marker` 4 MiB chunk-boundary
straddle, `app_path_variants` tmp/var normalization.

Runner prints PASS/FAIL per test and returns nonzero on any failure. The pass count is
reported from the actual run; the plan does not pre-claim a number.

## Files to modify

- `patch_chatgpt_providers.py` (only file). All embedded hunks and version-derivation
  constants stay byte-identical.

## Reuse

- `atomic_replace_file()` chown pattern → `resolve_config_owner`/`atomic_write_json`.
- `run()`, `contains_marker()`, `asar_header_hash()`, `asar_integrity_hash()`,
  `render_unified_diff`, `parse_hunks`, `derive_versioned_diff`, `unique_candidate`,
  `app_path_variants` — unchanged, exercised by `--self-test`.

## Steps

- [ ] Extend module docstring (target-app wording, `--self-test`); add `Callable` to typing
      imports.
- [ ] Add `invoking_user_ids()` + `resolve_config_owner(path)` ownership policy helpers.
- [ ] Rewrite `validate_provider_config` (strict, JS-aligned).
- [ ] Replace `ensure_provider_config` with `check_provider_config(path, overwrite)` +
      `write_provider_config(path)`; update `atomic_write_json` (owner + fresh-dir handling,
      chown failures → `PatchError`).
- [ ] Add `_remove_path`; rewrite `restore_backup` (staging restore + combined diagnostics).
- [ ] Add pure `verify_installed_bundle` + `verify_installed_state` (codesign → `PatchError`).
- [ ] Derive target executable from `CFBundleExecutable` in `stop_target_app_processes`.
- [ ] Restructure `patch_app` (new signature with `allow_running`; flow per above; config
      commit after verification; READY verification before summary).
- [ ] Update `main` (self-test dispatch, no pre-shutdown, pass `allow_running`); add
      `--self-test` argument; add `run_self_tests()` + `_expect_patch_error` +
      `build_synthetic_source` + fake-asar helper.
- [ ] Verify per below; fix any failing self-test before finishing.

## Verification

1. `python3 -m py_compile patch_chatgpt_providers.py` → clean.
2. `python3 patch_chatgpt_providers.py --self-test` → every test PASS, exit 0 (count
   reported by the run).
3. `python3 patch_chatgpt_providers.py --help` → renders, lists `--self-test`.
4. Manual flow review of `patch_app`: config writes and process shutdown occur only after
   layout confirmation; config commits after codesign + final checks; READY path verifies
   hash/markers/signature before reporting success.
