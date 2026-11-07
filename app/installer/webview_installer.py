# Test artifact builds are uploaded only to Actions and are not published as releases.
"""PyWebView bootstrapper with pinned-payload verification."""
from __future__ import annotations
import hashlib,json,os,re,shutil,subprocess,sys,threading,zipfile
from pathlib import Path
import webview
REPO_ROOT=Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:sys.path.insert(0,str(REPO_ROOT))
HTML_PATH=Path(getattr(sys,"_MEIPASS",REPO_ROOT))/"ui"/"web"/"installer.html"
from installer.hardware_profile import detect_hardware
from scripts.kaptia_locale import get_language, set_language
try:
 from installer.build_info import BUILD_NUMBER, BUILD_TAG, SOURCE_COMMIT, SOURCE_SHA256
except ImportError:
 BUILD_NUMBER, BUILD_TAG, SOURCE_COMMIT, SOURCE_SHA256 = 0, "development", "", ""
ROOT=Path(os.environ.get("LOCALAPPDATA",str(Path.home())))/"Kaptia"
PAYLOAD_ROOT=Path(getattr(sys,"_MEIPASS",REPO_ROOT))/"payload"
EMBEDDED_CORE_ZIP=PAYLOAD_ROOT/"kaptia-core-source.zip"
def _python_candidates():
 candidates=[]
 launcher=shutil.which('py')
 if launcher:
  for version in ('3.11','3.10'):candidates.append([launcher,'-'+version])
 for name in ('python.exe','python3.exe','python','python3'):
  found=shutil.which(name)
  if found:candidates.append([found])
 local=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))
 for base in (local/'Programs'/'Python',Path(os.environ.get('ProgramFiles',r'C:\Program Files'))):
  for version in ('Python311','Python310'):
   exe=base/version/'python.exe'
   if exe.is_file():candidates.append([str(exe)])
 valid=[];seen=set()
 for cmd in candidates:
  key=tuple(cmd)
  if key in seen:continue
  seen.add(key)
  try:
   q=subprocess.run(cmd+['--version'],capture_output=True,text=True,timeout=8)
   if q.returncode==0 and re.search(r'Python 3\.(10|11)\.',q.stdout+q.stderr):
    arch=subprocess.run(cmd+['-c',"import struct;print(struct.calcsize('P')*8)"],capture_output=True,text=True,timeout=8)
    if arch.returncode==0 and arch.stdout.strip()=='64':valid.append(cmd)
  except Exception:pass
 return valid
def _extract_embedded_core(root: Path):
    """Verify and safely extract the core archive embedded in this Setup executable."""
    commit = str(SOURCE_COMMIT or "").lower()
    expected = str(SOURCE_SHA256 or "").lower()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RuntimeError("Setup 缺少有效的核心 commit metadata。")
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise RuntimeError("Setup 缺少有效的核心 SHA-256 metadata。")
    if not EMBEDDED_CORE_ZIP.is_file():
        raise RuntimeError("Setup 內未包含核心套件；請重新下載完整安裝程式。")
    if EMBEDDED_CORE_ZIP.stat().st_size > 2 * 1024 * 1024 * 1024:
        raise RuntimeError("內嵌核心套件超過 2 GiB 安全限制。")

    digest = hashlib.sha256()
    with EMBEDDED_CORE_ZIP.open("rb") as source_file:
        for block in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != expected:
        raise RuntimeError("內嵌核心 SHA-256 不符，已停止安裝。")

    prefix = f"kaptiaLab-core-{commit}"
    root.mkdir(parents=True, exist_ok=True)
    staging = root / (".core-extract-" + commit)
    target = root / prefix
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(EMBEDDED_CORE_ZIP) as archive:
            if archive.testzip():
                raise RuntimeError("核心 ZIP CRC 驗證失敗。")
            infos = archive.infolist()
            if not infos or len(infos) > 20000:
                raise RuntimeError("核心 ZIP 檔案數量不符合安全限制。")
            expanded = sum(item.file_size for item in infos)
            if expanded > 8 * 1024 * 1024 * 1024:
                raise RuntimeError("核心 ZIP 解壓縮容量超過 8 GiB。")
            resolved = staging.resolve()
            for item in infos:
                name = item.filename.replace("\\", "/")
                parts = name.split("/")
                if not name or name.startswith("/") or re.match(r"^[A-Za-z]:", name):
                    raise RuntimeError("核心 ZIP 含不安全路徑：" + item.filename)
                if any(part in (".", "..") for part in parts):
                    raise RuntimeError("核心 ZIP 路徑越界：" + item.filename)
                if any(part == "" for part in parts[:-1]):
                    raise RuntimeError("核心 ZIP 含不安全路徑：" + item.filename)
                destination = (staging / name).resolve()
                if destination != resolved and resolved not in destination.parents:
                    raise RuntimeError("核心 ZIP 路徑越界：" + item.filename)
                mode = (item.external_attr >> 16) & 0o170000
                if mode == 0o120000 or mode not in (0, 0o100000, 0o040000):
                    raise RuntimeError("核心 ZIP 含 symbolic link 或特殊檔案。")
            archive.extractall(staging)

        source = staging / prefix
        if not (source / "README.md").is_file() or not (source / "scripts" / "chat.py").is_file():
            raise RuntimeError("核心 ZIP 結構不完整。")
        if target.exists():
            shutil.rmtree(target)
        source.rename(target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    shutil.rmtree(staging, ignore_errors=True)
    manifest = {
        "schema": 1,
        "build_number": int(BUILD_NUMBER),
        "tag": str(BUILD_TAG),
        "source_commit": commit,
        "core": {"sha256": expected},
    }
    return target, manifest

def _winget_path():
 found=shutil.which('winget')
 if found:return found
 candidate=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'Microsoft'/'WindowsApps'/'winget.exe'
 return str(candidate) if candidate.is_file() else None

class InstallerAPI:
 def __init__(self): self.lock=threading.RLock();self.busy=False;self.language="zh-TW";self.hardware=None
 def _js(self,d):
  try:
   if webview.windows:webview.windows[0].evaluate_js("update("+json.dumps(d,ensure_ascii=False)+")")
  except Exception:pass
 def _update(self,status=None,detail=None,phase=None,progress=None,busy=True,log=None,done=None):
  d={"busy":busy}
  for k,v in (("status",status),("detail",detail),("phase",phase),("progress",progress),("log",log),("done",done)):
   if v is not None:d[k]=v
  if busy:d["thinking"]=status or "Kaptia 正在處理…"
  self._js(d)
 def python_status(self):
  found=_python_candidates()
  return {'installed':bool(found),'version':'Python 3.10 / 3.11 已就緒' if found else '未找到 Python 3.10 / 3.11','can_auto_install':bool(_winget_path())}
 def install_python(self):
  with self.lock:
   if self.busy:return {'ok':False,'error':'安裝程序已在執行'}
   self.busy=True
  threading.Thread(target=self._install_python_worker,daemon=True).start()
  return {'ok':True}
 def _install_python_worker(self):
  try:
   if _python_candidates():
    with self.lock:self.busy=False
    self._js({'pythonReady':True,'log':'已找到相容的 Python，略過下載。'});return
   winget=_winget_path()
   if not winget:raise RuntimeError('此電腦未提供 winget。請更新 Microsoft App Installer，或從 python.org 安裝 Python 3.11 x64 後重新開啟 Setup。')
   self._js({'status':'正在安裝 Python 3.11…','phase':'PYTHON','thinking':'正在透過 Windows 套件管理員安裝 Python 3.11…','busy':True,'log':'winget install Python.Python.3.11（使用者範圍、靜默安裝）'})
   cmd=[winget,'install','--id','Python.Python.3.11','--exact','--scope','user','--silent','--accept-package-agreements','--accept-source-agreements','--disable-interactivity']
   proc=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
   try:output,_=proc.communicate(timeout=900)
   except subprocess.TimeoutExpired:proc.kill();proc.communicate();raise RuntimeError('Python 安裝逾時（15 分鐘）。請確認網路及 Windows 套件管理員狀態。')
   for line in (output or '').splitlines():self._js({'log':line.rstrip()})
   code=proc.returncode
   if code not in (0,3010):raise RuntimeError(f'winget 安裝 Python 失敗（exit code {code}）。')
   if not _python_candidates():raise RuntimeError('安裝程序已結束，但仍找不到 Python 3.10 / 3.11。請重新啟動 Windows 後再試。')
   with self.lock:self.busy=False
   self._js({'pythonReady':True,'status':'Python 安裝完成','detail':'已偵測到相容的 Python 版本，可以開始安裝 Kaptia。','phase':'PYTHON READY','busy':False,'log':'Python 3.11 已安裝並通過版本檢查。'})
  except Exception as e:self._js({'pythonError':f'{type(e).__name__}: {e}','status':'Python 安裝未完成','phase':'PYTHON ERROR','busy':False,'log':f'{type(e).__name__}: {e}'})
  finally:
   with self.lock:self.busy=False
 def scan_hardware(self):
  try:
   self.hardware=detect_hardware();r=self.hardware
   gpu=", ".join(f"{g.get('name')} ({g.get('vram_mb') or '?'} MB)" for g in r.gpus) or "GPU telemetry unavailable"
   return {"summary":f"{r.os_name} · {r.architecture} · {r.cpu_logical_cores} CPU threads · RAM {r.ram_total_gb} GB · {gpu} · {r.profile_label}"}
  except Exception as e:return {"summary":f"掃描失敗，使用安全預設：{type(e).__name__}: {e}"}
 def start_install(self,language="zh-TW"):
  with self.lock:
   if self.busy:return {"ok":False,"error":"安裝程序已在執行"}
   self.busy=True
  self.language=language if language in ("zh-TW","zh-CN","en","ja","ko") else "zh-TW"
  os.environ["KAPTIA_LANG"]=self.language
  try:set_language(self.language)
  except Exception:pass
  threading.Thread(target=self._install,daemon=True).start();return {"ok":True}
 def _run(self,cmd,cwd,phase,label):
  self._update(label,phase=phase,log="$ "+" ".join(map(str,cmd)))
  p=subprocess.Popen(cmd,cwd=str(cwd),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding="utf-8",errors="replace",bufsize=1,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
  for line in p.stdout:self._js({"log":line.rstrip()})
  code=p.wait()
  if code:raise RuntimeError(f"{label} 失敗（exit code {code}）")
 def _install(self):
  try:
   ROOT.mkdir(parents=True,exist_ok=True);self._update("正在驗證核心套件…",phase="VERIFY",progress=3)
   source,core_manifest=_extract_embedded_core(ROOT)
   app=ROOT/"app";shutil.rmtree(app,ignore_errors=True);source.rename(app)
   self._update("正在尋找 Python 3.10 / 3.11…",phase="RUNTIME",progress=10)
   candidates=_python_candidates()
   py=candidates[0] if candidates else None
   if py is None:raise RuntimeError('找不到 Python 3.10 / 3.11。請重新開啟 Setup，選擇安裝 Python，或從 python.org 安裝後重試。')
   arch=subprocess.run(py+['-c',"import struct;print(struct.calcsize('P')*8)"],capture_output=True,text=True,timeout=10)
   if arch.returncode!=0 or arch.stdout.strip()!='64':raise RuntimeError('目前 Python 不是 64 位元版本，請安裝 Python 3.11 x64。')
   venv=ROOT/".venv";vp=venv/"Scripts"/"python.exe"
   if not vp.is_file():self._run(py+["-m","venv",str(venv)],app,"ENVIRONMENT","建立獨立 Python 環境")
   self._update("正在安裝本機執行環境…",phase="DEPENDENCIES",progress=18)
   self._run([str(vp),"-m","pip","install","--upgrade","pip"],app,"DEPENDENCIES","更新 pip")
   self._run([str(vp),"-m","pip","install","-r",str(app/"requirements.txt")],app,"DEPENDENCIES","安裝 AI 助手執行環境")
   self._update("正在分析硬體…",phase="HARDWARE",progress=55)
   self.hardware=self.hardware or detect_hardware()
   (ROOT/"hardware-report.json").write_text(json.dumps(self.hardware.to_dict(),ensure_ascii=False,indent=2),encoding="utf-8")
   settings=ROOT/"settings.json"
   if not settings.exists():
    settings.write_text(json.dumps({"model_id":"Qwen/Qwen3-8B","quantization":"4bit","auto_updates":True},ensure_ascii=False,indent=2),encoding="utf-8")
   from datetime import datetime
   (ROOT/"version.json").write_text(json.dumps({"build_number":core_manifest["build_number"],"build_tag":core_manifest["tag"],"source_commit":core_manifest["source_commit"],"installed_at":datetime.now().astimezone().isoformat()},ensure_ascii=False,indent=2),encoding="utf-8")
   try:subprocess.run([str(vp),str(app/"scripts"/"kaptia_context_menu.py"),"--install-menu"],cwd=app,capture_output=True,text=True,timeout=20)
   except Exception as e:self._js({"log":"右鍵選單註冊未完成："+str(e)})
   env=os.environ.copy();env.pop("KAPTIA_SCRATCH_CHECKPOINT",None);env.update({"HF_HOME":str(ROOT/"model-cache"),"KAPTIA_LANG":self.language,"KAPTIA_MODEL_ID":"Qwen/Qwen3-8B","KAPTIA_QUANTIZATION":"4bit","KAPTIA_PROVIDER":"local"})
   # Register a per-user scheduled update check only when the saved preference allows it.
   try:
    saved=json.loads(settings.read_text(encoding="utf-8"))
    updater=app/"scripts"/"kaptia_update.py"
    if saved.get("auto_updates",True) is not False:
     gui=vp.with_name("pythonw.exe");gui=gui if gui.exists() else vp
     task_cmd=f'"{gui}" "{updater}"'
     task=subprocess.run(["schtasks.exe","/Create","/SC","HOURLY","/MO","6","/TN","KaptiaLabUpdateCheck","/TR",task_cmd,"/F"],capture_output=True,text=True,timeout=30)
     if task.returncode!=0:self._js({"log":"自動更新排程未建立："+(task.stderr or task.stdout).strip()})
     else:self._js({"log":"已建立每 6 小時自動更新檢查。"})
    else:
     subprocess.run(["schtasks.exe","/Delete","/TN","KaptiaLabUpdateCheck","/F"],capture_output=True,text=True,timeout=30)
     self._js({"log":"使用者已關閉自動更新，不建立背景排程。"})
   except Exception as e:self._js({"log":"自動更新排程設定未完成："+str(e)})
   self._update("安裝完成",detail="Kaptia 已安裝。首次對話時會下載並載入 Qwen3-8B 模型，過程不會執行模型訓練。",phase="COMPLETE",progress=100,busy=False,done="安裝完成")
   gui=vp.with_name("pythonw.exe");gui=gui if gui.exists() else vp
   subprocess.Popen([str(gui),str(app/"scripts"/"kaptia_webview.py")],cwd=app,env=env,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
  except Exception as e:self._update("安裝失敗",detail=f"{type(e).__name__}: {e}",phase="ERROR",busy=False,log=f"{type(e).__name__}: {e}",done="安裝失敗；請檢查錯誤日誌")
  finally:
   with self.lock:self.busy=False
def main():
 api=InstallerAPI();webview.create_window("Kaptia Setup",str(HTML_PATH),js_api=api,width=960,height=720,min_size=(760,600),background_color="#1b1d1e");webview.start(debug=False)
if __name__=="__main__":main()
