# Workshop Live Interaction Tool

Real-time live poll tool for webinars/workshops.
Built with **Python FastAPI + WebSockets** — no frontend build step required.

---

## Project structure

```
workshop-tool/
├── main.py              ← FastAPI app (backend + WebSocket server)
├── requirements.txt
├── static/
│   ├── participant.html ← What attendees open
│   └── host.html        ← Your control panel
├── workshop.service     ← systemd unit (Oracle Cloud deploy)
└── nginx.conf           ← nginx reverse proxy config
```

---

## Run locally

```bash
# 1. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r dependencies.txt

# 3. Start the server
uvicorn main:app --reload --port 8000
```

Open in browser:
- **Host panel:**   http://localhost:8000/host
- **Participant:**  http://localhost:8000/

---

## Deploy to Oracle Cloud Free Tier (Ubuntu ARM VM)

### 1. SSH into your VM and clone/copy the project
```bash
scp -r workshop-tool ubuntu@YOUR_VM_IP:~/
```

### 2. Install Python + nginx
```bash
sudo apt update && sudo apt install -y python3-venv python3-pip nginx
```

### 3. Create venv and install dependencies
```bash
cd ~/workshop-tool
python3 -m venv venv
venv/bin/pip install -r dependencies.txt
```

### 4. Install and enable the systemd service
```bash
sudo cp workshop.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable workshop
sudo systemctl start workshop
sudo systemctl status workshop   # should show: active (running)
```

### 5. Configure nginx
```bash
# Edit nginx.conf: replace YOUR_DOMAIN_OR_IP with your VM's public IP
sudo cp nginx.conf /etc/nginx/sites-available/workshop
sudo ln -s /etc/nginx/sites-available/workshop /etc/nginx/sites-enabled/
sudo nginx -t                    # test config
sudo systemctl reload nginx
```

### 6. Open firewall port 80 in Oracle Cloud Console
In the OCI Console → Networking → VCN → Security Lists → add ingress rule:
- Source: 0.0.0.0/0
- Protocol: TCP
- Port: 80

Also run on the VM:
```bash
sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT
sudo netfilter-persistent save    # install with: apt install iptables-persistent
```

Your app is now live at:
- `http://YOUR_VM_IP/`       ← share this with participants
- `http://YOUR_VM_IP/host`   ← your control panel

---

## Usage flow

1. Open `/host` in your browser before the session starts
2. Create a poll (question + options)
3. Click **Open voting** when you're ready
4. Participants vote at `/` — results update live for everyone
5. Click **Close voting** to freeze results
6. Click **Remove poll** to clear and prepare the next one

---

## Next steps (future phases)

- [ ] Add Q&A with upvoting
- [ ] Add word cloud
- [ ] Add simple host password (HTTP Basic Auth in nginx, or a token check in FastAPI)
- [ ] HTTPS via Let's Encrypt: `sudo certbot --nginx`
- [ ] Claude API integration for Q&A summarisation
```
