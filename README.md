<div align="center">
 #### Has a Key Auth If u need one Dm me Discord: Zxpyar. (with the dot)
# 🎮 Minecraft Account Manager & Launcher

#### A powerful, all-in-one multi-account (ALT) manager and game launcher for Minecraft players

<p>All in one place — <b>Token &amp; Cookie Converter</b> · <b>Account Manager</b> · <b>Game Launcher</b> · <b>Cloud Sync</b> · <b>Skin &amp; Capes</b></p>

<br/>

<img src="https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078D6.svg?style=flat-square&logo=windows&logoColor=white" alt="platform"/>
<img src="https://img.shields.io/badge/Minecraft-All%20Versions-5B8C51.svg?style=flat-square&logo=minecraft&logoColor=white" alt="Minecraft"/>
<img src="https://img.shields.io/badge/UI-CustomTkinter%20·%20Dark%20Theme-2D7D9A.svg?style=flat-square" alt="UI"/>
<img src="https://img.shields.io/badge/Status-Active%20%2F%20Maintained-success.svg?style=flat-square" alt="Status"/>
<img src="https://img.shields.io/badge/version-2.0.0-blue.svg?style=flat-square" alt="version"/>

<br/>
<br/>

<a href="#-features">Features</a> ·
<a href="#-download">Download</a> ·
<a href="#-getting-started">Getting Started</a> ·
<a href="#️-system-requirements">Requirements</a> ·
<a href="#-security--disclaimer">Security</a>

</div>

---

## ✨ What is this

**Minecraft Account Manager 2.0** is an all-in-one multi-account (ALT) management suite and built-in Minecraft client launcher.

Drop in your Access Tokens, Refresh Tokens, or Microsoft session cookies (`ESTSAUTH`, `RPSTicket`, Netscape, JSON format). The app validates them in milliseconds, organizes your accounts into a clean interactive card wall, displays real-time 3D skin avatars & capes, and lets you **launch directly into any Minecraft version with one click**!

> [!WARNING]
> For personal account management and educational purposes only. Do not use this software for anything that violates the Minecraft, Mojang, or Microsoft Terms of Service.

---

## 🚀 Features

<table>
<tr>
<td width="50%" valign="top">

### 🎮 Integrated Game Launcher
Launch directly into Minecraft with any account in seconds.

- **Multi-Version Support:** Vanilla `1.21`, `1.20.4`, `1.8.9`, `Fabric`, `Forge`, `OptiFine`, `Snapshots`, and custom versions
- **🌐 Quick-Join Server:** Auto-connect straight into any server (e.g. `play.hypixel.net`) on boot
- **📁 Folder Shortcuts:** 1-Click access to `Mods`, `Resourcepacks`, `Saves`, and `.minecraft` folders
- **Automatic 64-Bit Java Detection:** Auto-detects bundled modern OpenJDK (`java-runtime-delta` / Java 21) across Windows, macOS, and Linux
- **RAM & Performance Tuning:** Flexible memory allocation (2 GB – 16 GB) + optimized JVM flags (`G1GC`)
- **Version Downloader:** Download official vanilla versions directly with live progress
- **Live Game Console:** Real-time log streaming with instant `⏹ Kill Game` capability

</td>
<td width="50%" valign="top">

### 🗂️ Account Wall & Management
Bring all your Minecraft accounts together in a modern visual interface.

- **🏷️ Account Categories & Tags:** Tag accounts with `⭐ Main`, `🌾 Alt / Farm`, `🏆 Ranked`, `💎 Cape`, `📦 Bulk`, `🚫 Banned`
- **⚡ Concurrent Multi-Threading:** 10x faster parallel checking via `ThreadPoolExecutor`
- **📊 Real-time Stats Chips:** Instant topbar counters for Total, Active, Invalid, and Capes
- **Grid & List Views:** Toggle between beautiful 3D cards and compact table views
- **🌐 NameMC & Hypixel Stats:** 1-Click profile & stats lookup on NameMC and Plancke
- **🧹 Clean Invalid Tool:** 1-Click cleanup to remove all expired/invalid accounts
- **Live Mojang Validator:** Real-time verification of account status, username, UUID, and official Mojang capes
- **3D Skin Avatars:** High-resolution skin head rendering with local caching

</td>
</tr>
<tr>
<td width="50%" valign="top">

### ⚡ High-Speed Cookie & Token Scanner
Lightning-fast targeted file and ZIP log extractor.

- **Smart Cookie Parser:** Automatically resolves real gamer tags and email hints instead of generic labels
- **ZIP Archive Processing:** Scans archives in milliseconds using byte-level keyword filtering
- **Multi-Format Support:** Extracts `Cookie-Editor JSON`, `Netscape cookies.txt`, raw session headers, and combos (`user:pass:token`)
- **🌐 Proxy Routing:** SOCKS5 and HTTP proxy support for bypass and security
- **Bulk Import Dialog:** Visual progress bar with live active/invalid statistics

</td>
<td width="50%" valign="top">

### ☁️ Cloud Sync, Backups & Discord RPC
Keep your accounts synchronized and show off your status.

- **🎮 Discord Rich Presence:** Live Discord status showing your active Minecraft session & account
- **📦 Automated Backups & Restore:** Local daily timestamped JSON backups with 15-day rotation
- **Realtime Cloud Database:** Automatic Supabase cloud synchronization for your accounts
- **📢 Discord Webhooks:** Automated alerts and reports sent straight to your Discord server
- **Multi-Profile Login:** Individual local user profiles with SHA-256 secure credentials
- **Export Formats:** Export accounts to JSON, active tokens, session cookies, or combo lists

</td>
</tr>
</table>

---

## ⬇️ Download & Install

Choose your platform below:

### 🪟 Windows — Standalone `.exe` (No Python required)
> Just download and double-click — zero setup needed!

### 👉 **[Download AccountManager.exe (Latest Release)](https://github.com/kontoist9-tech/Minecraft-Alts-Manager/releases/latest)**

---

### 🍎 macOS — Python Installer

**Requirements:** Python 3.10+ (install via [python.org](https://www.python.org/downloads/) or `brew install python`)

```bash
# 1. Clone or download the repository
git clone https://github.com/kontoist9-tech/Minecraft-Alts-Manager.git
cd Minecraft-Alts-Manager

# 2. Run the installer (installs dependencies + launches the app)
chmod +x install.sh
./install.sh
```

> **Note for macOS:** If you see a *"cannot be opened"* warning, go to **System Settings → Privacy & Security** and click **"Open Anyway"**.

---

### 🐧 Linux — Python Installer

```bash
# 1. Clone or download the repository
git clone https://github.com/kontoist9-tech/Minecraft-Alts-Manager.git
cd Minecraft-Alts-Manager

# 2. Run the installer
chmod +x install.sh
./install.sh
```

> **Linux:** You may need to install `python3-tk` first: `sudo apt install python3-tk` (Ubuntu/Debian)

---

## 🚀 Getting Started

1. **Launch:** Start the app via `AccountManager.exe` (Windows) or `./install.sh` (Mac/Linux).
2. **Import Accounts:**
   - Click **`+ Add`** to add an account manually.

   - Click **`📦 Import`** to scan ZIP logs or token files.
   - Click **`📋 Paste`** to paste raw tokens or cookie headers directly.
4. **Play:**
   - Switch to the **`🎮 Game Launcher`** tab in the sidebar.
   - Select your profile and desired Minecraft version.
   - Click **`🚀 LAUNCH MINECRAFT`**!

---

## ⚙️ System Requirements

| Component | Requirement |
| :--- | :--- |
| **Operating System** | Windows 10 / Windows 11 (64-Bit) |
| **Java Runtime** | Java 8+ / Java 17+ / Java 21+ (Auto-detected from `.minecraft\runtime`) |
| **Storage** | ~25 MB portable standalone `.exe` |

---

## 🔒 Security & Disclaimer

- All account data is stored locally on your device in your user directory.
- Authentication tokens and session cookies are verified directly through official Microsoft & Mojang endpoints (`api.minecraftservices.com` / `login.live.com`).
- No source code or credentials are ever sent to third parties.

---

<div align="center">
  <sub>Developed with ❤️ for the Minecraft community.</sub>
</div>
