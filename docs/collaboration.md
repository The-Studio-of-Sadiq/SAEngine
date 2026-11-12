# Shared projects and live collaboration

Several engineers can work on one SAEngine project. Each engineer works on their own copy
of the project; an **office copy** of its versions sits on the office's own file server.
SAEngine uses no outside service: nothing leaves the office unless the office points it there.

## The office copy

**Project › Share Project...** asks where the office copy is kept:

- **Shared folder** (recommended): an empty folder on a network share or a mapped drive, for
  example `\\fileserver\projects\Tower A`. SAEngine sets it up (`saengine-share.json`,
  `history.git`, `locks/`, `presence/`). Sync, part locks and presence all work.
- **Git server address**: the office's own git server (`https://...` or `ssh://...`).
  Sync only; locks and presence need a shared folder.

The project's versions (Project › Versions) are copied there. Other engineers use
**Open Shared Project...** to copy it into a new folder on their computer.

## Sync

**Sync with Office Copy** (also the *Sync* button in the Versions editor):

1. Saves the open edits and any unsaved changes as a version ("Before syncing"), so no work
   is lost.
2. Brings in the office copy's new versions.
3. Merges **per part file**. A file changed on one side only is taken from that side. A file
   changed differently on both sides is a conflict of its part (for example
   *05 Floor Plan*). SAEngine asks for each such part: **Keep Mine** or **Take Theirs**. Until
   every conflicted part has an answer, nothing is merged.
4. Sends the result back to the office copy.

The other side's version of a conflicted part is not lost: both stay in Versions and can be
restored.

## Part locks

To avoid conflicts, lock the part you are about to edit with **Lock Part for Editing...**.
The lock is a file in the shared folder that only one engineer can create. A sync does not
send changes to a part someone else has locked; your versions stay on your computer until
the lock is released. **Release Part Lock...** releases your own lock. It can also break a
lock left behind by a computer that crashed, after you confirm.

## Presence

While a project shared through a folder is open, SAEngine writes a small presence file
about once a minute. The Versions editor shows who else has the project open.

## Live co-editing (in progress)

Live co-editing means several engineers editing one part at the same moment. It is designed
behind an interface in the workbench (`saengineProject/browser/liveCoEditing.ts`):

- The engine will be a CRDT, [Yjs](https://github.com/yjs/yjs) (MIT licence, compatible with
  AGPL-3.0), with its awareness protocol for presence in the part.
- It runs over a relay that the office hosts itself (the y-websocket server, MIT). Its
  address goes in the setting `saengine.collaboration.relayUrl`. The setting is empty by
  default, so live co-editing is off and no third-party cloud is used.
- It ships in the setup's **Collaboration** component.

Until the engine is added, **Live Co-Editing...** says what is missing. Shared folders, sync,
locks and presence work without it.
