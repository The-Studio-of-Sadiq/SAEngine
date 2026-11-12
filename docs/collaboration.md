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

## Live co-editing

Live co-editing lets several engineers edit one part at the same moment, like a shared
document: a colleague's edit appears in your floor plan as they make it.

**Start it:** **Project › Share › Live Co-Editing...** (or *Start Live Co-Editing* in the
command palette) in a shared project. While it is on, every part you open joins that part's
session, and the status bar shows how many colleagues are in the parts you have open (the
tooltip names them and what they have selected). Click it to stop.

**How edits merge.** Each part is shared object by object, using
[Yjs](https://github.com/yjs/yjs) (MIT):

- Two engineers editing different members (or different fields of one member) both keep their
  edits.
- The same field edited by both at once keeps the later edit, and both see it.
- A member deleted by one engineer stays deleted even if the other was editing it.

Save as usual. Everyone ends up with the same part, so **Sync with Office Copy** brings the
versions together without conflicts.

**The relay.** The engineers' SAEngines meet through a relay on the office network. Nothing
goes to an outside service, and SAEngine has no relay address of its own:

- **Host on this computer:** *Host Co-Editing Relay on This Computer*. SAEngine listens on port
  1234 and copies this computer's address (`ws://192.168.x.x:1234`) for colleagues. Windows
  may ask to allow SAEngine on private networks. The relay runs while SAEngine is open and
  keeps nothing on disk.
- **Office server:** any y-websocket-compatible server the office runs. Each engineer puts its
  address in the setting `saengine.collaboration.relayUrl`.

Anyone on the office network who knows the shared project's office-copy location can join its
sessions, so use a relay only on a network you trust. Your name in sessions is
`saengine.collaboration.displayName` (empty: this computer's user name).
