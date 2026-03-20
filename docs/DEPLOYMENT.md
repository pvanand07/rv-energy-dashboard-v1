# RV Energy Intelligence — Complete Run & Deployment Guide

**Elevatics AI** | FastAPI + SQLite + Apple Design  
*From `git clone` to production in 15 minutes.*

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Get the Code](#2-get-the-code)
3. [Local Development (No Docker)](#3-local-development-no-docker)
4. [Local Docker](#4-local-docker)
5. [Test Suite](#5-test-suite)
6. [Environment Variables](#6-environment-variables)
7. [Cloud Deployment — Render (Easiest, Free Tier)](#7-cloud-deployment--render-easiest-free-tier)
8. [Cloud Deployment — Railway](#8-cloud-deployment--railway)
9. [Cloud Deployment — Fly.io](#9-cloud-deployment--flyio)
10. [Cloud Deployment — AWS (EC2 + Nginx)](#10-cloud-deployment--aws-ec2--nginx)
11. [Cloud Deployment — AWS ECS / Fargate (Container)](#11-cloud-deployment--aws-ecs--fargate-container)
12. [Cloud Deployment — Google Cloud Run](#12-cloud-deployment--google-cloud-run)
13. [Cloud Deployment — DigitalOcean App Platform](#13-cloud-deployment--digitalocean-app-platform)
14. [Jetson AGX Orin (Edge/RV Hardware)](#14-jetson-agx-orin-edgerv-hardware)
15. [Production Checklist](#15-production-checklist)
16. [Monitoring & Health](#16-monitoring--health)
17. [Troubleshooting](#17-troubleshooting)

---

## 1. Prerequisites

| Tool | Minimum version | Install |
|------|----------------|---------|
| Python | 3.10+ | [python.org](https://python.org) |
| pip | 23+ | `python -m pip install --upgrade pip` |
| Git | Any | [git-scm.com](https://git-scm.com) |
| Docker (optional) | 24+ | [docker.com](https://docker.com) |

Verify:
```bash
python --version   # → Python 3.11.x or 3.12.x
pip --version      # → pip 24.x
git --version      # → git 2.x
docker --version   # → Docker 24.x (optional)
```

---

## 2. Get the Code

### Option A — Clone from GitHub
```bash
git clone https://github.com/elevatics-ai/rv-energy-intelligence
cd rv-energy-intelligence
```

### Option B — Unpack the tarball
```bash
tar -xzf rv-energy-intelligence.tar.gz
cd rv-energy-intelligence
```

### Project structure sanity check
```
rv-energy-intelligence/
├── main.py              ← FastAPI entry point
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── app/
│   ├── config.py        ← settings (reads env vars)
│   ├── database.py      ← SQLite init + connection
│   ├── models.py        ← Pydantic schemas
│   ├── simulation.py    ← 2880-step engine
│   ├── stability.py     ← Stability Score 0-10
│   ├── crud.py          ← all SQL
│   └── routers/         ← FastAPI route handlers
├── templates/
│   └── index.html       ← Apple-design frontend
├── static/              ← CSS/JS assets
├── data/                ← SQLite file lives here
├── docs/                ← ER diagram + architecture
└── tests/               ← 100 pytest tests
```

---

## 3. Local Development (No Docker)

The fastest path. Everything runs in a Python virtual environment.

### Step 1 — Create and activate a virtual environment
```bash
# macOS / Linux
python -m venv .venv
source .venv/bin/activate

# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\Activate.ps1

# Windows (CMD)
python -m venv .venv
.venv\Scripts\activate.bat
```

You should see `(.venv)` in your prompt.

### Step 2 — Install dependencies
```bash
pip install -r requirements.txt
```

Expected output ends with:
```
Successfully installed aiosqlite-0.20.0 anyio-4.x fastapi-0.111.0
                       jinja2-3.1.4 pydantic-2.7.1 uvicorn-0.29.0 ...
```

### Step 3 — Run the application
```bash
uvicorn main:app --reload --port 5000
```

Expected startup output:
```
INFO     ════════════════════════════════════════════════
INFO       RV Energy Intelligence  v2.1.0
INFO       Elevatics AI | Apple Design Edition
INFO     ════════════════════════════════════════════════
INFO     Initialising database…
INFO     Database ready. Serving at http://0.0.0.0:5000
INFO     API docs → http://0.0.0.0:5000/docs
INFO     Uvicorn running on http://0.0.0.0:5000
```

### Step 4 — Open in browser
```
Dashboard →  http://localhost:5000
API docs  →  http://localhost:5000/docs      ← Swagger UI
Alt docs  →  http://localhost:5000/redoc
Health    →  http://localhost:5000/api/health
```

### Development tips

```bash
# Auto-reload on file changes (already included above with --reload)
uvicorn main:app --reload --port 5000

# Show all SQL queries (set in config.py)
DEBUG=true uvicorn main:app --reload --port 5000

# Use a separate test database so you don't dirty the main one
DB_PATH=./data/dev.db uvicorn main:app --reload --port 5000

# Run on a different port
uvicorn main:app --reload --port 8080
```

### What happens on first run

1. `lifespan()` in `main.py` calls `init_db()`
2. `init_db()` creates `./data/rv_energy.db` (SQLite WAL mode)
3. All 5 tables are created: `appliances`, `simulation_runs`, `simulation_hourly`, `appliance_snapshots`, `weather_readings`
4. 19 default appliances are inserted (Refrigerator, AC, Water heater, etc.)
5. The first simulation runs and the dashboard renders fully populated

---

## 4. Local Docker

If you prefer containers or want a production-identical environment locally.

### Build and run with Docker Compose (recommended)
```bash
# Build image and start the container
docker compose up

# Detached (background)
docker compose up -d

# View logs
docker compose logs -f

# Stop
docker compose down
```

Open `http://localhost:5000`.

The `./data` directory is mounted as a volume so the database persists across container restarts.

### Build and run with plain Docker
```bash
# Build image
docker build -t rv-energy .

# Run — maps port 5000, persists data to ./data
docker run \
  -p 5000:5000 \
  -v $(pwd)/data:/app/data \
  --name rv-energy \
  rv-energy

# Windows PowerShell equivalent
docker run -p 5000:5000 -v ${PWD}/data:/app/data --name rv-energy rv-energy
```

### Useful Docker commands
```bash
# Check container status
docker ps

# View logs
docker logs rv-energy -f

# Execute a shell inside the running container
docker exec -it rv-energy /bin/bash

# Inspect the SQLite database from inside the container
docker exec -it rv-energy sqlite3 /app/data/rv_energy.db ".tables"

# Stop and remove container
docker stop rv-energy && docker rm rv-energy

# Rebuild after code changes
docker compose down && docker compose up --build
```

---

## 5. Test Suite

```bash
# Activate virtual environment first
source .venv/bin/activate

# Run all 100 tests
pytest tests/ -v

# Run with summary only (less noise)
pytest tests/ -q

# Run a specific file
pytest tests/test_stability.py -v
pytest tests/test_simulation.py -v
pytest tests/test_api.py -v

# Run a specific test class
pytest tests/test_api.py::TestSimulate -v

# Run a specific test
pytest tests/test_stability.py::TestGrades::test_grade_F_critical_conditions -v

# Run with coverage report
pip install pytest-cov
pytest tests/ --cov=app --cov-report=term-missing
```

Expected result:
```
100 passed in 4.09s
```

The test suite uses a temporary SQLite file (`/tmp/*.db`) that is created
and deleted per session — it never touches `./data/rv_energy.db`.

---

## 6. Environment Variables

All configuration is in `app/config.py` and read from environment variables.
Copy `.env.example` to `.env` and adjust:

```bash
cp .env.example .env
```

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_PATH` | `./data/rv_energy.db` | Path to SQLite database file |
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `5000` | Server port |
| `DEBUG` | `true` | Show stack traces in error responses |

### Set variables inline (without .env file)
```bash
DB_PATH=/var/data/rv.db PORT=8080 DEBUG=false uvicorn main:app
```

### Set in Docker Compose
Edit `docker-compose.yml`:
```yaml
environment:
  DB_PATH: /app/data/rv_energy.db
  DEBUG: "false"
  PORT: "5000"
```

---

## 7. Cloud Deployment — Render (Easiest, Free Tier)

[Render](https://render.com) is the simplest path to a public URL.
Free tier runs one instance at 512 MB RAM — sufficient for single-RV use.

### Steps

**1. Push your code to GitHub**
```bash
git init
git add .
git commit -m "Initial commit — RV Energy Intelligence v2.1"
git remote add origin https://github.com/YOUR_USER/rv-energy-intelligence
git push -u origin main
```

**2. Create a Render account**  
Go to [render.com](https://render.com) → Sign up (free).

**3. Create a new Web Service**
- Dashboard → **New** → **Web Service**
- Connect your GitHub repo
- Configure:

| Field | Value |
|-------|-------|
| Name | `rv-energy` |
| Region | Closest to you |
| Branch | `main` |
| Runtime | `Python 3` |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `uvicorn main:app --host 0.0.0.0 --port $PORT` |
| Instance Type | Free (or Starter for persistent disk) |

**4. Add environment variables**  
Under **Environment** tab:

| Key | Value |
|-----|-------|
| `DEBUG` | `false` |
| `DB_PATH` | `/opt/render/project/src/data/rv_energy.db` |

> ⚠️ **Free tier limitation:** Render free tier does not provide a persistent
> disk. The SQLite database resets on each redeploy. For persistent data,
> upgrade to the **Starter** plan ($7/mo) and add a disk mount at `/data`.

**5. Deploy**  
Click **Create Web Service** → watch the build logs → your app is live at
`https://rv-energy.onrender.com` (or your custom subdomain).

### Render with Persistent Disk (Recommended)

In the Render dashboard, under your service → **Disks**:
- **Name:** `rv-data`
- **Mount path:** `/data`
- **Size:** 1 GB

Then set `DB_PATH=/data/rv_energy.db` in environment variables.

---

## 8. Cloud Deployment — Railway

[Railway](https://railway.app) — $5/month hobby plan, generous free trial.

**1. Install the Railway CLI**
```bash
# macOS
brew install railway

# Linux / Windows (npm)
npm install -g @railway/cli
```

**2. Login and initialise**
```bash
railway login
cd rv-energy-intelligence
railway init
```

**3. Create a volume for the database**
```bash
# In Railway dashboard → your project → New → Volume
# Mount path: /data
# Name: rv-data
```

**4. Set environment variables**
```bash
railway variables set DEBUG=false
railway variables set DB_PATH=/data/rv_energy.db
```

**5. Add a Procfile** (Railway reads this)
```bash
echo "web: uvicorn main:app --host 0.0.0.0 --port \$PORT" > Procfile
git add Procfile && git commit -m "Add Procfile"
```

**6. Deploy**
```bash
railway up
```

Railway auto-detects Python, installs requirements, and deploys.
Your app URL: `https://rv-energy-production.up.railway.app`

---

## 9. Cloud Deployment — Fly.io

[Fly.io](https://fly.io) — excellent for persistent SQLite. Free tier available.
Fly runs Docker containers close to your users.

**1. Install flyctl**
```bash
# macOS
brew install flyctl

# Linux
curl -L https://fly.io/install.sh | sh

# Windows
pwsh -Command "iwr https://fly.io/install.ps1 -useb | iex"
```

**2. Login**
```bash
fly auth login
```

**3. Create fly.toml** (save in project root)
```toml
app = "rv-energy"
primary_region = "iad"   # Change to nearest: lhr, sin, syd, ord, etc.

[build]

[http_service]
  internal_port = 5000
  force_https = true
  auto_stop_machines = true
  auto_start_machines = true
  min_machines_running = 0

[[vm]]
  memory = "512mb"
  cpu_kind = "shared"
  cpus = 1

[env]
  PORT = "5000"
  DEBUG = "false"
  DB_PATH = "/data/rv_energy.db"

[[mounts]]
  source = "rv_data"
  destination = "/data"
  initial_size = "1gb"
```

**4. Launch**
```bash
fly launch --name rv-energy --no-deploy
fly volumes create rv_data --region iad --size 1
fly deploy
```

**5. View your app**
```bash
fly open
fly logs    # real-time logs
```

Your app URL: `https://rv-energy.fly.dev`

**Fly.io tips:**
```bash
# SSH into the container
fly ssh console

# Inspect the SQLite database
fly ssh console -C "sqlite3 /data/rv_energy.db '.tables'"

# Scale to always-on (no cold starts)
fly scale count 1

# Check status
fly status
```

---

## 10. Cloud Deployment — AWS (EC2 + Nginx)

Full control. Production-grade. ~$10-20/month (t3.micro).

### Step 1 — Launch EC2 instance

In the AWS Console:
- **AMI:** Ubuntu 22.04 LTS (free tier eligible)
- **Instance type:** `t3.micro` (1 vCPU, 1 GB RAM)
- **Security group:** open ports 22 (SSH), 80 (HTTP), 443 (HTTPS)
- **Storage:** 20 GB gp3

Download your key pair (e.g. `rv-key.pem`).

### Step 2 — Connect and set up the server

```bash
# Connect
chmod 400 rv-key.pem
ssh -i rv-key.pem ubuntu@YOUR_EC2_IP

# System packages
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.11 python3.11-venv python3-pip nginx git sqlite3

# Verify Python
python3.11 --version
```

### Step 3 — Deploy the application

```bash
# Create app user
sudo useradd -m -s /bin/bash rvapp
sudo su - rvapp

# Clone / upload code
git clone https://github.com/YOUR_USER/rv-energy-intelligence
cd rv-energy-intelligence

# Virtual environment
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Create data directory with correct permissions
mkdir -p data

# Test the app runs
uvicorn main:app --host 127.0.0.1 --port 5000
# Ctrl+C to stop
```

### Step 4 — Systemd service (auto-start on reboot)

```bash
# Back to ubuntu user
exit

# Create service file
sudo tee /etc/systemd/system/rv-energy.service << 'EOF'
[Unit]
Description=RV Energy Intelligence — FastAPI
After=network.target

[Service]
Type=exec
User=rvapp
Group=rvapp
WorkingDirectory=/home/rvapp/rv-energy-intelligence
Environment="PATH=/home/rvapp/rv-energy-intelligence/.venv/bin"
Environment="DB_PATH=/home/rvapp/rv-energy-intelligence/data/rv_energy.db"
Environment="DEBUG=false"
Environment="PORT=5000"
ExecStart=/home/rvapp/rv-energy-intelligence/.venv/bin/uvicorn main:app \
          --host 127.0.0.1 --port 5000 --workers 2
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable rv-energy
sudo systemctl start rv-energy

# Check status
sudo systemctl status rv-energy

# View logs
sudo journalctl -u rv-energy -f
```

### Step 5 — Nginx reverse proxy

```bash
# Create Nginx config
sudo tee /etc/nginx/sites-available/rv-energy << 'EOF'
server {
    listen 80;
    server_name YOUR_DOMAIN.com;  # or your EC2 public IP

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN";
    add_header X-Content-Type-Options "nosniff";

    location / {
        proxy_pass         http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
        proxy_send_timeout 60s;

        # WebSocket support (for future live telemetry)
        proxy_set_header   Upgrade    $http_upgrade;
        proxy_set_header   Connection "upgrade";
    }

    # Serve static files directly (bypass Python)
    location /static/ {
        alias /home/rvapp/rv-energy-intelligence/static/;
        expires 7d;
        add_header Cache-Control "public, immutable";
    }
}
EOF

# Enable site
sudo ln -s /etc/nginx/sites-available/rv-energy /etc/nginx/sites-enabled/
sudo nginx -t          # test config
sudo systemctl restart nginx
sudo systemctl enable nginx
```

Your app is now live at `http://YOUR_EC2_IP`.

### Step 6 — HTTPS with Let's Encrypt (free SSL)

```bash
sudo apt install -y certbot python3-certbot-nginx

# Replace YOUR_DOMAIN.com with your actual domain
# (Domain must point to your EC2 IP in DNS first)
sudo certbot --nginx -d YOUR_DOMAIN.com

# Auto-renew cron (already installed, verify it)
sudo certbot renew --dry-run
```

---

## 11. Cloud Deployment — AWS ECS / Fargate (Container)

Fully managed containers — no server to maintain.

### Push image to ECR

```bash
# Set your region and account ID
AWS_REGION=us-east-1
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Create ECR repository
aws ecr create-repository --repository-name rv-energy --region $AWS_REGION

# Authenticate Docker to ECR
aws ecr get-login-password --region $AWS_REGION | \
  docker login --username AWS --password-stdin \
  $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

# Build and push
docker build -t rv-energy .
docker tag rv-energy:latest \
  $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/rv-energy:latest
docker push \
  $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/rv-energy:latest
```

### Create ECS Fargate service

1. **ECS Console** → **Create Cluster** → Fargate → Name: `rv-energy-cluster`
2. **Task Definitions** → Create new → Fargate
   - Container: `rv-energy`, Image: your ECR URI
   - Port mappings: `5000`
   - Environment variables: `DEBUG=false`, `DB_PATH=/data/rv_energy.db`
   - Mount point: `/data` → EFS volume (see below)
3. **EFS** (for persistent SQLite):
   - Create EFS filesystem → note the filesystem ID
   - Mount in task definition: EFS volume → mount at `/data`
4. **Service** → Create → Fargate → attach to Application Load Balancer

> ⚠️ **SQLite + EFS note:** SQLite over NFS (EFS) has performance
> limitations. For high-traffic fleet deployments, migrate to RDS PostgreSQL
> instead (change `aiosqlite` → `asyncpg` in `database.py` and `crud.py`).

---

## 12. Cloud Deployment — Google Cloud Run

Serverless containers. Pay per request. Scales to zero.

```bash
# Install gcloud CLI — https://cloud.google.com/sdk/docs/install
gcloud auth login
gcloud config set project YOUR_PROJECT_ID

# Build and push to Artifact Registry
gcloud artifacts repositories create rv-energy \
  --repository-format=docker --location=us-central1

gcloud builds submit --tag \
  us-central1-docker.pkg.dev/YOUR_PROJECT_ID/rv-energy/app:latest

# Deploy to Cloud Run
gcloud run deploy rv-energy \
  --image us-central1-docker.pkg.dev/YOUR_PROJECT_ID/rv-energy/app:latest \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --port 5000 \
  --memory 512Mi \
  --cpu 1 \
  --set-env-vars "DEBUG=false" \
  --min-instances 0 \
  --max-instances 3
```

> ⚠️ **Cloud Run + SQLite:** Cloud Run containers are ephemeral — the
> filesystem resets on each cold start. Mount a Cloud Filestore NFS volume
> or switch to Cloud SQL (PostgreSQL) for production persistence.

**Cloud Run with persistent storage:**
```bash
# Create a Filestore instance (NFS)
gcloud filestore instances create rv-data \
  --zone=us-central1-a --tier=BASIC_HDD --file-share=name=data,capacity=1TB \
  --network=name=default

# Mount in Cloud Run (requires VPC connector)
gcloud run services update rv-energy \
  --add-volume name=rv-data,type=nfs,location=FILESTORE_IP:/data \
  --add-volume-mount volume=rv-data,mount-path=/data \
  --set-env-vars DB_PATH=/data/rv_energy.db
```

---

## 13. Cloud Deployment — DigitalOcean App Platform

The simplest managed platform with persistent storage included.

**1. Connect GitHub in DigitalOcean → App Platform → Create App**

**2. Configure the app:**

| Setting | Value |
|---------|-------|
| Source | GitHub repo |
| Branch | `main` |
| Autodeploy | Yes |
| Run command | `uvicorn main:app --host 0.0.0.0 --port $PORT` |
| HTTP port | `5000` |
| Instance size | Basic ($5/mo) |

**3. Add environment variables:**
```
DEBUG = false
DB_PATH = /workspace/data/rv_energy.db
```

**4. Add a persistent volume:**  
App → Settings → **Storage** → Add Volume  
- Mount path: `/workspace/data`
- Size: 1 GB

**5. Deploy** → DigitalOcean builds, deploys, and gives you a `.ondigitalocean.app` URL.

---

## 14. Jetson AGX Orin (Edge / RV Hardware)

Running directly on the Jetson that also hosts PMSV4 — no internet required.

### Install on Jetson (Ubuntu 20.04 / JetPack 5.x)

```bash
# Python 3.11 on JetPack (comes with Python 3.8 by default)
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3.11-dev build-essential

# Clone the code
cd /opt
sudo git clone https://github.com/YOUR_USER/rv-energy-intelligence
sudo chown -R $USER rv-energy-intelligence
cd rv-energy-intelligence

# Virtual environment
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Systemd service for Jetson

```bash
sudo tee /etc/systemd/system/rv-energy.service << 'EOF'
[Unit]
Description=RV Energy Intelligence
After=network.target

[Service]
Type=exec
User=jetson
WorkingDirectory=/opt/rv-energy-intelligence
Environment="PATH=/opt/rv-energy-intelligence/.venv/bin"
Environment="DB_PATH=/opt/rv-energy-intelligence/data/rv_energy.db"
Environment="DEBUG=false"
Environment="HOST=0.0.0.0"
Environment="PORT=5000"
ExecStart=/opt/rv-energy-intelligence/.venv/bin/uvicorn main:app \
          --host 0.0.0.0 --port 5000 --workers 1
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable rv-energy
sudo systemctl start rv-energy
```

### Access from the RV cabin network

The Jetson serves at `http://JETSON_IP:5000`.

Open on any device connected to the same WiFi:
```
# Find Jetson IP
hostname -I

# Open on tablet or phone browser
http://192.168.1.xxx:5000
```

### Auto-start on boot with display (kiosk mode)

If the Jetson is connected to the RV's touchscreen display:
```bash
# Install Chromium
sudo apt install -y chromium-browser

# Create kiosk autostart (for GNOME)
mkdir -p ~/.config/autostart
cat > ~/.config/autostart/rv-kiosk.desktop << 'EOF'
[Desktop Entry]
Type=Application
Name=RV Energy Kiosk
Exec=bash -c "sleep 5 && chromium-browser --kiosk --noerrdialogs --disable-infobars http://localhost:5000"
X-GNOME-Autostart-enabled=true
EOF
```

---

## 15. Production Checklist

Before going live with real users:

### Security
```bash
# 1. Disable debug mode
DEBUG=false

# 2. Restrict CORS (edit main.py)
# Change:    allow_origins=["*"]
# To:        allow_origins=["https://yourdomain.com"]

# 3. Add authentication (optional — for multi-user fleet)
pip install fastapi-users[sqlalchemy]
# See docs/ARCHITECTURE.md — Scale Path section

# 4. Set a strong secret key if you add auth
SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
```

### Performance
```bash
# Multiple workers (CPU-bound workloads)
uvicorn main:app --host 0.0.0.0 --port 5000 --workers 4

# Gunicorn + Uvicorn workers (production standard)
pip install gunicorn
gunicorn main:app \
  -w 4 \
  -k uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:5000 \
  --timeout 60 \
  --access-logfile - \
  --error-logfile -
```

### Database backup
```bash
# Automated daily backup (add to crontab)
# crontab -e
0 2 * * * sqlite3 /path/to/rv_energy.db ".backup /backups/rv_energy_$(date +\%Y\%m\%d).db"

# Backup to S3 (requires awscli)
0 3 * * * aws s3 cp /path/to/rv_energy.db s3://your-bucket/backups/rv_energy_$(date +\%Y\%m\%d).db
```

### SQLite WAL checkpoint (prevent WAL file growing indefinitely)
```bash
# Add to a nightly cron job
sqlite3 /path/to/rv_energy.db "PRAGMA wal_checkpoint(TRUNCATE);"
```

---

## 16. Monitoring & Health

### Health endpoint
```bash
# Returns 200 OK when healthy, 503 when DB unreachable
curl http://localhost:5000/api/health

# Expected response
{
  "status": "ok",
  "version": "2.1.0",
  "db_path": "./data/rv_energy.db",
  "appliances": 19
}
```

### Uptime monitoring (free)
- [UptimeRobot](https://uptimerobot.com) — ping `/api/health` every 5 min
- [Better Uptime](https://betteruptime.com)
- Configure alerts to your email/Slack when the service goes down

### Log aggregation
```bash
# Systemd logs (local)
journalctl -u rv-energy -f                    # follow live
journalctl -u rv-energy --since "1 hour ago"  # last hour
journalctl -u rv-energy -n 100                # last 100 lines

# Docker logs
docker logs rv-energy -f --tail 100

# Ship logs to a cloud provider
# Render/Railway/Fly.io: logs are in their dashboards automatically
```

### Database size check
```bash
sqlite3 ./data/rv_energy.db "
SELECT
  name,
  printf('%.1f KB', page_count * page_size / 1024.0) as size
FROM sqlite_master
JOIN (PRAGMA page_count) ON 1=1
JOIN (PRAGMA page_size) ON 1=1
WHERE type='table';
"

# Quick size check
ls -lh ./data/rv_energy.db

# Count simulation runs
sqlite3 ./data/rv_energy.db "SELECT COUNT(*) FROM simulation_runs;"
```

---

## 17. Troubleshooting

### App won't start — `ModuleNotFoundError`
```bash
# Make sure virtual environment is active
source .venv/bin/activate
which uvicorn   # should show .venv/bin/uvicorn

# Reinstall dependencies
pip install -r requirements.txt
```

### `Address already in use` on port 5000
```bash
# Find what's using the port
lsof -i :5000          # macOS/Linux
netstat -ano | findstr :5000  # Windows

# Kill it or use a different port
uvicorn main:app --port 5001
```

### Database errors — `no such table`
```bash
# Delete the DB and let init_db() recreate it
rm ./data/rv_energy.db
uvicorn main:app --reload
```

### `TemplateNotFound: index.html`
```bash
# Must run uvicorn from the project root (where templates/ exists)
cd rv-energy-intelligence   # ← this directory
uvicorn main:app --reload
```

### Weather not loading
The browser requests your GPS location and fetches from Open-Meteo.
- Make sure the browser is running on HTTPS (GPS requires HTTPS in production)
- Or explicitly allow `http://localhost:5000` location access in browser settings
- Weather is non-blocking — the dashboard works without it, just without live weather

### Slow first request after cold start (Render free tier)
Render free tier spins down after 15 min of inactivity. First request may
take 30–60 seconds. Upgrade to Starter ($7/mo) for always-on.

### Docker container exits immediately
```bash
# Check the exit reason
docker logs rv-energy

# Common cause: data directory permissions
docker run -p 5000:5000 \
  -v $(pwd)/data:/app/data \
  -u $(id -u):$(id -g) \
  rv-energy
```

### Tests fail with `sqlite3.OperationalError`
```bash
# Tests use a temp DB — ensure init_db runs via TestClient lifespan
# Do NOT call init_db() manually before TestClient()
# The test fixture in tests/test_api.py handles this correctly

# Run with verbose output to see which test fails
pytest tests/test_api.py -v -s
```

---

## Quick Reference

```bash
# ── Local dev ──────────────────────────────────────────────────────
source .venv/bin/activate
uvicorn main:app --reload --port 5000

# ── Tests ──────────────────────────────────────────────────────────
pytest tests/ -q                             # run all 100 tests
pytest tests/test_api.py -v                  # API tests only
pytest tests/ --cov=app                      # with coverage

# ── Docker ─────────────────────────────────────────────────────────
docker compose up                            # start
docker compose up --build                    # rebuild + start
docker compose down                          # stop
docker compose logs -f                       # logs

# ── Production (systemd) ───────────────────────────────────────────
sudo systemctl start   rv-energy
sudo systemctl stop    rv-energy
sudo systemctl restart rv-energy
sudo systemctl status  rv-energy
journalctl -u rv-energy -f

# ── API endpoints ──────────────────────────────────────────────────
GET    /                              # Dashboard (HTML)
GET    /docs                          # Swagger UI
GET    /api/health                    # Health check
GET    /api/appliances                # List appliances
POST   /api/appliances                # Create appliance
PUT    /api/appliances/{id}           # Update appliance
DELETE /api/appliances/{id}           # Delete appliance
POST   /api/appliances/{id}/toggle    # Toggle on/off
POST   /api/simulate                  # Run simulation
GET    /api/history                   # Simulation history
POST   /api/weather                   # Log weather reading

# ── SQLite inspection ──────────────────────────────────────────────
sqlite3 data/rv_energy.db ".tables"
sqlite3 data/rv_energy.db "SELECT * FROM appliances LIMIT 5;"
sqlite3 data/rv_energy.db \
  "SELECT si_score, si_grade, created_at FROM simulation_runs \
   ORDER BY created_at DESC LIMIT 10;"
```
