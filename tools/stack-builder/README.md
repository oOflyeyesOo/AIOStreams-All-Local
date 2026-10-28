# 🛠️ AIO Custom Stack Builder (Offline Generator)

A standalone, 100% client-side visual configuration tool for users who want to craft a custom or reduced multi-container `docker-compose.yml` and `.env` setup.

---

## 🚀 How to Use

1. **Open the Builder**: Double-click **`index.html`** in this folder to open it in any web browser. No running containers, local server, or internet connection are required.
2. **Select Services**: Choose one of the quick configuration presets (Full Stack, High-Speed Lean, Catalogs & Subtitles Only, Minimal Debrid Core) or toggle individual microservices on or off.
3. **Set Your Keys**: Enter your server address and external credentials (TMDB API key, Real-Debrid token, etc.). Internal passwords and cross-service tokens are pre-matched automatically.
4. **Export Configuration**:
   * Click **Copy** or **Download** on any tab (`docker-compose.yml`, `.env`, `01-init-dbs.sql`, or `1-Image Run`).
   * Or click **📦 Download All Files Manually** to download the complete set.
5. **Launch Anywhere**:
   Place the downloaded files in any directory on your target host and start:
   ```bash
   docker compose up -d
   ```
