# Ellis sample context

Run `./scripts/start.sh --demo ellis --no-autostart` to prepare fictional Ellis
memory and editable PairMatch files. Open the app and click Start session.
Without `--no-autostart`, voice starts automatically.

Each launch creates `data/demo/ellis/<run-id>/` with separate memory and cue
stores and a source copy in `workspace/code/`. Open the code and failing log
and let AMBI observe the actual context. Live behavior requires API credentials
and desktop permissions.

The profile supplies identity, preferences, activity history and unfinished work.
It contains no scripted greeting, response catalog, facial-cue action mappings,
or expected answers. The normal structured intervention model determines whether to
suggest something; normal cooldowns and user-acceptance requirements apply.
A successful launch is not evidence of a successful proactive response.

AMBI-Bench on port 8766 also loads data-only profiles through its own isolated
session launcher. Its scenario metadata is for source selection and developer
reference and is not injected into AMBI memory or voice context.
