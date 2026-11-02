# KaptiaLab Cloud Compute

Cloud Compute connects Kaptia to a server that the user rents and controls. It is remote compute, not a Claude/GPT/LLM API. Kaptia's configured local model remains responsible for conversation, planning, and result integration.

## Architecture
- Desktop client sends an explicitly approved, bounded task to the user's worker over HTTPS.
- Worker authenticates a bearer token, validates task type and limits, then runs a fixed entrypoint inside Docker.
- Worker returns job status and bounded stdout/stderr. Kaptia remains the coordinator.
- Initial release does not create, resize, pay for, or terminate cloud instances. Users create their own server account and install the worker.

## Provider compatibility

"Connectable" means a user may install the worker on a Linux server rented from the provider and configure its HTTPS endpoint. It does not mean Kaptia provisions instances, guarantees a GPU, or supports provider billing APIs.

| Provider | Potential host type | Worker connection |
|---|---|---|
| Custom VPS / dedicated server | CPU; GPU depends on host | Manual HTTPS endpoint |
| Hetzner Cloud / Dedicated | Primarily CPU; GPU depends on product | Manual HTTPS endpoint |
| DigitalOcean Droplets / GPU Droplets | CPU or GPU products | Manual HTTPS endpoint |
| Vultr Cloud Compute | CPU or GPU products | Manual HTTPS endpoint |
| AWS EC2 | CPU or GPU instances | Manual HTTPS endpoint |
| Google Cloud Compute Engine | CPU or GPU instances | Manual HTTPS endpoint |
| Microsoft Azure VMs | CPU or GPU sizes | Manual HTTPS endpoint |
| RunPod Pods | GPU-focused instances | Deploy worker in user's Pod |
| Vast.ai instances | GPU-focused instances | Deploy worker in user's instance |
| Lambda GPU Cloud | GPU instances | Deploy worker in user's instance |
| CoreWeave | GPU infrastructure | Deploy worker in user's environment |

These are hosting compatibility candidates, not tested end-to-end deployments. Confirm Docker privileges, supported Linux distribution, inbound HTTPS networking, GPU driver access, quotas, and pricing with the provider before renting.

Official provider references:
- Hetzner API: https://docs.hetzner.cloud/
- DigitalOcean GPU Droplets: https://docs.digitalocean.com/products/droplets/how-to/gpu/create/
- AWS EC2 GPU instances: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/accelerated-computing-instances.html
- Google Cloud GPUs: https://docs.cloud.google.com/compute/docs/gpus
- Azure GPU VMs: https://learn.microsoft.com/azure/virtual-machines/sizes-gpu
- RunPod GPU Pods: https://www.runpod.io/product/cloud-gpus
- Vast.ai: https://vast.ai/
- Lambda GPU Cloud: https://lambda.ai/service/gpu-cloud
- CoreWeave: https://www.coreweave.com/

## Worker setup

Requirements: Linux server, Docker Engine, Python 3.11+, HTTPS reverse proxy, and a long random token.
1. Install Docker and pull the configured runtime images.
2. Set KAPTIA_CLOUD_TOKEN to a random secret of at least 24 characters.
3. Install dependencies from requirements-cloud-worker.txt.
4. Start behind a TLS reverse proxy, for example: uvicorn cloud_worker.app:app --host 127.0.0.1 --port 8787.
5. Set KAPTIA_CLOUD_ENDPOINT=https://your-worker.example and KAPTIA_CLOUD_TOKEN on the Kaptia client machine.

Do not expose the worker directly over public HTTP. Do not commit tokens or put them in screenshots/logs. Docker isolation reduces risk but is not a guarantee against all container escape or host-level vulnerabilities. Run the worker on a dedicated server account/VM, keep Docker and the host patched, and do not mount sensitive host directories into task containers.

## Current task types and limits
- python_script: fixed Python entrypoint in a network-isolated container.
- blender_background: fixed Blender background entrypoint in a network-isolated container.
- **GPU execution is disabled in this worker version.** A GPU-capable rental does not automatically make this worker use the GPU; the current Docker invocation does not pass GPU devices through.
- Maximum source: 500,000 characters.
- Maximum runtime: 3,600 seconds.
- Initial concurrency: 2 jobs.
- Container limit: 4 CPU, 4 GiB RAM, 128 PIDs; no network, no Linux capabilities, read-only root.
- Job source is cleared after completion and on restart recovery. Completed/failed job records are pruned after 7 days.
- Worker restart marks interrupted queued/running tasks as failed; it does not resume execution.
- Worker returns bounded stdout/stderr. Persistent artifact transfer and full project-folder sync are not yet implemented.

## Privacy and cost
Only task source explicitly submitted to Cloud Compute is transferred. Treat it as data leaving the PC. Review project files and secrets before submission. Cloud compute is billed by the provider; Kaptia does not charge or control the cloud account. Stop or delete rented instances in the provider console when finished.

## Not yet implemented
- Provider API-based instance creation/stop/billing estimates.
- GPU pass-through, telemetry, and dynamic resource matching.
- Upload/download of complete project folders and artifacts.
- Automatic Agent task routing and cost-aware local/cloud scheduling.
- Distributed multi-node jobs.
