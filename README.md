# Astrohunter: Serverless Exoplanet Discovery Pipeline

A fully autonomous, event-driven, serverless pipeline deployed on Google Cloud Platform that scans NASA TESS (Transiting Exoplanet Survey Satellite) data for undiscovered exoplanets and variable stars, and sends real-time alerts to Telegram.

## Architecture Design

This project is designed to run 100% within the **GCP Always Free Tier**. It uses a serverless architecture to ensure zero costs while maintaining enterprise-grade reliability and scalability.

1. **Cloud Scheduler (The Cron Trigger)**
   - Acts as the "Alarm Clock".
   - Pings the Cloud Run service every 2 hours with an HTTP POST request containing the target batch size (e.g., 50 stars).

2. **Cloud Run (The Compute Engine)**
   - A stateless, containerized Python Flask API (`functions-framework`).
   - Wakes up instantly on receiving the ping.
   - Downloads TESS Light Curves using `lightkurve`.
   - Runs Box Least Squares (BLS) and Lomb-Scargle periodograms.
   - Applies harmonic filtering and SNR vetting to discard momentum dumps and systematic noise.
   - Shuts down immediately after the batch is processed to save CPU seconds.

3. **Cloud Storage (State Persistence)**
   - Because Cloud Run is stateless, the master target list and history are stored in a SQLite database (`astrohunter.db`).
   - The container downloads the DB from a secure GCS bucket on startup, processes the next batch, and uploads the updated DB back to the bucket before shutting down.

4. **Secret Manager (Secure Credentials)**
   - Telegram Bot Tokens and Chat IDs are stored securely in Google Secret Manager and injected securely into the Cloud Run container at runtime.

5. **Telegram Bot API (Alerting)**
   - If an unrecorded anomaly (SDE > 7.0) is found, a 3-panel scientific diagnostic plot is generated via `matplotlib`.
   - The plot and orbital parameters are dispatched directly to the user's phone in real-time.

## Infrastructure as Code (Terraform)
The entire GCP infrastructure is provisioned automatically using Terraform, ensuring consistent, repeatable deployments with zero manual console clicking.

## Local Development
1. Clone the repo
2. Create a virtual environment: `python -m venv venv`
3. Install dependencies: `pip install -r requirements.txt`
4. Set env variables: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
5. Run locally: `python main.py`


## How It Works: The Science
Astrohunter uses mathematical algorithms to detect faint, rhythmic changes in starlight (Light Curves) captured by NASA's TESS telescope. 

### 🪐 Finding Exoplanets (The Transit Method)
When a planet orbits a star, it occasionally passes directly between the star and the telescope. This blocks a tiny fraction of the starlight, creating a very brief, U-shaped dip in the light curve. 
- **The Algorithm:** The bot uses the **Box Least Squares (BLS)** algorithm to fold the time-series data over thousands of potential orbital periods to find repeating U-shaped dips. 
- **How to read the graph:** If the bot sends you an Exoplanet alert, look at the **Phase Folded** graph. You are looking for a clear, sharp dip in the center (Phase 0.0). The wider the dip, the longer the transit took. The deeper the dip, the larger the planet is relative to the star.

### 🌟 Finding Variable Stars & Eclipsing Binaries
Unlike planets that cause brief dips, many stars inherently pulse, expand/contract, or have giant star-spots that rotate in and out of view. These create continuous, wave-like (sinusoidal) variations in the starlight. Eclipsing binaries are two stars orbiting each other, creating alternating deep and shallow V-shaped dips.
- **The Algorithm:** The bot uses the **Lomb-Scargle Periodogram**, which is basically a Fourier transform designed for unevenly spaced astronomical data, to find the dominant frequencies of these continuous waves.
- **How to read the graph:** In a Variable Star alert, look at the **Phase Folded** graph. You will see a continuous, rolling sine-wave pattern. The **Period** tells you exactly how many days it takes for the star to complete one full pulsation or rotation cycle.

---

### ⚠️ Important Note on Discoveries & Publishing
While this bot is highly effective at detecting signals and automatically cross-referencing them against official databases (like the AAVSO VSX catalog), it is **not** a substitute for rigorous scientific verification. 

Before publicly claiming or publishing a new discovery found by this bot, you must independently cross-check the data:
1. **Recent Literature:** Official catalogs can take months or years to update. Always search the star's TIC or HD identifier on [NASA ADS](https://ui.adsabs.harvard.edu/) or arXiv to ensure the signal hasn't been recently published in a research paper.
2. **False Positives:** Mathematical echoes, momentum dumps from the telescope, and background eclipsing binaries can mimic planetary transits. Always manually vet the light curves and check ExoFOP for neighborhood contamination.
