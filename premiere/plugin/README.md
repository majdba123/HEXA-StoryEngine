# HEXA Premiere Panel

The panel is the Premiere-facing controller for StoryEngine.

Development flow:

1. Install the Python engine and run `hexa serve`.
2. Load `premiere/plugin/manifest.json` in Adobe UXP Developer Tool.
3. Open the HEXA panel in Premiere Pro.
4. Choose a Final Package folder or ZIP and narration audio.
5. Press **Generate**.
6. After completion, press **Add to Timeline**.

The panel does not run AI/video processing inside Premiere. Heavy processing stays in the local engine, keeping the host responsive.

For production macOS packaging, configure the loopback service with TLS (`hexa serve --ssl-certfile ... --ssl-keyfile ...`) and keep the panel pointed at the HTTPS loopback endpoint.
