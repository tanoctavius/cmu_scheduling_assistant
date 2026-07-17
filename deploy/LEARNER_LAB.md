# Deploying to AWS Academy Learner Lab

Step-by-step guide for deploying the CMU Scheduling Assistant (FastAPI backend + React frontend) to a Learner Lab EC2 instance. Assumes zero prior AWS experience.

**How it runs on the instance:**

```
Browser ──▶ :80   frontend (built React app, served static)
        ──▶ :8000 backend  (FastAPI via uv/uvicorn)

On every boot: refresh-ip.sh reads the instance's NEW public IP,
rewrites frontend/.env (VITE_BACKEND_URL), and rebuilds the frontend.
This is what makes the changing-IP problem disappear.
```

The backend uses the deterministic LLM stub until an `ANTHROPIC_API_KEY` is added, so the app is fully demoable the moment the instance boots — no secrets required.

---

## Part 1: One-Time Launch (first lab session, ~20 min)

### 1. Start the lab
AWS Academy → your course → Modules → **Launch AWS Academy Learner Lab** → **Start Lab**. Wait for the green dot, then click **AWS** to open the console.

### 2. Create a key pair
EC2 → Key Pairs → Create key pair → name it `scheduler-key`, type RSA, format `.pem`. It downloads automatically — keep it. Then on Mac/Linux:
```bash
chmod 400 ~/Downloads/scheduler-key.pem
```

### 3. Launch the instance
EC2 → **Launch instance**:

| Setting | Value |
|---|---|
| Name | `cmu-scheduler` |
| AMI | **Ubuntu Server 24.04 LTS** |
| Instance type | **t3.small** (t2.micro is too small for the npm build) |
| Key pair | `scheduler-key` |
| Security group | Allow: SSH (22) from My IP, **HTTP (80)** from Anywhere, **Custom TCP 8000** from Anywhere |
| IAM instance profile (under Advanced) | **LabInstanceProfile** |
| User data (bottom of Advanced) | Paste the contents of `user-data.sh` — **edit REPO_URL first if the repo moves or goes private** |

Launch. First boot takes **5–8 minutes** (it installs Node, uv, clones, builds the frontend). You can watch progress:
```bash
ssh -i ~/Downloads/scheduler-key.pem ubuntu@<PUBLIC_IP>
sudo tail -f /var/log/user-data.log
```

### 4. Verify
- Backend: `http://<PUBLIC_IP>:8000/health` → `{"status":"ok"}`
- Frontend: `http://<PUBLIC_IP>` → survey page loads

### 5. (Optional) Add the real LLM key
The stub works for the full demo flow. To use the real model:
```bash
ssh -i scheduler-key.pem ubuntu@<PUBLIC_IP>
cd /opt/app/backend
/usr/local/bin/uv sync --extra llm
echo "ANTHROPIC_API_KEY=sk-ant-..." | sudo tee .env
sudo systemctl restart scheduler-backend
```

---

## Part 2: Every Session After (2 minutes)

1. Start Lab in AWS Academy → wait for green
2. EC2 → Instances → `cmu-scheduler` → **Instance state → Start instance**
3. Wait ~2 min (boot + automatic frontend rebuild for the new IP)
4. Copy the **new** Public IPv4 → open `http://<NEW_IP>` 

The IP refresh is automatic — no SSH needed. Just grab the new IP.

**Demo tip:** start the lab and instance 15 minutes before you present.

---

## Part 3: Deploying Code Updates

After anyone pushes to main:
```bash
ssh -i scheduler-key.pem ubuntu@<PUBLIC_IP>
sudo bash /opt/app/deploy/update.sh
```
(Or copy `update.sh` to the instance if it's not committed to the repo yet.)

---

## The One Code Change the Repo Probably Needs: CORS

In dev, the frontend (localhost:5173) and backend (localhost:8000) are both localhost, and the repo's CORS settings likely reflect that. Deployed, the frontend origin becomes `http://<PUBLIC_IP>` calling `http://<PUBLIC_IP>:8000` — a different origin, so the browser will block API calls unless the backend allows it.

Check `backend/app/main.py` for `CORSMiddleware`. For the class demo, the pragmatic setting is:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # fine for a class demo; tighten for anything real
    allow_methods=["*"],
    allow_headers=["*"],
)
```

If API calls fail in the browser with the frontend loading fine, open DevTools → Console — a CORS error there means this is the fix. This is a good small PR to bring to the team.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Nothing loads at all | Instance stopped or IP changed | Start instance, use the NEW IP from the console |
| Frontend loads, API calls fail | CORS (see above) or backend down | Fix CORS / `sudo systemctl restart scheduler-backend` |
| Frontend shows but hits localhost:8000 | Refresh script didn't run | `sudo systemctl restart scheduler-refresh scheduler-frontend` |
| `curl :8000/health` fails on the instance | Backend crashed | `journalctl -u scheduler-backend -n 50` for the error |
| Port 80/8000 unreachable from browser | Security group missing rules | EC2 → Security Groups → add inbound TCP 80 and 8000, source 0.0.0.0/0 |
| First boot never finishes | user-data error | `sudo cat /var/log/user-data.log` — usually a typo in REPO_URL |
| Private repo won't clone | No auth in URL | Use `https://<TOKEN>@github.com/...` with a fine-grained token (read-only, this repo only) |
| Budget draining fast | Wrong instance type | Stick to t3.small; terminate anything bigger |
| Instance vanished | Terminated instead of Stopped | Relaunch via Part 1 — takes 20 min, nothing of value is lost (code is in GitHub) |

**Learner Lab reminders:** the lab auto-stops the instance when your session ends (that's normal); credentials in "AWS Details" rotate every session (never put them in code — the instance profile handles AWS access); stick to us-east-1.

---

## Suggested README Addition (answers "link the sandbox")

Once this works, add to the repo README so the whole team can find and use the deployment:

```markdown
## Deployment (AWS Academy Learner Lab)

The demo runs in [NAME]'s Learner Lab sandbox
(AWS Academy → [course name] → Modules → Launch AWS Academy Learner Lab).
The public IP changes every lab session — [NAME] posts the current URL
in the group chat when the lab is up.

Deploy/update instructions: [`deploy/LEARNER_LAB.md`](deploy/LEARNER_LAB.md)
```

---

**Cost estimate:** t3.small ≈ $0.02/hr, auto-stopped between sessions → roughly $5–15 of the lab budget for the rest of the semester. The Anthropic API bills separately and never touches the AWS budget.
