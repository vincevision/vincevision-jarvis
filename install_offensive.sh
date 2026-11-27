#!/bin/bash
# JARVIS Offensive Security - System Dependencies Installer

echo "[JARVIS] Installing offensive security dependencies..."

sudo apt update -y

# WiFi tools
sudo apt install -y \
    aircrack-ng \
    airmon-ng \
    aireplay-ng \
    airodump-ng \
    hostapd \
    dnsmasq \
    iw \
    wireless-tools

# Exploitation
sudo apt install -y \
    metasploit-framework \
    exploitdb \
    searchsploit

# OSINT
sudo apt install -y \
    theharvester \
    recon-ng \
    maltego \
    whois \
    dnsutils

# Dark Web / Anonymity
sudo apt install -y \
    tor \
    proxychains4 \
    torbrowser-launcher

# Input tools
sudo apt install -y \
    xinput \
    xdotool

# Network tools
sudo apt install -y \
    netcat-openbsd \
    nmap \
    curl \
    socat

# Install Sherlock via pip
pip install sherlock-project

echo "[JARVIS] ✅ All offensive security dependencies installed."