# FastAPI Project - Deployment

You can deploy the project using Docker Compose to a remote server.

This project expects you to have a Traefik proxy handling communication to the outside world and HTTPS certificates.

You can use CI/CD (continuous integration and continuous deployment) systems to deploy automatically, there are already configurations to do it with GitHub Actions.

But you have to configure a couple things first. 🤓

## Preparation

* Have a remote server ready and available.
* Configure the DNS records of your domain to point to the IP of the server you just created.
* Configure a wildcard subdomain for your domain, so that you can have multiple subdomains for different services, e.g. `*.fastapi-project.example.com`. This will be useful for accessing different components, like `dashboard.fastapi-project.example.com`, `api.fastapi-project.example.com`, `traefik.fastapi-project.example.com`, `adminer.fastapi-project.example.com`, etc. And also for `staging`, like `dashboard.staging.fastapi-project.example.com`, `adminer.staging.fastapi-project.example.com`, etc.
* Install and configure [Docker](https://docs.docker.com/engine/install/) on the remote server (Docker Engine, not Docker Desktop).

## Public Traefik

We need a Traefik proxy to handle incoming connections and HTTPS certificates.

You need to do these next steps only once.

### Traefik Docker Compose

* Create a remote directory to store your Traefik Docker Compose file:

```bash
mkdir -p /root/code/traefik-public/
```

Copy the Traefik Docker Compose file to your server. You could do it by running the command `rsync` in your local terminal:

```bash
rsync -a compose.traefik.yml root@your-server.example.com:/root/code/traefik-public/
```

### Traefik Public Network

This Traefik will expect a Docker "public network" named `traefik-public` to communicate with your stack(s).

This way, there will be a single public Traefik proxy that handles the communication (HTTP and HTTPS) with the outside world, and then behind that, you could have one or more stacks with different domains, even if they are on the same single server.

To create a Docker "public network" named `traefik-public` run the following command in your remote server:

```bash
docker network create traefik-public
```

### Traefik Environment Variables

The Traefik Docker Compose file expects some environment variables to be set in your terminal before starting it. You can do it by running the following commands in your remote server.

* Create the username for HTTP Basic Auth, e.g.:

```bash
export USERNAME=admin
```

* Create an environment variable with the password for HTTP Basic Auth, e.g.:

```bash
export PASSWORD=changethis
```

* Use openssl to generate the "hashed" version of the password for HTTP Basic Auth and store it in an environment variable:

```bash
export HASHED_PASSWORD=$(openssl passwd -apr1 $PASSWORD)
```

To verify that the hashed password is correct, you can print it:

```bash
echo $HASHED_PASSWORD
```

* Create an environment variable with the domain name for your server, e.g.:

```bash
export DOMAIN=fastapi-project.example.com
```

* Create an environment variable with the email for Let's Encrypt, e.g.:

```bash
export EMAIL=admin@example.com
```

**Note**: you need to set a different email, an email `@example.com` won't work.

### Start the Traefik Docker Compose

Go to the directory where you copied the Traefik Docker Compose file in your remote server:

```bash
cd /root/code/traefik-public/
```

Now with the environment variables set and the `compose.traefik.yml` in place, you can start the Traefik Docker Compose running the following command:

```bash
docker compose -f compose.traefik.yml up -d
```

## Deploy the FastAPI Project

Now that you have Traefik in place you can deploy your FastAPI project with Docker Compose.

**Note**: You might want to jump ahead to the section about Continuous Deployment with GitHub Actions.

## Copy the Code

```bash
rsync -av --filter=":- .gitignore" ./ root@your-server.example.com:/root/code/app/
```

Note: `--filter=":- .gitignore"` tells `rsync` to use the same rules as git, ignore files ignored by git, like the Python virtual environment.

## Environment Variables

You need to set some environment variables first.

### Generate secret keys

Some environment variables in the `.env` file have a default value of `changethis`.

You have to change them with a secret key, to generate secret keys you can run the following command:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Copy the content and use that as password / secret key. And run that again to generate another secure key.

### Required Environment Variables

Set the `ENVIRONMENT`, by default `local` (for development), but when deploying to a server you would put something like `staging` or `production`:

```bash
export ENVIRONMENT=production
```

Set the `DOMAIN`, by default `localhost` (for development), but when deploying you would use your own domain, for example:

```bash
export DOMAIN=fastapi-project.example.com
```

Set the `POSTGRES_PASSWORD` to something different than `changethis`:

```bash
export POSTGRES_PASSWORD="changethis"
```

Set the `SECRET_KEY`, used to sign tokens:

```bash
export SECRET_KEY="changethis"
```

Note: you can use the Python command above to generate a secure secret key.

Set the `FIRST_SUPER_USER_PASSWORD` to something different than `changethis`:

```bash
export FIRST_SUPERUSER_PASSWORD="changethis"
```

Set the `BACKEND_CORS_ORIGINS` to include your domain:

```bash
export BACKEND_CORS_ORIGINS="https://dashboard.${DOMAIN?Variable not set},https://api.${DOMAIN?Variable not set}"
```

You can set several other environment variables:

* `PROJECT_NAME`: API title (e.g. `Werefa API`) for OpenAPI docs.
* `BRAND_NAME`: Customer-facing name in email subjects and bodies (default `Werefa`).
* `EMAILS_FROM_NAME`: Sender display name (defaults to `BRAND_NAME`).
* `STACK_NAME`: The name of the stack used for Docker Compose labels and project name, this should be different for `staging`, `production`, etc. You could use the same domain replacing dots with dashes, e.g. `fastapi-project-example-com` and `staging-fastapi-project-example-com`.
* `BACKEND_CORS_ORIGINS`: A list of allowed CORS origins separated by commas.
* `FIRST_SUPERUSER`: The email of the first superuser, this superuser will be the one that can create new users.
* `SMTP_HOST`: The SMTP server host to send emails, this would come from your email provider (E.g. Mailgun, Sparkpost, Sendgrid, etc).
* `SMTP_USER`: The SMTP server user to send emails.
* `SMTP_PASSWORD`: The SMTP server password to send emails.
* `EMAILS_FROM_EMAIL`: The email account to send emails from.
* `POSTGRES_SERVER`: The hostname of the PostgreSQL server. You can leave the default of `db`, provided by the same Docker Compose. You normally wouldn't need to change this unless you are using a third-party provider.
* `POSTGRES_PORT`: The port of the PostgreSQL server. You can leave the default. You normally wouldn't need to change this unless you are using a third-party provider.
* `POSTGRES_USER`: The Postgres user, you can leave the default.
* `POSTGRES_DB`: The database name to use for this application. You can leave the default of `app`.
* `SENTRY_DSN`: The DSN for Sentry, if you are using it.

### SMS notifications

The `sms` notification channel dispatches through a pluggable gateway adapter, so
switching vendors is a config change plus one adapter class — see
`backend/werefa/notifications/infrastructure/sms/`.

* `SMS_PROVIDER`: Which gateway to use. Built-ins are `disabled` (default),
  `console` (logs the fully rendered message instead of sending — the right choice
  for local dev and staging) and `twilio`. Any name registered via
  `register_sms_provider()` also works; an unknown name fails at startup and lists
  the registered ones.
* `SMS_DEFAULT_COUNTRY_CODE`: Country assumed for national numbers, e.g. `+251`.
  `User.phone_number` is free-form, so `0911234567` only becomes `+251911234567`
  when this is set. Without it, users whose number isn't already stored in
  international form are skipped rather than guessed at.
* `SMS_MAX_BODY_CHARS`: Hard cap on the rendered message (default `320`, about two
  GSM-7 segments).
* `SMS_INCLUDE_TICKET_LINK`: Append the ticket deep link to the message (default
  `true`).
* `SMS_TIMEOUT_SECONDS`: Gateway HTTP timeout (default `5`). Kept short because
  dispatch is synchronous — see the note in `sms/twilio.py`.

Twilio-specific, required when `SMS_PROVIDER=twilio` (startup fails otherwise):

* `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN`: API credentials.
* `TWILIO_MESSAGING_SERVICE_SID`: Preferred sender in production — Twilio handles
  sender pools, sticky sender and per-country compliance. Wins when both this and
  `TWILIO_FROM_NUMBER` are set.
* `TWILIO_FROM_NUMBER`: A purchased number in E.164, as an alternative sender.
* `TWILIO_API_BASE_URL`: Override the API host (default `https://api.twilio.com`),
  useful for pointing staging at a local fake.

#### Delivery receipts

* `TWILIO_STATUS_CALLBACK_URL`: Public URL of the delivery-status webhook, e.g.
  `https://api.example.com/api/v1/webhooks/twilio/sms-status`. Optional, and
  strongly recommended.

Twilio returning a 201 means it *queued* the message. Whether a carrier accepted
it, whether the handset exists, whether the number is barred — all of that comes
back later, on this callback. With the URL unset nothing asks for one, and an SMS
ledger row is written `delivered` the moment Twilio accepts it, which is the old
optimistic reading: a text to a disconnected number is recorded exactly like one
the customer acted on.

Set it, and a row waits at `sent` until the carrier reports back, then moves to
`delivered` or `failed` (with the carrier's code in `delivery_error_code`). That
distinction is load-bearing beyond the audit trail: FR-05 liveness flags customers
for not answering prompts, and it now checks whether the prompt actually arrived
before counting the silence against them — see
`backend/werefa/notifications/domain/receipts.py`.

Two operational notes:

* The value must be **exactly** the URL Twilio is given, character for character.
  It is one of the inputs to the `X-Twilio-Signature` HMAC, and the webhook
  validates against this setting rather than against the URL the request appears
  to have arrived at (a proxy will have rewritten the scheme or host). A value
  that disagrees with reality fails every callback silently.
* The endpoint is unauthenticated by nature and rejects anything it cannot verify,
  so `TWILIO_AUTH_TOKEN` must be correct or no receipt is ever recorded. Watch for
  `twilio_status_callback_bad_signature` in the logs.

* `NOTIFICATION_RECEIPT_GRACE_SECONDS` (default `300`): how long a row may sit
  unresolved before "we do not know yet" becomes "nobody ever answered". Covers a
  `sent` row owed a carrier receipt and a `queued` row owed the delivery worker.

  This is the safety net for the failure above. If the callback URL never
  resolves, receipts simply never arrive — and without an expiry, every SMS row
  would stay an open question forever, which quietly restores the old unfairness
  for every customer. Past this age liveness treats the prompt as not having
  reached anyone: it stops blaming them for the silence *and* stops excusing it.

  Keep it comfortably above the delivery retry budget, or a busy gateway starts
  looking like an unreachable one. To tell a misconfigured webhook from genuinely
  unreachable customers, look at `liveness_prompt_undelivered` log lines: a run of
  them with `prompt_status=sent` is the webhook, `prompt_status=failed` is the
  carrier, and `prompt_channel=logger` means those customers have no reachable
  channel configured at all.

#### Expect more SMS and email than before

Turning receipts on is not the only change in what customers receive. The
`websocket` channel used to report success for a publish that completed with
**nobody subscribed** — which is every customer whose app is closed. Dispatch
stopped there, so with the default `websocket, email, logger` preferences the
alert was recorded as delivered and nothing was ever sent.

It now declines when it can show nobody received it, and dispatch falls through to
the next preference. A customer with `sms` in their preferences and a closed app
therefore gets a text where they previously got silence. That is the intent — but
it is a real change in gateway spend, so size it before enabling SMS broadly.

Behind Redis the subscriber count is unknowable (they may be on another replica),
so the publish is recorded `sent` rather than `delivered`: no fall-through, no
double-notify, and the row ages out of "unknown" like any other unanswered wait.

* `LIVENESS_AUTO_HOLD_UNREACHABLE` (default `true`): park a spot automatically
  once we can show the prompt never reached the customer.

  This is the one setting here that changes *queue* behaviour, so it is worth
  knowing about before you turn receipts on. Without it, "we could not reach
  them" only ever appears on the staff board, and the line's next move is Call
  Next reaching an unreachable customer anyway, nobody answering, and a no-show
  recorded against someone who was never spoken to. With it the spot is held
  instead: the line moves on, their place is kept, nothing is recorded against
  anyone. `LIVENESS_MAX_HOLDS` still caps it — after that it really is a human's
  call, and the board says so. Look for `liveness_auto_held_unreachable`.

Note that SMS only goes out to users who have `sms` in their notification
preferences; it is not in `NOTIFICATION_DEFAULT_PREFS`, so enabling a provider
alone does not start texting anyone.

## GitHub Actions Environment Variables

There are some environment variables only used by GitHub Actions that you can configure:

* `LATEST_CHANGES`: Used by the GitHub Action [latest-changes](https://github.com/tiangolo/latest-changes) to automatically add release notes based on the PRs merged. It's a personal access token, read the docs for details.
* `SMOKESHOW_AUTH_KEY`: Used to handle and publish the code coverage using [Smokeshow](https://github.com/samuelcolvin/smokeshow), follow their instructions to create a (free) Smokeshow key.

### Deploy with Docker Compose

With the environment variables in place, you can deploy with Docker Compose:

```bash
cd /root/code/app/
docker compose -f compose.yml build
docker compose -f compose.yml up -d
```

For production you wouldn't want to have the overrides in `compose.override.yml`, that's why we explicitly specify `compose.yml` as the file to use.

## Continuous Deployment (CD)

You can use GitHub Actions to deploy your project automatically. 😎

You can have multiple environment deployments.

There are already two environments configured, `staging` and `production`. 🚀

### Install GitHub Actions Runner

* On your remote server, create a user for your GitHub Actions:

```bash
sudo adduser github
```

* Add Docker permissions to the `github` user:

```bash
sudo usermod -aG docker github
```

* Temporarily switch to the `github` user:

```bash
sudo su - github
```

* Go to the `github` user's home directory:

```bash
cd
```

* [Install a GitHub Action self-hosted runner following the official guide](https://docs.github.com/en/actions/hosting-your-own-runners/managing-self-hosted-runners/adding-self-hosted-runners#adding-a-self-hosted-runner-to-a-repository).

* When asked about labels, add a label for the environment, e.g. `production`. You can also add labels later.

After installing, the guide would tell you to run a command to start the runner. Nevertheless, it would stop once you terminate that process or if your local connection to your server is lost.

To make sure it runs on startup and continues running, you can install it as a service. To do that, exit the `github` user and go back to the `root` user:

```bash
exit
```

After you do it, you will be on the previous user again. And you will be on the previous directory, belonging to that user.

Before being able to go the `github` user directory, you need to become the `root` user (you might already be):

```bash
sudo su
```

* As the `root` user, go to the `actions-runner` directory inside of the `github` user's home directory:

```bash
cd /home/github/actions-runner
```

* Install the self-hosted runner as a service with the user `github`:

```bash
./svc.sh install github
```

* Start the service:

```bash
./svc.sh start
```

* Check the status of the service:

```bash
./svc.sh status
```

You can read more about it in the official guide: [Configuring the self-hosted runner application as a service](https://docs.github.com/en/actions/hosting-your-own-runners/managing-self-hosted-runners/configuring-the-self-hosted-runner-application-as-a-service).

### Set Secrets

On your repository, configure secrets for the environment variables you need, the same ones described above, including `SECRET_KEY`, etc. Follow the [official GitHub guide for setting repository secrets](https://docs.github.com/en/actions/security-guides/using-secrets-in-github-actions#creating-secrets-for-a-repository).

The current Github Actions workflows expect these secrets:

* `DOMAIN_PRODUCTION`
* `DOMAIN_STAGING`
* `STACK_NAME_PRODUCTION`
* `STACK_NAME_STAGING`
* `EMAILS_FROM_EMAIL`
* `FIRST_SUPERUSER`
* `FIRST_SUPERUSER_PASSWORD`
* `POSTGRES_PASSWORD`
* `SECRET_KEY`
* `LATEST_CHANGES`
* `SMOKESHOW_AUTH_KEY`

## GitHub Action Deployment Workflows

There are GitHub Action workflows in the `.github/workflows` directory already configured for deploying to the environments (GitHub Actions runners with the labels):

* `staging`: after pushing (or merging) to the branch `master`.
* `production`: after publishing a release.

If you need to add extra environments you could use those as a starting point.

## URLs

Replace `fastapi-project.example.com` with your domain.

### Main Traefik Dashboard

Traefik UI: `https://traefik.fastapi-project.example.com`

### Production

Frontend: `https://dashboard.fastapi-project.example.com`

Backend API docs: `https://api.fastapi-project.example.com/docs`

Backend API base URL: `https://api.fastapi-project.example.com`

Adminer: `https://adminer.fastapi-project.example.com`

### Staging

Frontend: `https://dashboard.staging.fastapi-project.example.com`

Backend API docs: `https://api.staging.fastapi-project.example.com/docs`

Backend API base URL: `https://api.staging.fastapi-project.example.com`

Adminer: `https://adminer.staging.fastapi-project.example.com`
