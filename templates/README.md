# 📑 AIOStreams Community Templates & Preset Hub

This directory contains curated, tested community templates, layouts, stream formatters, and Stream Expression Language (SEL) filtering rules for **AIOStreams** and **AIOMetadata**.

---

## 🗂️ Directory Organization

```
templates/
├── builtin/                    # Mounted directly to /app/resources/templates in AIOStreams
│   ├── all-local-selfhosted.json   # 100% Local Self-Hosted Stack template (pre-routed Docker hosts)
│   └── debrid-starter.json         # Native AIOStreams Debrid Starter template
│
├── setup-templates/            # Complete AIOStreams configurations ready for 1-Click Import
│   ├── all-local-selfhosted.json           # All-Local Docker stack (Comet, MediaFusion, AIOMetadata, SubSense, etc.)
│   ├── tamtaro-complete-setup-template.json# Tam-Taro Complete SEL Setup (Debrid/Usenet/P2P detection, failovers)
│   ├── tamtaro-partial-setup-template.json # Tam-Taro Lean partial setup
│   ├── tamtaro-all-templates-collection.json# Master collection of all Tamtaro configurations
│   ├── core-builds-base-config.json        # brevityA Core-Builds Base Performance setup
│   ├── core-stable-torbox-4k.json          # brevityA Stable 4K build
│   ├── core-stable-torbox-1080p.json       # brevityA Stable 1080p build
│   ├── core-nexus-base-torbox.json         # brevityA Nexus Base Torbox build
│   ├── prism-torbox-essential-1080p.json   # MightyIcyy Prism Essential build
│   ├── auburn-tiger-rb3.json               # RB3 Auburn Tiger community edition
│   ├── grabberhawk-aiostreams-config.json  # Grabberhawk Fast Retrieval profile
│   ├── ang3lo-config-english-only.json     # Ang3lo English-focused profile
│   └── ang3lo-config-portuguese.json       # Ang3lo Dual English / Portuguese profile
│
├── formatters/                 # Custom Stream Formatter layouts for Stremio video cards
│   ├── core-nexus-apex-v2-formatter.json   # Apex v2: Modern badges, resolution, audio channels, size
│   ├── core-nexus-elite-formatter.json     # Elite: Compact cards with high-density metadata
│   ├── core-nexus-minimal-formatter.json   # Minimal: Clean single-line styling
│   ├── core-nexus-sigma-formatter.json     # Sigma: Comprehensive technical stream specs
│   ├── core-nexus-tv-formatter.json        # TV: Optimized for Android TV / large screens
│   ├── core-nexus-ultra-formatter.json     # Ultra: Ultra-compact stream naming
│   ├── core-nexus-uniform-formatter.json   # Uniform: Standardized grid spacing
│   ├── core-syntax-v3.json                 # Syntax v3: Colorful release tag formatting
│   ├── core-zenith-diamond.json            # Diamond: Premium gradient styling
│   ├── midnight-slate.json                 # Midnight Slate: Dark slate color palette
│   ├── nexus-prime-formatter.json          # Nexus Prime: Streamlined prime layout
│   ├── rb3-clean-v4-formatter.json         # RB3 Clean v4: Clean community formatter
│   └── core-clean.json                     # Core Clean: Minimalist baseline
│
├── filtering-and-expressions/  # Stream Expression Language (SEL) rules & Synced URLs
│   ├── tamtaro-synced-ese-standard.json    # Standard Excluded Stream Expressions (CAM, TS, Low-res)
│   ├── tamtaro-synced-ese-extended.json    # Extended Excluded Stream Expressions (Anti-spam, strict audio)
│   ├── tamtaro-synced-ise.json             # Included Stream Expressions
│   ├── tamtaro-synced-pse.json             # Priority Stream Expressions (REMUX & high-bitrate prioritizer)
│   ├── tamtaro-synced-excluded-regex.json  # Excluded regex patterns
│   ├── vidhin-english-expressions.json     # Vidhin English Ranked Stream Expressions (RSE quality tiers & penalties)
│   ├── vidhin-english-legacy-expressions.json # Vidhin Legacy English Release Group Expressions
│   ├── vidhin-german-expressions.json      # Vidhin German Ranked Stream Expressions
│   ├── core-builds-eses.json               # brevityA Excluded Stream Expressions
│   ├── core-builds-eses-v2-beta.json       # brevityA ESE v2 Beta
│   ├── core-builds-ises.json               # brevityA Included Stream Expressions
│   ├── core-builds-pses.json               # brevityA Priority Stream Expressions
│   └── ranked-regex-patterns.json          # Priority release group ranking expressions
│
├── regex-rankings/             # TRaSH Guides & PMM Release Group Regex Patterns
│   ├── vidhin-all-templates.json           # Vidhin05 Master Wizard (English, German, Legacy English)
│   ├── vidhin-english-regexes.json         # Vidhin English TRaSH Regex Patterns (Audio, Video, Anime, Streaming)
│   ├── vidhin-german-regexes.json          # Vidhin German TRaSH Regex Patterns
│   └── vidhin-trash-regex-all.json         # Vidhin05 Merged Release Regexes (all tiers & quality groups)
│
└── aiometadata-configs/        # Metadata & Catalog Replacement Profiles (for port 4005)
    ├── tamtaro-aiometadata-with-anime.json # Tam-Taro rich catalogs + Anime categories
    ├── tamtaro-aiometadata-without-anime.json # Tam-Taro rich catalogs (Western focus)
    └── grabberhawk-aiometadata-config.json  # Grabberhawk catalog curation profile
```

---

## 🚀 How to Use Templates in AIOStreams

### Method 1: 1-Click Launch via URL
When accessing your local AIOStreams instance, append `?template=<URL>`:
```
http://localhost:3000/stremio/configure?template=http://localhost:8088/templates/setup-templates/all-local-selfhosted.json
```
Or use the direct GitHub Raw link:
```
http://localhost:3000/stremio/configure?template=https://raw.githubusercontent.com/Tam-Taro/SEL-Filtering-and-Sorting/main/AIOStreams%20Templates/Tamtaro-complete-setup-template.json
```
AIOStreams will automatically load the template and walk you through the configuration wizard.

---

### Method 2: Manual Import via AIOStreams UI
1. Open your AIOStreams web page (`http://localhost:3000` or your domain).
2. Go to the **Save & Install** tab (at the bottom of the left sidebar).
3. Click **"Import"**.
4. Either:
   * Paste the template JSON content, or
   * Select a downloaded `.json` file from `templates/setup-templates/`.
5. Enter your personal credentials (e.g., Real-Debrid API key) when prompted, and save!

---

### Method 3: Using Formatter Layouts
1. Open AIOStreams and go to the **Stream Formatter** section.
2. Select **Custom Formatter**.
3. Open any file in `templates/formatters/` (e.g. `core-nexus-apex-v2-formatter.json`).
4. Copy the `name` and `description` template strings into AIOStreams, or paste the entire formatter JSON in the Import box.

---

### Method 4: Auto-Updating Synced URLs
AIOStreams supports **Synced URLs** for Excluded/Included expressions:
1. In AIOStreams, go to **Filters** -> **Excluded Stream Expressions (ESE)**.
2. Under **Synced URLs**, paste the direct raw URL of any file in `templates/filtering-and-expressions/`.
3. Whenever the template updates, your AIOStreams instance automatically pulls the newest filter rules.

---

## ⚡ Tam-Taro SEL & AIOMetadata Quick-Start Guide

Tam-Taro's setup is the community gold standard for AIOStreams. This repository has pre-configured your self-hosted Docker instance with:
- **`FEATURED_TEMPLATE_IDS=tamtaro.complete,Vidhin05.english-template`**: Tam-Taro Complete appears at the top of the AIOStreams template selection.
- **Auto-Sync Engine (`SEL_SYNC_ACCESS=all`)**: Excluded stream expressions (CAMs, TS, screeners) and priority rankings auto-sync every hour from GitHub hotfixes.
- **Vidhin TRaSH Regex Integration**: Merged release group tiers are whitelisted and pre-linked.

### 1. Running Tam-Taro's Setup Wizard in AIOStreams
1. Open AIOStreams (`http://localhost:3000` or your domain).
2. Go to **Templates** &rarr; select **Tamtaro Complete SEL Setup** (pinned at top), or click **Open in AIOStreams** in the Dashboard Templates Hub.
3. Follow the wizard steps:
   - **Mode Selection**: Select your Debrid provider (Real-Debrid, Premiumize, Torbox) or P2P mode.
   - **Language Settings**: Select your preferred stream languages (Default: English).
   - **Filter Exclusions**: Anti-CAM, anti-telesync, and anti-upscale filters are enabled automatically via synced URLs.
   - **Formatter Style**: Choose between Tam-Taro's clean layout or one of the brevityA Apex/Diamond formatters.
4. Save and generate your AIOStreams manifest URL!

### 2. Pairing with AIOMetadata (Port 4005)
Tam-Taro's template intentionally **omits catalogs** so that users can pair AIOStreams with **AIOMetadata** for rich, customizable streaming provider rows and ratings badges (IMDb, Rotten Tomatoes, Trakt):
1. In [`dashboard.html`](../dashboard.html), navigate to the **AIOMetadata (:4005)** card.
2. Click **"Tam-Taro Presets 📑"** and choose:
   - `Tam-Taro AIOMetadata Profile (With Anime)`: Netflix, Disney+, Apple TV+, Max, Prime Video + Anime catalogs.
   - `Tam-Taro AIOMetadata Profile (Western Only)`: Western streaming providers with ratings.
3. Click **"📋 Copy Config"** to copy the full configuration JSON to your clipboard.
4. Click **"Configure UI ↗"** to open AIOMetadata at `http://localhost:4005`.
5. In AIOMetadata, click **Import** &rarr; paste the JSON &rarr; click **Save & Install**.
6. Install AIOMetadata in Stremio/Nuvio: your catalogs will now display beautiful provider categories and ratings, while AIOStreams resolves the streams!

---

## 🎯 Vidhin's TRaSH Regexes & Ranked Stream Expressions (RSE)

Sourced directly from **[Vidhin05/Releases-Regex](https://github.com/Vidhin05/Releases-Regex)** and [TRaSH Guides](https://trash-guides.info), this engine automatically scores and sorts streams based on source quality (Remux, Bluray, WEB), release groups, audio/visual tags (HDR, Atmos, DTS), and unwanted tag penalties.

### ⚙️ How Vidhin's Scoring Architecture Operates
Vidhin's setup coordinates two distinct layers:
1. **Regex Patterns (`regexes.json`)**: High-performance regex patterns matching raw release titles and filenames.
2. **Ranked Stream Expressions (`expressions.json`)**: Evaluates those regex patterns, assigns calibrated positive and negative scores, executes query-type validations, and generates clean RSE tags.

### ⚠️ Essential Setup Instructions:
1. **Sort Order Requirement**:
   * In AIOStreams, add **Stream Expression Score** to your sort order (NOT the legacy `Regex` sort).
2. **Custom Formatter Tags**:
   * Always use `{stream.seScore}` and `{stream.rseMatched}`.
   * **Do NOT use `{stream.regexMatched}`**: `regexMatched` only returns the first raw pattern it matches (for instance, showing `Web T1` instead of `Web T3` on anime releases). `{stream.rseMatched}` accurately reflects the scoring engine's decisions.

| Formatter Syntax | Output Behavior |
| :--- | :--- |
| `{stream.rseMatched}` | **Recommended.** Shows all matched expressions (tiers, Dual Audio/Uncensored bonuses, penalties). |
| `{stream.rseMatched::first}` | Displays the first matched element only. |
| `{stream.rseMatched::first::~ T["{stream.rseMatched::first}"\|\|""]}` | **Tier only** (e.g. `Remux T1`, `Web T1`) — filters when containing ` T`, suppressing bonus tags. |
| `{stream.seScore}` | The calculated numeric stream score. |

### 🔄 Supported Auto-Sync Variants:
* **English**: Complete scoring across Quality (Remux, Bluray, Web, Asian tiers), Anime (BD/Web, SeaDex Best/Alt, Uncensored), Audio hierarchy, Visual (HDR10+, Dolby Vision), Movie boutique labels, and streaming source boosts.
* **German**: All English features plus TRaSH DE quality profiles (DE DL, DE-only, Web Scene DE, DE Anime BD/Web tiers, Microsized).
* **Legacy English**: Lightweight release-group preference scoring.

---

## 🌟 Upstream Credits & Sources
* **[Tam-Taro/SEL-Filtering-and-Sorting](https://github.com/Tam-Taro/SEL-Filtering-and-Sorting)**: Complete SEL Setup, Synced Expressions, and AIOMetadata configs.
* **[brevityA/Core-Builds](https://github.com/brevityA/Core-Builds)**: Core Nexus formatters, performance profiles, and deduplication rules.
* **[Vidhin05/Releases-Regex](https://github.com/Vidhin05/Releases-Regex)**: Merged TRaSH Guides release group regexes.
* **[Viren070/AIOStreams](https://github.com/Viren070/AIOStreams)**: Official AIOStreams engine and native template engine.
* **[Ang3lo-Azevedo/AIOStreams-config](https://github.com/Ang3lo-Azevedo/AIOStreams-config)**: Multilingual configuration profiles.
* **[grabberhawk/stremio-aiostreams-config](https://github.com/grabberhawk/stremio-aiostreams-config)**: Streamlined retrieval and AIOMetadata presets.

