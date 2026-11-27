# Daily Productivity Pack

Three new agents, usable by voice **and** by the Brain 2.0 planner/executor.

## 📝 Notes agent (`notes_agent`)
Capture and recall knowledge by voice. Stored in `memory/notes.db` (gitignored,
private). Full-text search via SQLite FTS5.

- *"note that the router password is …"* → `add`
- *"search my notes for router"* → `search`
- *"list my notes"* → `list`
- *"read note 3"* → `read` · *"update note 3 …"* · *"delete note 3"*

Params: `action`, `text`, `title`, `tags`, `query`, `id`, `limit`, `tag`.

## 🖥️ System agent (`system_agent`)
Voice-queryable PC health via `psutil`.

- *"how's my PC?"* / *"system status"* → CPU, RAM, disk, battery, uptime
- *"what's eating my CPU?"* → `processes` (top N, sort by cpu/memory)
- *"battery"* · *"disk space"* · *"uptime"* · *"network"*

Params: `action` (status/cpu/memory/disk/battery/network/processes/uptime),
`count`, `sort`.

## 🌅 Briefing agent (`briefing_agent`)
A spoken "good morning" that ties everything together: greeting + date,
weather (default **Nairobi**), unread email, system health, and a news
headline. Each section degrades gracefully if its source is unavailable.

- *"good morning"* / *"brief me"* → full briefing
- Custom: `sections="greeting,weather,news"`, `city`, `topic`

## Integration
- Registered as voice tools in `main.py` (declarations + dispatch).
- Available to multi-step plans: added to `agent/executor.py` dispatch and the
  `agent/planner.py` tool catalog — e.g. *"check my system, note the CPU usage,
  then brief me"* can chain them with `{{stepN}}` data flow.

## Tests
```bash
python -m pytest -q tests/test_productivity_pack.py
```
Offline: psutil is faked, briefing sources are mocked. No network/hardware needed.
