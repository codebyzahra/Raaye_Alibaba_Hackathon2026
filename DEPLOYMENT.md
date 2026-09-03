# Deploying Raaye to Alibaba Cloud Function Compute

This guide deploys the Raaye FastAPI backend to **Alibaba Cloud Function Compute (FC 3.0)** using a Custom Runtime (`custom.debian11`, Python 3.9). The frontend is deployed separately on **Vercel**.

> **Scope:** Function Compute + Vercel. No ECS, no RDS. SQLite is created in-function ephemeral storage.

---

## Prerequisites

| Tool | Install | Purpose |
|------|---------|---------|
| **Serverless Devs CLI** (`s`) | `npm install -g @serverless-devs/s` | Deploy & manage FC functions |
| **Vercel CLI** | `npm install -g vercel` | Deploy frontend |
| **Alibaba Cloud account** | [alibabacloud.com](https://www.alibabacloud.com) | Cloud provider |
| **DashScope API key** | [Model Studio console](https://www.alibabacloud.com/product/model-studio) | Qwen model access |
| **Node.js ≥ 18** | [nodejs.org](https://nodejs.org) | Required by `s` and `vercel` CLI |
| **Python 3.11** | [python.org](https://python.org) | For pre-installing FC dependencies |

Verify the CLIs are installed:

```bash
s --version
vercel --version
```

---

## 1. Configure credentials

Register your Alibaba Cloud AccessKey with the Serverless Devs CLI:

```bash
s config add \
  --AccessKeyID <your-access-key-id> \
  --AccessKeySecret <your-access-key-secret> \
  -a raaye
```

Then set `default` as the active access alias (or edit `s.yaml` to use `access: raaye`):

```bash
s config get
```

---

## 2. Pre-install dependencies for FC

The FC sandbox is **read-only** — pip cannot install packages at runtime. Dependencies must be pre-installed locally into `.fc-deps/` targeting Python 3.9 on Linux:

```bash
pip install --no-user --target .fc-deps -r requirements.txt \
  --python-version 3.9 --platform manylinux2014_x86_64 --only-binary=:all:
```

> **Note:** If pip complains about missing pure-Python transitive dependencies (e.g. `exceptiongroup`), add them explicitly to `requirements.txt` and re-run.

---

## 3. Deploy backend

From the project root:

```bash
s deploy -y
```

This will:
1. Package the code (respecting `.fcignore` to exclude frontend, CSVs, docs, etc.)
2. Upload to FC in the configured region (`ap-southeast-1` by default)
3. Create/update the function `raaye-api` with Custom Runtime `custom.debian11`
4. Set up the HTTP trigger

> **Important:** `s.yaml` does **not** contain sensitive or model-specific environment variables. After deploying, set `DASHSCOPE_API_KEY`, `QWEN_MODEL`, and `DASHSCOPE_BASE_URL` manually in the FC console (see [Step 4](#4-environment-variables)). The only variable in `s.yaml` is `DEMO_MODE`.

### Change the region

Edit `s.yaml` → `vars.region`, or override at deploy time:

```bash
s deploy --region cn-shanghai
```

Available regions: `ap-southeast-1` (Singapore), `cn-shanghai`, `cn-hangzhou`, `us-west-1`, etc.

---

## 4. Environment variables

`DEMO_MODE` is set in `s.yaml` and deployed automatically. The remaining variables must be set **manually in the FC console** so that secrets are never committed to source control:

1. Open the [Function Compute console](https://fc.console.aliyun.com).
2. Select the **`raaye-api`** function in region **ap-southeast-1**.
3. Go to **Configuration → Environment Variables**.
4. Add the following variables:

| Variable | Value | Description |
|----------|-------|-------------|
| `DASHSCOPE_API_KEY` | `sk-...` | Alibaba Cloud Model Studio API key |
| `QWEN_MODEL` | `qwen-plus-2025-07-28` | Qwen model identifier |
| `DASHSCOPE_BASE_URL` | `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` | DashScope OpenAI-compatible endpoint |
| `DEMO_MODE` | `false` | `false` = live Qwen analysis; `true` = cached demo results |

> **Without `DASHSCOPE_API_KEY`**, the app falls back to the rule-based keyword analyzer. Demo businesses (cached JSON) work regardless of this setting.

> **Note:** `s deploy` does not overwrite variables set in the console that are absent from `s.yaml`, so your secrets persist across redeployments.

---

## 5. Verify

After a successful deploy, the CLI prints the function's HTTP trigger URL:

```
  httpTrigger:
    url: https://raaye-api-xxxx.ap-southeast-1.fcapp.run
```

Test it:

```bash
# API docs (Swagger UI)
curl https://raaye-api-xxxx.ap-southeast-1.fcapp.run/docs

# List demo businesses
curl https://raaye-api-xxxx.ap-southeast-1.fcapp.run/api/demo/businesses

# Load a demo business
curl -X POST https://raaye-api-xxxx.ap-southeast-1.fcapp.run/api/demo/electronics

# Live analysis
curl -X POST https://raaye-api-xxxx.ap-southeast-1.fcapp.run/analyze \
  -H "Content-Type: application/json" \
  -d '{"reviews": ["bohat acha product hai"]}'
```

---

## 6. Deploy frontend to Vercel

1. Update `API_BASE` in `frontend/src/App.jsx` to your FC URL:

```js
const API_BASE = 'https://raaye-api-xxxx.ap-southeast-1.fcapp.run'
```

2. Deploy:

```bash
cd frontend
vercel login        # one-time
vercel --yes --prod
```

Vercel will build the React app and give you a live URL like `https://your-app.vercel.app`.

---

## Updating the function

After making code changes:

```bash
# Rebuild deps if requirements.txt changed
pip install --no-user --target .fc-deps -r requirements.txt \
  --python-version 3.9 --platform manylinux2014_x86_64 --only-binary=:all:

# Redeploy
s deploy -y
```

FC creates a new version and routes traffic to it. No downtime.

---

## Viewing logs

```bash
s logs
```

Or stream in real-time:

```bash
s logs --tail
```

---

## Tear down

Remove the function and all associated resources:

```bash
s remove
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `bootstrap: Permission denied` | Ensure the file has execute permission: `git update-index --chmod=+x bootstrap` |
| `ImportError: cannot import name 'Literal' from 'typing'` | Runtime reverted to Python 3.7 — redeploy to restore `custom.debian11` |
| `ModuleNotFoundError: pydantic_core._pydantic_core` | Rebuild `.fc-deps/` with `--python-version 3.9 --platform manylinux2014_x86_64` |
| Demo businesses not showing | Ensure demo cache JSON files exist in `data/` and caches load at startup |
| Qwen calls fail / fallback active | Verify `DASHSCOPE_API_KEY` is set in the FC console (Configuration → Environment Variables) |
| Function too large | Check `.fcignore` is excluding frontend/, evaluation/, and CSV files |
| Settings revert after console edit | Only `DEMO_MODE` is in `s.yaml`; other vars are set in the FC console and persist across deploys |

---

## Cost estimate

Function Compute free tier includes **1 million invocations/month** and generous compute allowance. For a hackathon demo with light traffic, costs should be negligible or zero.

See [FC pricing](https://www.alibabacloud.com/product/function-compute/pricing) for details.
