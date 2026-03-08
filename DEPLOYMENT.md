# Xpenology (Synology) Deployment Instructions

This guide explains how to deploy the **Paribu Trading Bot** on your Xpenology NAS using Docker.

## Prerequisites
- **Container Manager** (or Docker) installed on your NAS.
- **SSH Access** enabled (optional but recommended for easier setup).
- The `borsa` folder copied to your NAS (e.g., `/volume1/docker/borsa`).

## Method 1: Using Task Scheduler (Recommended)
Since Xpenology's UI sometimes has issues with `docker-compose` builds, we will use the Task Scheduler.

1.  **Upload Files**: Upload the entire `borsa` folder (containing `Dockerfile`, `docker-compose.yml`, `main.py`, etc.) to your NAS. Let's assume the path is `/volume1/docker/borsa`.
2.  **Open Control Panel**: Go to **Control Panel** > **Task Scheduler**.
3.  **Create Task**: Click **Create** > **Scheduled Task** > **User-defined script**.
4.  **General Tab**:
    - Task: `Deploy Paribu Bot`
    - User: `root` (Important!)
    - Uncheck "Enabled" (We only run it manually).
5.  **Task Settings Tab**:
    - Run command:
      ```bash
      cd /volume1/docker/borsa
      docker-compose up -d --build
      ```
6.  **Run**: Save the task, select it, and click **Run**.
7.  **Verify**: Open **Container Manager** > **Container**. You should see `paribu-bot` running.

## Method 2: SSH
1.  Connect to your NAS via SSH: `ssh user@nas-ip`
2.  Switch to root: `sudo -i`
3.  Navigate to folder: `cd /volume1/docker/borsa`
4.  Run: `docker-compose up -d --build`

## Configuration
To change API keys or settings, edit the `docker-compose.yml` file directly or create a `.env` file in the same folder.

```env
PARIBU_API_KEY=your_key_here
PARIBU_API_SECRET=your_secret_here
```
