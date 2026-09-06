# Project setup

This project is a Flask API for searching YouTube videos and downloading audio/video.

## Run locally on Replit

Install dependencies from `requirements.txt`, then start the app with:

```bash
gunicorn --bind 0.0.0.0:5000 --reuse-port --timeout 600 app:app
```

The Replit workflow is configured as **Start application** and serves port `5000`.

## Publishing

The project is configured for an Autoscale deployment using the same Gunicorn command.
Use the Replit Publishing tool to create or update the public deployment.