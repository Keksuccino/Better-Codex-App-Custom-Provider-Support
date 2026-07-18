# Better Codex App Custom Provider Support

An unofficial patch for the macOS ChatGPT/Codex desktop app that adds per-task model-provider selection without requiring you to sign out of your ChatGPT account.

The patch:

- Adds a provider section to the model menu.
- Sends the selected provider when a new task starts.
- Maps model IDs to providers automatically.
- Keeps tasks from all configured providers visible.
- Keeps the normal ChatGPT login active for OpenAI models.

This project currently supports **macOS only**.

## Requirements

- macOS
- ChatGPT installed at `/Applications/ChatGPT.app`
- Python 3.9 or newer
- Node.js with `npx`

## Install

```bash
git clone https://github.com/Keksuccino/Better-Codex-App-Custom-Provider-Support.git
cd Better-Codex-App-Custom-Provider-Support
python3 patch_chatgpt_providers.py
```

The installer closes processes belonging to the target app, creates a complete backup, patches `app.asar`, updates Electron's ASAR integrity metadata, and applies an ad-hoc signature.

Run `python3 patch_chatgpt_providers.py --help` to see alternate app, config, and backup paths.

## Configure a custom provider

Custom Codex providers belong in `~/.codex/config.toml`. Provider IDs such as `openrouter` are referenced by the patch configuration later.

Example OpenRouter provider:

```toml
[model_providers.openrouter]
name = "OpenRouter"
base_url = "https://openrouter.ai/api/v1"
wire_api = "responses"

[model_providers.openrouter.auth]
command = "/usr/bin/security"
args = ["find-generic-password", "-a", "YOUR_MACOS_USERNAME", "-s", "Codex OpenRouter API Key", "-w"]
timeout_ms = 5000
refresh_interval_ms = 0
```

Replace `YOUR_MACOS_USERNAME`, then add or update the API key in macOS Keychain. The command prompts for the key instead of placing it in shell history:

```bash
security add-generic-password -U -a "$USER" -s "Codex OpenRouter API Key" -w
```

Codex also supports environment-variable authentication with `env_key`. Do not combine `env_key` with a `[model_providers.<id>.auth]` section. For all authentication methods and provider options, see the [Codex custom model provider documentation](https://learn.chatgpt.com/docs/config-file/config-advanced#custom-model-providers).

Do not set a global `model_provider` if OpenAI and custom providers should coexist in the desktop app. The patch selects the provider when each new task starts.

## Add custom models to Codex

Codex loads custom model metadata from the file configured by `model_catalog_json`.

1. Export the bundled catalog as a starting point:

   ```bash
   mkdir -p ~/.codex/model-catalogs
   codex debug models --bundled > ~/.codex/model-catalogs/custom.json
   ```

2. Add model objects to the top-level `models` array. Copy an existing entry with similar capabilities, then update its model ID, display name, context window, modalities, reasoning levels, and tool support.

   The model ID is the `slug` value. It must match the model ID expected by the provider, for example:

   ```json
   {
     "slug": "moonshotai/kimi-k3",
     "display_name": "Kimi K3 (OpenRouter)",
     "description": "MoonshotAI Kimi K3 through OpenRouter."
   }
   ```

   Keep the remaining required fields from the copied entry and adjust them to the model's real capabilities. Do not advertise unsupported tools, modalities, or context-window sizes.

3. Point Codex at the catalog in `~/.codex/config.toml`:

   ```toml
   model_catalog_json = "/Users/your-name/.codex/model-catalogs/custom.json"
   ```

4. Restart the app after changing `model_catalog_json` or the model catalog.

Use `codex debug models` to inspect the effective catalog Codex sees.

## Configure the patched provider menu

The installer creates:

```text
~/.codex/desktop-model-providers.json
```

Example:

```json
{
  "version": 1,
  "default_provider": "openai",
  "providers": [
    {
      "id": "openai",
      "label": "ChatGPT / OpenAI",
      "description": "Uses your signed-in ChatGPT account"
    },
    {
      "id": "openrouter",
      "label": "OpenRouter",
      "description": "Uses [model_providers.openrouter] from config.toml"
    }
  ],
  "model_providers": {
    "moonshotai/kimi-k3": "openrouter",
    "x-ai/grok-4.5": "openrouter",
    "anthropic/claude-fable-5": "openrouter"
  }
}
```

- `providers` defines the providers displayed in the app menu.
- `model_providers` maps exact model slugs to provider IDs for Automatic mode.
- `default_provider` handles models without an explicit mapping.
- Every custom provider ID must match a `[model_providers.<id>]` section in `config.toml`.
- API keys do not belong in this JSON file.

The app reloads this file when the provider menu opens and before a new task starts. Repatching is not required after editing it.

## Updates and recovery

ChatGPT updates replace the patch. Run the installer again after an update.

The installer is not tied to a fixed app version or archive hash. It patches compatible source structures and stops before modifying the installed app if an update changes the relevant code.

Backups are stored by default in:

```text
~/Applications/ChatGPT Patch Backups/
```

This is an unofficial modification and is not affiliated with or supported by OpenAI.
