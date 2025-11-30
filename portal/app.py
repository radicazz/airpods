"""Airpod Portal - Web interface for managing AI services."""
from __future__ import annotations

import os
from flask import Flask, render_template, jsonify

app = Flask(__name__)
app.secret_key = os.environ.get("PORTAL_SECRET_KEY", "dev-secret-change-me")


@app.route("/")
def index():
    """Portal landing page."""
    services = [
        {
            "name": "open-webui",
            "display_name": "Chat",
            "path": "/chat",
            "icon": "💬",
            "description": "AI Chat Interface",
            "enabled": True,
        },
        {
            "name": "comfyui",
            "display_name": "ComfyUI",
            "path": "/comfy",
            "icon": "🎨",
            "description": "Stable Diffusion Workflows",
            "enabled": True,
        },
    ]
    return render_template("index.html", services=services, title="Airpod Services")


@app.route("/health")
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok"})


@app.route("/api/services")
def api_services():
    """API endpoint for service list."""
    services = [
        {
            "name": "open-webui",
            "display_name": "Chat",
            "path": "/chat",
            "icon": "💬",
            "description": "AI Chat Interface",
            "enabled": True,
        },
        {
            "name": "comfyui",
            "display_name": "ComfyUI",
            "path": "/comfy",
            "icon": "🎨",
            "description": "Stable Diffusion Workflows",
            "enabled": True,
        },
    ]
    return jsonify({"services": services})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
