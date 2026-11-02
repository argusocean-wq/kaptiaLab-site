'use strict';

const vscode = require('vscode');
const http = require('http');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

const HOST = '127.0.0.1';
const PORT = 43871;
let serverProcess;

function appRoot() {
  const base = process.env.LOCALAPPDATA || process.env.USERPROFILE;
  return path.join(base, 'Kaptia');
}

function requestJson(route, method, payload, timeoutMs = 180000) {
  return new Promise((resolve, reject) => {
    const body = payload ? Buffer.from(JSON.stringify(payload), 'utf8') : null;
    const req = http.request({
      hostname: HOST, port: PORT, path: route, method,
      timeout: timeoutMs,
      headers: body ? {
        'Content-Type': 'application/json',
        'Content-Length': body.length
      } : {}
    }, (res) => {
      const chunks = [];
      res.on('data', chunk => chunks.push(chunk));
      res.on('end', () => {
        let parsed;
        try { parsed = JSON.parse(Buffer.concat(chunks).toString('utf8')); }
        catch (_) { return reject(new Error('Kaptia 回傳了無法解析的資料。')); }
        if (res.statusCode < 200 || res.statusCode >= 300) {
          return reject(new Error(parsed.message || parsed.error || ('HTTP ' + res.statusCode)));
        }
        resolve(parsed);
      });
    });
    req.on('timeout', () => req.destroy(new Error('等待 Kaptia 回覆逾時。')));
    req.on('error', reject);
    if (body) req.write(body);
    req.end();
  });
}

async function ensureServer() {
  try {
    await requestJson('/health', 'GET', null, 1200);
    return;
  } catch (_) {}
  const root = appRoot();
  const python = path.join(root, '.venv', 'Scripts', 'python.exe');
  const script = path.join(root, 'app', 'scripts', 'kaptia_context_server.py');
  const checkpoint = path.join(root, 'model-data', 'kaptia-scratch-pretrain', 'best_checkpoint.pt');
  if (!fs.existsSync(python) || !fs.existsSync(script) || !fs.existsSync(checkpoint)) {
    throw new Error('找不到 Kaptia 本機執行環境或 scratch checkpoint。請先完成 Kaptia 安裝與起步訓練。');
  }
  if (!serverProcess || serverProcess.exitCode !== null) {
    serverProcess = spawn(python, [script], {
      cwd: path.join(root, 'app'),
      windowsHide: true,
      detached: true,
      stdio: 'ignore',
      env: { ...process.env, KAPTIA_SCRATCH_CHECKPOINT: checkpoint }
    });
    serverProcess.unref();
  }
  const deadline = Date.now() + 15000;
  let lastError;
  while (Date.now() < deadline) {
    await new Promise(resolve => setTimeout(resolve, 500));
    try {
      await requestJson('/health', 'GET', null, 1500);
      return;
    } catch (err) { lastError = err; }
  }
  throw new Error('Kaptia 本機模型服務未能啟動。' + (lastError ? ' ' + lastError.message : ''));
}

function activate(context) {
  const disposable = vscode.commands.registerCommand('kaptia.askAboutSelection', async () => {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
      vscode.window.showInformationMessage('請先在程式碼編輯器中選取一段內容。');
      return;
    }
    const selection = editor.selection;
    if (selection.isEmpty) {
      vscode.window.showInformationMessage('請先選取想詢問 Kaptia 的程式碼，再按滑鼠右鍵。');
      return;
    }
    const document = editor.document;
    const start = Math.max(0, selection.start.line - 12);
    const end = Math.min(document.lineCount - 1, selection.end.line + 12);
    const before = document.getText(new vscode.Range(start, 0, selection.start.line, 0));
    const after = document.getText(new vscode.Range(selection.end.line, selection.end.character, end, document.lineAt(end).text.length));
    const code = document.getText(selection);
    const settings = vscode.workspace.getConfiguration('kaptia');
    const assistant = settings.get('defaultAssistant', 'Kaptia');
    const question = settings.get('defaultQuestion', '請用繁體中文分析選取內容，說明用途、執行流程、重點與可能問題。');
    if (!String(question).trim()) {
      vscode.window.showErrorMessage('Kaptia 的預設問題是空白；請到設定中填寫 kaptia.defaultQuestion。');
      return;
    }

    await vscode.window.withProgress({
      location: vscode.ProgressLocation.Notification,
      title: 'Kaptia 正在分析選取的程式碼…',
      cancellable: false
    }, async () => {
      try {
        await ensureServer();
        const result = await requestJson('/ask', 'POST', {
          question: '請以「' + assistant + '」的預設助手角色回答：' + question,
          selection: code,
          before,
          after,
          fileName: path.basename(document.fileName)
        });
        const panel = vscode.window.createWebviewPanel(
          'kaptiaAnswer', '問問 Kaptia', vscode.ViewColumn.Beside,
          { enableScripts: false, retainContextWhenHidden: false }
        );
        const esc = (s) => String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        panel.webview.html = `<!doctype html><html lang="zh-Hant"><meta charset="utf-8">
          <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline';">
          <body style="font-family:system-ui;padding:22px;background:#111;color:#eee;line-height:1.65">
          <h2>問問 Kaptia</h2><p style="color:#aaa">檔案：${esc(path.basename(document.fileName))}</p>
          <pre style="white-space:pre-wrap;background:#202020;padding:12px;border-radius:8px">${esc(code.slice(0,6000))}</pre>
          <h3>回答</h3><p style="white-space:pre-wrap">${esc(result.answer || 'Kaptia 沒有產生回答。')}</p>
          <hr><p style="color:#aaa;font-size:12px">${esc(result.warning || '本機 scratch 模型實驗功能；答案可能錯誤，請自行核對。')}</p>
          </body></html>`;
      } catch (err) {
        vscode.window.showErrorMessage('問問 Kaptia 失敗：' + err.message);
      }
    });
  });
  context.subscriptions.push(disposable);
}

function deactivate() {}

module.exports = { activate, deactivate };
