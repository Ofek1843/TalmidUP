# Opportunity and AI Radar MVP

This is a lightweight, self-contained starter for the two-part agent:

- `opportunity` mode: looks for pain, demand, payment intent, and recurring work.
- `tech` mode: looks for new model/tool/API/product updates.

## What it does

- Pulls from a small set of RSS/JSON sources.
- Scores each item with transparent heuristics.
- Produces Markdown reports.
- Keeps a local cache so repeated runs only process new items.

## Run

```bash
python main.py run --mode opportunity
python main.py run --mode tech
python main.py run --mode both
```

## Schedule

Recommended cadence:

- `opportunity`: every 6-24 hours
- `tech`: 1-2 times per week

You can schedule this externally with Task Scheduler, cron, or a small loop process.

## Output

Reports are written to `./out` by default.

## Phone alerts

This starter can send alerts to Telegram on your phone.

Set these environment variables before running:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Only items above the notification threshold are sent.

## Suggested setup

1. Create a Telegram bot with `@BotFather`.
2. Message your bot once so Telegram opens the chat.
3. Get your `chat_id`.
4. Set the two environment variables.
5. Run the script on a schedule.

## GitHub Actions schedule

Recommended default schedule:

- `opportunity`: every day at `08:00 UTC`
- `tech`: every Monday and Thursday at `08:30 UTC`

This keeps the signal fresh without spamming you.

## Next steps

- Add more sources.
- Swap the heuristic scorer with an LLM classifier.
- Add notifications to email, Slack, or Discord.
