# Open WebUI Plugins for AirPods

Auto-installed custom filters for Open WebUI. Synced automatically on `airpods start open-webui`.

## Plugin Categories

### 🔧 Basic Filters
- **system_prompt_enforcer** - Enforce consistent system prompts
- **profanity_filter** - Filter inappropriate language
- **token_counter** - Track and limit token usage
- **auto_summarizer** - Auto-request summaries in long chats
- **code_detector** - Detect programming languages in code blocks
- **timestamp_logger** - Add timestamps for analytics

### 🚀 Advanced Workflows
- **vision_joycaption** - Add vision to non-vision models via JoyCaption API
- **twitter_scraper** - Scrape Twitter/X via Nitter (no API required)
- **web_researcher** - Auto web search for current information

## Auto-Installation

Plugins sync automatically when starting Open WebUI:

\`\`\`bash
airpods start open-webui
# Output: ✓ Synced 9 plugin(s)
\`\`\`

Files are copied to \`$AIRPODS_HOME/volumes/webui_plugins/\` and mounted into the container.

## Usage

1. Start: \`airpods start open-webui\`
2. Open http://localhost:3000
3. Go to **Admin Panel → Functions**
4. Enable desired plugins
5. Configure settings (valves)

## Advanced Plugin Examples

### Vision via JoyCaption

Enables image understanding for models like llama3/mistral that lack native vision:

\`\`\`bash
# Deploy JoyCaption (example)
docker run -d --name joycaption -p 5000:5000 --gpus all fancyfeast/joycaption:latest
\`\`\`

Then configure the valve in Open WebUI to point to \`http://joycaption:5000/caption\`.

### Twitter Scraper

Scrapes tweets without Twitter API:

**Trigger examples:**
- "Show me @elonmusk's latest tweets"
- "What's trending on Twitter about AI?"

Uses Nitter (privacy-friendly frontend). Optionally self-host for reliability.

### Web Researcher

Auto-searches when queries need current info:

**Trigger examples:**
- "What is the latest news about GPT-5?"
- "Current Bitcoin price"
- "Recent quantum computing developments"

## Creating Custom Plugins

Template:

\`\`\`python
"""
title: My Plugin
author: you
version: 0.1.0
"""

from pydantic import BaseModel, Field
from typing import Optional

class Filter:
    class Valves(BaseModel):
        priority: int = Field(default=0)

    def __init__(self):
        self.valves = self.Valves()

    def inlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        # Modify request before AI
        return body

    def outlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        # Modify response after AI
        return body
\`\`\`

Save in \`plugins/open-webui/\`, restart Open WebUI, enable in Admin Panel.

## Troubleshooting

**Plugins not showing:**
- Check \`airpods logs open-webui\`
- Verify in \`$AIRPODS_HOME/volumes/webui_plugins/\`
- Restart: \`airpods stop open-webui && airpods start open-webui\`

**Vision/scraping not working:**
- Check external service is running and accessible
- Verify network connectivity in logs
- Update valve URLs to match your setup

See [Open WebUI Functions docs](https://docs.openwebui.com/features/plugin_system/) for more details.
