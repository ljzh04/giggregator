@echo off
REM Daily CareerJet top-up: home IP is whitelisted with CareerJet, Vercel egress is not.
REM Runs single-adapter ingest straight into production Turso (via .env, never committed).
cd /d C:\Users\LJ\Documents\Projects\giggregator
C:\Users\LJ\AppData\Local\hermes\bin\uv.exe run --env-file .env python -m giggregator.ingest --once --only careerjet_ph --db prod >> "%TEMP%\giggregator_careerjet_topup.log" 2>&1
