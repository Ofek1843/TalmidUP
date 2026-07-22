# Cloud deployment

This project is ready to run in a small Linux container.

## What the cloud version does

- Runs on a schedule outside your laptop.
- Collects new items from sources.
- Sends Telegram alerts to your phone.
- Writes reports and state locally inside the container.

## Recommended simple setup

Use any container host that can:

- run a Docker image
- keep environment variables secret
- restart the job on a schedule

## Environment variables

Set these in the cloud host:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

## Build

```bash
docker build -t opportunity-radar .
```

## Run

```bash
docker run --rm \
  -e TELEGRAM_BOT_TOKEN="..." \
  -e TELEGRAM_CHAT_ID="..." \
  opportunity-radar
```

## Scheduling

Run the container on a schedule:

- `opportunity`: every 6-24 hours
- `tech`: 1-2 times per week

If your cloud provider supports cron jobs, use that.
If not, run a small scheduler service that triggers this container.

## Notes

- A container keeps running even if your laptop is off.
- If the host stops the container, the job stops too.
- For better reliability, use a managed scheduler or a VM with a cron job.
