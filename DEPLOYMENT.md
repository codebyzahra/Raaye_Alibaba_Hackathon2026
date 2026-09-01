# Deploying Raaye to Alibaba Cloud Function Compute

This guide deploys the Raaye FastAPI backend to **Alibaba Cloud Function Compute (FC 3.0)** using a Custom Runtime. The frontend is served separately (static build or local dev).

> **Scope:** Function Compute only. No ECS, no RDS. SQLite is created in-function ephemeral storage — fine for demos, not for persistent production data.

---

## Prerequisites

| Tool | Install | Purpose |
|------|---------|---------|
| **Serverless Devs CLI** (`s`) | `npm install -g @serverless-devs/s` | Deploy & manage FC functions |
| **Alibaba Cloud account** | [alibabacloud.com](https://www.alibabacloud.com) | Cloud provider |
| **DashScope API key** | [Model Studio console](https://www.alibabacloud.com/product/model-studio) | Qwen model access |
| **Node.js ≥ 18** | [nodejs.org](https://nodejs.org) | Required by `s` CLI |

Verify the CLI is installed:

```bash
s --version
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

## 2. Deploy

From the project root:

```bash
s deploy
```

This will:
1. Package the code (respecting `.fcignore` to exclude frontend, CSVs, docs, etc.)
2. Upload to FC in the configured region (`ap-southeast-1` by default)
3. Create the function `raaye-api` with Custom Runtime
4. Set up the HTTP trigger

### Change the region

Edit `s.yaml` → `vars.region`, or override at deploy time:

```bash
s deploy --region cn-shanghai
```

Available regions: `ap-southeast-1` (Singapore), `cn-shanghai`, `cn-hangzhou`, `us-west-1`, etc.

---

## 3. Set environment variables (secrets)

Secrets like `DASHSCOPE_API_KEY` are **not stored in `s.yaml`** — set them manually in the Function Compute console after the first deploy.

### Via the FC console (recommended)

1. Open the [Function Compute console](https://fcnext.console.aliyun.com)
2. Select your region (e.g. `ap-southeast-1`)
3. Click the **`raaye-api`** function
4. Go to **Configuration → Environment Variables**
5. Click **Edit** and add:

   | Key | Value |
   |-----|-------|
   | `DASHSCOPE_API_KEY` | `sk-your-actual-key-here` |

6. Click **Save**

The function restarts automatically with the new variable.

> **Without `DASHSCOPE_API_KEY`**, the app works fine in demo mode — it serves cached reviews and falls back to the rule-based analyzer for live requests. Add the key only when you need live Qwen inference.

Get your API key from [Alibaba Cloud Model Studio](https://www.alibabacloud.com/product/model-studio).

---

## 4. Verify

After a successful deploy, the CLI prints the function's HTTP trigger URL:

```
  httpTrigger:
    url: https://raaye-api-xxxx.ap-southeast-1.fcapp.run
```

Test it:

```bash
# Health check (should return FastAPI docs or 404 for root)
curl https://raaye-api-xxxx.ap-southeast-1.fcapp.run/docs

# List demo businesses
curl https://raaye-api-xxxx.ap-southeast-1.fcapp.run/api/demo/businesses

# Load a demo business
curl -X POST https://raaye-api-xxxx.ap-southeast-1.fcapp.run/api/demo/electronics
```

---

## 5. Connect the frontend

Update the frontend's API base URL to point to your FC function.

**Option A — Vite proxy (development):**

In `frontend/vite.config.js`, update the proxy target:

```js
proxy: {
  '/api': 'https://raaye-api-xxxx.ap-southeast-1.fcapp.run',
  '/analyze': 'https://raaye-api-xxxx.ap-southeast-1.fcapp.run',
}
```

**Option B — Static build:**

Build the frontend and serve from any static host (GitHub Pages, Vercel, OSS). Set `API_BASE` in `App.jsx` to your FC URL before building.

---

## Environment variables reference

### Set in `s.yaml` (non-secret, safe to commit)

| Variable | Default | Description |
|----------|---------|-------------|
| `QWEN_MODEL` | `qwen-plus-2025-07-28` | Qwen model identifier |
| `DASHSCOPE_BASE_URL` | `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` | DashScope OpenAI-compatible endpoint |
| `DEMO_MODE` | `true` | Serve cached demo reviews instead of calling Qwen |

### Set in the FC console (secrets, never committed)

| Variable | Required | Description |
|----------|----------|-------------|
| `DASHSCOPE_API_KEY` | No* | Alibaba Cloud Model Studio API key. Without it, the app uses demo caches and the rule-based fallback. |

\* Required only for live Qwen inference. Demo mode works without it.

To update non-secret variables, edit `s.yaml` and redeploy with `s deploy`. For secrets, use the FC console as described in Step 3.

---

## Updating the function

After making code changes:

```bash
s deploy
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
| `bootstrap: Permission denied` | Ensure the file has execute permission: `chmod +x bootstrap` (commit via Git on Linux/Mac, or use `git update-index --chmod=+x bootstrap`) |
| Cold-start timeout | First invocation installs pip dependencies (~10-20s). Increase `timeout` in `s.yaml` if needed |
| Qwen calls fail / fallback active | Set `DASHSCOPE_API_KEY` in the FC console (Function → Configuration → Environment Variables). Without it, the app uses demo caches and the rule-based fallback. |
| SQLite errors | FC ephemeral storage is writable at `/code` and `/tmp`. SQLite creates `raaye.db` in `/code` — this is reset on cold starts (expected for demo mode) |
| Function too large | Check `.fcignore` is excluding frontend/, evaluation/, and CSV files |

---

## Cost estimate

Function Compute free tier includes **1 million invocations/month** and generous compute allowance. For a hackathon demo with light traffic, costs should be negligible or zero.

See [FC pricing](https://www.alibabacloud.com/product/function-compute/pricing) for details.
