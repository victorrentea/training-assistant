# Firefighter Agent Prompt

Use this prompt when setting up a scheduled task in Claude Desktop (via `/schedule` or the Scheduled sidebar).

## Recommended Schedule
- **Frequency**: Every 10 minutes (or on-demand)
- **Name**: "Production Firefighter"

## Prompt

```
Run the health check script for the production deployment of the Workshop Live Interaction Tool.

1. Execute: cd /Users/victorrentea/conductor/workspaces/training-assistant/lansing-v1 && ./healthcheck.sh
2. If the health check PASSES (exit 0): reply with a one-line "Production healthy" and stop.
3. If the health check FAILS (exit 1):
   a. Note which endpoints failed and their HTTP status codes
   b. Check Railway deployment logs: run `railway logs --latest` or check https://railway.app dashboard
   c. Check recent git commits: `git log --oneline -5` to see if a recent push broke things
   d. Check GitHub CI status: `gh run list --branch master -L 3`
   e. Based on findings, attempt to fix:
      - If a code bug: fix in the codebase, commit, and push to master
      - If a deployment issue: check Railway dashboard for build errors
      - If an infrastructure issue: report findings and suggest manual intervention
   f. After fixing, re-run ./healthcheck.sh to verify the fix worked
   g. Summarize what happened and what was fixed
```

## Setup Instructions for Claude Desktop

1. Open Claude Desktop
2. Click "Scheduled" in the left sidebar (or type `/schedule`)
3. Click "+ New task"
4. Set:
   - **Name**: Production Firefighter
   - **Prompt**: paste the prompt above
   - **Frequency**: Every 10 minutes (or choose your preferred interval)
   - **Project**: point to `/Users/victorrentea/conductor/workspaces/training-assistant/lansing-v1`
5. Save

Note: Scheduled tasks only run while your Mac is awake and Claude Desktop is open.

## Alternative: Claude Code `/loop` Skill

For monitoring during an active Claude Code session, you can use:

```
/loop 10m ./healthcheck.sh
```

This runs the health check every 10 minutes within your current Claude Code session.
