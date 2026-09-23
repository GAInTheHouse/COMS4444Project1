# Contributing (for student groups)

Changes are made through pull requests from your own fork. Anything else
(direct pushes, PRs from a branch on this repo) will be rejected.

1. **Fork this repo.**
2. Copy the template into your own group's directory and rename the class to
   match — see `README.md`'s "Writing a player" section. If you're group 4:

   ```
   cp -r players/player_template players/player_4
   # edit players/player_4/player.py  →  class Player4
   ```

3. **Only touch `players/player_4/`** (your own group number). Do not edit
   `core/`, `models/`, `ui/`, `main.py`, another group's folder, or anything
   else in the repo. A PR that touches files outside your own directory will
   be rejected, not merged with the rest stripped out.
4. **Sync your fork with this repo's `main` before opening a PR.** Other
   groups' PRs land on `main` continuously; starting from a stale fork is the
   most common source of merge conflicts.
5. **Name the PR with your group number and what it is**, e.g. "Group 4 —
   10/15 deliverable" or "Group 4 — final player." One comment on the PR is
   enough; you don't need a novel.
6. Push and open the PR against this repo's `main`. We review and merge —
   usually a squash merge, so the PR title becomes the commit message on
   `main`.

You'll submit more than once over the semester (each deliverable is its own
PR), not just at the end.

## What merging means for visibility

Once your PR is merged, `players/player_4/` is on `main` and **other groups
can see it** — this repo is public, matching how this course's simulators
have always worked. Don't wait until the last minute to be first with a good
idea if that matters to you.

## Before you open the PR

```
uv run ruff format
uv run ruff check --fix
uv run pytest
```

CI runs the same three checks on your PR and blocks merging if they fail.
