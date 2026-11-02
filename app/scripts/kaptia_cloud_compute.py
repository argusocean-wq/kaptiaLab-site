"""KaptiaLab Cloud Compute client: connects to a user-owned worker, not an LLM API."""
from __future__ import annotations
import json, os, urllib.error, urllib.request, uuid
from typing import Any

PROVIDERS = [
 {"id":"custom","name":"Custom VPS / Dedicated Server","class":"CPU/GPU","status":"supported","connection":"Install Kaptia Worker; provide HTTPS endpoint"},
 {"id":"hetzner","name":"Hetzner Cloud / Dedicated","class":"CPU","status":"supported","connection":"Manual worker endpoint; GPU depends on rented host"},
 {"id":"digitalocean","name":"DigitalOcean Droplets / GPU Droplets","class":"CPU/GPU","status":"supported","connection":"Manual worker endpoint"},
 {"id":"vultr","name":"Vultr Cloud Compute","class":"CPU/GPU","status":"supported","connection":"Manual worker endpoint"},
 {"id":"aws","name":"Amazon Web Services EC2","class":"CPU/GPU","status":"supported","connection":"Manual worker endpoint; no account provisioning integration"},
 {"id":"gcp","name":"Google Cloud Compute Engine","class":"CPU/GPU","status":"supported","connection":"Manual worker endpoint; no account provisioning integration"},
 {"id":"azure","name":"Microsoft Azure Virtual Machines","class":"CPU/GPU","status":"supported","connection":"Manual worker endpoint; no account provisioning integration"},
 {"id":"runpod","name":"RunPod Pods","class":"GPU","status":"supported","connection":"Deploy worker in user's Pod; provide endpoint"},
 {"id":"vast","name":"Vast.ai Instances","class":"GPU","status":"supported","connection":"Deploy worker in user's instance; provide endpoint"},
 {"id":"lambda","name":"Lambda GPU Cloud","class":"GPU","status":"supported","connection":"Deploy worker in user's instance; provide endpoint"},
 {"id":"coreweave","name":"CoreWeave","class":"GPU","status":"supported","connection":"Deploy worker in user's environment; provide endpoint"},
]
TASK_TYPES={"python_script","blender_background"}
MAX_SOURCE_CHARS=500_000
MAX_TIMEOUT_SECONDS=3600

class CloudComputeError(RuntimeError): pass

class CloudComputeClient:
 def __init__(self, endpoint:str, token:str, timeout:int=20):
  endpoint=str(endpoint or "").strip().rstrip("/")
  if not endpoint.startswith("https://"): raise ValueError("Cloud Worker 必須使用 HTTPS endpoint")
  if not token or len(token)<24: raise ValueError("Cloud Worker token 至少需要 24 個字元")
  self.endpoint,self.token=endpoint,token
  self.timeout=max(3,min(int(timeout),60))
 @classmethod
 def from_environment(cls, endpoint_env="KAPTIA_CLOUD_ENDPOINT", token_env="KAPTIA_CLOUD_TOKEN"):
  return cls(os.environ.get(endpoint_env,""),os.environ.get(token_env,""))
 def _request(self,method,path,payload=None):
  body=None if payload is None else json.dumps(payload).encode("utf-8")
  req=urllib.request.Request(self.endpoint+path,data=body,method=method,headers={
   "Authorization":"Bearer "+self.token,"Content-Type":"application/json","User-Agent":"KaptiaLab-CloudCompute/1"})
  try:
   with urllib.request.urlopen(req,timeout=self.timeout) as response:
    raw=response.read(2_000_001)
    if len(raw)>2_000_000: raise CloudComputeError("Cloud Worker 回應超過大小限制")
    data=json.loads(raw.decode("utf-8"))
    if not isinstance(data,dict): raise CloudComputeError("Cloud Worker 回應格式無效")
    return data
  except urllib.error.HTTPError as exc:
   raise CloudComputeError(f"Cloud Worker HTTP {exc.code}: {exc.read(4096).decode('utf-8','replace')}") from exc
  except (urllib.error.URLError,TimeoutError,OSError) as exc:
   raise CloudComputeError(f"無法連線 Cloud Worker：{exc}") from exc
 def health(self): return self._request("GET","/v1/health")
 def capabilities(self): return self._request("GET","/v1/capabilities")
 def submit(self,task_type,source,timeout_seconds=900,task_id=None):
  if task_type not in TASK_TYPES: raise ValueError("不支援的雲端任務類型")
  if not isinstance(source,str) or not source.strip() or len(source)>MAX_SOURCE_CHARS: raise ValueError("source 必須為非空字串且不得超過 500,000 字元")
  timeout_seconds=int(timeout_seconds)
  if not 1<=timeout_seconds<=MAX_TIMEOUT_SECONDS: raise ValueError("timeout_seconds 必須介於 1 到 3600")
  return self._request("POST","/v1/jobs",{"task_id":task_id or uuid.uuid4().hex,"task_type":task_type,"source":source,"timeout_seconds":timeout_seconds})
 def get_job(self,job_id):
  if not job_id or len(job_id)>80 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in job_id): raise ValueError("job_id 格式無效")
  return self._request("GET","/v1/jobs/"+job_id)

def list_providers() -> list[dict[str,Any]]:
 return [dict(item) for item in PROVIDERS]
