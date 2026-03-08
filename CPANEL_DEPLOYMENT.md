# cPanel Deployment

This project can run on cPanel with Application Manager and Passenger.

## Required cPanel features

- Application Manager enabled
- Python app support enabled by the hosting provider
- SSH or Terminal access recommended

## Suggested layout

- Domain: `energate.artovy.com`
- App path: `/home/<cpanel-user>/repos/energate`
- App URL: `https://energate.artovy.com/`
- Startup file: `passenger_wsgi.py`
- Application entry point: `application`

## Deployment steps

1. Clone the repository into your cPanel account.
2. In cPanel, open `Application Manager`.
3. Create a Python application.
4. Set the application root to the repository directory.
5. Set the application URL to `energate.artovy.com`.
6. Set the startup file to `passenger_wsgi.py`.
7. Set the entry point to `application`.
8. Create the virtual environment if cPanel does not create it automatically.
9. Install dependencies from `requirements.txt`.
10. Add environment variables from `.env.example` in the app config or in an `.env` file.
11. Restart the application after each code or env change.

## Environment variables

Minimum recommended values:

```env
PARIBU_API_KEY=
PARIBU_API_SECRET=
WEB_USERNAME=admin
WEB_PASSWORD=change-me
FLASK_DEBUG=false
TRADE_AMOUNT_TL=100
PRICE_DIFFERENCE_THRESHOLD=1.0
CHECK_INTERVAL=5
DRY_RUN=True
```

## Notes

- The app serves Flask directly. Do not call `app.run()` from Passenger. This repo already avoids that because `main.py` only runs the dev server under `__main__`.
- Runtime state files are local and not committed: `.env`, `active_trades.json`, `blacklist.json`, `trade_history.json`.
- If your cPanel app does not refresh after deploy, restart it from Application Manager or touch the Passenger restart file.
