# AI assistants

SAEngine's own assistant lives in the **chat in the title bar** (beside Sign In): see
[The assistant in the chat](#the-assistant-in-the-chat). This page also covers the built-in
[Model Context Protocol](https://modelcontextprotocol.io) server, so an AI
assistant on your computer — Claude Code, Claude Desktop or any other MCP client — can work in a
SAEngine window with you: read the project and its results, open parts, run Run All, build the
report, take a screenshot to see what you see, and (only if you allow it) make edits you can undo.

It is **off by default**. Nothing listens until you allow it.

## Turning it on

- **For this session:** Command Palette → **SAEngine: Allow AI Assistants to Control This Window**.
  A dialog shows the address, the token and the exact lines to paste into your assistant.
- **Every time:** Settings → `saengine.ai.allowControl` (each window starts its own server).
- **Developers:** launch the dev build with `SAENGINE_AI=1` (see below).

While it is on, the status bar shows **AI allowed** (or **AI connected** once an assistant has
connected). Click it to disconnect and stop, to allow or stop edits, to show the connection details
again, or to open the **AI Activity** log. When an assistant connects you get a notification.

Stopping (or closing the window) closes the server; the token stops working at once. Allowing again
gives a new token.

## Connecting

The server speaks MCP over Streamable HTTP at `http://127.0.0.1:<port>/mcp`, and every request must
carry `Authorization: Bearer <token>`. The dialog's buttons copy these lines with your port and token
filled in.

### Claude Code

```bash
claude mcp add --transport http saengine http://127.0.0.1:<port>/mcp --header "Authorization: Bearer <token>"
```

Then ask, e.g., "Use saengine: which parts of my project are stale? Run All and tell me which
members fail." Remove it again with `claude mcp remove saengine`.

### Claude Desktop

Claude Desktop starts local servers as programs, so it reaches SAEngine through
[`mcp-remote`](https://www.npmjs.com/package/mcp-remote) (needs Node.js; `npx` downloads it the first
time). In **Settings → Developer → Edit Config** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "saengine": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://127.0.0.1:<port>/mcp", "--header", "Authorization:${SAENGINE_AUTH}"],
      "env": { "SAENGINE_AUTH": "Bearer <token>" }
    }
  }
}
```

Restart Claude Desktop after editing it. (The header is passed through an environment variable
because Windows splits arguments with spaces.)

### Other MCP clients

Any client that supports Streamable HTTP with a custom header works: URL
`http://127.0.0.1:<port>/mcp`, header `Authorization: Bearer <token>`.

### A stable address

The port is a free one each time by default. Set `saengine.ai.port` (e.g. `8765`) to keep it; then
only the token changes between sessions. With several windows open, the later ones fall back to a
free port.

### Developers: `SAENGINE_AI=1`

```bash
SAENGINE_AI=1 ./scripts/code.sh
```

On Windows: `set SAENGINE_AI=1` then `scripts\code.bat`. Every dev window starts its server at once,
prints `[SAEngine AI] window <id>: <url> token <token>` in the terminal and writes the same to
`<user-data-dir>/saengine-ai-window-<id>.json` (removed when the server stops). A planning session can
read that file to attach to the window the owner opened. Release builds ignore the variable.

This never turns on Chromium's remote debugging port: that port gives any local process full,
unauthenticated control of the window, so SAEngine does not open it.

## Tools

| Tool | What it does |
| --- | --- |
| `get_project` | The project: name, folder, type, every part with its status (not started, done, stale, failed…) and hint, the open editors, whether edits are allowed. |
| `list_editors` | The open editors (title, file, part, unsaved) and the active one. |
| `open_part` | Opens a part (`soil`, `floorPlan`, `fem`, …) as the Project sidebar does. |
| `open_file` | Opens a file of the project (path relative to the project; nothing outside it). |
| `read_active_document` | The active editor's document as you see it, unsaved edits included (JSON parsed), with the text selection and the selected model item. |
| `read_results` | A results summary: `design`, `fem` (run manifest), `substructure`, `mep`, `boq`. |
| `list_commands` | The commands `run_command` may run. |
| `run_command` | Runs one allowed command exactly as its menu does (see below). Long commands keep running; the assistant follows the part statuses. |
| `screenshot` | A PNG of this window (only this window, never the screen). |
| `show_message` | A notification for you, always shown as "AI assistant: …". |
| `reveal_element` | Selects and shows a member (`columns`/`beams`/… and id), story, grid line or object type in its editor. |
| `search_code` | Passages of the code pack in force (BNBC 2020 unless the project chooses another) and of this manual that answer a question, each with its clauses, tables and pages. |
| `explain_results` | The design checks of the last run per element, governing check first (demand, capacity, utilisation, combination), for one member or the failing ones. |
| `propose_changes` | A change set to the project's JSON files that you preview (each value before and after) and accept or reject (in the chat for the chat's assistant, in a dialog for an MCP client); accepted, it is one undoable step. Works without the edits switch, because nothing changes until you accept. |
| `list_actions` | The catalogue of [shared editing actions](actions.md) (name, kind, summary): edits, queries and runs. |
| `describe_action` | One action with its parameters (JSON schema) and the parts it changes. |
| `run_actions` | Runs a batch of actions on the open project, all or nothing (see [Building with actions](#building-with-actions)). Edits come back as one change set you accept or reject; run steps ask you first. |

### Commands the assistant may run

Run All (and cancel, log), Run Analysis, Run Selected Cases, analysis log and charts, member details,
Design Reinforcement (the design proposal preview — applying it stays your click), Print Design
Report, Generate Drawings, Export DXF / IFC / BOQ CSV, project overview / exports / start / versions /
import report, Save Version, Export Project (.civil), the New Project wizard, the members table and
the Python runtime check. With edits allowed also: Size Footings, Import Footings, Add Borehole, Undo
and Redo.

Nothing else: no terminal, tasks, extensions, settings or file deletion, no backend commands that take
file paths or scripts, and no command that changes the assistant's own access. A command never gets
arguments from the assistant; the few that need the project's folder get it from SAEngine.

### Edits

Edits are off for every new session. **Allow AI Edits for This Session** (status bar menu or Command
Palette) turns them on until you stop them or the server stops. Then:

- The edit commands above run as their menus do.

Changes to the model itself never need this switch, because nothing changes until you accept them:
`run_actions` and `propose_changes` show a change set you accept or reject (below).

## Building with actions

The assistant changes the model with the same [actions](actions.md) as the command line
(`saengine action ...`), scripts (the SDK) and the app: typed, validated steps such as `grid.set`,
`storeys.set`, `columns.place`, `load.area.set`, `foundations.generate`, `run.all`. With them it can
build a whole project from an empty folder to the report. It works through three tools:
`list_actions`, `describe_action` and `run_actions`.

- **A batch is all or nothing.** The engine works out every step on your project as you see it,
  unsaved edits included. If one step fails nothing changes. The answer names the step and each
  refused value (field, value, reason, by the same input rules as for you), and the assistant
  corrects it and tries again.
- **Edits are a change set.** A batch that edits comes back as one change set: in the chat, as a
  card in the assistant's answer; for an MCP client, as a dialog. It shows what each step did
  ("Placed 6 columns", "3 storeys") and every value before and after. **Accept** applies it to the
  part files' text models as one step: **Undo** after it in the chat (or Ctrl+Z) reverts all of it. It shows at once in every editor, live co-editing shares it, and it stays
  unsaved until you save. **Reject** changes nothing.
- **Runs ask you first.** A batch with a step that writes to disk (`writes` in the catalogue:
  `run.all`, `run.step`, `design.reinforcement.apply`, `foundations.generate`, `export.*` and
  `project.create`) runs only after you agree (**Save and Run** in the chat, or a dialog for an
  MCP client). SAEngine then saves your edited parts
  (as Run All does), the engine writes the results, and the open files are read again. Such a
  batch holds only those steps and queries; the assistant sends the edits first, as their own
  change set. The answer lists the files the run saved first (`written`).
- **You can stop a run.** Stop in the chat (or Stop on the run's progress notification) stops the
  batch before its next step, and a Run All at its next step boundary; the answer says what was done and what
  was written (that stays written, and Undo does not take back a run).
- **Nonsense is refused with the allowed range.** A storey of 30 m, spans in metres, a beam far
  too shallow for its span, loads in N or psf, more storeys than the structural system may have
  in the site's Seismic Design Category: the same input guardrails as for you refuse them and
  say what is allowed (see [engineering-decisions.md](engineering-decisions.md)).
- **You check the results.** The assistant reports what the run and the checks say. It does not
  approve a design. Design Reinforcement is never automatic: the assistant applies it only when
  you ask.

The order the assistant follows for a new project: `project.create` (in the empty folder open in the
window, where the project then opens; in a window without a folder SAEngine asks where to create
it, by default in Documents\SAEngine Projects, in a subfolder named after the project, and opens
it in the window) → settings (code pack, site, use, analysis) → soil → grid and
storeys → materials and types → members → loads → an analysis (`run.step`) → foundations → `run.all` → results and checks →
Design Reinforcement and exports when you ask.

You can run the same batches yourself: Command Palette → **SAEngine: Run Actions from File...** runs a
batch file (`[{"action": "grid.set", "params": {...}}, ...]`, the file `saengine action batch` takes)
on the open project, and **SAEngine: Show Action Catalogue** lists every action with its parameters
and copies an example step. For the catalogue and the batch format see [actions.md](actions.md).

## Safety model

| Threat | What stops it |
| --- | --- |
| Something on the network | The server listens on 127.0.0.1 only. |
| A web page you visit (CSRF, DNS rebinding) | Requests with an `Origin` header (every browser request) are refused, the `Host` must be `127.0.0.1`/`localhost`/`[::1]` with the server's port (a rebinding page uses its own host name), no CORS headers are sent, and the token is required — a page cannot read it or send it. |
| Another program or another user on the PC | It needs the window's random 256-bit token, compared in constant time on every request (a session id alone is not enough). The token is shown only in the dialog (and, for dev launches, the terminal and a file in your own profile folder). |
| A guessed or leaked token | The token lives only as long as the session: stop AI access and it is dead. Refused requests are logged in AI Activity and notified once. |
| The assistant doing too much | Read tools and an allow-list of menu commands only; edits need your switch, go through the undo stack and stay unsaved; messages are always marked as the assistant's; every call is logged in **AI Activity** with its arguments and outcome. |
| Malware already running as you | Out of scope: it could control SAEngine (or anything you run) without this server. |

The protocol handling is Code-OSS's own MCP gateway session; SAEngine adds the HTTP checks
(`src/vs/platform/saengine/{common,node}/saengineAi*.ts`) and the tools (`src/vs/workbench/contrib/saengineAi`).

## The assistant in the chat

SAEngine's assistant is in the chat of the title bar, beside **Sign In** (Command Palette →
**SAEngine: Ask the AI Assistant**). There is one chat: the separate AI Assistant view of earlier
versions is gone. The chat comes with the setup's optional **AI assistant** component (GitHub
Copilot Chat); without it there is no assistant in SAEngine, and assistants outside SAEngine can
still connect over MCP (above). It works in the normal (non-developer) window.

### The SAEngine agent

Pick **SAEngine** in the chat's mode picker; it is the default for new chats while a project is
open. It knows the build-a-project playbook and SAEngine's rules, and it uses only SAEngine's tools
(the **saengine** tool set): `list_actions`, `describe_action`, `run_actions`, `search_code`,
`explain_results`, `read_results`, `get_project`, `list_editors`, `read_active_document`,
`screenshot`, `open_part`, `open_file`, `reveal_element` and `propose_changes`. The same tools as
for MCP clients, run by the same code; in the chat they never run menu commands, edit files
directly or use the terminal. You can turn single tools off in the chat's tool picker. The chat's
other modes (Agent, Ask) can use the saengine tools too, together with the chat's own tools.

What it does:

- **Code questions** are answered only from the passages `search_code` finds in the code pack and
  the manual, with their clauses (e.g. "BNBC 2020 Part 6 Table 6.2.14 (p. 615)"). When nothing
  matches, it says the code pack does not cover the question instead of answering from memory.
- **Results**: why a member fails, which check governs, under which combination
  (`explain_results`); it says when the results are stale.
- **Changes** in words ("make the typical storey 3.2 m", "use C28 for the columns") come as a change
  set card in the chat with every value before and after: **Accept** or **Reject**. Accepted, it
  is one undoable step (**Undo** in the chat, or Ctrl+Z) and stays unsaved until you save.
- **Whole projects** ("a 3-storey RC frame, 3 by 2 bays of 6 m, in Dhaka, designed"): the assistant
  builds them with the actions, in a few change sets and one Run All you agree to (see
  [Building with actions](#building-with-actions)).
- **Run steps** (`project.create`, `run.all`, `run.step`, exports, Design Reinforcement) show a
  **Save and Run** / **Cancel** card first. Stop in the chat stops the request; a card still open
  is rejected.

The change-set and run cards are SAEngine's own questions, not the chat's tool approval: no
"always allow" or auto-approve setting of the chat skips them.

### Models: Copilot or your own key

The chat uses the model you pick in its model picker:

- **Copilot**: Sign In (title bar) with your GitHub account; the models of your Copilot plan.
- **Your own key**, no GitHub account needed: **SAEngine: Use My Anthropic API Key...** (Claude
  models; the recommended default), **SAEngine: Use a Self-Hosted Model (OpenAI-Compatible
  Endpoint)...** (for example a model on this computer at `http://localhost:11434/v1`; it must
  support tool calls), or any other provider in **SAEngine: Choose AI Models and Providers...**
  (the chat's Manage Language Models: OpenAI, Google, OpenRouter, Azure, ...). Keys are kept in the
  operating system's secret store, never in settings or project files.

The earlier assistant's settings (`saengine.ai.assistant.provider`, `.anthropicModel`, `.effort`,
`.endpoint`, `.model`) are no longer read. On the first start with the chat, SAEngine moves them
once into the chat's language models: a saved Anthropic key becomes an **Anthropic** provider, an
OpenAI-compatible endpoint a **Self-hosted** Custom Endpoint with its model; the old keys are
removed from the secret store. Pick the model in the chat's model picker.

### What is sent, and when

Nothing of a project is sent before you agree. While a project is open, the first request of the
chat (in any mode) to a model provider asks: *Allow for This Project* or *Not Now* ("Not Now" sends
nothing and keeps your words in the input). The answer is kept per project and per provider on this
computer (`saengine.ai.projectDataConsent`), never in the project's files; an "Allow" given to
Anthropic for the earlier assistant still holds. A tool that reads project data (the overview, the
open document, results, a picture of the window) checks the same consent before it runs.

The status bar always shows where this project's data may go (**AI: api.anthropic.com**, or **AI:
asks first**); click it, or **SAEngine: AI Data Sharing for This Project**, to stop sending to a
provider. In SAEngine the chat does not attach the open part by itself and does not save your
unsaved parts when you send a question (`chat.implicitContext.enabled`, `chat.saveBeforeSend`).

Requests go from the chat straight to the provider you picked, under that provider's terms.
SAEngine and its developers never receive or sell your project data.
