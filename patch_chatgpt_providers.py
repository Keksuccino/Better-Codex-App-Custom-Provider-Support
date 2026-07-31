#!/usr/bin/env python3
"""Install the custom model-provider picker patch into ChatGPT.app on macOS.

ChatGPT.app is the desktop Codex client; its JavaScript bundles are patched with
a custom model-provider picker and per-model provider routing. The default
target is /Applications/ChatGPT.app; pass a different bundle with --app. The
installer only claims support for bundles whose exact source hunks match, so a
future app update fails cleanly before the installed app is modified.

Run with --self-test to exercise the installer's validation logic without
touching the installed app.
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
import types
from typing import Any, Callable, NoReturn


PATCH_MARKER = b"__codexDesktopModelProvidersPatchV3"
LEGACY_PATCH_MARKER = b"__codexDesktopModelProvidersPatchV2"
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
+  return (window.__codexDesktopModelProvidersPatchV3 ??= {
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
+  return (window.__codexDesktopModelProvidersPatchV3 ??= {
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


# ChatGPT 26.721 moved both targets into app-initial, renamed the minified
# bindings, and introduced the Power Picker. Keep a separate exact-hunk variant
# so unsupported future builds still fail before the installed app is touched.
def derive_versioned_diff(base: str, replacements: tuple[tuple[str, str, int], ...]) -> str:
    """Derive an exact-hunk build variant while verifying every fragile rename.

    Electron's bundler changes short identifiers between releases even when the
    surrounding behavior is unchanged. Expected occurrence counts deliberately
    turn an accidental partial replacement into an installer-development error.
    """
    derived = base
    for old, new, expected_count in replacements:
        actual_count = derived.count(old)
        if actual_count != expected_count:
            message = f"Versioned patch replacement count changed for {old!r}: expected {expected_count}, found {actual_count}"
            raise RuntimeError(message)
        derived = derived.replace(old, new)
    return derived


CENTRAL_RENAMES_26721 = (
    ("   let t = oe(e);", "   let t = abe(e);", 1),
    ("await Xe(`codex-home`", "await tp(`codex-home`", 1),
    ("await Xe(`read-file`", "await tp(`read-file`", 1),
    (" var jf,\n   Mf,", " var s9t,\n   c9t,", 1),
    (
        """@@ -4809,6 +4950,7 @@
             throw Error(
               `AppServerRequestClient is missing a message dispatcher`,
             );
+          e = await codexPatchAppServerParams(`thread/start`, e);
           return this.enqueueRequest(
             `thread/start`,
             e,
""",
        """@@ -137758,6 +137899,7 @@
             throw Error(
               `AppServerRequestClient is missing a message dispatcher`,
             );
+          e = await codexPatchAppServerParams(`thread/start`, e);
           let n = t?.priority ?? `critical`,
             r = Q7t(`thread/start`, t?.source),
             i =
""",
        1,
    ),
)
CENTRAL_DIFF_26721 = derive_versioned_diff(CENTRAL_DIFF, CENTRAL_RENAMES_26721)


PICKER_DIFF_26721 = r"""@@ -520849,7 +520849,7 @@
 }
 function Scs(e) {
-  let t = (0, wcs.c)(12),
+  let t = (0, wcs.c)(13),
     { submenu: n } = e,
     r = n.ariaLabel,
     i = n.contentClassName,
@@ -520871,10 +520871,15 @@
     t[7] !== n.label ||
     t[8] !== n.value ||
     t[9] !== o ||
-    t[10] !== l
+    t[10] !== l ||
+    t[11] !== n.extras
       ? ((u = (0, QX.jsx)(Kos, {
           ariaLabel: r,
           contentClassName: i,
           disabled: a,
           flyoutHeader: o,
           label: s,
           value: c,
-          children: l,
+          children:
+            n.extras == null
+              ? l
+              : (0, QX.jsxs)(QX.Fragment, { children: [n.extras, l] }),
         })),
         (t[4] = n.ariaLabel),
         (t[5] = n.contentClassName),
@@ -520887,8 +520892,9 @@
         (t[8] = n.value),
         (t[9] = o),
         (t[10] = l),
-        (t[11] = u))
-      : (u = t[11]),
+        (t[11] = n.extras),
+        (t[12] = u))
+      : (u = t[12]),
     u
   );
 }
@@ -549520,6 +549525,202 @@
       (xMs = Aa(Q, (e, { get: t }) =>
         bMs({
           conversationId: e,
           resumeState: t(PD, e) ?? void 0,
           turnCount: t(LD, e),
         }),
       )));
   });
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
+  return (window.__codexDesktopModelProvidersPatchV3 ??= {
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
+        let { codexHome: e } = await tp(`codex-home`, {
+            params: { hostId: `local` },
+          }),
+          n = e.includes(`\\`) && !e.includes(`/`) ? `\\` : `/`,
+          r = `${e.replace(/[\\/]+$/u, ``)}${n}desktop-model-providers.json`;
+        t.configPath = r;
+        let { contents: i } = await tp(`read-file`, {
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
+      void Rf(`clear-prewarmed-threads-for-host`, { hostId: `local` }).catch(
+        () => {},
+      );
+    },
+    c =
+      e.providers.find((t) => t.id === e.defaultProvider)?.label ??
+      e.defaultProvider,
+    l = e.providers.map((e) =>
+      (0, wQ.jsx)(
+        yz.Item,
+        {
+          RightIcon: a === e.id ? Ym : void 0,
+          SubText:
+            e.description.length === 0
+              ? null
+              : (0, wQ.jsx)(`span`, {
+                  className: `text-token-description-foreground`,
+                  children: e.description,
+                }),
+          onSelect: s(e.id),
+          children: e.label,
+        },
+        e.id,
+      ),
+    );
+  return (0, wQ.jsxs)(wQ.Fragment, {
+    children: [
+      (0, wQ.jsx)(yz.Title, { children: `Provider for new tasks` }),
+      n == null
+        ? null
+        : (0, wQ.jsx)(yz.Item, {
+            disabled: !0,
+            SubText: (0, wQ.jsx)(`span`, {
+              className: `text-token-description-foreground`,
+              children: n,
+            }),
+            children: `Provider config error — using fallback`,
+          }),
+      (0, wQ.jsx)(yz.Item, {
+        RightIcon: a === `auto` ? Ym : void 0,
+        SubText: (0, wQ.jsx)(`span`, {
+          className: `text-token-description-foreground`,
+          children: `Uses the mapped provider for each model; ${c} when unmapped`,
+        }),
+        onSelect: s(`auto`),
+        children: `Automatic`,
+      }),
+      l,
+      (0, wQ.jsx)(yz.Separator, {}),
+    ],
+  });
+}
 function CMs(e) {
   let t = (0, TMs.c)(164),
@@ -549693,6 +549895,7 @@
           value: s,
         },
         model: {
+          extras: (0, wQ.jsx)(CodexCustomProviderPickerSection, {}),
           ariaLabel: U.formatMessage(
             {
               id: `composer.intelligenceDropdown.model.rowAriaLabel`,
@@ -549782,6 +549985,7 @@
       : ((g = (0, wQ.jsxs)(wQ.Fragment, {
           children: [
+            (0, wQ.jsx)(CodexCustomProviderPickerSection, {}),
             m,
             (0, wQ.jsx)(`div`, {
               className: `vertical-scroll-fade-mask flex max-h-[250px] flex-col overflow-y-auto`,
@@ -550438,11 +550642,13 @@
 }
 var TMs,
   wQ,
+  CodexProviderPatchReact,
   EMs = e(() => {
     ((TMs = c()),
+      (CodexProviderPatchReact = r(o(), 1)),
       pd(),
       ad(),
       gls(),
"""


# Build 6067 preserves the 26.721 behavior and menu structure, but the bundler
# renamed the surrounding symbols. Derive this layout from the verified 26.721
# patch so the shared routing and picker implementation cannot drift.
CENTRAL_RENAMES_26727 = (
    ("   let t = abe(e);", "   let t = rSe(e);", 1),
    ("await tp(`codex-home`", "await rp(`codex-home`", 1),
    ("await tp(`read-file`", "await rp(`read-file`", 1),
    (" var s9t,\n   c9t,", " var xdn,\n   Sdn,", 1),
    (
        "            r = Q7t(`thread/start`, t?.source),",
        "            r = fdn(`thread/start`, t?.source),",
        1,
    ),
)
CENTRAL_DIFF_26727 = derive_versioned_diff(CENTRAL_DIFF_26721, CENTRAL_RENAMES_26727)


PICKER_RENAMES_26727 = (
    ("function Scs(e) {", "function Mws(e) {", 1),
    ("wcs.c", "Pws.c", 2),
    ("QX", "JY", 3),
    ("Kos", "nCs", 1),
    ("xMs", "XJs", 1),
    ("Aa", "Ca", 1),
    ("bMs", "YJs", 1),
    ("PD", "aD", 1),
    ("LD", "lD", 1),
    ("await tp(`codex-home`", "await rp(`codex-home`", 1),
    ("await tp(`read-file`", "await rp(`read-file`", 1),
    (
        "void Rf(`clear-prewarmed-threads-for-host`",
        "void rp(`clear-prewarmed-threads-for-host`",
        1,
    ),
    ("wQ", "CZ", 16),
    ("yz", "_z", 5),
    ("Ym", "ch", 2),
    ("function CMs(e) {", "function QJs(e) {", 1),
    ("TMs", "eYs", 3),
    ("  EMs = e(() => {", "  tYs = n(() => {", 1),
    ("     ((eYs = c()),", "     ((eYs = l()),", 1),
    (
        "(CodexProviderPatchReact = r(o(), 1))",
        "(CodexProviderPatchReact = r(s(), 1))",
        1,
    ),
    (
        "       pd(),\n       ad(),\n       gls(),",
        "       ld(),\n       td(),\n       ETs(),",
        1,
    ),
)
PICKER_DIFF_26727 = derive_versioned_diff(PICKER_DIFF_26721, PICKER_RENAMES_26727)


CENTRAL_DIFF_V2_TO_V3 = r"""@@ -137601,7 +137601,7 @@
   };
 }
 function codexProviderRoutingState() {
-  return (window.__codexDesktopModelProvidersPatchV2 ??= {
+  return (window.__codexDesktopModelProvidersPatchV3 ??= {
     config: codexProviderRoutingFallback(),
     configPath: null,
     error: null,
"""


PICKER_DIFF_26721_V2_TO_V3 = r"""@@ -520849,7 +520849,7 @@
 }
 function Scs(e) {
-  let t = (0, wcs.c)(12),
+  let t = (0, wcs.c)(13),
     { submenu: n } = e,
     r = n.ariaLabel,
     i = n.contentClassName,
@@ -520871,10 +520871,15 @@
     t[7] !== n.label ||
     t[8] !== n.value ||
     t[9] !== o ||
-    t[10] !== l
+    t[10] !== l ||
+    t[11] !== n.extras
       ? ((u = (0, QX.jsx)(Kos, {
           ariaLabel: r,
           contentClassName: i,
           disabled: a,
           flyoutHeader: o,
           label: s,
           value: c,
-          children: l,
+          children:
+            n.extras == null
+              ? l
+              : (0, QX.jsxs)(QX.Fragment, { children: [n.extras, l] }),
         })),
         (t[4] = n.ariaLabel),
         (t[5] = n.contentClassName),
@@ -520887,8 +520892,9 @@
         (t[8] = n.value),
         (t[9] = o),
         (t[10] = l),
-        (t[11] = u))
-      : (u = t[11]),
+        (t[11] = n.extras),
+        (t[12] = u))
+      : (u = t[12]),
     u
   );
 }
@@ -549630,7 +549636,7 @@
   };
 }
 function codexPickerProviderRoutingState() {
-  return (window.__codexDesktopModelProvidersPatchV2 ??= {
+  return (window.__codexDesktopModelProvidersPatchV3 ??= {
     config: codexPickerProviderRoutingFallback(),
     configPath: null,
     error: null,
@@ -549886,7 +549892,6 @@
         (t[39] = f))
       : (f = t[39]),
       (G = {
-        extras: (0, wQ.jsx)(CodexCustomProviderPickerSection, {}),
         effort: {
           ariaLabel: U.formatMessage(
             {
@@ -549921,6 +549926,7 @@
           value: s,
         },
         model: {
+          extras: (0, wQ.jsx)(CodexCustomProviderPickerSection, {}),
           ariaLabel: U.formatMessage(
             {
               id: `composer.intelligenceDropdown.model.rowAriaLabel`,
@@ -550013,6 +550019,7 @@
       ? (g = t[52])
       : ((g = (0, wQ.jsxs)(wQ.Fragment, {
           children: [
+            (0, wQ.jsx)(CodexCustomProviderPickerSection, {}),
             m,
             (0, wQ.jsx)(`div`, {
               className: `vertical-scroll-fade-mask flex max-h-[250px] flex-col overflow-y-auto`,
@@ -550148,7 +550155,6 @@
       : (k = t[77]),
       (K = (0, wQ.jsxs)(wQ.Fragment, {
         children: [
-          (0, wQ.jsx)(CodexCustomProviderPickerSection, {}),
           (0, wQ.jsx)(Kos, {
             ariaLabel: U.formatMessage(
               {
@@ -550354,7 +550360,6 @@
   t[90] !== le || t[91] !== pe || t[92] !== me
     ? ((he = (0, wQ.jsxs)(wQ.Fragment, {
         children: [
-          (0, wQ.jsx)(CodexCustomProviderPickerSection, {}),
           le,
           pe,
           me,
"""


PICKER_DIFF_LEGACY_V2_TO_V3 = r"""@@ -10242,7 +10242,7 @@
   };
 }
 function codexPickerProviderRoutingState() {
-  return (window.__codexDesktopModelProvidersPatchV2 ??= {
+  return (window.__codexDesktopModelProvidersPatchV3 ??= {
     config: codexPickerProviderRoutingFallback(),
     configPath: null,
     error: null,
@@ -10360,6 +10360,6 @@
 function MO(e) {
   let t = (0, PO.c)(169),
     {
"""


PATCH_VARIANTS: tuple[tuple[str, str, str], ...] = (
    ("ChatGPT 26.727 Power Picker", CENTRAL_DIFF_26727, PICKER_DIFF_26727),
    ("ChatGPT 26.721 Power Picker", CENTRAL_DIFF_26721, PICKER_DIFF_26721),
    ("ChatGPT 26.715 legacy picker", CENTRAL_DIFF, PICKER_DIFF),
    (
        "ChatGPT 26.721 provider-picker V2 upgrade",
        CENTRAL_DIFF_V2_TO_V3,
        PICKER_DIFF_26721_V2_TO_V3,
    ),
    (
        "ChatGPT 26.715 provider-picker V2 marker upgrade",
        CENTRAL_DIFF_V2_TO_V3,
        PICKER_DIFF_LEGACY_V2_TO_V3,
    ),
)


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
    upgraded: bool = False,
) -> None:
    codex_config = config.parent / "config.toml"
    if already_installed:
        terminal_status(
            "READY",
            "Patch already installed; no app files were changed.",
            "32",
        )
    else:
        terminal_status(
            "SUCCESS",
            "Patch upgraded successfully."
            if upgraded
            else "Patch installed successfully.",
            "32",
        )

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


def invoking_user_ids() -> tuple[int, int] | None:
    """Return the (uid, gid) of the sudo-invoking user, when running as root."""
    if os.geteuid() != 0:
        return None
    sudo_user = os.environ.get("SUDO_USER")
    if not sudo_user or sudo_user == "root":
        return None
    try:
        entry = pwd.getpwnam(sudo_user)
    except KeyError:
        return None
    return entry.pw_uid, entry.pw_gid


def resolve_config_owner(path: Path) -> tuple[int, int] | None:
    """Choose the owner for a config file this installer is about to write.

    Policy:
    - Not running as root: the current user owns the file (return None).
    - Root with the config under the invoking user's home (the default
      ~/.codex/desktop-model-providers.json): the invoking user, so the user
      can read and edit it without sudo.
    - Root with a custom --config path: preserve the existing file's owner when
      it exists, otherwise leave root ownership. Custom paths are never
      reassigned to SUDO_USER.
    """
    if os.geteuid() != 0:
        return None
    try:
        user_home = Path(invoking_user_home()).resolve()
    except OSError:
        user_home = None
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    if user_home is not None and resolved.is_relative_to(user_home):
        return invoking_user_ids()
    try:
        stat_result = path.stat()
    except OSError:
        return None
    return stat_result.st_uid, stat_result.st_gid


def _ensure_config_parent_ownership(
    path: Path, owner: tuple[int, int] | None
) -> None:
    """Assign freshly created parent directories to the config owner.

    Only directories that did not exist before this call are adjusted, and only
    when the installer is root and the config will be owned by the invoking
    user. Failures are surfaced as PatchError rather than silently swallowed.
    """
    if owner is None:
        path.parent.mkdir(parents=True, exist_ok=True)
        return
    newly_created: list[Path] = []
    current = path.parent
    while not current.exists():
        newly_created.append(current)
        if current.parent == current:
            break
        current = current.parent
    path.parent.mkdir(parents=True, exist_ok=True)
    for entry in reversed(newly_created):
        try:
            os.chown(entry, *owner)
        except OSError as exc:
            raise PatchError(
                f"Cannot set ownership of {entry} to uid={owner[0]}, "
                f"gid={owner[1]}: {exc}"
            ) from exc


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
        help="ChatGPT.app (the desktop Codex client) to patch "
        "(default: /Applications/ChatGPT.app)",
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
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run built-in unit tests and exit without touching the app",
    )
    return parser.parse_args()


def validate_provider_config(data: Any) -> None:
    """Validate provider-routing config with the same semantics as the JS.

    The injected picker code runs an equivalent normalizer (see
    codexNormalizeProviderRoutingConfig); the two must agree, so this function
    mirrors its strictness: booleans are rejected where JS uses `!==`, and
    values are trimmed only where the JS trims them.
    """
    if not isinstance(data, dict):
        raise PatchError("Provider config must be a JSON object")
    version = data.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version != 1:
        raise PatchError("Provider config version must be the integer 1")
    providers = data.get("providers")
    if not isinstance(providers, list) or not providers:
        raise PatchError("Provider config 'providers' must be a non-empty array")

    provider_ids: set[str] = set()
    for provider in providers:
        if not isinstance(provider, dict):
            raise PatchError("Every provider must be an object")
        raw_id = provider.get("id")
        if not isinstance(raw_id, str) or not raw_id.strip():
            raise PatchError("Every provider id must be a non-empty string")
        provider_id = raw_id.strip()
        if provider_id in provider_ids:
            raise PatchError(f"Duplicate provider id: {provider_id}")
        provider_ids.add(provider_id)
        label = provider.get("label")
        if not isinstance(label, str) or not label.strip():
            raise PatchError(f"Provider '{provider_id}' needs a non-empty label")
        description = provider.get("description", "")
        if not isinstance(description, str):
            raise PatchError(f"Provider '{provider_id}' description must be a string")

    raw_default = data.get("default_provider")
    if not isinstance(raw_default, str) or not raw_default.strip():
        raise PatchError("default_provider must be a non-empty string")
    if raw_default.strip() not in provider_ids:
        raise PatchError("default_provider must reference a configured provider")

    mappings = data.get("model_providers")
    if not isinstance(mappings, dict):
        raise PatchError("model_providers must be an object")
    for raw_model, raw_provider in mappings.items():
        if not isinstance(raw_model, str) or not raw_model.strip():
            raise PatchError("Every model mapping key must be a non-empty string")
        # The injected JS checks membership with the untrimmed value, so keep
        # that exact behavior here: "openrouter " must not silently match.
        if not isinstance(raw_provider, str) or raw_provider not in provider_ids:
            raise PatchError(
                f"Model '{raw_model}' references unknown provider '{raw_provider}'"
            )


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    owner = resolve_config_owner(path)
    _ensure_config_parent_ownership(path, owner)
    payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, 0o600)
        if owner is not None:
            try:
                os.chown(temporary_path, *owner)
            except OSError as exc:
                raise PatchError(
                    f"Cannot set ownership of {temporary_path} to uid={owner[0]}, "
                    f"gid={owner[1]}: {exc}"
                ) from exc
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def check_provider_config(path: Path, overwrite: bool) -> str:
    """Decide how the provider-routing config will be handled, without writing.

    Returns one of:
      - "replace": --overwrite-config was requested; the existing file is not
        read or validated, so a malformed config can always be repaired.
      - "create": the file is missing or empty and will be written.
      - "keep": the file exists and validates; it will be left untouched.
    Raises PatchError only when an existing file must be kept but is invalid.
    """
    if overwrite:
        return "replace"
    if not path.exists():
        return "create"
    if path.stat().st_size == 0:
        return "create"
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise PatchError(f"Cannot read valid JSON from {path}: {exc}") from exc
    validate_provider_config(data)
    return "keep"


def write_provider_config(path: Path) -> None:
    """Write the built-in provider-routing template (ownership policy applied)."""
    validate_provider_config(DEFAULT_PROVIDER_CONFIG)
    atomic_write_json(path, DEFAULT_PROVIDER_CONFIG)


def _commit_provider_config(config: Path, config_state: str) -> None:
    """Write the provider-routing config when its state requires it.

    Runs only after the app patch is verified, so a failed install never
    changes the user's configuration. Prints the outcome.
    """
    if config_state in ("create", "replace"):
        write_provider_config(config)
        terminal_status(
            "CONFIG",
            "Provider-routing config created."
            if config_state == "create"
            else "Provider-routing config replaced by the built-in template.",
            "36",
            detail=config,
        )
    else:
        terminal_status(
            "CONFIG",
            "Existing provider-routing config kept.",
            "36",
            detail=config,
        )


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


def contains_marker(path: Path, marker: bytes = PATCH_MARKER) -> bool:
    overlap = len(marker) - 1
    previous = b""
    with path.open("rb") as handle:
        while chunk := handle.read(4 * 1024 * 1024):
            data = previous + chunk
            if marker in data:
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
    info, _ = load_plist(app / "Contents" / "Info.plist")
    executable_name = info.get("CFBundleExecutable")
    if not isinstance(executable_name, str) or not executable_name:
        raise PatchError("Info.plist has no CFBundleExecutable entry")
    executable = app / "Contents" / "MacOS" / executable_name
    if not executable.is_file():
        raise PatchError(f"Cannot identify the target app executable: {executable}")

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
    content_needles: tuple[str, ...],
    role: str,
) -> Path:
    candidates = sorted(
        path
        for path in assets.glob("*.js")
        if not path.name.endswith(".map.js")
    )
    matches = []
    for path in candidates:
        source = path.read_text(encoding="utf-8")
        if all(needle in source for needle in content_needles):
            matches.append(path)
    if len(matches) != 1:
        raise PatchError(
            f"Expected exactly one {role} JavaScript bundle containing all "
            f"required source markers, found {len(matches)} among "
            f"{len(candidates)} JavaScript bundles"
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


def render_unified_diff(source: str, unified_diff: str, source_name: str) -> str:
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
                f"{source_name}: hunk {hunk_number} matched {len(matches)} times; "
                "the app build is unsupported or already modified"
            )
        index = matches[0]
        source_lines[index : index + len(old_lines)] = new_lines
        search_start = index + len(new_lines)

    return "\n".join(source_lines) + ("\n" if had_trailing_newline else "")


def apply_supported_patch_variant(central: Path, picker: Path) -> str:
    originals = {
        path: path.read_text(encoding="utf-8") for path in {central, picker}
    }
    compatible: list[tuple[str, dict[Path, str]]] = []

    for name, central_diff, picker_diff in PATCH_VARIANTS:
        rendered = originals.copy()
        try:
            rendered[central] = render_unified_diff(
                rendered[central], central_diff, central.name
            )
            rendered[picker] = render_unified_diff(
                rendered[picker], picker_diff, picker.name
            )
        except PatchError:
            continue
        compatible.append((name, rendered))

    if len(compatible) != 1:
        raise PatchError(
            "Expected exactly one supported JavaScript patch layout, found "
            f"{len(compatible)}. This app build is unsupported or already modified."
        )

    name, rendered = compatible[0]
    for path, source in rendered.items():
        path.write_text(source, encoding="utf-8")
    return name


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


def _remove_path(path: Path) -> str:
    """Remove a directory or file, returning a failure detail ("" on success).

    Leftover staging is reported rather than silently hidden, so callers can
    surface it in their diagnostics.
    """
    try:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    except OSError as exc:
        return f"Cleanup error removing {path}: {exc}"
    return ""


def restore_backup(app: Path, backup: Path) -> Path:
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    failed_copy = app.with_name(f"{app.stem}.patch-failed-{timestamp}.app")
    suffix = 1
    while failed_copy.exists():
        failed_copy = app.with_name(
            f"{app.stem}.patch-failed-{timestamp}-{suffix}.app"
        )
        suffix += 1

    staging = app.with_name(f"{app.stem}.restore-staging-{timestamp}.app")
    suffix = 1
    while staging.exists():
        staging = app.with_name(
            f"{app.stem}.restore-staging-{timestamp}-{suffix}.app"
        )
        suffix += 1

    # Restore into a sibling staging directory first, so a partial or failed
    # restore can never leave the live app path half-written. The app path is
    # only swapped once the restored copy has been verified complete.
    try:
        run(
            ["/usr/bin/ditto", str(backup), str(staging)],
            label="Restoring the original app from backup",
        )
        if not (staging / "Contents" / "Resources" / "app.asar").is_file():
            raise PatchError("Restored app is missing app.asar")
    except Exception as exc:
        cleanup_detail = _remove_path(staging)
        if cleanup_detail:
            raise PatchError(
                "Restore failed and the partial staging copy could not be "
                f"removed.\n\n{cleanup_detail}"
            ) from exc
        raise

    try:
        os.replace(app, failed_copy)
    except Exception as exc:
        cleanup_detail = _remove_path(staging)
        if cleanup_detail:
            raise PatchError(
                "Restore failed and the partial staging copy could not be "
                f"removed.\n\n{cleanup_detail}"
            ) from exc
        raise

    try:
        os.replace(staging, app)
    except Exception as exc:
        moved_back = False
        move_back_detail = ""
        try:
            os.replace(failed_copy, app)
            moved_back = True
        except Exception as move_back_exc:
            move_back_detail = f"\nMove-back error: {move_back_exc}"
        cleanup_detail = _remove_path(staging)
        raise PatchError(
            "Restore of the original app failed at the final swap step.\n\n"
            f"Backup: {backup}\n"
            f"Failed copy: {failed_copy}\n"
            f"Staging: {staging}\n"
            f"Swap error: {exc}"
            + move_back_detail
            + (f"\nCleanup error: {cleanup_detail}" if cleanup_detail else "")
            + "\n\n"
            + (
                "The failed patched copy was moved back into place."
                if moved_back
                else (
                    "The failed patched copy could NOT be moved back into "
                    "place; the app path may currently be missing."
                )
            )
        ) from exc
    return failed_copy


def verify_installed_bundle(asar_path: Path, info: dict[str, Any]) -> None:
    """Pure checks that an already-patched bundle is internally consistent.

    The patch marker alone is not proof of a successful install: a crash
    between replacing app.asar and Info.plist leaves a bundle whose marker
    exists but whose header no longer matches the plist integrity entry.
    """
    if asar_header_hash(asar_path) != asar_integrity_hash(info):
        raise PatchError(
            "The installed app contains the patch marker, but its ASAR header "
            "does not match the Info.plist integrity metadata. The patch looks "
            "half-applied or the bundle was modified after patching.\n\n"
            "Restore the original app from your install-time backup, or "
            "reinstall ChatGPT, then run this installer again."
        )
    if not contains_marker(asar_path, PATCH_MARKER):
        raise PatchError(
            "The installed app is missing the provider-routing patch marker."
        )
    if contains_marker(asar_path, LEGACY_PATCH_MARKER):
        raise PatchError(
            "The installed app contains both the current and the legacy patch "
            "markers. Reinstall ChatGPT or restore your backup, then patch again."
        )
    if not contains_marker(asar_path, b"CodexCustomProviderPickerSection"):
        raise PatchError(
            "The installed app contains the routing marker but the provider "
            "picker is missing from the bundle. Reinstall ChatGPT or restore "
            "your backup, then patch again."
        )


def verify_installed_state(app: Path, asar_path: Path, info: dict[str, Any]) -> None:
    """Confirm an already-patched app is consistent and signed before READY."""
    verify_installed_bundle(asar_path, info)
    try:
        subprocess.run(
            ["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or "").strip() or (exc.stdout or "").strip()
        raise PatchError(
            "The installed app's code signature could not be verified; it may "
            "have been modified after patching."
            + (f"\n\n{details}" if details else "")
            + "\n\nRestore the original app from your install-time backup, "
            "or reinstall ChatGPT, then run this installer again."
        ) from exc
    except OSError as exc:
        raise PatchError(
            "The installed app's code signature could not be verified; it may "
            "have been modified after patching.\n\n"
            f"{exc}\n\n"
            "Restore the original app from your install-time backup, or "
            "reinstall ChatGPT, then run this installer again."
        ) from exc


def patch_app(
    app: Path,
    config: Path,
    backup_dir: Path,
    overwrite_config: bool,
    allow_running: bool,
) -> None:
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

    info, plist_format = load_plist(info_path)
    version = str(info.get("CFBundleShortVersionString", "unknown"))
    build = str(info.get("CFBundleVersion", "unknown"))

    # Decide how the provider-routing config will be handled without touching
    # it yet: an unsupported or already-patched app must not be able to clobber
    # the user's configuration. The write happens only after the app has been
    # patched, codesigned, and verified.
    config_state = check_provider_config(config, overwrite_config)
    if config_state == "keep":
        config_status = (
            "Existing provider-routing config validated; it will be left untouched."
        )
    elif config_state == "replace":
        config_status = (
            "Provider-routing config will be replaced by the built-in template "
            "after the patch is verified."
        )
    else:
        config_status = (
            "Provider-routing config will be created after the patch is verified."
        )
    terminal_status("CONFIG", config_status, "36", detail=config)

    if contains_marker(asar_path):
        terminal_status(
            "APP",
            f"Detected ChatGPT {version}, build {build}.",
            "34",
            detail=app,
        )
        verify_installed_state(app, asar_path, info)
        _commit_provider_config(config, config_state)
        print_completion_summary(config, already_installed=True)
        return

    is_upgrade = contains_marker(asar_path, LEGACY_PATCH_MARKER)
    if is_upgrade:
        terminal_status(
            "UPGRADE",
            "An earlier provider-picker patch was detected and will be upgraded.",
            "35",
            detail=f"ChatGPT {version}, build {build}",
        )

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
            ("async prewarmThreadStart(", "async sendConfigReadRequest("),
            "App Server client",
        )
        picker = unique_candidate(
            assets,
            ("composer.intelligenceDropdown.tooltip", "modelOptionsDisabled"),
            "model picker",
        )

        patch_targets = list(dict.fromkeys((central, picker)))

        run(
            [
                "npx",
                "--yes",
                PRETTIER_PACKAGE,
                "--write",
                *(str(path) for path in patch_targets),
            ],
            label="Preparing the JavaScript bundles",
        )
        patch_layout = apply_supported_patch_variant(central, picker)
        terminal_status(
            "LAYOUT",
            "Matched a supported application bundle layout.",
            "32",
            detail=patch_layout,
        )

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
                *(str(path) for path in patch_targets),
            ],
            label="Formatting and validating the patched JavaScript",
        )
        run(
            ["npx", "--yes", ASAR_PACKAGE, "pack", str(extracted), str(patched_asar)],
            label="Packing patched application resources",
        )

        if not contains_marker(patched_asar):
            raise PatchError("Packed ASAR does not contain the patch marker")
        if contains_marker(patched_asar, LEGACY_PATCH_MARKER):
            raise PatchError("Packed ASAR still contains the legacy patch marker")
        patched_header_hash = asar_header_hash(patched_asar)
        info["ElectronAsarIntegrity"]["Resources/app.asar"]["hash"] = patched_header_hash
        with patched_plist.open("wb") as handle:
            plistlib.dump(info, handle, fmt=plist_format, sort_keys=False)

        # Stop the target app only after every validation and repack step has
        # succeeded, so a running ChatGPT is never disturbed by a failed patch.
        stop_target_app_processes(app, allow_running)

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
            # Unify the fresh-install checks with the READY path so both verify
            # hash vs plist, V3 present, V2 absent, and the picker symbol.
            verify_installed_bundle(asar_path, final_info)
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

    # The app is patched, codesigned, and verified. Commit the provider-routing
    # config only now, so a failed install never changes user configuration.
    try:
        _commit_provider_config(config, config_state)
    except PatchError as exc:
        raise PatchError(
            "The app was patched successfully, but the provider-routing config "
            f"could not be installed at {config}.\n\n{exc}"
        ) from exc

    print_completion_summary(config, backup=backup, upgraded=is_upgrade)


def _expect_patch_error(context: str, fn: Callable[[], None]) -> None:
    try:
        fn()
    except PatchError:
        return
    raise AssertionError(f"{context}: expected PatchError, but it succeeded")


def build_synthetic_source(unified_diff: str) -> str:
    """Build a minimal source a unified diff applies to cleanly.

    Concatenates each hunk's old_lines (context + removals) in hunk order, so
    render_unified_diff finds each hunk exactly once. Used by the self-tests to
    prove every PATCH_VARIANTS entry is internally consistent and that applying
    a patch to its own output fails (the repeat-application guard).
    """
    sections: list[str] = []
    for hunk in parse_hunks(unified_diff):
        old_lines = [line[1:] for line in hunk if line[0] in " -"]
        if old_lines:
            sections.append("\n".join(old_lines))
    return "\n\n".join(sections) + "\n"


def make_fake_asar(header_json: bytes, tail: bytes = b"") -> bytes:
    """Build a minimal structurally valid ASAR file for self-tests.

    Mirrors the real @electron/asar header layout: an 8-byte size pickle
    (payload size = 4, header-pickle size), then a header pickle of
    (payload size, header-string size) followed by the header JSON string,
    padded to a 4-byte boundary, then arbitrary tail bytes.
    """
    header_string_size = len(header_json)
    header_payload_size = 4 + header_string_size
    header_pickle = (
        struct.pack("<II", header_payload_size, header_string_size) + header_json
    )
    header_pickle += b"\x00" * ((-len(header_pickle)) % 4)
    return struct.pack("<II", 4, len(header_pickle)) + header_pickle + tail


def _write_fake_asar(path: Path, header_json: bytes, tail: bytes) -> str:
    path.write_bytes(make_fake_asar(header_json, tail))
    return asar_header_hash(path)


def run_self_tests() -> int:
    """Run the installer's built-in unit tests; never touches the app."""

    def valid_default_config() -> None:
        validate_provider_config(DEFAULT_PROVIDER_CONFIG)
        validate_provider_config({**DEFAULT_PROVIDER_CONFIG, "model_providers": {}})

    def config_version_must_be_integer_1() -> None:
        for bad in (True, False, 1.0, "1", None):
            _expect_patch_error(
                f"version {bad!r}",
                lambda bad=bad: validate_provider_config(
                    {**DEFAULT_PROVIDER_CONFIG, "version": bad}
                ),
            )

    def config_requires_non_empty_providers() -> None:
        _expect_patch_error(
            "empty providers",
            lambda: validate_provider_config(
                {**DEFAULT_PROVIDER_CONFIG, "providers": []}
            ),
        )
        _expect_patch_error(
            "missing providers",
            lambda: validate_provider_config(
                {"version": 1, "default_provider": "openai"}
            ),
        )

    def config_rejects_unhashable_default_provider() -> None:
        _expect_patch_error(
            "list default_provider",
            lambda: validate_provider_config(
                {**DEFAULT_PROVIDER_CONFIG, "default_provider": ["openai"]}
            ),
        )
        _expect_patch_error(
            "dict default_provider",
            lambda: validate_provider_config(
                {**DEFAULT_PROVIDER_CONFIG, "default_provider": {"id": "openai"}}
            ),
        )

    def config_rejects_bad_provider_entries() -> None:
        providers = [
            *DEFAULT_PROVIDER_CONFIG["providers"],
            {"id": "openai", "label": "dup", "description": ""},
        ]
        _expect_patch_error(
            "duplicate provider id",
            lambda: validate_provider_config(
                {**DEFAULT_PROVIDER_CONFIG, "providers": providers}
            ),
        )
        _expect_patch_error(
            "empty provider id",
            lambda: validate_provider_config(
                {
                    **DEFAULT_PROVIDER_CONFIG,
                    "providers": [{"id": "  ", "label": "x", "description": ""}],
                }
            ),
        )
        _expect_patch_error(
            "blank provider label",
            lambda: validate_provider_config(
                {
                    **DEFAULT_PROVIDER_CONFIG,
                    "providers": [{"id": "p", "label": " ", "description": ""}],
                }
            ),
        )

    def config_rejects_unhashable_mapping_values() -> None:
        _expect_patch_error(
            "list mapping value",
            lambda: validate_provider_config(
                {**DEFAULT_PROVIDER_CONFIG, "model_providers": {"a/b": ["openrouter"]}}
            ),
        )
        _expect_patch_error(
            "unknown mapping provider",
            lambda: validate_provider_config(
                {**DEFAULT_PROVIDER_CONFIG, "model_providers": {"a/b": "nope"}}
            ),
        )
        _expect_patch_error(
            "whitespace-padded mapping provider (JS parity)",
            lambda: validate_provider_config(
                {**DEFAULT_PROVIDER_CONFIG, "model_providers": {"a/b": "openrouter "}}
            ),
        )

    def config_trims_default_provider_like_js() -> None:
        validate_provider_config(
            {**DEFAULT_PROVIDER_CONFIG, "default_provider": " openai "}
        )
        _expect_patch_error(
            "blank default_provider",
            lambda: validate_provider_config(
                {**DEFAULT_PROVIDER_CONFIG, "default_provider": "  "}
            ),
        )

    def config_lifecycle_states() -> None:
        with tempfile.TemporaryDirectory(prefix="chatgpt-self-test-") as temporary:
            config = Path(temporary) / "desktop-model-providers.json"
            assert check_provider_config(config, False) == "create"
            config.write_text("", encoding="utf-8")
            assert check_provider_config(config, False) == "create"
            config.write_text("{not valid json", encoding="utf-8")
            _expect_patch_error(
                "invalid keep",
                lambda: check_provider_config(config, False),
            )
            # --overwrite-config must repair malformed JSON, not reject it.
            assert check_provider_config(config, True) == "replace"
            write_provider_config(config)
            assert check_provider_config(config, False) == "keep"
            mode = config.stat().st_mode & 0o777
            assert mode == 0o600, oct(mode)
            data = json.loads(config.read_text(encoding="utf-8"))
            assert data == DEFAULT_PROVIDER_CONFIG

    def render_unified_diff_applies_a_hunk() -> None:
        diff = "\n".join(["@@ -1,3 +1,4 @@", " alpha", " beta", "+gamma", " delta"])
        rendered = render_unified_diff("alpha\nbeta\ndelta\n", diff, "fixture.js")
        assert rendered == "alpha\nbeta\ngamma\ndelta\n", rendered

    def render_unified_diff_preserves_trailing_newline_state() -> None:
        diff = "\n".join(["@@ -1,2 +1,3 @@", " a", "+b", " c"])
        assert render_unified_diff("a\nc", diff, "f.js") == "a\nb\nc"
        assert render_unified_diff("a\nc\n", diff, "f.js") == "a\nb\nc\n"

    def render_unified_diff_rejects_ambiguous_or_absent_context() -> None:
        diff = "\n".join(["@@ -1,2 +1,3 @@", " a", "+b", " c"])
        _expect_patch_error(
            "duplicate context",
            lambda: render_unified_diff("a\nc\na\nc\n", diff, "f.js"),
        )
        _expect_patch_error(
            "missing context",
            lambda: render_unified_diff("x\ny\n", diff, "f.js"),
        )

    def render_unified_diff_handles_anchor_hunks() -> None:
        diff = "\n".join(["@@ -2,2 +2,2 @@", " b", " c"])
        assert render_unified_diff("a\nb\nc\n", diff, "f.js") == "a\nb\nc\n"

    def parse_hunks_validates_diff_structure() -> None:
        _expect_patch_error(
            "malformed hunk line",
            lambda: parse_hunks("@@ -1,2 +1,2 @@\nnot-a-diff-line\n"),
        )
        _expect_patch_error("no hunks", lambda: parse_hunks("plain text\n"))
        hunks = parse_hunks("@@ -1,2 +1,2 @@\n a\n+b\n@@ -5,1 +6,1 @@\n-c\n+d\n")
        assert len(hunks) == 2 and all(hunks)

    def derive_versioned_diff_enforces_occurrence_counts() -> None:
        try:
            derive_versioned_diff("a b a", (("a", "z", 1),))
        except RuntimeError:
            pass
        else:
            raise AssertionError("expected RuntimeError for wrong occurrence count")
        assert derive_versioned_diff("a b a", (("a", "z", 2),)) == "z b z"

    def patch_variants_are_well_formed() -> None:
        for name, central_diff, picker_diff in PATCH_VARIANTS:
            for label, diff in (("central", central_diff), ("picker", picker_diff)):
                hunks = parse_hunks(diff)
                assert hunks, f"{name} {label}: no hunks"
                changed = any(line[0] in "+-" for hunk in hunks for line in hunk)
                assert changed, f"{name} {label}: no changed lines"

    def synthetic_fixtures_apply_uniquely_and_reject_repeats() -> None:
        with tempfile.TemporaryDirectory(prefix="chatgpt-self-test-") as temporary:
            work = Path(temporary)
            for index, (name, central_diff, picker_diff) in enumerate(PATCH_VARIANTS):
                central = work / f"central-{index}.js"
                picker = work / f"picker-{index}.js"
                central.write_text(
                    build_synthetic_source(central_diff), encoding="utf-8"
                )
                picker.write_text(
                    build_synthetic_source(picker_diff), encoding="utf-8"
                )
                matched = apply_supported_patch_variant(central, picker)
                assert matched == name, f"expected {name!r}, got {matched!r}"
                _expect_patch_error(
                    f"repeat application of {name}",
                    lambda: apply_supported_patch_variant(central, picker),
                )

    def unique_candidate_requires_exactly_one_match() -> None:
        with tempfile.TemporaryDirectory(prefix="chatgpt-self-test-") as temporary:
            assets = Path(temporary)
            (assets / "a.js").write_text("needle one", encoding="utf-8")
            (assets / "b.js").write_text("nothing", encoding="utf-8")
            found = unique_candidate(assets, ("needle", "one"), "fixture")
            assert found == assets / "a.js"
            (assets / "c.js").write_text("needle one too", encoding="utf-8")
            _expect_patch_error(
                "ambiguous bundle",
                lambda: unique_candidate(assets, ("needle", "one"), "fixture"),
            )
            (assets / "c.js").unlink()
            _expect_patch_error(
                "missing bundle",
                lambda: unique_candidate(assets, ("needle", "absent"), "fixture"),
            )

    def contains_marker_spans_chunk_boundaries() -> None:
        marker = PATCH_MARKER
        chunk = 4 * 1024 * 1024
        with tempfile.TemporaryDirectory(prefix="chatgpt-self-test-") as temporary:
            blob = Path(temporary) / "blob.bin"
            with blob.open("wb") as handle:
                handle.write(b"x" * (chunk - len(marker) + 2))
                handle.write(marker)
                handle.write(b"y" * 8)
            assert contains_marker(blob) is True
            assert contains_marker(blob, b"absent-marker") is False

    def app_path_variants_normalizes_tmp_and_var() -> None:
        variants = app_path_variants(Path("/tmp/a.app"))
        assert {"/tmp/a.app", "/private/tmp/a.app"} <= set(variants)
        assert "/private/var/x.app" in app_path_variants(Path("/var/x.app"))

    def ready_verification_rejects_broken_states() -> None:
        header = b'{"files":{}}'
        v3 = PATCH_MARKER
        v2 = LEGACY_PATCH_MARKER
        picker = b"CodexCustomProviderPickerSection"
        with tempfile.TemporaryDirectory(prefix="chatgpt-self-test-") as temporary:
            asar = Path(temporary) / "app.asar"
            good_hash = _write_fake_asar(asar, header, v3 + picker)
            good_info = {
                "ElectronAsarIntegrity": {"Resources/app.asar": {"hash": good_hash}}
            }
            verify_installed_bundle(asar, good_info)

            _write_fake_asar(asar, header, v3 + picker)
            bad_info = {
                "ElectronAsarIntegrity": {"Resources/app.asar": {"hash": "0" * 64}}
            }
            _expect_patch_error(
                "hash mismatch",
                lambda: verify_installed_bundle(asar, bad_info),
            )

            _write_fake_asar(asar, header, v3 + v2 + picker)
            mixed_hash = asar_header_hash(asar)
            mixed_info = {
                "ElectronAsarIntegrity": {"Resources/app.asar": {"hash": mixed_hash}}
            }
            _expect_patch_error(
                "mixed V3+V2 markers",
                lambda: verify_installed_bundle(asar, mixed_info),
            )

            _write_fake_asar(asar, header, v3)
            no_picker_hash = asar_header_hash(asar)
            no_picker_info = {
                "ElectronAsarIntegrity": {"Resources/app.asar": {"hash": no_picker_hash}}
            }
            _expect_patch_error(
                "missing picker symbol",
                lambda: verify_installed_bundle(asar, no_picker_info),
            )

    def codesign_failure_becomes_patch_error() -> None:
        header = b'{"files":{}}'
        with tempfile.TemporaryDirectory(prefix="chatgpt-self-test-") as temporary:
            root = Path(temporary)
            asar = root / "app.asar"
            good_hash = _write_fake_asar(
                asar, header, PATCH_MARKER + b"CodexCustomProviderPickerSection"
            )
            info = {
                "ElectronAsarIntegrity": {"Resources/app.asar": {"hash": good_hash}}
            }
            app_dir = root / "Fake.app"
            original_run = subprocess.run

            def failing_run(*args, **kwargs):
                raise subprocess.CalledProcessError(
                    1, args[0] if args else "codesign"
                )

            subprocess.run = failing_run
            try:
                _expect_patch_error(
                    "codesign failure",
                    lambda: verify_installed_state(app_dir, asar, info),
                )
            finally:
                subprocess.run = original_run

    def restore_backup_happy_path() -> None:
        if sys.platform != "darwin":
            return
        with tempfile.TemporaryDirectory(prefix="chatgpt-self-test-") as temporary:
            root = Path(temporary)
            backup = root / "ChatGPT-1.0-build-1-00000000-000000.app"
            resources = backup / "Contents" / "Resources"
            resources.mkdir(parents=True)
            (resources / "app.asar").write_bytes(b"backup-asar")
            app = root / "ChatGPT.app"
            (app / "Contents" / "Resources").mkdir(parents=True)
            (app / "Contents" / "Resources" / "app.asar").write_bytes(
                b"broken-asar"
            )
            failed_copy = restore_backup(app, backup)
            restored = (app / "Contents" / "Resources" / "app.asar").read_bytes()
            assert restored == b"backup-asar"
            assert failed_copy.exists()
            kept = (failed_copy / "Contents" / "Resources" / "app.asar").read_bytes()
            assert kept == b"broken-asar"

    def restore_backup_failure_reports_actionable_paths() -> None:
        if sys.platform != "darwin":
            return
        with tempfile.TemporaryDirectory(prefix="chatgpt-self-test-") as temporary:
            root = Path(temporary)
            backup = root / "ChatGPT-backup.app"
            resources = backup / "Contents" / "Resources"
            resources.mkdir(parents=True)
            (resources / "app.asar").write_bytes(b"backup-asar")
            app = root / "ChatGPT.app"
            (app / "Contents" / "Resources").mkdir(parents=True)
            (app / "Contents" / "Resources" / "app.asar").write_bytes(
                b"broken-asar"
            )

            original_replace = os.replace
            call_count = {"n": 0}

            def failing_swap(src, dst):
                call_count["n"] += 1
                if call_count["n"] == 2:  # staging -> app swap
                    raise OSError("simulated swap failure")
                return original_replace(src, dst)

            os.replace = failing_swap
            try:
                try:
                    restore_backup(app, backup)
                except PatchError as exc:
                    message = str(exc)
                    assert str(backup) in message
                    assert "patch-failed" in message
                    assert "restore-staging" in message
                    assert "moved back into place" in message
                else:
                    raise AssertionError("expected PatchError from failed swap")
            finally:
                os.replace = original_replace
            assert app.exists()
            staging_left = [
                p for p in app.parent.iterdir() if "restore-staging" in p.name
            ]
            assert not staging_left, staging_left

    def restore_backup_move_back_failure_reports_missing_app() -> None:
        if sys.platform != "darwin":
            return
        with tempfile.TemporaryDirectory(prefix="chatgpt-self-test-") as temporary:
            root = Path(temporary)
            backup = root / "ChatGPT-backup.app"
            resources = backup / "Contents" / "Resources"
            resources.mkdir(parents=True)
            (resources / "app.asar").write_bytes(b"backup-asar")
            app = root / "ChatGPT.app"
            (app / "Contents" / "Resources").mkdir(parents=True)
            (app / "Contents" / "Resources" / "app.asar").write_bytes(
                b"broken-asar"
            )

            original_replace = os.replace
            call_count = {"n": 0}

            def failing_swap(src, dst):
                call_count["n"] += 1
                if call_count["n"] in (2, 3):  # staging->app and failed_copy->app
                    raise OSError("simulated swap failure")
                return original_replace(src, dst)

            os.replace = failing_swap
            try:
                try:
                    restore_backup(app, backup)
                except PatchError as exc:
                    assert "may currently be missing" in str(exc)
                else:
                    raise AssertionError("expected PatchError from failed restore")
            finally:
                os.replace = original_replace

    def ownership_policy_assigns_invoking_user_under_home() -> None:
        with tempfile.TemporaryDirectory(prefix="chatgpt-self-test-") as temporary:
            home = Path(temporary) / "home"
            fake_entry = types.SimpleNamespace(
                pw_uid=501, pw_gid=20, pw_dir=str(home)
            )
            original_env = dict(os.environ)
            original_geteuid = os.geteuid
            original_getpwnam = pwd.getpwnam
            os.environ["SUDO_USER"] = "testuser"
            os.geteuid = lambda: 0
            pwd.getpwnam = lambda name: fake_entry
            try:
                config = home / ".codex" / "desktop-model-providers.json"
                assert resolve_config_owner(config) == (501, 20)
            finally:
                os.geteuid = original_geteuid
                pwd.getpwnam = original_getpwnam
                os.environ.clear()
                os.environ.update(original_env)

    def ownership_policy_preserves_custom_config_owner() -> None:
        with tempfile.TemporaryDirectory(prefix="chatgpt-self-test-") as temporary:
            custom = Path(temporary) / "custom" / "model-providers.json"
            custom.parent.mkdir(parents=True)
            custom.write_text("{}", encoding="utf-8")
            original_geteuid = os.geteuid
            os.geteuid = lambda: 0
            try:
                owner = resolve_config_owner(custom)
            finally:
                os.geteuid = original_geteuid
            stat_result = custom.stat()
            assert owner == (stat_result.st_uid, stat_result.st_gid), owner

    def ownership_policy_keeps_root_for_missing_custom_config() -> None:
        with tempfile.TemporaryDirectory(prefix="chatgpt-self-test-") as temporary:
            custom = Path(temporary) / "custom" / "model-providers.json"
            original_geteuid = os.geteuid
            os.geteuid = lambda: 0
            try:
                assert resolve_config_owner(custom) is None
            finally:
                os.geteuid = original_geteuid

    def ownership_chown_failure_raises_patch_error() -> None:
        with tempfile.TemporaryDirectory(prefix="chatgpt-self-test-") as temporary:
            home = Path(temporary) / "home"
            fake_entry = types.SimpleNamespace(
                pw_uid=501, pw_gid=20, pw_dir=str(home)
            )
            original_env = dict(os.environ)
            original_geteuid = os.geteuid
            original_getpwnam = pwd.getpwnam
            original_chown = os.chown
            os.environ["SUDO_USER"] = "testuser"
            os.geteuid = lambda: 0
            pwd.getpwnam = lambda name: fake_entry

            def failing_chown(path, uid, gid):
                raise OSError("simulated chown failure")

            os.chown = failing_chown
            try:
                _expect_patch_error(
                    "chown failure",
                    lambda: atomic_write_json(
                        home / "desktop-model-providers.json",
                        DEFAULT_PROVIDER_CONFIG,
                    ),
                )
            finally:
                os.geteuid = original_geteuid
                pwd.getpwnam = original_getpwnam
                os.chown = original_chown
                os.environ.clear()
                os.environ.update(original_env)

    tests = [
        ("valid default config passes validation", valid_default_config),
        ("config version must be integer 1", config_version_must_be_integer_1),
        ("config requires non-empty providers", config_requires_non_empty_providers),
        (
            "config rejects unhashable default_provider",
            config_rejects_unhashable_default_provider,
        ),
        ("config rejects bad provider entries", config_rejects_bad_provider_entries),
        (
            "config rejects unhashable mapping values",
            config_rejects_unhashable_mapping_values,
        ),
        (
            "config trims default_provider like injected JS",
            config_trims_default_provider_like_js,
        ),
        ("config lifecycle states (keep/create/replace)", config_lifecycle_states),
        ("render_unified_diff applies a hunk", render_unified_diff_applies_a_hunk),
        (
            "render_unified_diff preserves trailing newline state",
            render_unified_diff_preserves_trailing_newline_state,
        ),
        (
            "render_unified_diff rejects ambiguous/absent context",
            render_unified_diff_rejects_ambiguous_or_absent_context,
        ),
        ("render_unified_diff handles anchor hunks", render_unified_diff_handles_anchor_hunks),
        ("parse_hunks validates diff structure", parse_hunks_validates_diff_structure),
        (
            "derive_versioned_diff enforces occurrence counts",
            derive_versioned_diff_enforces_occurrence_counts,
        ),
        ("every patch variant parses", patch_variants_are_well_formed),
        (
            "synthetic fixtures apply uniquely and reject repeats",
            synthetic_fixtures_apply_uniquely_and_reject_repeats,
        ),
        (
            "unique_candidate requires exactly one match",
            unique_candidate_requires_exactly_one_match,
        ),
        ("contains_marker spans chunk boundaries", contains_marker_spans_chunk_boundaries),
        (
            "app_path_variants normalizes tmp/var paths",
            app_path_variants_normalizes_tmp_and_var,
        ),
        (
            "README bundle verification rejects broken states",
            ready_verification_rejects_broken_states,
        ),
        ("codesign failure becomes PatchError", codesign_failure_becomes_patch_error),
        ("restore backup happy path", restore_backup_happy_path),
        (
            "restore failure reports actionable paths",
            restore_backup_failure_reports_actionable_paths,
        ),
        (
            "restore move-back failure reports missing app",
            restore_backup_move_back_failure_reports_missing_app,
        ),
        (
            "ownership policy: invoking user under home",
            ownership_policy_assigns_invoking_user_under_home,
        ),
        (
            "ownership policy: existing custom config preserves owner",
            ownership_policy_preserves_custom_config_owner,
        ),
        (
            "ownership policy: missing custom config stays root-owned",
            ownership_policy_keeps_root_for_missing_custom_config,
        ),
        (
            "ownership policy: chown failure raises PatchError",
            ownership_chown_failure_raises_patch_error,
        ),
    ]

    terminal_heading("Self-test")
    failures: list[tuple[str, str]] = []
    for name, test in tests:
        try:
            test()
        except Exception as exc:
            failures.append((name, str(exc)))
            terminal_status("FAIL", name, "31", detail=exc)
        else:
            terminal_status("PASS", name, "32")
    if failures:
        terminal_panel(
            "Self-test",
            f"{len(failures)} of {len(tests)} self-tests failed.",
            "31",
        )
        return 1
    terminal_status("OK", f"All {len(tests)} self-tests passed.", "32")
    return 0


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_tests()
    try:
        app = args.app.expanduser().resolve()
        patch_app(
            app,
            args.config.expanduser().resolve(),
            args.backup_dir.expanduser().resolve(),
            args.overwrite_config,
            args.allow_running,
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
