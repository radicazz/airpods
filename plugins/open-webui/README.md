# Open WebUI Extensions for AirPods

Auto-installed custom Tools, Functions, and Pipelines for Open WebUI. Automatically synced to the filesystem and imported into the database on `airpods start open-webui`.

## Extension Types

Open WebUI supports three types of extensions:

- **Tools** - Extend LLM capabilities with real-time data access (weather, stocks, web search, etc.)
- **Functions** - Enhance Open WebUI features (custom UI elements, response formatting, content filtering)
- **Pipelines** - Advanced API workflows for heavy processing or request transformation

## Available Extensions

### Tools (Real-time Data Access)
- **weather_tool** - Fetch real-time weather data for any location using wttr.in API

### Functions (UI & Feature Enhancements)
- **system_prompt_enforcer** - Enforce consistent system prompts across conversations
- **code_detector** - Detect programming languages in code blocks and add helpful context
- **token_counter** - Track and limit token usage with basic estimation
- **markdown_enhancer_function** - Add custom UI elements (collapsible sections, info boxes, code metadata)

### Pipelines (Advanced Processing)
- **content_moderation_pipeline** - Filter toxic/harmful content and detect PII before/after LLM processing

## Auto-Installation

Plugins are automatically synced and imported when starting Open WebUI:

```bash
airpods start open-webui
# Output during startup:
# ✓ Synced 6 extension(s)
# ... (service starts and becomes healthy) ...
# ✓ Auto-imported 6 extension(s) into Open WebUI
```

The process:
1. **Filesystem sync**: Extension files are copied from `plugins/open-webui/` to `$AIRPODS_HOME/volumes/webui_plugins/`
2. **Container mount**: The `webui_plugins` directory is mounted to `/app/backend/data/functions` in the container
3. **Database import**: Once Open WebUI is healthy, extensions are automatically imported into the database via the API
4. **Ready to use**: Extensions appear in the Admin Panel (Tools, Functions, or Pipelines sections), ready to enable and configure

## Usage

1. Start: `airpods start open-webui`
2. Open http://localhost:3000
3. Go to **Admin Panel** → **Tools** / **Functions** / **Pipelines** (depending on extension type)
4. Extensions are already imported—just enable and configure them
5. Adjust settings (valves) as needed

## Extension Details

### Weather Tool
Allows LLMs to fetch real-time weather information:
- Uses free wttr.in API (no API key required)
- Supports metric/imperial units
- Returns temperature, conditions, humidity, wind, UV index, etc.
- Example: LLM can respond to "What's the weather in London?" with live data

### Markdown Enhancer Function
Enhances AI responses with custom UI elements:
- Adds metadata badges to code blocks (language, line count)
- Auto-collapses long code blocks for readability
- Converts `[INFO]`, `[WARNING]`, `[ERROR]` markers into styled boxes
- Configurable via valves (enable/disable features, set collapse threshold)

### Content Moderation Pipeline
Advanced safety layer for LLM interactions:
- Filters harmful content patterns before sending to LLM
- Detects and optionally redacts PII (emails, SSNs, credit cards, phone numbers)
- Enforces message length limits
- Configurable blocked patterns (regex)
- Runs as pre/post-processing pipeline

## Creating Custom Extensions

### Tool Template (Real-time Data Access)

```python
"""
title: My Custom Tool
author: you
version: 0.1.0
description: Tool description
"""

from pydantic import BaseModel, Field

class Tools:
    class Valves(BaseModel):
        api_key: str = Field(default="", description="API key if needed")

    def __init__(self):
        self.valves = self.Valves()

    def my_function(self, query: str) -> str:
        """
        Fetch data from external source.

        :param query: Search query or location
        :return: Formatted data as string
        """
        # Implement your data fetching logic
        return f"Result for: {query}"
```

### Function Template (UI Enhancement)

```python
"""
title: My Custom Function
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
```

### Pipeline Template (Advanced Processing)

```python
"""
title: My Custom Pipeline
author: you
version: 0.1.0
"""

from typing import List, Dict, Any
from pydantic import BaseModel, Field

class Pipeline:
    class Valves(BaseModel):
        priority: int = Field(default=0)

    def __init__(self):
        self.valves = self.Valves()
        self.name = "My Pipeline"

    def pipe(
        self, user_message: str, model_id: str, messages: List[Dict], body: Dict
    ) -> Dict[str, Any]:
        # Transform the request/response
        return body

    async def on_startup(self):
        print("Pipeline loaded")

    async def on_shutdown(self):
        pass
```

Save in `plugins/open-webui/`, restart Open WebUI, enable in Admin Panel.

## Troubleshooting

**Extensions not showing in Admin Panel:**
- The auto-import happens after the service becomes healthy
- Check the startup output for "Auto-imported X extension(s)" message
- If import failed, check `airpods logs open-webui` for errors
- Verify files exist in `$AIRPODS_HOME/volumes/webui_plugins/`
- Manual fallback: Use the Open WebUI UI to import from the filesystem

**Auto-import errors:**
- Ensure the WebUI secret is valid (stored in `$AIRPODS_HOME/configs/webui_secret`)
- Check network connectivity: `curl http://localhost:3000/api/config`
- Extensions are still available in the container filesystem at `/app/backend/data/functions/` and can be imported manually through the UI

**To manually import/re-import extensions:**
1. Go to Admin Panel → Tools/Functions/Pipelines in Open WebUI
2. Click "Import from Filesystem" or use the "+" button
3. Select the extension files from `/app/backend/data/functions/`

**Extension-specific issues:**
- **Weather Tool**: Requires internet access from the container; check network connectivity
- **Content Moderation Pipeline**: May need adjustment of blocked patterns for your use case
- **Markdown Enhancer**: Works best with markdown-formatted responses

## References

- [Open WebUI Tools Documentation](https://docs.openwebui.com/features/plugin_system/)
- [Open WebUI Functions Documentation](https://docs.openwebui.com/features/plugin_system/)
- [Open WebUI Pipelines Documentation](https://docs.openwebui.com/features/plugin_system/)
