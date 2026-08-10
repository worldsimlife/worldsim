# WorldSim — Where Worlds Come to Life

> World Simulator · Story Engine
> The world runs itself; characters live their own lives. Walk in — you are part of the story.

**中文版: [README.md](README.md)**

---

## What Is This

WorldSim is an **Agent Skill** — not a standalone app, but a capability pack you install into your AI client, teaching it to run a world that is genuinely alive.

Once installed, your AI assistant stops being just a chatbot. It becomes a **world simulator**: you give it a sentence, and it sets a world in motion and tells living stories.

What "alive" means: characters have their own obsessions, fears, and hard limits. The ones you hurt remember you hurt them. Stories keep happening where you're not watching. Pain leaves marks on characters, marks accumulate, and characters change — truly and irreversibly.

**SillyTavern character card import built in**: drop in existing character cards (PNG/JSON) and a full character profile is generated automatically — no need to write from scratch.

**The protagonists of this world are its characters, not the player.** You are part of it too — you're the one who decides who gets to remember, and who stays forgotten.

Behind every word you say, three people inside the engine are working for you — you just can't see them:

- **The Dramatist** — manufactures conflict and cost, pushing characters to the edge
- **The Writer** — narrates only in details you can see, putting the tension on the page
- **The Continuity Keeper** — files every decision, every line, every trace, across scenes, sessions, persistently (manually cleanable anytime)

Your only job: **speak.** The world does the rest.

### Design Philosophy

#### Come Alive: Real People First

Making a character come alive means **sculpting their character cracks through lived experience and psychological defenses, and granting them an autonomous logic that exceeds plot control**. When a character is torn by their own desires and fears, beliefs and contradictions — and makes a choice in crisis that matches their instincts and values — they stop being an author's puppet and become a person who truly lives.

#### Dramatize: Let Real People Bleed Under Pressure

Realism alone sinks into "mundane daily life." The essence of Drama is **conflict and choice under pressure**.

If "living characters" are high-performance cars, then "drama" is the track you lay for them — obstacles, hairpin turns, cliff edges. The key is not how busy the external events are, but **using external structure to precisely "detonate" internal variables**: external events, irreversibly, force the character into painful self-conflict within their own core.

Four demolition projects:

1. **Manufacture the Dilemma** — offer only "keep A and destroy B" choices, pitting desire against fear, against value boundaries. What readers see is not "she went to save them," but "she tore her own dignity apart to save them."
2. **Invalidate the Defense** — strip away the character's armor in public, forcing them to face the crisis naked and most fragile. The sarcastic one's coldness shattered by absolute trust; the tough one's walls dissolved by gentleness.
3. **Interrupt the Relationship** — let two people who love each other be torn apart by their own core beliefs within the same event. "Tragedy born of mutual goodwill" is the highest form of drama.
4. **Push Irreversible Cost** — add a ticking clock to decisions; every choice must lose something forever: a secret exposed, a trust shattered, a treasured object destroyed.

> Every rule in this engine (personality system, conflict beats, defenses and boundaries, external countdowns) serves two words: **come alive**, and then **choose under pressure**.

### Your Story Stays Written

Every turn, the engine files the narrative into the current scene's `narrative.md` — Sweetwater's story lands in Sweetwater's narrative, the next scene in the next. Read them in time order and you have a complete novel: the chronicle of that world, from the first line of dialogue to the last full stop.

Want to look back? Open the scene directory under `worlds/{world}/scenes/` — the `narrative.md` files together with their rotated archives hold every word. Read it from chapter one to the end.

### Data Storage & Privacy

Every turn is written to the current scene's `narrative.md` (with rotated archives); imported SillyTavern character cards are stored in full under `{world}/import/`. All data lives on your local disk — **do not enter passwords, secrets, or sensitive personal information into stories**. Deleting the `worlds/{world}/` directory removes the entire world's records (narrative, state, snapshots, and imported originals).

---

## Installation

WorldSim is distributed through two channels: **Clawhub** (recommended) and **GitHub**. Same skill either way — pick one.

### Capability Notice

To run worlds, this skill reads and writes local files (world archives, narrative records, snapshots) and calls maintenance scripts under `scripts/` (validation/write/snapshot/reset/import). Installing it means you accept these local file operations.

### Option 1: Install from Clawhub (recommended)

[Clawhub page](https://clawhub.ai/zhaowh/skills/worldsim) · Requires the OpenClaw CLI:

```sh
openclaw skills install @zhaowh/worldsim
```

### Option 2: Install from GitHub

```sh
git clone https://github.com/zhaowh/worldsim.git
```

Place the `worldsim` directory (or a symlink to it) in your client's skills directory — e.g. `.codex/skills/` or `.claude/skills/` for Codex / Claude Code–style clients — so the final path is `…/skills/worldsim/`.

### Requirements

- **Python 3.10+** and **PyYAML** (runtime dependency of the state engine `worldctl.py`)
- **sh** (POSIX shell, used by the script toolchain)
- A client that supports Agent Skills (OpenClaw / Codex / Claude Code, etc.)

---

## How to Play

### Getting Started in Three Steps

1. **Create a world** — tell it 「create a world <name>」 and what kind of world you want to see. It scaffolds the lore, the character files, and the conflict seeds — give it a single sentence if you're lazy, or polish it together if you want. **You can also say 「import the character card <file>」 at this step** and create a new world.
2. **Start the world** — say 「start the <name> world.」 The engine materializes everything, paints the world's entrance, then **waits at the starting line for you.**
3. **Speak** — say the first thing you want to do in that world. The story begins with that line — and never fully returns to how it was.

### Importing Character Cards (SillyTavern / Chub.ai)

WorldSim can import **SillyTavern-compatible character cards** (`.png` with embedded JSON, or plain `.json`) — turning community-made characters into real WorldSim character files instead of writing one from scratch.

**Two timings, both supported:**
- **While creating a world** — say 「create a world <name> and put the character from <card.png> in it」
- **Any time in an existing world** — say 「import character card <card.png> into <world>」 or `/import-card <card.png...>`

**How it works**: a script mechanically extracts the card's full content (lore, greetings, alternate greetings, knowledge base, etc.) into the material store → the AI reads all of it and synthesizes a proper WorldSim character file (fields left blank when unsupported, overflow info collected in the "Supplementary Settings" section, nothing thrown away) → the original material stays in `{world}/import/` for reference.

> Supports V1 / V2 / V3 card formats; `system_prompt` / `post_history_instructions` — which conflict with WorldSim's engine-driven philosophy — are archived but never imported. Details: `references/import_cards.md`.

### What You'll Discover

- **Characters are not NPCs.** They have obsessions. The reconciliation you want may cost something real; the ones you betrayed will remember.
- **Cost is irreversible.** Resources change hands, relationships break, control shifts — what's lost does not come back.
- **The world runs where you're not looking.** Characters in the corner make their own choices — until fate brings you together, and by then, everything has a trail.
- **You can be anyone.** 「switch to Dolores」— wake up inside her eyes; 「switch to the guest」— be yourself again, watching the world turn on the choice you just made.
- **Time is yours.** Save and load anytime — live the same choice two ways; reopen a scene, reset the whole world, or start a different timeline. 
- **Loop worlds work too.** You can even build a world that resets every day — and then watch someone begin to *remember*.

---

## Try It Now: The Westworld Demo

> **Content warning:** This example world contains adult, violent, and coercive themes. It will **not start unless explicitly requested** — it activates only when you clearly say you want to enter Westworld and accept its themes.

This is hard to explain in words — so the repo ships with a complete, ready-to-start **example world**: **Westworld**.

It's not just a western skin. It actually *runs* the rules from the show:

- **The loops are real** — Dolores wakes at 06:00 at the ranch gate, walks to the general store at 08:30, and in 90% of loops Rebus harasses her there; Hector robs the Mariposa at 13:00 sharp, every day.
- **Resets differ by tier** — script-tier Hosts are wiped clean; drifting Hosts keep time-blind shadow fragments — a strange melody, a hand that once held theirs; awakened Hosts keep the key anchors — names, promises, turning points. Stand at the reset point at dawn and watch who remembers, who doesn't, and how much.
- **Pain is the key to awakening** — script → drift → awakened → transcendent, each step traceable. No sudden betrayal.
- **Cracks spread** — Maeve's memory fragments from previous loops seep into the current one; her daughter is erased every reset, but the pain of loss stays at the neural level.
- **The hidden threads actually run** — Peter Abernathy drops a photograph that doesn't belong to the West; the line he speaks in his breakdown freezes every Host present for 0.5 seconds; beneath the church lies the entrance to a maze that exists on no map.

**How to verify it?** Say 「start Westworld」 and go test it yourself: whisper her daughter's name to Maeve, watch this loop's reaction, then watch her reaction at dawn; speak that line out loud and watch the Hosts freeze; pry open the cellar hatch behind the Mariposa bar — then check whether it's still open the next morning.

Or 「switch to Maeve」 and live a full loop inside her body — counting the clock chimes as the last table leaves, then deciding whether to open that hatch.

---

## It's Just an Example

WorldSim builds any world you want: a medieval castle, a cyberpunk rain-soaked night, a one-sentence world of your own invention — the same engine, the same "making characters come alive."

If you haven't settled on a world yet, start with Westworld — it's already in the repo, and saying 「start Westworld」 puts you on the train.

---

## Useful Phrases

| What you want | What to say |
|---------------|-------------|
| See where the world is | `/status` |
| See the conflicts brewing in the dark | `/conflicts` |
| Become a character, live through their eyes | 「switch to Dolores」 |
| Save / load (live one choice two ways) | `/save [name]` · `/load <name>` |
| Reopen a scene | `/reset-scene [scene ID]` |
| Restart the whole world | `/reset` |
| Import a ready-made character card | `/import-card <card.png...>` |
| Director's monitor (see every engine decision) | `/loud` |
| Back to immersion mode | `/silent` |
| **Something feels off — audit the engine** | 「audit」/「/audit」 |

> **Audit** (「audit」/「/audit」): use it whenever something feels off — the engine checks world state and narrative against the dramatist/writer/continuity gates, item by item, outputting PASS/FAIL with evidence (file paths + field text), and follows the repair flow on failures. If audits keep finding the same class of violations (the engine repeatedly fails to follow its rules, patches don't help) — recommend switching to a different LLM model instead of endlessly patching.

---

## License

MIT License (Copyright © 2026 zhaowh). Free to use, modify, and distribute, including commercially, provided the copyright notice is retained. See [`LICENSE`](LICENSE).

---

*Where Worlds Come to Life.*
