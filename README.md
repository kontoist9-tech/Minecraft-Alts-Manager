<div align="center">

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

- **Multi-Version Support:** Vanilla `1.20.4`, `1.8.9`, `Fabric`, `Forge`, `OptiFine`, `Snapshots`, and custom versions
- **Automatic 64-Bit Java Detection:** Auto-detects bundled modern OpenJDK (`java-runtime-delta` / Java 21) from `.minecraft`
- **RAM & Performance Tuning:** Flexible memory allocation (2 GB – 16 GB) + optimized JVM flags (`G1GC`)
- **Version Downloader:** Download official vanilla versions directly with live progress
- **Live Game Console:** Real-time log streaming with instant `⏹ Kill Game` capability

</td>
<td width="50%" valign="top">

### 🗂️ Account Wall & Management
Bring all your Minecraft accounts together in a modern visual interface.

- **Grid & List Views:** Toggle between beautiful 3D cards and compact table views
- **Instant Search & Filters:** Filter by Active, Invalid, Banned, Sold, or custom notes
- **Live Mojang Validator:** Real-time verification of account status, username, UUID, and official Mojang capes
- **3D Skin Avatars:** High-resolution skin head rendering with local caching
- **One-Click Actions:** Copy tokens, copy cookies, or refresh validation instantly

</td>
</tr>
<tr>
<td width="50%" valign="top">

### ⚡ High-Speed Cookie & Token Scanner
Lightning-fast targeted file and ZIP log extractor.

- **ZIP Archive Processing:** Scans archives in milliseconds using byte-level keyword filtering
- **Multi-Format Support:** Extracts `Cookie-Editor JSON`, `Netscape cookies.txt`, raw session headers, and combos (`user:pass:token`)
- **Smart Domain Filter:** Strictly targets Microsoft & Minecraft authentication (`.live.com`, `.xboxlive.com`, `ESTSAUTH`, `RPSTicket`)
- **Bulk Import Dialog:** Visual progress bar with live active/invalid statistics

</td>
<td width="50%" valign="top">

### ☁️ Cloud Sync & Multi-User Support
Never lose your accounts across multiple computers.

- **Realtime Cloud Database:** Automatic Supabase cloud synchronization for your accounts
- **Multi-Profile Login:** Individual local user profiles with SHA-256 secure credentials
- **Role-Based Views:** Standard users see their personal accounts, while admin views the master database
- **Export Formats:** Export accounts to JSON, active tokens, session cookies, or combo lists

</td>
</tr>
</table>

---

## ⬇️ Download

Get the pre-compiled standalone executable — no Python or extra dependencies required:

### 👉 **[Download AccountManager.exe (Latest Release)](https://github.com/kontoist9-tech/Minecraft-Alts-Manager/releases/latest)**

---

## 🚀 Getting Started

1. **Download:** Download the latest `AccountManager.exe` from the [Releases](https://github.com/kontoist9-tech/Minecraft-Alts-Manager/releases/latest) page.
2. **Launch:** Run `AccountManager.exe` by double-clicking it.
3. **Import Accounts:**
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
