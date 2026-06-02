# Dynamo Benchflow Execution Plan

## Prerequisites on Management Cluster (fire-athena)

1. **Create namespace** on fire-athena for experiment submission:
   ```bash
   KUBECONFIG=~/kubeconfigs/kubeconfig_files/fire-athena
   oc new-project benchflow-dynamo  # or use existing benchflow namespace
   ```

2. **Register poseidon kubeconfig secret** on fire-athena:
   ```bash
   oc create secret generic poseidon \
     --from-file=kubeconfig=~/kubeconfigs/kubeconfig_files/poseidon \
     -n benchflow-dynamo
   ```

3. **Create Kueue LocalQueue** named `poseidon` in the experiment namespace:
   ```bash
   # Check existing LocalQueues for reference
   oc get localqueues -A
   # Create one pointing at the cluster queue (match existing pattern)
   ```

4. **Build and push benchflow image** with dynamo support:
   ```bash
   cd ~/workspace/benchflow
   # Build image with local changes
   podman build -t <registry>/benchflow:dynamo-dev .
   podman push <registry>/benchflow:dynamo-dev
   ```

## Prerequisites on Target Cluster (poseidon)

1. **Dynamo operator installed** (already done — v1.1.1)

2. **PVCs exist** in `dynamo-system` namespace:
   ```bash
   KUBECONFIG=~/kubeconfigs/kubeconfig_files/poseidon
   oc get pvc -n dynamo-system
   # Need: model-cache (100Gi RWX), compilation-cache (50Gi RWX)
   ```

3. **HF token secret** exists:
   ```bash
   oc get secret hf-token-secret -n dynamo-system
   # If not: head -1 ~/creds/g3_hf_token | tr -d '\n\r' | \
   #   oc create secret generic hf-token-secret --from-literal=HF_TOKEN=- -n dynamo-system
   ```

4. **Model downloaded** to PVC:
   ```bash
   # Check if Qwen/Qwen3-32B is in model-cache PVC
   # If not, run the download job from poseidon-dynamo-setup.md step 3
   ```

5. **SCC granted** for Dynamo service accounts:
   ```bash
   oc adm policy add-scc-to-user anyuid -z <dgd-name>-k8s-service-discovery -n dynamo-system
   ```

## Execution: Full E2E via Management Cluster

```bash
KUBECONFIG=~/kubeconfigs/kubeconfig_files/fire-athena

bflow experiment run \
  --model Qwen/Qwen3-32B \
  --deployment-profile dynamo-agg-round-robin-qwen3-32b \
  --benchmark-profile guidellm-concurrent-1k-1k \
  --metrics-profile dynamo \
  --namespace benchflow-dynamo \
  --cluster-name poseidon \
  --no-download \
  --benchflow-image <registry>/benchflow:dynamo-dev \
  --follow
```

## Execution: Deploy-Only Test (no benchmark)

```bash
KUBECONFIG=~/kubeconfigs/kubeconfig_files/fire-athena

bflow experiment run \
  --model Qwen/Qwen3-32B \
  --deployment-profile dynamo-agg-round-robin-qwen3-32b \
  --benchmark-profile guidellm-concurrent-1k-1k \
  --metrics-profile dynamo \
  --namespace benchflow-dynamo \
  --cluster-name poseidon \
  --no-download --no-benchmark --no-collect \
  --benchflow-image <registry>/benchflow:dynamo-dev \
  --follow
```

## Execution: Benchmark-Only (DGD already deployed)

If DGD is already running on poseidon (deployed manually or from previous run):

```bash
KUBECONFIG=~/kubeconfigs/kubeconfig_files/fire-athena

bflow experiment run \
  --model Qwen/Qwen3-32B \
  --deployment-profile dynamo-agg-round-robin-qwen3-32b \
  --benchmark-profile guidellm-concurrent-1k-1k \
  --metrics-profile dynamo \
  --namespace benchflow-dynamo \
  --cluster-name poseidon \
  --no-download --no-deploy --no-cleanup \
  --target-url http://<dgd-name>-frontend.dynamo-system.svc.cluster.local:8000 \
  --target-metrics-release-name <dgd-name> \
  --follow
```

## Execution: KV Router Mode

```bash
bflow experiment run \
  --model Qwen/Qwen3-32B \
  --deployment-profile dynamo-agg-kv-router-qwen3-32b \
  --benchmark-profile aiperf-mooncake-trace-2k \
  --metrics-profile dynamo \
  --namespace benchflow-dynamo \
  --cluster-name poseidon \
  --no-download \
  --benchflow-image <registry>/benchflow:dynamo-dev \
  --follow
```

## Local Validation (no cluster needed)

```bash
cd ~/workspace/benchflow

# 1. Profile resolution (dry-run)
bflow experiment resolve \
  --model Qwen/Qwen3-32B \
  --deployment-profile dynamo-agg-round-robin-qwen3-32b \
  --benchmark-profile guidellm-concurrent-1k-1k \
  --metrics-profile dynamo \
  --namespace dynamo-system

# 2. Import check
python3 -c "from benchflow.deploy import deploy_dynamo; from benchflow.cleanup import cleanup_dynamo; print('OK')"

# 3. Template rendering check
python3 -c "
from benchflow.assets import render_jinja_yaml_document
import yaml
ctx = {
    'release_name': 'test', 'namespace': 'dynamo-system',
    'labels': {'app': 'benchflow'}, 'model_name': 'Qwen/Qwen3-32B',
    'runtime_image': 'nvcr.io/nvidia/ai-dynamo/vllm-runtime:1.1.1',
    'worker_replicas': 4, 'tensor_parallelism': 2,
    'vllm_args': ['--gpu-memory-utilization=0.90'], 'max_model_len': '131072',
    'hf_overrides': None, 'router_mode': 'round-robin', 'router_args': [],
    'kv_transfer_config': None, 'kvbm_cpu_cache_gb': None,
    'hf_secret_name': 'hf-token-secret', 'model_cache_pvc': 'model-cache',
    'compilation_cache_pvc': 'compilation-cache',
    'hf_home': '/home/dynamo/.cache/huggingface',
    'use_dra_resources': False, 'worker_env': [], 'frontend_cpu': '8',
}
doc = render_jinja_yaml_document('deployment/dynamo/aggregate.yaml.j2', ctx)
print(yaml.safe_dump(doc, sort_keys=False))
"
```

## Post-Deploy Validation

After DGD is deployed on poseidon:

```bash
KUBECONFIG=~/kubeconfigs/kubeconfig_files/poseidon

# Check DGD status
oc get dgd -n dynamo-system
oc get dgd <name> -n dynamo-system -o jsonpath='{.status.conditions}'

# Check pods
oc get pods -n dynamo-system

# Check frontend service
oc get svc -n dynamo-system | grep frontend

# Quick inference test (from a pod on poseidon)
oc run curl-test --rm -it --image=curlimages/curl -- \
  curl -s http://<name>-frontend.dynamo-system.svc.cluster.local:8000/v1/models
```

## Known Issues / Notes

- SCC: DGD service account `<dgd-name>-k8s-service-discovery` needs `anyuid` SCC on OpenShift
- HF token: must be single line, no trailing newlines (use `head -1 | tr -d '\n\r'`)
- NFS perms: after model download, may need `chmod -R 777` on cache dir (fsGroup 1000 vs OpenShift random UID)
- DRA resources: kv-router profile uses `dra.llm-d.io/gpu-nic-pair` — requires DRA configured on cluster
