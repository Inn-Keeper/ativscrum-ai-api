# ativScrum AI API

Stateless FastAPI service for ativScrum's optional, cloud-team-only AI features.
It validates the caller's Supabase access token, reads only that caller's
organization through Row Level Security, consumes an atomic daily quota, sends
a minimized context to Groq, and returns a strictly validated suggestion.

The service does not persist prompts, board context, or model responses. AI
output remains a suggestion until the frontend user explicitly accepts it.

## Requirements

- Python 3.11
- a Supabase project with `ativscrum/supabase/schema.sql` applied
- a Groq API key with Zero Data Retention enabled before public use

## Local setup

```bash
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install ".[dev]"
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

Set `ALLOWED_ORIGINS` to the exact frontend origins that may call the API. For
local development plus one deployment, for example:

```dotenv
ALLOWED_ORIGINS=http://localhost:5173,https://ativscrum.example
```

Do not use `*`. Do not put a Supabase service-role key in this service. Runtime
Supabase calls deliberately use only the public anon key plus the caller's
bearer token, so database RLS remains the tenant boundary.

Check the process without invoking Supabase or Groq:

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

Check that runtime secrets are present:

```bash
curl http://localhost:8000/ready
```

Example authenticated request (replace the placeholders locally; never commit
or paste a real access token into documentation or logs):

```bash
curl --request POST http://localhost:8000/api/v1/ai/generate \
  --header 'Authorization: Bearer <SUPABASE_USER_ACCESS_TOKEN>' \
  --header 'Content-Type: application/json' \
  --data '{"kind":"sprint_summary","org_id":"<ORGANIZATION_UUID>","sprint_id":"<SPRINT_ID>"}'
```

## Configuration

| Variable | Required | Purpose |
| --- | --- | --- |
| `APP_ENV` | no | Environment label; defaults to `development`. |
| `ALLOWED_ORIGINS` | yes in deployment | Comma-separated exact frontend origins allowed by CORS. |
| `SUPABASE_URL` | yes | Supabase project URL. |
| `SUPABASE_ANON_KEY` | yes | Public anon key; authorization still comes from the caller token and RLS. |
| `GROQ_API_KEY` | yes | Server-only Groq credential. |
| `AI_MODEL_FAST` | no | Strict-output fast model; defaults to `openai/gpt-oss-20b`. |
| `AI_MODEL_QUALITY` | no | Strict-output quality model; defaults to `openai/gpt-oss-120b`. |
| `AI_TIMEOUT_SECONDS` | no | Provider timeout; defaults to `20`. |
| `AI_MAX_RETRIES` | no | Retry count for transient provider failures; defaults to `1`. |
| `AI_CONTEXT_MAX_CHARS` | no | Hard cap for serialized minimized context; defaults to `24000`. |
| `AI_MAX_OUTPUT_TOKENS` | no | Maximum provider output tokens; defaults to `1200`. |

The live isolation test needs an isolated Supabase test project and a temporary
cleanup credential with admin rights. Store `TEST_SUPABASE_URL`,
`TEST_SUPABASE_ANON_KEY`, and `TEST_SUPABASE_SERVICE_ROLE_KEY` only in local or
CI secret storage. They are test-process inputs, not service configuration, and
must never be added to `.env.example`, the deployed service, or frontend code.
The fixture creates disposable users and organizations and deletes them after
the run.

```bash
pytest -q
ruff check .
ruff format --check .
```

Without isolated test credentials, the live tenant tests skip. They must pass
before AI is enabled publicly.

## Container

```bash
docker build -t ativscrum-ai-api:portfolio .
docker run --rm --env-file .env -p 8000:8000 ativscrum-ai-api:portfolio
```

The two-stage image installs the package in a virtual environment and runs it
as a non-root user on port 8000.

## Free Koyeb deployment

Publish this repository first, then follow Koyeb's
[Git deployment guide](https://www.koyeb.com/docs/build-and-deploy/deploy-with-git):

1. Create a Web Service from the repository root and select Dockerfile build.
2. Choose Frankfurt and one Free instance. Confirm current availability and
   limits in the [instance reference](https://www.koyeb.com/docs/reference/instances).
3. Expose HTTP port `8000` and configure the health check path as `/health`.
   See [Koyeb health checks](https://www.koyeb.com/docs/run-and-scale/health-checks).
4. Add every runtime variable from the table above as a Koyeb environment
   variable or secret. Set `ALLOWED_ORIGINS` to the exact production Vercel
   origin (and an exact preview origin only if previews genuinely need AI).
5. In [Groq Data Controls](https://console.groq.com/docs/your-data), enable Zero
   Data Retention before public traffic. ZDR does not remove Groq usage metadata.
6. Deploy, then verify `/health` and `/ready` before configuring the frontend.

Koyeb's Free instance scales to zero after one hour without traffic, so the
first AI request may cold-start. The frontend intentionally displays a startup
message. Review [scale-to-zero behavior](https://www.koyeb.com/docs/run-and-scale/scale-to-zero)
before launch.

Do not set the frontend's production `VITE_AI_API_URL` until the operator has
completed and recorded ativScrum's GDPR readiness checklist outside source
control. This repository does not claim that a deployment is GDPR-compliant.

## Publication step

This repository does not yet have a confirmed public GitHub URL. After it is
published, add the final URL to the ativScrum README and cloud setup guide; do
not publish a guessed link.
