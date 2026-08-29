# go-e-solar-charger

Reads power values directly from a Tesla Powerwall Gateway and feeds them
into a go-e Charger's PV-surplus-charging logic, so the wallbox charges
mainly from your own solar production. Includes a small web dashboard.

## Dashboard

- `http://<host>:8090/` - live view of Solar/Netz/Batterie/Haus power and
  the go-e Charger's status (connected/charging, current, energy for the
  running charge session).
- `http://<host>:8090/config` - enter the Powerwall Gateway's IP, login
  email/password and the go-e Charger's IP. A "Verbindung testen" button
  checks the values immediately, without saving them. Saved values are
  written to `./data/config.json` (mounted as a volume, see
  `docker-compose.yml`) so they survive container restarts.

Port `8090` is just what `docker-compose.yml` ships with - change the left
side of the `ports:` mapping if you'd rather use a different one.

## Running

```
docker compose up -d
```

Then open `/config` and fill in your Powerwall and go-e details.

## Security note

The dashboard has no login of its own and stores the Powerwall password
(and, if you use one, the go-e API key) in plain text in
`./data/config.json`. Keep this on your local network - don't expose the
port to the internet.

## Powerwall API

The Powerwall Gateway's local API isn't officially documented by Tesla;
this project follows the same reverse-engineered endpoints used by
[pypowerwall](https://github.com/jasonacox/pypowerwall) and
[powerwall2](https://github.com/vloschiavo/powerwall2). The email/password
are the same ones you'd use to log into the Gateway's own local web UI.

## go-e Charger API

Uses the [go-eCharger local API v2](https://github.com/goecharger/go-eCharger-API-v2)
over plain HTTP. No credentials are needed unless you've enabled a local
API key in the charger's own settings.
