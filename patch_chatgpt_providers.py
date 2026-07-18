#!/usr/bin/env python3
"""Install the custom model-provider picker patch into ChatGPT.app on macOS.

The patch is intentionally version-sensitive: it only edits JavaScript bundles
whose expected source hunks match exactly. App updates that change those bundles
cause a clean failure before the installed app is modified.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import plistlib
import pwd
import re
import shlex
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import textwrap
import time
from typing import Any, NoReturn


PATCH_MARKER = b"__codexDesktopModelProvidersPatchV2"
ASAR_PACKAGE = "@electron/asar@3.2.10"
PRETTIER_PACKAGE = "prettier@3.6.2"

DEFAULT_PROVIDER_CONFIG: dict[str, Any] = {
    "version": 1,
    "default_provider": "openai",
    "providers": [
        {
            "id": "openai",
            "label": "ChatGPT / OpenAI",
            "description": (
                "Built-in provider; uses your signed-in ChatGPT account"
            ),
        },
        {
            "id": "openrouter",
            "label": "OpenRouter",
            "description": (
                "Custom provider; uses [model_providers.openrouter] from config.toml"
            ),
        },
    ],
    "model_providers": {
        "moonshotai/kimi-k3": "openrouter",
        "x-ai/grok-4.5": "openrouter",
        "anthropic/claude-fable-5": "openrouter",
    },
}


CENTRAL_DIFF = r"""@@ -4631,6 +4631,146 @@
   if (`data` in e) return e;
   let t = oe(e);
   return t == null ? e : { ...e, data: t };
+}
+function codexProviderRoutingFallback() {
+  return {
+    version: 1,
+    defaultProvider: `openai`,
+    providers: [
+      {
+        id: `openai`,
+        label: `ChatGPT / OpenAI`,
+        description: `Uses your signed-in ChatGPT account`,
+      },
+      {
+        id: `openrouter`,
+        label: `OpenRouter`,
+        description: `Uses the OpenRouter provider from config.toml`,
+      },
+    ],
+    modelProviders: {
+      "moonshotai/kimi-k3": `openrouter`,
+      "x-ai/grok-4.5": `openrouter`,
+      "anthropic/claude-fable-5": `openrouter`,
+    },
+  };
+}
+function codexNormalizeProviderRoutingConfig(e) {
+  if (e == null || typeof e !== `object` || Array.isArray(e))
+    throw Error(`Expected a JSON object`);
+  if (e.version !== 1) throw Error(`Unsupported version`);
+  if (!Array.isArray(e.providers) || e.providers.length === 0)
+    throw Error(`providers must be a non-empty array`);
+  let t = [],
+    n = new Set();
+  for (let r of e.providers) {
+    if (r == null || typeof r !== `object` || Array.isArray(r))
+      throw Error(`Every provider must be an object`);
+    let e = typeof r.id === `string` ? r.id.trim() : ``;
+    if (e.length === 0 || n.has(e))
+      throw Error(`Provider ids must be unique non-empty strings`);
+    n.add(e);
+    let i = typeof r.label === `string` ? r.label.trim() : ``;
+    t.push({
+      id: e,
+      label: i.length > 0 ? i : e,
+      description:
+        typeof r.description === `string` ? r.description.trim() : ``,
+    });
+  }
+  let r =
+    typeof e.default_provider === `string` ? e.default_provider.trim() : ``;
+  if (!n.has(r))
+    throw Error(`default_provider must reference a configured provider`);
+  let i = {};
+  if (
+    e.model_providers == null ||
+    typeof e.model_providers !== `object` ||
+    Array.isArray(e.model_providers)
+  )
+    throw Error(`model_providers must be an object`);
+  for (let [t, r] of Object.entries(e.model_providers)) {
+    let e = t.trim();
+    if (e.length === 0 || typeof r !== `string` || !n.has(r))
+      throw Error(`Every model mapping must reference a configured provider`);
+    i[e] = r;
+  }
+  return {
+    version: 1,
+    defaultProvider: r,
+    providers: t,
+    modelProviders: i,
+  };
+}
+function codexProviderRoutingState() {
+  return (window.__codexDesktopModelProvidersPatchV2 ??= {
+    config: codexProviderRoutingFallback(),
+    configPath: null,
+    error: null,
+    loaded: !1,
+    promise: null,
+  });
+}
+async function codexLoadProviderRoutingConfig(e = !1) {
+  let t = codexProviderRoutingState();
+  if (!e && t.loaded) return t.config;
+  if (t.promise != null) return t.promise;
+  return (
+    (t.promise = (async () => {
+      try {
+        let { codexHome: e } = await Xe(`codex-home`, {
+            params: { hostId: `local` },
+          }),
+          n = e.includes(`\\`) && !e.includes(`/`) ? `\\` : `/`,
+          r = `${e.replace(/[\\/]+$/u, ``)}${n}desktop-model-providers.json`,
+          { contents: i } = await Xe(`read-file`, {
+            params: { hostId: `local`, path: r },
+          }),
+          a = codexNormalizeProviderRoutingConfig(JSON.parse(i));
+        return (
+          (t.config = a),
+          (t.configPath = r),
+          (t.error = null),
+          (t.loaded = !0),
+          a
+        );
+      } catch (e) {
+        return (
+          (t.config = codexProviderRoutingFallback()),
+          (t.error = e instanceof Error ? e.message : String(e)),
+          (t.loaded = !0),
+          t.config
+        );
+      } finally {
+        t.promise = null;
+      }
+    })()),
+    t.promise
+  );
+}
+function codexCustomProviderChoice(e) {
+  try {
+    let t = window.localStorage.getItem(`codex.customProviderSelection.v1`);
+    return t === `auto` || e.providers.some((e) => e.id === t) ? t : `auto`;
+  } catch {
+    return `auto`;
+  }
+}
+async function codexProviderForThreadStart(e) {
+  let t = await codexLoadProviderRoutingConfig(!0),
+    n = codexCustomProviderChoice(t);
+  return n === `auto` ? (t.modelProviders[e?.model] ?? t.defaultProvider) : n;
+}
+async function codexPatchAppServerParams(e, t) {
+  if (e === `thread/list`) {
+    let e = t != null && typeof t === `object` ? t : {};
+    return e.modelProviders == null ? { ...e, modelProviders: [] } : e;
+  }
+  if (e === `thread/start` && t != null && typeof t === `object`)
+    return t.modelProvider == null
+      ? { ...t, modelProvider: await codexProviderForThreadStart(t) }
+      : t;
+  return t;
 }
 var jf,
   Mf,
@@ -4800,6 +4940,7 @@
             throw Error(
               `AppServerRequestClient is missing a message dispatcher`,
             );
+          t = await codexPatchAppServerParams(e, t);
           return e === `config/read`
             ? this.sendConfigReadRequest(t, n)
             : this.enqueueRequest(e, t, n);
@@ -4809,6 +4950,7 @@
             throw Error(
               `AppServerRequestClient is missing a message dispatcher`,
             );
+          e = await codexPatchAppServerParams(`thread/start`, e);
           return this.enqueueRequest(
             `thread/start`,
             e,
"""


PICKER_DIFF = r"""@@ -10162,6 +10162,204 @@
       };
 }
 var jO = e(() => {});
+function codexPickerProviderRoutingFallback() {
+  return {
+    version: 1,
+    defaultProvider: `openai`,
+    providers: [
+      {
+        id: `openai`,
+        label: `ChatGPT / OpenAI`,
+        description: `Uses your signed-in ChatGPT account`,
+      },
+      {
+        id: `openrouter`,
+        label: `OpenRouter`,
+        description: `Uses the OpenRouter provider from config.toml`,
+      },
+    ],
+    modelProviders: {
+      "moonshotai/kimi-k3": `openrouter`,
+      "x-ai/grok-4.5": `openrouter`,
+      "anthropic/claude-fable-5": `openrouter`,
+    },
+  };
+}
+function codexPickerNormalizeProviderRoutingConfig(e) {
+  if (e == null || typeof e !== `object` || Array.isArray(e))
+    throw Error(`Expected a JSON object`);
+  if (e.version !== 1) throw Error(`Unsupported version`);
+  if (!Array.isArray(e.providers) || e.providers.length === 0)
+    throw Error(`providers must be a non-empty array`);
+  let t = [],
+    n = new Set();
+  for (let r of e.providers) {
+    if (r == null || typeof r !== `object` || Array.isArray(r))
+      throw Error(`Every provider must be an object`);
+    let e = typeof r.id === `string` ? r.id.trim() : ``;
+    if (e.length === 0 || n.has(e))
+      throw Error(`Provider ids must be unique non-empty strings`);
+    n.add(e);
+    let i = typeof r.label === `string` ? r.label.trim() : ``;
+    t.push({
+      id: e,
+      label: i.length > 0 ? i : e,
+      description:
+        typeof r.description === `string` ? r.description.trim() : ``,
+    });
+  }
+  let r =
+    typeof e.default_provider === `string` ? e.default_provider.trim() : ``;
+  if (!n.has(r))
+    throw Error(`default_provider must reference a configured provider`);
+  let i = {};
+  if (
+    e.model_providers == null ||
+    typeof e.model_providers !== `object` ||
+    Array.isArray(e.model_providers)
+  )
+    throw Error(`model_providers must be an object`);
+  for (let [t, r] of Object.entries(e.model_providers)) {
+    let e = t.trim();
+    if (e.length === 0 || typeof r !== `string` || !n.has(r))
+      throw Error(`Every model mapping must reference a configured provider`);
+    i[e] = r;
+  }
+  return {
+    version: 1,
+    defaultProvider: r,
+    providers: t,
+    modelProviders: i,
+  };
+}
+function codexPickerProviderRoutingState() {
+  return (window.__codexDesktopModelProvidersPatchV2 ??= {
+    config: codexPickerProviderRoutingFallback(),
+    configPath: null,
+    error: null,
+    loaded: !1,
+    promise: null,
+  });
+}
+async function codexPickerLoadProviderRoutingConfig(e = !1) {
+  let t = codexPickerProviderRoutingState();
+  if (!e && t.loaded) return t.config;
+  if (t.promise != null) return t.promise;
+  return (
+    (t.promise = (async () => {
+      try {
+        let { codexHome: e } = await ye(`codex-home`, {
+            params: { hostId: `local` },
+          }),
+          n = e.includes(`\\`) && !e.includes(`/`) ? `\\` : `/`,
+          r = `${e.replace(/[\\/]+$/u, ``)}${n}desktop-model-providers.json`;
+        t.configPath = r;
+        let { contents: i } = await ye(`read-file`, {
+            params: { hostId: `local`, path: r },
+          }),
+          a = codexPickerNormalizeProviderRoutingConfig(JSON.parse(i));
+        return ((t.config = a), (t.error = null), (t.loaded = !0), a);
+      } catch (e) {
+        return (
+          (t.config = codexPickerProviderRoutingFallback()),
+          (t.error = e instanceof Error ? e.message : String(e)),
+          (t.loaded = !0),
+          t.config
+        );
+      } finally {
+        t.promise = null;
+      }
+    })()),
+    t.promise
+  );
+}
+function codexReadCustomProviderChoice(e) {
+  try {
+    let t = window.localStorage.getItem(`codex.customProviderSelection.v1`);
+    return t === `auto` || e.providers.some((e) => e.id === t) ? t : `auto`;
+  } catch {
+    return `auto`;
+  }
+}
+function codexWriteCustomProviderChoice(e) {
+  try {
+    window.localStorage.setItem(`codex.customProviderSelection.v1`, e);
+  } catch {}
+}
+function CodexCustomProviderPickerSection() {
+  let r = codexPickerProviderRoutingState(),
+    [e, t] = CodexProviderPatchReact.useState(r.config),
+    [n, i] = CodexProviderPatchReact.useState(r.error),
+    [a, o] = CodexProviderPatchReact.useState(() =>
+      codexReadCustomProviderChoice(r.config),
+    );
+  CodexProviderPatchReact.useEffect(() => {
+    let e = !0;
+    return (
+      codexPickerLoadProviderRoutingConfig(!0).then((n) => {
+        e &&
+          (t(n),
+          i(codexPickerProviderRoutingState().error),
+          o((e) =>
+            e === `auto` || n.providers.some((t) => t.id === e) ? e : `auto`,
+          ));
+      }),
+      () => {
+        e = !1;
+      }
+    );
+  }, []);
+  let s = (e) => (t) => {
+      (t?.preventDefault(), codexWriteCustomProviderChoice(e), o(e));
+    },
+    c =
+      e.providers.find((t) => t.id === e.defaultProvider)?.label ??
+      e.defaultProvider,
+    l = e.providers.map((e) =>
+      (0, FO.jsx)(
+        zy.Item,
+        {
+          RightIcon: a === e.id ? ct : void 0,
+          SubText:
+            e.description.length === 0
+              ? null
+              : (0, FO.jsx)(`span`, {
+                  className: `text-token-description-foreground`,
+                  children: e.description,
+                }),
+          onSelect: s(e.id),
+          children: e.label,
+        },
+        e.id,
+      ),
+    );
+  return (0, FO.jsxs)(FO.Fragment, {
+    children: [
+      (0, FO.jsx)(zy.Title, { children: `Provider for new tasks` }),
+      n == null
+        ? null
+        : (0, FO.jsx)(zy.Item, {
+            disabled: !0,
+            SubText: (0, FO.jsx)(`span`, {
+              className: `text-token-description-foreground`,
+              children: n,
+            }),
+            children: `Provider config error — using fallback`,
+          }),
+      (0, FO.jsx)(zy.Item, {
+        RightIcon: a === `auto` ? ct : void 0,
+        SubText: (0, FO.jsx)(`span`, {
+          className: `text-token-description-foreground`,
+          children: `Uses the mapped provider for each model; ${c} when unmapped`,
+        }),
+        onSelect: s(`auto`),
+        children: `Automatic`,
+      }),
+      l,
+      (0, FO.jsx)(zy.Separator, {}),
+    ],
+  });
+}
 function MO(e) {
   let t = (0, PO.c)(169),
     {
@@ -10312,6 +10510,7 @@
       ? (s = t[48])
       : ((s = (0, FO.jsxs)(FO.Fragment, {
           children: [
+            (0, FO.jsx)(CodexCustomProviderPickerSection, {}),
             a,
             (0, FO.jsx)(`div`, {
               className: `vertical-scroll-fade-mask flex max-h-[250px] flex-col overflow-y-auto`,
@@ -10984,8 +11183,10 @@
 }
 var PO,
   FO,
+  CodexProviderPatchReact,
   IO = e(() => {
     ((PO = w()),
+      (CodexProviderPatchReact = t(m(), 1)),
       T(),
       Q(),
       Pg(),
"""


class PatchError(RuntimeError):
    """A safe, expected patch failure."""


def colors_enabled(stream: Any = sys.stdout) -> bool:
    return "NO_COLOR" not in os.environ and (
        getattr(stream, "isatty", lambda: False)()
        or os.environ.get("FORCE_COLOR") not in (None, "", "0")
    )


def color(text: object, *codes: str, stream: Any = sys.stdout) -> str:
    rendered = str(text)
    if not colors_enabled(stream) or not codes:
        return rendered
    return f"\033[{';'.join(codes)}m{rendered}\033[0m"


def terminal_width() -> int:
    return max(64, min(shutil.get_terminal_size((96, 24)).columns, 110))


def terminal_status(
    label: str,
    message: object,
    code: str,
    *,
    detail: object | None = None,
    stream: Any = sys.stdout,
) -> None:
    badge_width = 10
    plain_badge = f"[{label}]"
    badge = color(plain_badge, "1", code, stream=stream)
    badge_padding = " " * max(1, badge_width - len(plain_badge))
    available = max(30, terminal_width() - badge_width)
    lines = textwrap.wrap(
        str(message),
        width=available,
        break_long_words=False,
        break_on_hyphens=False,
    ) or [""]
    print(f"{badge}{badge_padding}{lines[0]}", file=stream)
    for line in lines[1:]:
        print(f"{'':{badge_width}}{line}", file=stream)
    if detail is not None:
        detail_lines = textwrap.wrap(
            str(detail),
            width=max(30, terminal_width() - badge_width - 2),
            break_long_words=False,
            break_on_hyphens=False,
        ) or [""]
        for index, line in enumerate(detail_lines):
            marker = "↳ " if index == 0 else "  "
            print(
                f"{'':{badge_width}}{color(marker + line, '2', stream=stream)}",
                file=stream,
            )
    stream.flush()


def terminal_heading(title: str, code: str = "36") -> None:
    visible_title = f" {title.upper()} "
    rule_length = max(2, terminal_width() - len(visible_title))
    print()
    print(
        color(f"{visible_title}{'━' * rule_length}", "1", code),
    )
    sys.stdout.flush()


def terminal_panel(
    title: str,
    message: object,
    code: str,
    *,
    stream: Any = sys.stderr,
) -> None:
    width = terminal_width()
    title_text = f" {title.upper()} "
    top = f"╭─{title_text}{'─' * max(1, width - len(title_text) - 2)}"
    bottom = f"╰{'─' * (width - 1)}"
    print(file=stream)
    print(color(top, "1", code, stream=stream), file=stream)
    paragraphs = str(message).splitlines() or [""]
    for paragraph in paragraphs:
        wrapped = textwrap.wrap(
            paragraph,
            width=max(30, width - 4),
            break_long_words=False,
            break_on_hyphens=False,
        ) or [""]
        for line in wrapped:
            border = color("│", code, stream=stream)
            print(f"{border} {color(line, '1', stream=stream)}", file=stream)
    print(color(bottom, "1", code, stream=stream), file=stream)
    print(file=stream)
    stream.flush()


def terminal_bullet(label: str, description: str) -> None:
    bullet = color("◆", "1", "36")
    key = color(label, "1", "33")
    prefix_width = 29
    prefix = f"  {bullet} {key}"
    padding = " " * max(1, prefix_width - 4 - len(label))
    available = max(30, terminal_width() - prefix_width)
    lines = textwrap.wrap(
        description,
        width=available,
        break_long_words=False,
        break_on_hyphens=False,
    ) or [""]
    print(f"{prefix}{padding}{lines[0]}")
    for line in lines[1:]:
        print(f"{'':{prefix_width}}{line}")
    sys.stdout.flush()


def print_completion_summary(
    config: Path,
    *,
    backup: Path | None = None,
    already_installed: bool = False,
) -> None:
    codex_config = config.parent / "config.toml"
    if already_installed:
        terminal_status(
            "READY",
            "Patch already installed; no app files were changed.",
            "32",
        )
    else:
        terminal_status("SUCCESS", "Patch installed successfully.", "32")

    terminal_heading("Custom provider config")
    terminal_status("CONFIG", "Edit this file to customize provider routing:", "36", detail=config)
    terminal_bullet("providers", "Providers displayed in the app menu.")
    terminal_bullet(
        "model_providers",
        "Maps each exact model slug to the provider used by Automatic mode.",
    )
    terminal_bullet(
        "default_provider",
        "Provider used by Automatic mode when a model has no explicit mapping.",
    )
    terminal_status(
        "LINK",
        "Custom provider IDs must match a [model_providers.<id>] section.",
        "35",
        detail=codex_config,
    )
    terminal_status(
        "KEYS",
        "Do not put API keys in the provider-routing JSON file.",
        "33",
        detail="Keep credentials in the provider authentication configuration or environment.",
    )

    terminal_heading("After editing", "35")
    terminal_status(
        "RELOAD",
        "Save valid JSON, then close and reopen the model/provider menu.",
        "35",
        detail="No repatching or app restart is needed.",
    )

    if backup is not None:
        terminal_heading("Recovery", "34")
        terminal_status("BACKUP", "Complete original app backup:", "34", detail=backup)

    terminal_heading("Important", "33")
    terminal_status(
        "NOTICE",
        "The app now has an ad-hoc signature. A ChatGPT update may replace this patch.",
        "33",
    )
    print()


def fail(message: str, exit_code: int = 1) -> NoReturn:
    terminal_panel("Error", message, "31", stream=sys.stderr)
    raise SystemExit(exit_code)


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
    label: str | None = None,
) -> subprocess.CompletedProcess[str]:
    terminal_status(
        "STEP",
        label or f"Running {Path(command[0]).name}",
        "36",
        detail=shlex.join(command),
    )
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError as exc:
        output = exc.stdout.strip() if exc.stdout else ""
        if output:
            terminal_panel("Command output", output, "31", stream=sys.stderr)
        raise PatchError(f"Command failed with exit status {exc.returncode}") from exc


class FancyArgumentParser(argparse.ArgumentParser):
    def _print_message(self, message: str, file: Any = None) -> None:
        if not message:
            return
        stream = file or sys.stdout
        width = terminal_width()
        title = " COMMAND HELP "
        top = f"╭─{title}{'─' * max(1, width - len(title) - 2)}"
        bottom = f"╰{'─' * (width - 1)}"
        print(file=stream)
        print(color(top, "1", "36", stream=stream), file=stream)
        for raw_line in message.rstrip().splitlines():
            border = color("│", "36", stream=stream)
            stripped = raw_line.strip()
            if not stripped:
                print(border, file=stream)
                continue
            if raw_line.startswith("usage:"):
                label, remainder = raw_line.split(":", 1)
                rendered = (
                    color(label.upper(), "1", "35", stream=stream)
                    + color(":", "35", stream=stream)
                    + color(remainder, "1", stream=stream)
                )
            elif stripped in {"options:", "optional arguments:"}:
                rendered = color(stripped.upper(), "1", "36", stream=stream)
            elif raw_line.startswith("  -"):
                option_and_help = re.split(r"(\s{2,})", stripped, maxsplit=1)
                option = option_and_help[0]
                remainder = "".join(option_and_help[1:])
                rendered = (
                    "  "
                    + color(option, "1", "33", stream=stream)
                    + color(remainder, stream=stream)
                )
            else:
                rendered = color(raw_line, stream=stream)
            print(f"{border} {rendered}", file=stream)
        print(color(bottom, "1", "36", stream=stream), file=stream)
        print(file=stream)
        stream.flush()

    def error(self, message: str) -> NoReturn:
        terminal_panel("Argument error", message, "31", stream=sys.stderr)
        terminal_status(
            "HELP",
            "Show all installer options with:",
            "33",
            detail=f"{self.prog} --help",
            stream=sys.stderr,
        )
        self.exit(2)


def invoking_user_home() -> Path:
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user and sudo_user != "root":
        try:
            return Path(pwd.getpwnam(sudo_user).pw_dir)
        except KeyError:
            pass
    return Path.home()


def parse_args() -> argparse.Namespace:
    home = invoking_user_home()
    configured_codex_home = os.environ.get("CODEX_HOME")
    codex_home = (
        Path(configured_codex_home).expanduser()
        if configured_codex_home
        else home / ".codex"
    )
    parser = FancyArgumentParser(
        description=(
            "Add a dynamic provider selector and per-model provider routing to the "
            "macOS ChatGPT/Codex desktop app."
        )
    )
    parser.add_argument(
        "--app",
        type=Path,
        default=Path("/Applications/ChatGPT.app"),
        help="ChatGPT.app to patch (default: /Applications/ChatGPT.app)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=codex_home / "desktop-model-providers.json",
        help="Provider-routing JSON file in the effective Codex home",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=home / "Applications" / "ChatGPT Patch Backups",
        help="Directory in which a complete app backup is created",
    )
    parser.add_argument(
        "--overwrite-config",
        action="store_true",
        help="Replace the provider-routing JSON with the built-in template",
    )
    parser.add_argument(
        "--allow-running",
        action="store_true",
        help="Do not close target-app processes before patching (unsafe)",
    )
    return parser.parse_args()


def validate_provider_config(data: Any) -> None:
    if not isinstance(data, dict):
        raise PatchError("Provider config must be a JSON object")
    if data.get("version") != 1:
        raise PatchError("Provider config version must be 1")
    providers = data.get("providers")
    if not isinstance(providers, list) or not providers:
        raise PatchError("Provider config 'providers' must be a non-empty array")

    provider_ids: set[str] = set()
    for provider in providers:
        if not isinstance(provider, dict):
            raise PatchError("Every provider must be an object")
        provider_id = provider.get("id")
        if not isinstance(provider_id, str) or not provider_id.strip():
            raise PatchError("Every provider id must be a non-empty string")
        provider_id = provider_id.strip()
        if provider_id in provider_ids:
            raise PatchError(f"Duplicate provider id: {provider_id}")
        provider_ids.add(provider_id)
        label = provider.get("label")
        if not isinstance(label, str) or not label.strip():
            raise PatchError(f"Provider '{provider_id}' needs a non-empty label")
        description = provider.get("description", "")
        if not isinstance(description, str):
            raise PatchError(f"Provider '{provider_id}' description must be a string")

    default_provider = data.get("default_provider")
    if default_provider not in provider_ids:
        raise PatchError("default_provider must reference a configured provider")

    mappings = data.get("model_providers")
    if not isinstance(mappings, dict):
        raise PatchError("model_providers must be an object")
    for model, provider_id in mappings.items():
        if not isinstance(model, str) or not model.strip():
            raise PatchError("Every model mapping key must be a non-empty string")
        if provider_id not in provider_ids:
            raise PatchError(
                f"Model '{model}' references unknown provider '{provider_id}'"
            )


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def ensure_provider_config(path: Path, overwrite: bool) -> str:
    if overwrite or not path.exists() or path.stat().st_size == 0:
        validate_provider_config(DEFAULT_PROVIDER_CONFIG)
        atomic_write_json(path, DEFAULT_PROVIDER_CONFIG)
        return "written"
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise PatchError(f"Cannot read valid JSON from {path}: {exc}") from exc
    validate_provider_config(data)
    return "kept"


def asar_header_hash(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            size_pickle = handle.read(8)
            if len(size_pickle) != 8:
                raise PatchError("ASAR archive is too short to contain a header")
            size_payload, header_pickle_size = struct.unpack("<II", size_pickle)
            if size_payload != 4 or header_pickle_size < 8:
                raise PatchError("ASAR archive has an invalid header-size pickle")

            header_pickle = handle.read(header_pickle_size)
            if len(header_pickle) != header_pickle_size:
                raise PatchError("ASAR archive contains a truncated header")
    except OSError as exc:
        raise PatchError(f"Cannot read ASAR header from {path}: {exc}") from exc

    header_payload_size, header_string_size = struct.unpack("<II", header_pickle[:8])
    if header_payload_size > header_pickle_size - 4:
        raise PatchError("ASAR header payload size is invalid")
    header_start = 8
    header_end = header_start + header_string_size
    if header_end > len(header_pickle):
        raise PatchError("ASAR header string is truncated")

    header_json = header_pickle[header_start:header_end]
    try:
        json.loads(header_json.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PatchError("ASAR header does not contain valid UTF-8 JSON") from exc
    return hashlib.sha256(header_json).hexdigest()


def contains_marker(path: Path) -> bool:
    overlap = len(PATCH_MARKER) - 1
    previous = b""
    with path.open("rb") as handle:
        while chunk := handle.read(4 * 1024 * 1024):
            data = previous + chunk
            if PATCH_MARKER in data:
                return True
            previous = data[-overlap:] if overlap else b""
    return False


def load_plist(path: Path) -> tuple[dict[str, Any], plistlib.PlistFormat]:
    raw = path.read_bytes()
    plist_format = plistlib.FMT_BINARY if raw.startswith(b"bplist00") else plistlib.FMT_XML
    try:
        data = plistlib.loads(raw)
    except Exception as exc:
        raise PatchError(f"Cannot parse {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise PatchError(f"Unexpected plist root in {path}")
    return data, plist_format


def asar_integrity_hash(plist: dict[str, Any]) -> str:
    try:
        value = plist["ElectronAsarIntegrity"]["Resources/app.asar"]["hash"]
    except (KeyError, TypeError) as exc:
        raise PatchError("Info.plist has no Electron ASAR integrity entry") from exc
    if not isinstance(value, str):
        raise PatchError("Electron ASAR integrity hash is not a string")
    return value.lower()


def app_path_variants(app: Path) -> set[str]:
    variants = {str(app), str(app.resolve())}
    for value in tuple(variants):
        if value.startswith("/private/tmp/") or value.startswith("/private/var/"):
            variants.add(value[len("/private") :])
        elif value.startswith("/tmp/") or value.startswith("/var/"):
            variants.add(f"/private{value}")
    return variants


def find_target_app_processes(app: Path) -> list[tuple[int, str]]:
    prefixes = tuple(f"{variant.rstrip('/')}/" for variant in app_path_variants(app))
    try:
        result = subprocess.run(
            ["/bin/ps", "-ww", "-axo", "pid=,command="],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PatchError(f"Could not inspect running processes: {exc}") from exc

    matches: list[tuple[int, str]] = []
    for line in result.stdout.splitlines():
        parsed = re.match(r"\s*(\d+)\s+(.+)", line)
        if parsed is None:
            continue
        pid = int(parsed.group(1))
        command = parsed.group(2)
        if pid != os.getpid() and command.startswith(prefixes):
            matches.append((pid, command))
    return matches


def signal_processes(processes: list[tuple[int, str]], signal_number: int) -> None:
    for pid, _command in processes:
        try:
            os.kill(pid, signal_number)
        except ProcessLookupError:
            continue
        except PermissionError as exc:
            raise PatchError(f"Permission denied while stopping process {pid}") from exc


def wait_for_app_processes_to_exit(app: Path, timeout: float) -> list[tuple[int, str]]:
    deadline = time.monotonic() + timeout
    remaining = find_target_app_processes(app)
    while remaining and time.monotonic() < deadline:
        time.sleep(0.2)
        remaining = find_target_app_processes(app)
    return remaining


def stop_target_app_processes(app: Path, allow_running: bool) -> None:
    executable = app / "Contents" / "MacOS" / "ChatGPT"
    if not executable.is_file():
        raise PatchError(f"Cannot identify the target ChatGPT app executable: {executable}")

    processes = find_target_app_processes(app)
    if not processes:
        terminal_status(
            "PROCESS",
            "The target ChatGPT app is not running.",
            "32",
            detail=app,
        )
        return

    pid_summary = ", ".join(str(pid) for pid, _command in processes)
    if allow_running:
        terminal_status(
            "WARNING",
            "Target-app processes are running, but automatic closing was disabled.",
            "33",
            detail=f"PIDs: {pid_summary}",
        )
        return

    terminal_status(
        "CLOSE",
        f"Closing {len(processes)} process(es) launched from the target app bundle.",
        "35",
        detail=f"PIDs: {pid_summary}",
    )
    signal_processes(processes, signal.SIGTERM)
    remaining = wait_for_app_processes_to_exit(app, 5.0)

    if remaining:
        remaining_pids = ", ".join(str(pid) for pid, _command in remaining)
        terminal_status(
            "FORCE",
            "Some target-app processes ignored the close request; force-closing them.",
            "33",
            detail=f"PIDs: {remaining_pids}",
        )
        signal_processes(remaining, signal.SIGKILL)
        remaining = wait_for_app_processes_to_exit(app, 3.0)

    if remaining:
        details = "\n".join(f"PID {pid}: {command}" for pid, command in remaining)
        raise PatchError(
            "Could not stop every process belonging to the target app bundle.\n\n"
            f"{details}"
        )

    terminal_status(
        "CLOSED",
        "All processes belonging to the target app bundle have stopped.",
        "32",
    )


def unique_candidate(
    assets: Path,
    filename_fragment: str,
    content_needles: tuple[str, ...],
    role: str,
) -> Path:
    filename_matches = sorted(
        path
        for path in assets.glob("*.js")
        if filename_fragment in path.name and not path.name.endswith(".map.js")
    )
    matches = []
    for path in filename_matches:
        source = path.read_text(encoding="utf-8")
        if all(needle in source for needle in content_needles):
            matches.append(path)
    if len(matches) != 1:
        raise PatchError(
            f"Expected exactly one {role} JavaScript bundle containing "
            f"'{filename_fragment}' and its source markers, found {len(matches)} "
            f"out of {len(filename_matches)} filename matches"
        )
    return matches[0]


def parse_hunks(unified_diff: str) -> list[list[str]]:
    lines = unified_diff.splitlines()
    hunks: list[list[str]] = []
    current: list[str] | None = None
    for line in lines:
        if line.startswith("@@ "):
            current = []
            hunks.append(current)
        elif current is not None:
            if not line or line[0] not in " +-":
                raise PatchError(f"Malformed embedded diff line: {line!r}")
            current.append(line)
    if not hunks:
        raise PatchError("Embedded patch contains no hunks")
    return hunks


def apply_unified_diff(path: Path, unified_diff: str) -> None:
    source = path.read_text(encoding="utf-8")
    had_trailing_newline = source.endswith("\n")
    source_lines = source.splitlines()
    search_start = 0

    for hunk_number, hunk in enumerate(parse_hunks(unified_diff), start=1):
        old_lines = [line[1:] for line in hunk if line[0] in " -"]
        new_lines = [line[1:] for line in hunk if line[0] in " +"]
        matches = [
            index
            for index in range(search_start, len(source_lines) - len(old_lines) + 1)
            if source_lines[index : index + len(old_lines)] == old_lines
        ]
        if len(matches) != 1:
            raise PatchError(
                f"{path.name}: hunk {hunk_number} matched {len(matches)} times; "
                "the app build is unsupported or already modified"
            )
        index = matches[0]
        source_lines[index : index + len(old_lines)] = new_lines
        search_start = index + len(new_lines)

    result = "\n".join(source_lines) + ("\n" if had_trailing_newline else "")
    path.write_text(result, encoding="utf-8")


def make_backup(app: Path, backup_dir: Path, version: str, build: str) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_version = re.sub(r"[^A-Za-z0-9._-]+", "-", version)
    safe_build = re.sub(r"[^A-Za-z0-9._-]+", "-", build)
    backup = backup_dir / (
        f"ChatGPT-{safe_version}-build-{safe_build}-{timestamp}.app"
    )
    suffix = 1
    while backup.exists():
        backup = backup_dir / (
            f"ChatGPT-{safe_version}-build-{safe_build}-{timestamp}-{suffix}.app"
        )
        suffix += 1
    run(
        ["/usr/bin/ditto", str(app), str(backup)],
        label="Creating a complete app backup",
    )
    if not (backup / "Contents" / "Resources" / "app.asar").is_file():
        raise PatchError(f"Backup verification failed: {backup}")
    return backup


def atomic_replace_file(source: Path, target: Path) -> None:
    original_stat = target.stat()
    fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.patch-", dir=target.parent)
    os.close(fd)
    temporary_path = Path(temporary_name)
    try:
        shutil.copyfile(source, temporary_path)
        os.chmod(temporary_path, original_stat.st_mode)
        if os.geteuid() == 0:
            os.chown(temporary_path, original_stat.st_uid, original_stat.st_gid)
        os.replace(temporary_path, target)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def restore_backup(app: Path, backup: Path) -> Path:
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    failed_copy = app.with_name(f"{app.stem}.patch-failed-{timestamp}.app")
    suffix = 1
    while failed_copy.exists():
        failed_copy = app.with_name(
            f"{app.stem}.patch-failed-{timestamp}-{suffix}.app"
        )
        suffix += 1
    os.replace(app, failed_copy)
    try:
        run(
            ["/usr/bin/ditto", str(backup), str(app)],
            label="Restoring the original app from backup",
        )
    except Exception:
        os.replace(failed_copy, app)
        raise
    return failed_copy


def patch_app(app: Path, config: Path, backup_dir: Path, overwrite_config: bool) -> None:
    info_path = app / "Contents" / "Info.plist"
    resources = app / "Contents" / "Resources"
    asar_path = resources / "app.asar"
    unpacked_path = resources / "app.asar.unpacked"

    if sys.platform != "darwin":
        raise PatchError("This installer only supports macOS")
    if not app.is_dir() or not info_path.is_file() or not asar_path.is_file():
        raise PatchError(f"Not a supported ChatGPT app bundle: {app}")
    if not unpacked_path.is_dir():
        raise PatchError(f"Missing ASAR companion directory: {unpacked_path}")
    if shutil.which("npx") is None:
        raise PatchError("npx is required. Install Node.js, then run this installer again")

    config_action = ensure_provider_config(config, overwrite_config)
    terminal_status(
        "CONFIG",
        "Provider-routing config created."
        if config_action == "written"
        else "Existing provider-routing config validated.",
        "36",
        detail=config,
    )

    info, plist_format = load_plist(info_path)
    version = str(info.get("CFBundleShortVersionString", "unknown"))
    build = str(info.get("CFBundleVersion", "unknown"))
    if contains_marker(asar_path):
        terminal_status(
            "APP",
            f"Detected ChatGPT {version}, build {build}.",
            "34",
            detail=app,
        )
        print_completion_summary(config, already_installed=True)
        return

    current_header_hash = asar_header_hash(asar_path)
    expected_header_hash = asar_integrity_hash(info)
    if current_header_hash != expected_header_hash:
        raise PatchError(
            "The ASAR header does not match the current app's Info.plist integrity "
            "metadata. The bundle may be incomplete or modified."
        )
    terminal_status(
        "VERIFY",
        "The original app's ASAR header integrity is valid.",
        "32",
        detail=current_header_hash,
    )

    terminal_heading("Installation", "35")
    terminal_status(
        "APP",
        f"Preparing ChatGPT {version}, build {build}.",
        "34",
        detail=app,
    )
    with tempfile.TemporaryDirectory(prefix="chatgpt-provider-patch-") as temporary:
        work = Path(temporary)
        extracted = work / "app"
        patched_asar = work / "app.asar"
        patched_plist = work / "Info.plist"

        run(
            ["npx", "--yes", ASAR_PACKAGE, "extract", str(asar_path), str(extracted)],
            label="Extracting application resources",
        )
        assets = extracted / "webview" / "assets"
        if not assets.is_dir():
            raise PatchError("Extracted app has no webview/assets directory")

        central = unique_candidate(
            assets,
            "artifact-tab-content.electron~notebook-preview-panel~app-main~business-checkout",
            ("async prewarmThreadStart(", "async sendConfigReadRequest("),
            "App Server client",
        )
        picker = unique_candidate(
            assets,
            "settings-command-menu-section-items~new-thread-panel-page~settings-pag",
            ("composer.intelligenceDropdown.tooltip",),
            "model picker",
        )

        run(
            [
                "npx",
                "--yes",
                PRETTIER_PACKAGE,
                "--write",
                str(central),
                str(picker),
            ],
            label="Preparing the JavaScript bundles",
        )
        apply_unified_diff(central, CENTRAL_DIFF)
        apply_unified_diff(picker, PICKER_DIFF)

        if PATCH_MARKER.decode() not in central.read_text(encoding="utf-8"):
            raise PatchError("Routing marker missing after patch")
        if "CodexCustomProviderPickerSection" not in picker.read_text(encoding="utf-8"):
            raise PatchError("Provider picker missing after patch")

        run(
            [
                "npx",
                "--yes",
                PRETTIER_PACKAGE,
                "--write",
                str(central),
                str(picker),
            ],
            label="Formatting and validating the patched JavaScript",
        )
        run(
            ["npx", "--yes", ASAR_PACKAGE, "pack", str(extracted), str(patched_asar)],
            label="Packing patched application resources",
        )

        if not contains_marker(patched_asar):
            raise PatchError("Packed ASAR does not contain the patch marker")
        patched_header_hash = asar_header_hash(patched_asar)
        info["ElectronAsarIntegrity"]["Resources/app.asar"]["hash"] = patched_header_hash
        with patched_plist.open("wb") as handle:
            plistlib.dump(info, handle, fmt=plist_format, sort_keys=False)

        backup = make_backup(app, backup_dir, version, build)
        terminal_status("OK", "App backup created.", "32", detail=backup)

        live_mutation_started = False
        try:
            live_mutation_started = True
            atomic_replace_file(patched_asar, asar_path)
            atomic_replace_file(patched_plist, info_path)
            run(
                ["/usr/bin/codesign", "--deep", "--force", "--sign", "-", str(app)],
                label="Applying the ad-hoc app signature",
            )
            run(
                [
                    "/usr/bin/codesign",
                    "--verify",
                    "--deep",
                    "--strict",
                    "--verbose=2",
                    str(app),
                ],
                label="Verifying the app signature",
            )

            final_info, _ = load_plist(info_path)
            if asar_header_hash(asar_path) != asar_integrity_hash(final_info):
                raise PatchError("Installed ASAR integrity verification failed")
            if not contains_marker(asar_path):
                raise PatchError("Installed ASAR is missing the patch marker")
        except Exception as exc:
            if live_mutation_started:
                terminal_status(
                    "RECOVERY",
                    "Installation failed after app files changed. Restoring the backup.",
                    "33",
                    stream=sys.stderr,
                )
                try:
                    failed_copy = restore_backup(app, backup)
                    terminal_status(
                        "RESTORED",
                        "The original app was restored. The failed patched copy was retained.",
                        "32",
                        detail=failed_copy,
                        stream=sys.stderr,
                    )
                except Exception as restore_exc:
                    terminal_panel(
                        "Recovery failed",
                        f"Automatic restoration failed: {restore_exc}\n"
                        f"The full backup remains at: {backup}",
                        "31",
                        stream=sys.stderr,
                    )
            raise exc

    print_completion_summary(config, backup=backup)


def main() -> int:
    args = parse_args()
    try:
        app = args.app.expanduser().resolve()
        stop_target_app_processes(app, args.allow_running)
        patch_app(
            app,
            args.config.expanduser().resolve(),
            args.backup_dir.expanduser().resolve(),
            args.overwrite_config,
        )
    except PatchError as exc:
        fail(str(exc))
    except PermissionError as exc:
        fail(f"Permission denied: {exc}")
    except KeyboardInterrupt:
        fail("Interrupted", 130)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
