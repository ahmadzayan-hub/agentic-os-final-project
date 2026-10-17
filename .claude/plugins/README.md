# Plugins

A plugin bundles skills, agents, hooks or MCP servers so they can be reused across projects. This folder documents how to add one to this repository; it ships none yet.

## Option 1: a plugin folder under `.claude/skills/`

```text
.claude/skills/<plugin-name>/
├── .claude-plugin/plugin.json      # {"name": "<plugin-name>", "description": "…", "version": "0.1.0"}
├── skills/<skill>/SKILL.md
├── agents/<agent>.md
└── hooks/hooks.json
```

It loads for everyone who clones the repository and trusts the folder, and its skills are called as `/<plugin-name>:<skill>`.

## Option 2: a repository marketplace

Put a `marketplace.json` in `<folder>/.claude-plugin/` listing plugins by relative path. Then register it in `.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "<marketplace-name>": { "source": { "source": "directory", "path": "./<folder>" } }
  },
  "enabledPlugins": { "<plugin>@<marketplace-name>": true }
}
```

Check the layout with `claude plugin validate ./<folder>`.

## Rules

- Plugins declared through a marketplace in settings do not load in claude.ai/code cloud sessions; skills, agents, commands and hooks in this repository do.
- A plugin runs with the same trust as code in this repository. Review it as code, pin third-party sources, and never put secrets in its files.
