# Kaptia editor context menu

Select code in Cursor or VS Code, right-click, then choose **問問 Kaptia**. Kaptia sends the selected code and a limited amount of surrounding text to its local-only service at `127.0.0.1:43871`. No source is sent to a cloud service.

The Windows installer tries to install this extension into any detected Cursor and VS Code installations. If no editor is detected, it saves `Kaptia-Ask-Context.vsix` under the Kaptia installation folder for manual installation through the editor's Extensions menu.

This extension uses only Kaptia's own scratch checkpoint. It does not use an external model. The current bootstrap model is very small and may be unable to explain code reliably; the UI labels the answer as experimental and warns users to verify it.

## Current scope

- Cursor / VS Code extension host.
- Selected code + limited neighboring context.
- User-provided question and answer in a side panel.
- Explanation only: it does not edit files or apply code changes automatically.
